"""The 3-path merged discovery pipeline.

Produces `PageEvidence` — the contract every signal parser consumes and which,
until this module existed, nothing produced. This is the last structural gap
before an end-to-end crawl.

Why three paths
---------------
`docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md` is the empirical case. A sitemap audit
of highradius.com returned 3,145 URLs. A one-second DOM crawl of the homepage
alone surfaced pages absent from every sitemap: `/anti-corruption-and-bribery-policy/`,
`/code-of-ethics/`, `/human-rights-policy/`, `/glossary/`, `/finsider/`.

Sitemaps miss URLs systematically, not occasionally — orphaned campaign pages,
faceted filters generated client-side, and CMS drift where a plugin failed to
update `sitemap.xml`. Any one path alone under-reports.

    Path A  XML sitemaps    → what the webmaster published
    Path B  DOM link graph  → what is actually reachable
    Path C  CMS REST API    → what the database contains
                            ↓
              merged graph G = (V, E), with orphans flagged

An **orphan** is a page that exists in the sitemap or the CMS but has zero
inbound internal links. That is a genuine SEO finding, not a crawl artefact:
nothing on the site points at it, so neither users nor crawlers reach it.

Budget
------
Discovery is bounded by `max_pages` (ADR 0001: build for 20k–500k). The ceiling
is enforced and **reported**, never silently applied — a truncated crawl that
looks complete is worse than one that says it stopped.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.discovery_parsers import (
    extract_page_links,
    parse_link_header,
    parse_shopify_records,
    parse_sitemap,
    parse_wordpress_records,
    with_page_param,
    wordpress_total_pages,
)
from src.modules.seo.page_classifier.signal_parsers import CmsRecord, PageEvidence
from src.modules.seo.page_classifier.url_rules import (
    is_crawlable_url,
    is_faceted_filter,
    is_spider_trap,
    normalize_url,
)
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

__all__ = [
    "ABSOLUTE_MAX_PAGES",
    "DEFAULT_MAX_PAGES",
    "CheckpointSink",
    "ProgressSink",
    "SHOPIFY_ENDPOINTS",
    "WORDPRESS_ENDPOINTS",
    "DiscoveredNode",
    "DiscoveryReport",
    "DiscoverySource",
    "SiteGraph",
    "discover_site",
    "is_refusal",
]

_logger = get_logger("modules.seo.discovery")

DEFAULT_MAX_PAGES = 20_000
"""Node ceiling for one crawl job. ADR 0001 targets 20k–500k; beyond that the
in-memory implementations need replacing with the Bloom-filter path."""

ABSOLUTE_MAX_PAGES = 500_000
"""What "no ceiling" actually resolves to.

There is no genuinely unbounded mode, and offering one would be a lie about the
implementation. `SiteGraph` holds every node **and every page's HTML** in memory;
ADR 0001 sets 500k as the top of the range these structures are built for and
defers the Bloom-filter and disk-spill path needed beyond it.

For any real site this is "everything reachable". For a site large enough to
exceed it, an unbounded crawl would exhaust memory hours in and lose the work —
so the ceiling is stated and reported rather than removed."""

DEFAULT_DOM_RESERVE_FRACTION = 0.2
"""Share of the node budget reserved for URLs only the DOM crawl can find.

Without it, Path A starves Path B on any site whose sitemap is larger than the
budget — and that is most real sites. HighRadius publishes ~3,145 sitemap URLs,
so a 250-page crawl was filled entirely by Path A before the DOM crawl ran, and
`dom_only` was structurally guaranteed to be zero (see
`docs/build-log/0007-first-live-run.md` §4.1 and ADR 0007).

