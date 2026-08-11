"""The governed entry point for Phase 1.

One `run()` is **one crawl job**, not one page, per
`docs/adr/0003-job-level-governance-and-async-internals.md`. That is the whole
governance stance of this module, and it is worth restating why:

* A 20,000-page crawl under per-page governance would perform 20,000 guardrail
  evaluations and 40,000 synchronous audit writes. The logging alone exceeds the
  entire 30-second budget.
* An operator approving "crawl highradius.com" is making **one** decision.
  Asking them to approve 20,000 fetches is not more safety, it is an unusable
  prompt.

So the tool declares `RiskClass.READ`: a crawl mutates nothing outside this
repository. Per-page results are an output artefact; the audit log receives one
record for the job.

Cost
----
`estimated_cost_usd` is **0.0 and must stay that way**. The Layer 3 LLM cost is
variable — zero to several hundred calls depending on how ambiguous a site is —
and a static estimate cannot describe it. Declaring a non-zero figure would trip
the `cost implies FINANCIAL` invariant in `ToolMetadata`, forcing MANDATORY_HITL
on every run and making unattended classification impossible.

Spend is instead capped per job via `PageClassificationInput.llm_spend_cap_usd`
and metered per call by `LLMClient` (ADR 0005). When the cap is reached, Layer 3
stops and the remaining pages keep their best structural guess — the crawl
degrades, it does not fail.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, ClassVar, Protocol, runtime_checkable

from pydantic import Field

from src.core.base_tool import BaseTool
from src.core.errors import CrawlBlockedError
from src.core.logger import get_logger
from src.core.rate_limiter import CostLedger
from src.core.schemas import RiskClass, StrictModel, ToolMetadata
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import (
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    adiscover_site,
)
from src.modules.seo.page_classifier.cascading_pipeline import (
    ZeroShotClassifier,
    classify_page,
    needs_llm_escalation,
)
from src.modules.seo.page_classifier.discovery import (
    ABSOLUTE_MAX_PAGES,
    DEFAULT_DOM_RESERVE_FRACTION,
    DEFAULT_MAX_PAGES,
    CheckpointSink,
    DiscoveryReport,
    ProgressSink,
    SiteGraph,
    discover_site,
)
from src.modules.seo.page_classifier.logical_hierarchy import (
    NavCoverageReport,
    assign_navigation,
)
from src.modules.seo.page_classifier.nav_tree_parser import (
    NavigationTree,
    parse_navigation,
)
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    PrimaryPageType,
    SignalScore,
)
from src.modules.seo.page_classifier.signal_parsers import PageEvidence
from src.modules.seo.page_classifier.site_profile import probe_site
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

__all__ = [
    "CrawlSummary",
    "LlmPageClassifier",
    "PageClassificationInput",
    "PageClassificationOutput",
    "PageClassificationTool",
    "register_tools",
]

_logger = get_logger("modules.seo.page_classifier.tool")


@runtime_checkable
class LlmPageClassifier(Protocol):
    """Layer 3 escalation handler. No implementation exists yet.

    Deliberately batch-shaped: it receives every escalating page at once so an
    implementation can use the provider's Batch API, which is where ADR 0005's
    50% discount comes from. A per-page interface would quietly forfeit it.
    """

    def classify_batch(self, evidence: Sequence[PageEvidence]) -> Mapping[str, SignalScore]:
        """Classify ambiguous pages, keyed by `normalized_path`.

        Omitting a key is allowed and means "no answer" — a budget-exhausted or
        refused page keeps its structural guess rather than failing the crawl.
        """
        ...


class PageClassificationInput(StrictModel):
    """What to crawl, and the limits that apply to it.

    Attributes:
        base_url: Site root. Validated by the SSRF guard before any fetch.
        max_pages: Node ceiling. `None` crawls everything reachable, up to the
            ADR 0001 limit of 500,000.
        max_depth: Link depth ceiling for the DOM crawl; `None` is unlimited.
        crawl_dom: Run Path B. Disabling is much cheaper but misses exactly the
            pages Path B exists to find.
        respect_robots: Only disable for a site you own.
        llm_spend_cap_usd: Hard ceiling on Layer 3 spend for this job. `0.0`
            disables Layer 3 entirely, which is the cheapest correct setting.
        user_agent: Product token sent, and matched against robots.txt.
    """

    base_url: str = Field(min_length=1)
    max_pages: Annotated[int, Field(gt=0, le=ABSOLUTE_MAX_PAGES)] | None = DEFAULT_MAX_PAGES
    """`None` means "every URL the crawl can reach", up to `ABSOLUTE_MAX_PAGES`.

    Not truly unbounded, and the difference matters: the graph holds every node
    and every page body in memory, so an unbounded crawl of a large catalogue
    would exhaust it hours in and lose the whole run. `resolved_max_pages`
    performs the substitution, and the ceiling that was applied is reported in
    `DiscoveryReport` either way."""
    max_depth: Annotated[int, Field(ge=0, le=15)] | None = None
    """`None` — the default — traverses until the link frontier is exhausted.

    Bounded by `max_pages`, not by depth: the graph refuses new nodes once full,
    so the frontier drains. A depth ceiling therefore does not decide *how many*
    pages are crawled, only *which* ones, and a fixed default of 5 silently
    truncated deep sites that had budget left. Set an integer to reinstate the
    ceiling when shallow structure is what is wanted."""
    crawl_dom: bool = True
    respect_robots: bool = True
    llm_spend_cap_usd: float = Field(default=0.0, ge=0.0, le=100.0)
    rate_limit_rps: float | None = Field(default=None, gt=0.0, le=25.0)
    """Requests per second **per host**. `None` uses the configured default.

    A declared `Crawl-delay` is combined with this using `min`, in both
    directions: a site asking to be crawled slowly is never sped up, and a site
    permitting speed never overrides a deliberately polite setting.

    This is load on somebody else's server. The ceiling of 25 exists because
    beyond it a crawler stops being a guest — and even below it, the polite
    default is the right choice for any site not owned by the operator."""

    user_agent: str = Field(default="RankunoBot", min_length=1)
    browser_headers: bool = False
    """Send the `Accept`/`Accept-Language` headers a browser would.

    Off by default. Some enterprise edge configurations reject any client they do
    not recognise — returning `403` even for `robots.txt`, so the site cannot
    state what it permits. This, with a `user_agent` the edge accepts, gets past
    that filter.

    An operator sets it per job rather than the crawler retrying under a new
    identity after a refusal: re-sending a rejected request as something else is
    working around the refusal, not configuring a client. Use it on sites you own
    or have permission to crawl. robots.txt is still obeyed either way."""
    concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1, le=MAX_CONCURRENCY)
    """Simultaneous in-flight requests. Bounds local resources only — per-host
    politeness is enforced by the fetcher's token bucket regardless, so raising
    this cannot make the crawler rude to a single host."""

    use_async_crawl: bool = True
    """Run the concurrent crawl path. Disabling falls back to serial fetching,
    which is roughly 10x slower and exists only as an escape hatch for
    debugging a crawl that behaves differently under concurrency."""

    @property
    def resolved_max_pages(self) -> int:
        """The ceiling actually applied, substituting the cap for `None`."""
        return self.max_pages if self.max_pages is not None else ABSOLUTE_MAX_PAGES

    dom_reserve_fraction: float = Field(default=DEFAULT_DOM_RESERVE_FRACTION, ge=0.0, le=0.9)
    """Share of `max_pages` only the DOM crawl may fill.

    Without a reserve, a sitemap larger than the budget consumes every slot and
    pages the sitemap omits — the ones an audit most wants — are structurally
    excluded. Setting this to `0.0` restores that behaviour and is almost never
    what you want (ADR 0007)."""


class CrawlSummary(StrictModel):
    """Aggregate outcome of one crawl.

    Exists so the numbers that matter are read off the result rather than
    recomputed by every consumer — in particular the escalation rate, which
    ADR 0005 identifies as the dominant term in the cost model.

    Attributes:
        pages_classified: Profiles produced.
        escalated_to_llm: Pages that consumed a paid Layer 3 call.
        escalation_rate: Fraction escalated. The number to watch: ADR 0005 needs
            this at or below 0.005 for the cost target to hold.
        unknown_pages: Pages left `UNKNOWN`. Phase 1's stated goal is zero, so a
            non-zero value here is a defect signal, not a normal outcome.
        low_confidence_pages: Pages below the escalation threshold that Layer 3
            could not resolve — usually because no LLM was wired in.
        orphan_pages: Pages with zero inbound internal links. A real SEO finding.
        llm_spend_usd: Actual Layer 3 spend.
    """

    pages_classified: int = Field(default=0, ge=0)
    escalated_to_llm: int = Field(default=0, ge=0)
    escalation_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    unknown_pages: int = Field(default=0, ge=0)
    low_confidence_pages: int = Field(default=0, ge=0)
    orphan_pages: int = Field(default=0, ge=0)
    llm_spend_usd: float = Field(default=0.0, ge=0.0)


class PageClassificationOutput(StrictModel):
    """Everything one crawl job produced.

    Attributes:
        base_url: Crawl root.
        site_profile: What the probe pass detected.
        weight_profile: Which weight vector was applied, and which was detected.
            Both are recorded so a reviewer can tell a genuine accuracy
            difference between two sites from a weighting artefact.
        discovery: Per-path discovery breakdown.
        summary: Aggregate outcome.
        pages: One profile per discovered URL.
        navigation: The site's header menu, as published. Empty when the menu
            could not be read — a client-rendered header leaves no links in the
            served HTML.
        nav_coverage: How much of the crawl the menu accounts for. Reported
            rather than assumed: menu coverage varies enormously between sites,
            and a consumer showing a navigation tree needs to know whether it
            describes the site or a corner of it.
    """

    base_url: str
    site_profile: SiteProfile
    weight_profile: WeightProfileReport
    discovery: DiscoveryReport
    summary: CrawlSummary
    pages: tuple[FullPageIntelligenceProfile, ...] = ()
    navigation: NavigationTree = NavigationTree()
    nav_coverage: NavCoverageReport = NavCoverageReport()


class PageClassificationTool(BaseTool[PageClassificationInput, PageClassificationOutput]):
    """Crawl a site and classify every page it finds.

    Read-only: it fetches public pages and produces a report. Nothing outside
    this repository is mutated, which is why it is `RiskClass.READ` and may run
    unattended.
    """

    metadata: ClassVar[ToolMetadata] = ToolMetadata(
        name="seo.page_classifier",
        version="0.1.0",
        summary="Crawl a site and classify every page by hierarchy, type and intent.",
        risk_class=RiskClass.READ,
        rate_limit_key="web.crawl",
        # Must stay 0.0 — see the module docstring. Layer 3 spend is capped per
        # job and metered per call, not estimated here.
        estimated_cost_usd=0.0,
    )
    input_model: ClassVar[type[StrictModel]] = PageClassificationInput
    output_model: ClassVar[type[StrictModel]] = PageClassificationOutput

    def __init__(
        self,
        *,
        fetcher: HttpFetcher | None = None,
        url_policy: UrlSafetyPolicy | None = None,
        local_classifier: ZeroShotClassifier | None = None,
        llm_classifier: LlmPageClassifier | None = None,
        cost_ledger: CostLedger | None = None,
        progress_sink: ProgressSink | None = None,
        checkpoint_sink: CheckpointSink | None = None,
        **kwargs: object,
    ) -> None:
        """Build the tool.

        Args:
            fetcher: Safety-wired fetcher. One is built per job if omitted, and
                closed when the job ends.
            url_policy: SSRF policy for a fetcher built here.
            checkpoint_sink: Optional durability hook, offered the graph so
                partial work survives an interruption.
            progress_sink: Optional observability hook, called as pages are
                fetched. Constructor-injected rather than a field on the input
                model: it is a callable the *caller* owns, not a crawl parameter,
                and it has no place in a serialised, audited request payload.
            local_classifier: Layer 2 implementation. `None` means the layer is
                unavailable and the cascade falls through to Layer 3.
            llm_classifier: Layer 3 handler. `None` means ambiguous pages keep
                their structural guess.
            cost_ledger: Ledger charged for Layer 3.
            **kwargs: Forwarded to `BaseTool`.
        """
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._fetcher = fetcher
        self._url_policy = url_policy
        self._local_classifier = local_classifier
        self._llm_classifier = llm_classifier
        self._cost_ledger = cost_ledger
        self._progress_sink = progress_sink
        self._checkpoint_sink = checkpoint_sink

    def describe_invocation(self, payload: PageClassificationInput) -> str:
        """Operator-facing summary. Names the site, not the object graph."""
        # Spelled out rather than rendering `None`: this is what an approver
        # reads before authorising the crawl, and "depth None" states the
        # opposite of what it means to someone skimming it.
        depth = "unlimited depth" if payload.max_depth is None else f"depth {payload.max_depth}"
        pages = (
            f"every reachable page (max {ABSOLUTE_MAX_PAGES:,})"
            if payload.max_pages is None
            else f"up to {payload.max_pages:,} pages"
        )
        # The request rate is named because it is the part of this decision that
        # lands on somebody else's server.
        rate = (
            "default rate"
            if payload.rate_limit_rps is None
            else f"{payload.rate_limit_rps:g} req/sec"
        )
        return (
            f"Crawl and classify {pages} of {payload.base_url} "
            f"({depth}, {rate}, LLM cap ${payload.llm_spend_cap_usd:.2f})"
        )

    def execute(self, payload: PageClassificationInput) -> PageClassificationOutput:
        """Probe, discover, classify.

        Args:
            payload: Validated crawl parameters.

        Returns:
            The complete job result.

        Raises:
            CrawlBlockedError: If nothing was retrieved from the network at all.
        """
        fetcher, owns_fetcher = self._resolve_fetcher(payload)
        try:
            # The probe runs synchronously and before the async crawl begins:
            # it is six requests, so parallelising it saves nothing, and running
            # it outside the event loop keeps `execute()` simple.
            site_profile = probe_site(fetcher, payload.base_url)
            graph, discovery = self._discover(fetcher, payload, site_profile)

            # Checked before classification, not after. Classifying the seed node
            # would produce a confident `HOMEPAGE` from the URL string on no
            # evidence whatsoever, and returning that as a result is how a fully
            # blocked site comes to look like a successful one-page crawl.
            if discovery.retrieved_nothing:
                raise CrawlBlockedError(_blocked_message(payload.base_url, discovery))

            evidence = graph.to_page_evidence()
            pages = self._classify_all(evidence, site_profile, payload)
            navigation, nav_coverage, pages = self._apply_navigation(graph, payload.base_url, pages)
        finally:
            if owns_fetcher:
                fetcher.close()

        summary = self._summarise(pages, discovery)
        _logger.info(
            "crawl_job_complete",
            extra={
                "base_url": payload.base_url,
                "pages": summary.pages_classified,
                "escalation_rate": round(summary.escalation_rate, 5),
                "unknown": summary.unknown_pages,
            },
        )

        return PageClassificationOutput(
            base_url=payload.base_url,
            site_profile=site_profile,
            weight_profile=WeightProfileReport.for_site(site_profile),
            discovery=discovery,
            summary=summary,
            pages=pages,
            navigation=navigation,
            nav_coverage=nav_coverage,
        )

    def _apply_navigation(
        self,
        graph: SiteGraph,
        base_url: str,
        pages: tuple[FullPageIntelligenceProfile, ...],
    ) -> tuple[NavigationTree, NavCoverageReport, tuple[FullPageIntelligenceProfile, ...]]:
        """Parse the header menu and place every page under a section.

        Read from the homepage only. The header menu is global, so parsing it on
        every page would repeat identical work thousands of times for one answer.

        This fills `nav_parent_url` and `breadcrumb_path`, which have been on the
        profile contract since Phase 1 was specified and have never been
        populated by anything.

        Returns:
            The menu, its coverage, and the profiles with navigation filled in.
        """
        homepage_html = graph.html_for(base_url)
        if not homepage_html:
            # No homepage body means no menu to read. Reported as an empty tree
            # rather than an error: a sitemap-only crawl is legitimate and simply
            # has no navigation data.
            _logger.info("nav_skipped_no_homepage_html", extra={"base_url": base_url})
            return NavigationTree(), NavCoverageReport(total_urls=len(pages)), pages

        navigation = parse_navigation(homepage_html, base_url)
        assignments, coverage = assign_navigation(navigation, pages)

        placed = tuple(
            page.model_copy(
                update={
                    "nav_parent_url": assignment.nav_parent_url,
                    "breadcrumb_path": assignment.nav_path,
                }
            )
            if (assignment := assignments.get(page.url)) is not None
            else page
            for page in pages
        )
        return navigation, coverage, placed

    # -- internals ---------------------------------------------------------

    def _discover(
        self,
        fetcher: HttpFetcher,
        payload: PageClassificationInput,
        site_profile: SiteProfile,
    ) -> tuple[SiteGraph, DiscoveryReport]:
        """Run discovery, concurrently where possible.

        ADR 0003's design is exactly this: governance is synchronous because it
        is per-job, while the crawl inside `execute()` is async because it is
        per-request. `asyncio.run` is safe here because `BaseTool.run()` is
        synchronous — but if a caller has somehow arranged otherwise, falling
        back to the serial path is far better than raising.
        """
        kwargs = {
            "site_profile": site_profile,
            "max_pages": payload.resolved_max_pages,
            "max_depth": payload.max_depth,
            "crawl_dom": payload.crawl_dom,
            "dom_reserve_fraction": payload.dom_reserve_fraction,
            "on_progress": self._progress_sink,
            "on_checkpoint": self._checkpoint_sink,
        }

        if payload.use_async_crawl and not _event_loop_running():
            return asyncio.run(
                adiscover_site(fetcher, payload.base_url, concurrency=payload.concurrency, **kwargs)  # type: ignore[arg-type]
            )

        if payload.use_async_crawl:
            _logger.warning("async_crawl_unavailable_in_running_loop")
        return discover_site(fetcher, payload.base_url, **kwargs)  # type: ignore[arg-type]

    def _resolve_fetcher(self, payload: PageClassificationInput) -> tuple[HttpFetcher, bool]:
        """Return the fetcher to use, and whether this job owns its lifetime."""
        if self._fetcher is not None:
            return self._fetcher, False
        fetcher = HttpFetcher(
            url_policy=self._url_policy,
            user_agent=payload.user_agent,
            browser_headers=payload.browser_headers,
            rate_limit_rps=payload.rate_limit_rps,
            # Sized to the crawl's own concurrency: a pool smaller than the
            # worker count makes requests queue on sockets instead of on the
            # rate limiter, and the configured rate is never reached.
            max_connections=max(payload.concurrency, DEFAULT_CONCURRENCY),
            respect_robots=payload.respect_robots,
        )
        return fetcher, True

    def _classify_all(
        self,
        evidence: Sequence[PageEvidence],
        site_profile: SiteProfile,
        payload: PageClassificationInput,
    ) -> tuple[FullPageIntelligenceProfile, ...]:
        """Classify every page, escalating the ambiguous ones as one batch."""
        llm_signals = self._resolve_escalations(evidence, site_profile, payload)
        return tuple(
            classify_page(
                item,
                site_profile=site_profile,
                local_classifier=self._local_classifier,
                llm_signal=llm_signals.get(item.normalized_path),
            )
            for item in evidence
        )

    def _resolve_escalations(
        self,
        evidence: Sequence[PageEvidence],
        site_profile: SiteProfile,
        payload: PageClassificationInput,
    ) -> Mapping[str, SignalScore]:
        """Run Layer 3 over the pages Layers 0-2 could not settle.

        Escalating pages are identified *before* any call is made, so they can
        be submitted as one batch. Per ADR 0005 the batch discount is the
        difference between meeting the cost target and missing it by 2x.
        """
        if self._llm_classifier is None or payload.llm_spend_cap_usd <= 0:
            return {}

        ambiguous = [
            item
            for item in evidence
            if needs_llm_escalation(
                item, site_profile=site_profile, local_classifier=self._local_classifier
            )
        ]
        if not ambiguous:
            return {}

        _logger.info(
            "llm_escalation_batch",
            extra={
                "pages": len(ambiguous),
                "of_total": len(evidence),
                "cap_usd": payload.llm_spend_cap_usd,
            },
        )

        try:
            return self._llm_classifier.classify_batch(ambiguous)
        except Exception as exc:  # noqa: BLE001 - Layer 3 is optional by design
            # Degrade, do not fail: every one of these pages still has a
            # structural classification. Losing the LLM refinement is a quality
            # reduction, not a crawl failure.
            _logger.warning("llm_escalation_failed", extra={"error": str(exc)})
            return {}

    def _summarise(
        self,
        pages: Sequence[FullPageIntelligenceProfile],
        discovery: DiscoveryReport,
    ) -> CrawlSummary:
        """Compute the aggregate numbers worth watching."""
        total = len(pages)
        escalated = sum(1 for page in pages if page.escalated_to_llm)
        spent = self._cost_ledger.spent_usd if self._cost_ledger is not None else 0.0

        return CrawlSummary(
            pages_classified=total,
            escalated_to_llm=escalated,
            escalation_rate=(escalated / total) if total else 0.0,
            unknown_pages=sum(
                1 for page in pages if page.primary_page_type is PrimaryPageType.UNKNOWN
            ),
            low_confidence_pages=sum(1 for page in pages if not page.is_confidently_classified),
            orphan_pages=discovery.orphans,
            llm_spend_usd=spent,
        )


def _blocked_message(base_url: str, discovery: DiscoveryReport) -> str:
    """Explain a zero-retrieval crawl in terms the operator can act on.

    Two distinguishable causes, and conflating them would send someone to fix
    the wrong thing:

    * **Requests were made and refused** — bot protection, an IP block, or a
      robots.txt disallow. Nothing about the crawl configuration will change it.
    * **No request was made at all** — every candidate URL was filtered before
      the fetch, which points at the configuration rather than the target.
    """
    if discovery.fetch_failures:
        return (
            f"Crawl failed: all {discovery.fetch_failures} requests to {base_url} were "
            f"refused by the target server. The site is blocking automated clients — "
            f"robots.txt, the sitemap and the homepage were all unreachable, so nothing "
            f"could be classified from real data."
        )
    return (
        f"Crawl failed: no request to {base_url} returned usable content, and none was "
        f"refused either. Every candidate URL was filtered before fetching — check the "
        f"page ceiling and the URL rules."
    )


def _event_loop_running() -> bool:
    """Whether this thread already has a running event loop.

    `asyncio.run()` raises inside one. Detecting it lets the tool degrade to the
    serial crawl rather than failing a job over an execution context it does not
    control.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def register_tools() -> None:
    """Register this module's tools with the process-wide registry.

    Explicit rather than an import-time side effect: a capability nobody
    registered must not silently become available to an agent, and registering
    on import would make that dependent on import order.
    """
    from src.core.registry import registry

    registry.register(PageClassificationTool)