The reserved slots are the *only* ones a sitemap-omitted page can occupy, which
makes them the highest-value slots in the crawl: a URL no sitemap lists is
exactly what an audit is looking for."""

WORDPRESS_ENDPOINTS = (
    ("/wp-json/wp/v2/pages?per_page=100", "page"),
    ("/wp-json/wp/v2/posts?per_page=100", "post"),
)
"""WordPress content endpoints. Public so the async path shares one definition
rather than drifting from a second copy."""

SHOPIFY_ENDPOINTS = (
    ("/products.json?limit=250", "products"),
    ("/collections.json?limit=250", "collections"),
)
"""Shopify catalogue endpoints. Shared with the async path."""

MAX_CMS_PAGES = 40
"""Pages fetched per CMS collection before giving up.

At WordPress's 100 records per page that is 4,000 records, and at Shopify's 250
it is 10,000 — comfortably past the point where the node budget binds instead.
A ceiling is required because pagination termination depends on the remote
server behaving: one that ignores `page` and serves the same response forever
would otherwise loop until the crawl was killed."""


CheckpointSink = Callable[["SiteGraph"], None]
"""Called with the graph so far, so an interruption does not lose the crawl.

Separate from `ProgressSink` because the two carry different things at
different costs: progress is three integers on every page, a checkpoint is the
whole URL set and must be throttled by the implementation. Merging them would
force the cheap call to pay the expensive call's price.

Like `ProgressSink`, it cannot influence the crawl and its exceptions are
swallowed.
"""

ProgressSink = Callable[[int, int, tuple[str, ...]], None]
"""Called as a crawl advances with `(fetched, discovered, recent_urls)`.

Observability only. It cannot influence the crawl and its exceptions are
swallowed, so ADR 0003 still holds: one `BaseTool.run()` is one governed job,
and nothing here introduces a per-page decision point.

Implementations must be cheap and must not block. This is invoked from inside
the fetch loop, including from the concurrent path.
"""


def _checkpoint(sink: CheckpointSink | None, graph: SiteGraph) -> None:
    """Offer the graph for checkpointing. Cheap when the sink declines."""
    if sink is None:
        return
    try:
        sink(graph)
    except Exception as exc:  # noqa: BLE001 - saving work must not lose work
        _logger.debug("checkpoint_sink_failed", extra={"error": str(exc)})


def _notify(sink: ProgressSink | None, graph: SiteGraph, fetched: int, recent: list[str]) -> None:
    """Report progress, never letting a reporting failure break a crawl.

    A telemetry sink writes to disk or a socket. Neither is worth losing a
    twenty-minute crawl over.
    """
    if sink is None:
        return
    try:
        sink(fetched, len(graph), tuple(recent[-20:]))
    except Exception as exc:  # noqa: BLE001 - observability must not break work
        _logger.debug("progress_sink_failed", extra={"error": str(exc)})


class DiscoverySource(StrictModel):
    """Which paths surfaced a URL.

    Kept as flags rather than a single winner, because agreement between paths
    is itself information: a URL found by all three is certainly real, while one
    found only by a DOM link may be a generated artefact.

    Attributes:
        sitemap: Listed in an XML sitemap.
        dom_link: Reached by following a link from another page.
        cms_api: Present in the CMS database.
    """

    sitemap: bool = False
    dom_link: bool = False
    cms_api: bool = False

    @property
    def count(self) -> int:
        """How many independent paths surfaced this URL."""
        return sum((self.sitemap, self.dom_link, self.cms_api))


class DiscoveredNode(StrictModel):
    """One URL in the site graph, with everything discovery learned about it.

    Attributes:
        url: Absolute URL, as first seen.
        normalized: Canonical dedup key from `url_rules.normalize_url`.
        sources: Which paths surfaced it.
        sitemap_source: Grouped sitemap filename, if it came from one.
        cms_record: CMS record, if Path C found one.
        inbound_links: Internal links pointing at it.
        outbound_links: Internal links it emits.
        depth: Link distance from the crawl root, `None` if never linked.
    """

    url: str = Field(min_length=1)
    normalized: str = Field(min_length=1)
    sources: DiscoverySource = DiscoverySource()
    sitemap_source: str | None = None
    cms_record: CmsRecord | None = None
    inbound_links: int = Field(default=0, ge=0)
    outbound_links: int = Field(default=0, ge=0)
    depth: int | None = None

    @property
    def is_orphan(self) -> bool:
        """Whether nothing on the site links here.

        A real SEO finding. A page in the sitemap that no page links to is
        invisible to link-based discovery and accrues no internal authority.
        """
        return self.inbound_links == 0


class DiscoveryReport(StrictModel):
    """Summary of one discovery pass.

    Attributes:
        base_url: Crawl root.
        total_urls: Nodes in the merged graph.
        from_sitemap: Count surfaced by Path A.
        from_dom: Count surfaced by Path B.
        from_cms: Count surfaced by Path C.
        sitemap_only: Present in a sitemap but never linked — orphan candidates.
        dom_only: Reachable by link but absent from every sitemap. These are the
            pages a sitemap-only audit would miss entirely.
        orphans: Nodes with zero inbound internal links.
        sitemaps_fetched: Sitemap files successfully parsed.
        pages_fetched: Pages actually retrieved during the DOM crawl.
        truncated: Whether the page ceiling stopped discovery.
        stopped_reason: Why the crawl was abandoned, if it was.
        dom_reserve: Slots reserved for DOM-only discoveries.
        dom_reserve_used: Reserved slots actually filled. Compare against
            `dom_reserve`: at the cap, the reserve is too small for this site
            and pages the sitemap omits are still being dropped.
    """

    base_url: str
    total_urls: int = Field(default=0, ge=0)
    from_sitemap: int = Field(default=0, ge=0)
    from_dom: int = Field(default=0, ge=0)
    from_cms: int = Field(default=0, ge=0)
    sitemap_only: int = Field(default=0, ge=0)
    dom_only: int = Field(default=0, ge=0)
    orphans: int = Field(default=0, ge=0)
    sitemaps_fetched: int = Field(default=0, ge=0)
    pages_fetched: int = Field(default=0, ge=0)
    fetch_failures: int = Field(default=0, ge=0)
    media_skipped: int = Field(default=0, ge=0)
    """Entries refused because they address a file, not a page.

    Almost always a WordPress `attachment-sitemap.xml`, which lists every
    uploaded image as though it were a page."""
    traps_skipped: int = Field(default=0, ge=0)
    """URLs refused as self-referential crawl loops.

    A finding about the site rather than the crawl: a template emitting
    relative hrefs that resolve one level deeper each time they are followed.
    Observed at 63% of all URLs on one live site."""
    truncated: bool = False
    stopped_reason: str | None = None
    """Why the crawl ended early, or `None` if it ran to completion.

    Distinct from `truncated`, which means the page ceiling was reached — a
    planned stop at a known boundary. This means the crawl was abandoned: the
    target stopped responding, or something failed mid-run. The pages already
    found are real, but the crawl covered less of the site than the settings
    asked for and there is no way to know how much less."""
    dom_reserve: int = Field(default=0, ge=0)
    dom_reserve_used: int = Field(default=0, ge=0)

    @property
    def retrieved_nothing(self) -> bool:
        """Whether the crawl obtained no data from the network at all.

        The distinction that matters: a graph can be non-empty while nothing was
        ever fetched, because the crawl root is seeded as a node before the first
        request. A site behind bot protection therefore produces one confidently
        classified `HOMEPAGE` — classified from the URL string, on no evidence —
        and looks exactly like a successful crawl of a one-page site.

        Observed live: macys.com returned 403 to every request, including
        `robots.txt`, and the run reported `succeeded` with one page at 0.97
        confidence (build-log 0013).
        """
        return self.pages_fetched == 0 and self.sitemaps_fetched == 0 and self.from_cms == 0


class SiteGraph:
    """Mutable builder for the merged site graph.

    A plain class rather than a model: it is assembled incrementally across
    three paths, and `validate_assignment` on every edge insertion would cost
    more than the validation is worth at 20,000 nodes. The values it *emits*
    (`DiscoveredNode`, `PageEvidence`, `DiscoveryReport`) are all strict models.
    """

    def __init__(
        self,
        base_url: str,
        max_pages: int = DEFAULT_MAX_PAGES,
        dom_reserve_fraction: float = DEFAULT_DOM_RESERVE_FRACTION,
    ) -> None:
        """Create an empty graph rooted at `base_url`.

        Args:
            base_url: Crawl root.
            max_pages: Hard node ceiling for the whole graph.
            dom_reserve_fraction: Share of `max_pages` that only the DOM crawl
                may fill. Sitemap and CMS discovery are capped below the hard
                ceiling by this amount, so a sitemap-omitted page always has
                somewhere to land.
        """
        self.base_url = base_url
        self.max_pages = max_pages
        self.dom_reserve = int(max_pages * max(0.0, min(dom_reserve_fraction, 0.9)))
        # At least one slot must remain for the non-DOM paths, or a tiny budget
        # would discover nothing at all before the crawl starts.
        self.pre_crawl_budget = max(1, max_pages - self.dom_reserve)
        self._nodes: dict[str, DiscoveredNode] = {}
        self._html: dict[str, str] = {}
        self.truncated = False
        self.stopped_reason: str | None = None
        """Set when the crawl is abandoned rather than completed. See
        `DiscoveryReport.stopped_reason`."""
        self.fetch_failures = 0
        """Requests actively **refused** by the server, plus transport failures.

        Counted on the graph because every discovery path already holds one, and
        because a crawl that retrieved nothing must be able to say so — silently
        dropping every 403 is what let a fully blocked site report success.

        A `404` is deliberately **not** a refusal. Discovery probes
        `/sitemap_index.xml` and `/sitemap.xml` speculatively and most sites have
        only one of them, so counting 404s would put a non-zero failure count on
        virtually every healthy crawl and destroy the signal this exists to
        carry. See `is_refusal`."""
        self.media_skipped = 0
        """URLs refused because they address a file rather than a page.

        Reported rather than merely dropped: on an image-heavy WordPress site
        this is the difference between "the sitemap listed 400 pages" and "the
        sitemap listed 400 entries, 300 of which were uploads", and a reader
        who cannot see the number has no way to tell those apart."""
        self.traps_skipped = 0
        """URLs refused as self-referential crawl loops.

        A large number here is a finding about the *client's site*, not about
        the crawl: it means a template emits relative hrefs that resolve one
        level deeper every time they are followed. Worth reporting to them."""

    def __len__(self) -> int:
        """Node count."""
        return len(self._nodes)

    @property
    def nodes(self) -> tuple[DiscoveredNode, ...]:
        """Every node, in discovery order."""
        return tuple(self._nodes.values())

    def at_capacity(self) -> bool:
        """Whether the node ceiling has been reached."""
        return len(self._nodes) >= self.max_pages

    def add(
        self,
        url: str,
        *,
        sitemap: bool = False,
        dom_link: bool = False,
        cms_api: bool = False,
        sitemap_source: str | None = None,
        cms_record: CmsRecord | None = None,
        depth: int | None = None,
    ) -> DiscoveredNode | None:
        """Insert or update a node, merging discovery sources.

        Returns:
            The node, or `None` if the URL is not a page, or if the applicable
            ceiling refused a new one. Existing nodes are always updatable, so a
            full graph still records new evidence about URLs it already holds.
        """
        # Enforced here rather than in each discovery path because this is the
        # only function all of them go through. `extract_page_links` screened
        # DOM links and nothing screened the other two, so a WordPress
        # `attachment-sitemap.xml` put every uploaded image into the graph as a
        # page — each one fetched, and each one classified UNKNOWN.
        #
        # The crawl root is exempt: an operator who types a URL ending in a
        # media suffix should get an empty-looking report, not a silently empty
        # graph with no explanation in it.
        if url != self.base_url and not is_crawlable_url(url):
            self.media_skipped += 1
            return None

        # Counted separately from media: a site drowning in loop artefacts has a
        # broken template, and a site full of image URLs has a media sitemap.
        # One number covering both would name neither.
        if url != self.base_url and is_spider_trap(url):
            self.traps_skipped += 1
            return None

        key = normalize_url(url)
        existing = self._nodes.get(key)

        if existing is None:
            # DOM discoveries may use the whole budget; every other path stops
            # at `pre_crawl_budget`, leaving the reserve for URLs no sitemap
            # lists. Without this split, a large sitemap consumes everything and
            # the reserve's beneficiaries are never even offered a slot.
            limit = self.max_pages if dom_link else self.pre_crawl_budget
            if len(self._nodes) >= limit:
                self.truncated = True
                return None
            existing = DiscoveredNode(url=url, normalized=key)
            self._nodes[key] = existing

        merged = existing.sources
        existing.sources = DiscoverySource(
            sitemap=merged.sitemap or sitemap,
            dom_link=merged.dom_link or dom_link,
            cms_api=merged.cms_api or cms_api,
        )
        if sitemap_source and not existing.sitemap_source:
            existing.sitemap_source = sitemap_source
        if cms_record is not None and existing.cms_record is None:
            existing.cms_record = cms_record
        if depth is not None and (existing.depth is None or depth < existing.depth):
            existing.depth = depth
        return existing

    def record_links(self, from_url: str, to_urls: tuple[str, ...], depth: int) -> list[str]:
        """Record outbound links and return every target that entered the graph.

        Returns targets regardless of whether the node already existed. A URL
        already known from the sitemap still has to be *fetched* by the DOM
        crawl, and returning only graph-new URLs would silently skip every page
        the sitemap listed — producing a report full of discovered URLs and
        almost no captured HTML. Crawl-visited bookkeeping belongs to the
        caller's frontier, not to the graph.

        Args:
            from_url: The linking page.
            to_urls: Absolute link targets.
            depth: Link distance of the linking page.

        Returns:
            Targets successfully recorded, for the caller's frontier to filter.
        """
        source = self._nodes.get(normalize_url(from_url))
        if source is not None:
            source.outbound_links += len(to_urls)

        recorded: list[str] = []
        for target in to_urls:
            node = self.add(target, dom_link=True, depth=depth + 1)
            if node is None:
                continue  # Ceiling reached; the graph refused a new node.
            node.inbound_links += 1
            recorded.append(target)
        return recorded

    def store_html(self, url: str, html: str) -> None:
        """Retain a page's HTML for later evidence assembly."""
        self._html[normalize_url(url)] = html

    def all_urls(self) -> tuple[str, ...]:
        """Every URL in the graph, in discovery order.

        Materialised only when a checkpoint is actually being written — at
        20,000 nodes this is the expensive part, and building it per page would
        cost more than the crawl.
        """
        return tuple(node.url for node in self._nodes.values())

    def html_for(self, url: str) -> str | None:
        """Retrieve a stored page body, or `None` if it was never fetched.

        Exists for the navigation parse, which needs the homepage's markup after
        the crawl rather than during it — the header menu is global, so it is
        read once from the root instead of on every page.
        """
        return self._html.get(normalize_url(url))

    def to_page_evidence(self, total_pages: int | None = None) -> tuple[PageEvidence, ...]:
        """Project the graph into the contract the signal parsers consume.

        This is the join between discovery and classification, and the reason
        this module exists.

        Args:
            total_pages: Crawl size for in-degree scaling. Defaults to the node
                count.

        Returns:
            One `PageEvidence` per node.
        """
        size = total_pages if total_pages is not None else len(self._nodes)
        return tuple(
            PageEvidence(
                url=node.url,
                normalized_path=node.normalized,
                html=self._html.get(node.normalized),
                sitemap_source=node.sitemap_source,
                cms_record=node.cms_record,
                inbound_internal_links=node.inbound_links,
                outbound_internal_links=node.outbound_links,
                total_pages_in_crawl=size,
            )
            for node in self._nodes.values()
        )

    def report(self) -> DiscoveryReport:
        """Summarise what each path contributed."""
        nodes = self._nodes.values()
        # Nodes beyond the non-DOM budget can only have arrived via the reserve.
        reserve_used = max(0, len(self._nodes) - self.pre_crawl_budget)
        return DiscoveryReport(
            dom_reserve=self.dom_reserve,
            dom_reserve_used=reserve_used,
            base_url=self.base_url,
            total_urls=len(self._nodes),
            from_sitemap=sum(1 for n in nodes if n.sources.sitemap),
            from_dom=sum(1 for n in nodes if n.sources.dom_link),
            from_cms=sum(1 for n in nodes if n.sources.cms_api),
            sitemap_only=sum(1 for n in nodes if n.sources.sitemap and not n.sources.dom_link),
            dom_only=sum(1 for n in nodes if n.sources.dom_link and not n.sources.sitemap),
            orphans=sum(1 for n in nodes if n.is_orphan),
            fetch_failures=self.fetch_failures,
            media_skipped=self.media_skipped,
            traps_skipped=self.traps_skipped,
            truncated=self.truncated,
            stopped_reason=self.stopped_reason,
        )


def discover_site(
    fetcher: HttpFetcher,
    base_url: str,
    *,
    site_profile: SiteProfile | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int | None = None,
    crawl_dom: bool = True,
    dom_reserve_fraction: float = DEFAULT_DOM_RESERVE_FRACTION,
    on_progress: ProgressSink | None = None,
    on_checkpoint: CheckpointSink | None = None,
) -> tuple[SiteGraph, DiscoveryReport]:
    """Run all three discovery paths and merge them into one graph.

    Args:
        fetcher: Safety-wired fetcher. Every request inherits SSRF validation,
            robots compliance and per-host throttling from it.
        base_url: Site root.
        site_profile: Platform hints from the probe pass. Path C is skipped for
            an unrecognised platform rather than guessed at.
        max_pages: Node ceiling.
        max_depth: Link depth ceiling for the DOM crawl. `None` traverses until
            the link frontier is exhausted or `max_pages` is reached.
        crawl_dom: Disable to run sitemap and CMS discovery only — much cheaper,
            at the cost of missing exactly the pages Path B exists to find.
        dom_reserve_fraction: Share of `max_pages` only the DOM crawl may fill,
            so a large sitemap cannot starve out sitemap-omitted pages.
        on_progress: Optional observability hook, called as pages are fetched.
        on_checkpoint: Optional durability hook, offered the graph so partial
            work survives an interruption. Implementations must throttle.

    Returns:
        The merged graph and its report.
    """
    graph = SiteGraph(base_url, max_pages=max_pages, dom_reserve_fraction=dom_reserve_fraction)

    sitemaps_fetched = _discover_from_sitemaps(fetcher, base_url, graph)
    _discover_from_cms(fetcher, base_url, graph, site_profile)
    # Reported once before the DOM crawl: sitemap and CMS discovery establish the
    # denominator, so without this the first progress reading is 0 of 0.
    _notify(on_progress, graph, 0, [])
    # The sitemap alone is often most of what a crawl will ever know. Saving it
    # before the DOM crawl starts means an interruption seconds in still leaves
    # something worth rendering.
    _checkpoint(on_checkpoint, graph)

    pages_fetched = 0
    if crawl_dom:
        try:
            pages_fetched = _crawl_dom(
                fetcher, base_url, graph, max_depth, on_progress, on_checkpoint
            )
        except Exception as exc:  # noqa: BLE001 - a partial graph beats no graph
            _logger.exception("dom_crawl_aborted", extra={"url": base_url})
            graph.stopped_reason = f"{type(exc).__name__}: {exc}"

    report = graph.report().model_copy(
        update={"sitemaps_fetched": sitemaps_fetched, "pages_fetched": pages_fetched}
    )
    _logger.info("discovery_complete", extra=report.model_dump())
    return graph, report


def _discover_from_sitemaps(fetcher: HttpFetcher, base_url: str, graph: SiteGraph) -> int:
    """Path A — walk the sitemap index and every child sitemap."""
    root = base_url.rstrip("/")
    pending = deque([f"{root}/sitemap_index.xml", f"{root}/sitemap.xml"])
    visited: set[str] = set()
    parsed_count = 0

    while pending:
        sitemap_url = pending.popleft()
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        body = _safe_body(fetcher, sitemap_url, graph)
        if body is None:
            continue

        document = parse_sitemap(body, source_name=sitemap_url.rsplit("/", 1)[-1])
        if document.kind.name == "UNKNOWN":
            continue
        parsed_count += 1

        if document.is_index:
            pending.extend(loc for loc in document.locations if loc not in visited)
            continue

        for location in document.locations:
            graph.add(location, sitemap=True, sitemap_source=document.source_name)

    return parsed_count


def _discover_from_cms(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    site_profile: SiteProfile | None,
) -> None:
    """Path C — read the CMS database directly.

    Skipped entirely for an unrecognised platform. Probing endpoints that are
    not there wastes requests and, on a sensitive host, looks like scanning.
    """
    if site_profile is None or site_profile.cms_family is CmsFamily.UNKNOWN:
        return

    root = base_url.rstrip("/")

    if site_profile.cms_family is CmsFamily.WORDPRESS:
        for path, record_type in WORDPRESS_ENDPOINTS:
            for body in _paginate(fetcher, f"{root}{path}", graph):
                for url, record in parse_wordpress_records(body, record_type).items():
                    graph.add(url, cms_api=True, cms_record=record)

    elif site_profile.cms_family is CmsFamily.SHOPIFY:
        for path, collection in SHOPIFY_ENDPOINTS:
            for body in _paginate(fetcher, f"{root}{path}", graph):
                records = parse_shopify_records(body, root, collection=collection)
                for url, record in records.items():
                    graph.add(url, cms_api=True, cms_record=record)


def _paginate(fetcher: HttpFetcher, endpoint: str, graph: SiteGraph) -> Iterator[str]:
    """Yield every page of a CMS collection, not just the first.

    Reading page one and stopping is what capped the Allbirds crawl at 35 CMS
    records for a much larger catalogue, and CMS coverage is the dominant driver
    of classification confidence (build-log 0010 §4). This is the fix.

    Three termination signals, in order of reliability:

    * **`Link: rel="next"`** — Shopify's cursor pagination. Authoritative, and
      the only signal that exists in the response at all.
    * **`X-WP-TotalPages`** — WordPress states the count up front, so pagination
      stops exactly instead of probing until the server returns an error.
    * **An empty or repeated page** — the universal fallback.

    Args:
        fetcher: Safety-wired fetcher.
        endpoint: First-page URL, already carrying its `per_page`/`limit`.
        graph: Receives the refusal count, so a blocked CMS endpoint is visible
            in the report rather than only in debug logs.

    Yields:
        Response bodies, in page order.
    """
    url: str | None = endpoint
    declared_pages: int | None = None
    seen_bodies: set[int] = set()

    for page in range(1, MAX_CMS_PAGES + 1):
        if url is None:
            return
        try:
            result = fetcher.fetch(url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop discovery
            _logger.debug("cms_page_failed", extra={"url": url, "error": str(exc)})
            graph.fetch_failures += 1
            return
        if not result.ok:
            if is_refusal(result.status_code):
                graph.fetch_failures += 1
            return
        if not result.body.strip():
            return

        # A server that ignores the page parameter serves page one forever.
        # Without this the loop would run to the ceiling collecting duplicates.
        fingerprint = hash(result.body)
        if fingerprint in seen_bodies:
            _logger.debug("cms_pagination_not_advancing", extra={"endpoint": endpoint})
            return
        seen_bodies.add(fingerprint)

        yield result.body

        if declared_pages is None:
            declared_pages = wordpress_total_pages(result.headers)
        if declared_pages is not None and page >= declared_pages:
            return

        next_link = parse_link_header(result.headers.get("link", "")).get("next")
        url = next_link or with_page_param(endpoint, page + 1)

    _logger.info("cms_pagination_ceiling_reached", extra={"endpoint": endpoint})


def _crawl_dom(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    max_depth: int | None,
    on_progress: ProgressSink | None = None,
    on_checkpoint: CheckpointSink | None = None,
) -> int:
    """Path B — breadth-first link traversal from the root.

    Breadth-first rather than depth-first so that when the ceiling is hit, what
    was captured is the shallow, structurally important part of the site rather
    than one arbitrarily deep branch.

    `max_depth=None` traverses without a depth ceiling. That is bounded, not
    unbounded: `graph.record_links` drops targets the graph refused, and the
    graph refuses new nodes at `max_pages`, so the frontier stops growing once
    the budget is spent. `max_pages` is the real limit either way — a depth
    ceiling only decides *which* pages fill it.
    """
    graph.add(base_url, dom_link=True, depth=0)
    frontier: deque[tuple[str, int]] = deque([(base_url, 0)])
    seen: set[str] = {normalize_url(base_url)}
    fetched = 0
    recent: list[str] = []

    while frontier:
        url, depth = frontier.popleft()
        # Capacity deliberately does NOT skip the fetch. `graph.add` already
        # refuses *new* nodes when full, so the frontier stops growing on its
        # own. Skipping here instead meant that whenever the sitemap alone
        # filled the budget, the DOM crawl fetched nothing at all.
        if max_depth is not None and depth > max_depth:
            continue

        # Filter permutations are classified from the URL alone; fetching them
        # is the combinatorial trap the Amazon-scale rules exist to avoid.
        if is_faceted_filter(url):
            continue

        result = _safe_fetch_html(fetcher, url, graph)
        if result is None:
            continue
        fetched += 1
        graph.store_html(url, result)
        recent.append(url)
        _notify(on_progress, graph, fetched, recent)
        _checkpoint(on_checkpoint, graph)

        links = extract_page_links(result, url)
        for target in graph.record_links(url, links, depth):
            key = normalize_url(target)
            if key not in seen:
                seen.add(key)
                frontier.append((target, depth + 1))

    return fetched


def is_refusal(status_code: int) -> bool:
    """Whether a status means the server *declined* rather than lacked the page.

    The distinction decides whether `fetch_failures` is a usable blocked-crawl
    signal or noise. Discovery probes two sitemap URLs speculatively and most
    sites publish only one, so treating `404` as a failure would mark nearly
    every healthy crawl as partly failed.

    Counted: `401`, `403`, `407`, `429` — access refused or rate-limited — and
    any `5xx`, where the server broke rather than answered.
    """
    return status_code in {401, 403, 407, 429} or status_code >= 500


def _safe_body(fetcher: HttpFetcher, url: str, graph: SiteGraph) -> str | None:
    """Fetch a URL, returning `None` for any failure or non-2xx.

    Refusals are counted on the graph rather than only logged at debug level.
    A crawl that is refused everywhere must be able to say so; silently
    discarding every 403 is what let a fully blocked site report success.
    """
    try:
        result = fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("discovery_fetch_failed", extra={"url": url, "error": str(exc)})
        graph.fetch_failures += 1
        return None
    if not result.ok:
        if is_refusal(result.status_code):
            graph.fetch_failures += 1
        return None
    return result.body


def _safe_fetch_html(fetcher: HttpFetcher, url: str, graph: SiteGraph) -> str | None:
    """Fetch a URL, returning its body only when it is HTML.

    A non-HTML 200 is *not* counted as a failure. The server answered; the
    payload simply is not a page. Counting it would inflate the refusal count
    with PDFs and feeds and make a blocked crawl harder to recognise, not
    easier.
    """
    try:
        result = fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("discovery_fetch_failed", extra={"url": url, "error": str(exc)})
        graph.fetch_failures += 1
        return None
    if not result.ok:
        if is_refusal(result.status_code):
            graph.fetch_failures += 1
        return None
    return result.body if result.is_html else None
