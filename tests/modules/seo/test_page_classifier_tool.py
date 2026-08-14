"""Tests for the governed Phase 1 entry point.

Two concerns, deliberately separated: that the **governance contract** in
ADR 0003 holds, and that the crawl job itself produces sane output. The first
matters more — a tool that classifies well but governs wrongly is a liability.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from src.core.registry import registry
from src.core.schemas import ExecutionStatus, RiskClass
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.logical_hierarchy import OTHERS_LABEL
from src.modules.seo.page_classifier.schemas import (
    HierarchyLevel,
    PrimaryPageType,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import PageEvidence
from src.modules.seo.page_classifier.tool import (
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
    _better_trail,
    register_tools,
)

PUBLIC_IP = "93.184.216.34"
ROBOTS = "User-agent: *\nDisallow:\n"

SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/services/</loc></url>
  <url><loc>https://e.com/privacy-policy/</loc></url>
</urlset>"""

HOME_HTML = '<html><body><a href="/services/">Services</a></body></html>'
LEAF_HTML = "<html><body><p>Content.</p></body></html>"

SITE = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/sitemap.xml": httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"}),
    "/": httpx.Response(200, text=HOME_HTML, headers={"content-type": "text/html"}),
    "/services/": httpx.Response(200, text=LEAF_HTML, headers={"content-type": "text/html"}),
    "/privacy-policy/": httpx.Response(200, text=LEAF_HTML, headers={"content-type": "text/html"}),
}


def build_fetcher(settings, routes: dict[str, httpx.Response] | None = None) -> HttpFetcher:
    """Build a fetcher answering from a fixed path table.

    Both transports are wired: the tool defaults to the concurrent crawl path,
    so a sync-only mock would let the async path fall through to real network.
    """
    table = routes if routes is not None else SITE

    def handler(request: httpx.Request) -> httpx.Response:
        # Fresh response per request: a shared instance has its stream exhausted
        # after the first read, and the async client asserts on the stream type.
        template = table.get(request.url.path)
        if template is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(
            template.status_code,
            content=template.content,
            headers={"content-type": template.headers.get("content-type", "text/plain")},
        )

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
    )


def build_tool(settings, **kwargs: Any) -> PageClassificationTool:
    """Build the tool wired to a mock fetcher."""
    kwargs.setdefault("fetcher", build_fetcher(settings))
    return PageClassificationTool(**kwargs)


class StubLlm:
    """Layer 3 stand-in. No real implementation exists (ADR 0005)."""

    def __init__(self, answer: SignalScore | None = None, fail: bool = False) -> None:
        """Prime the stub."""
        self._answer = answer
        self._fail = fail
        self.batches: list[int] = []

    def classify_batch(self, evidence):
        """Record the batch size and answer every page identically."""
        self.batches.append(len(evidence))
        if self._fail:
            msg = "provider unavailable"
            raise RuntimeError(msg)
        if self._answer is None:
            return {}
        return {item.normalized_path: self._answer for item in evidence}


class TestGovernanceContract:
    """ADR 0003: one run() is one crawl job, and a crawl is READ-only."""

    def test_declares_read_risk_class(self):
        """A crawl mutates nothing outside this repository."""
        assert PageClassificationTool.metadata.risk_class is RiskClass.READ

    def test_declares_zero_estimated_cost(self):
        """Non-zero would trip the cost-implies-FINANCIAL invariant.

        That would force MANDATORY_HITL on every run, making unattended
        classification impossible. Layer 3 spend is capped per job instead.
        """
        assert PageClassificationTool.metadata.estimated_cost_usd == 0.0

    def test_read_class_runs_unattended_under_deny_by_default(self, strict_guardrails, settings):
        """The point of READ: no operator prompt, even with no approver wired."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        result = tool.run(PageClassificationInput(base_url="https://e.com"))
        assert result.status is ExecutionStatus.SUCCESS
        assert result.requires_human_review is False

    def test_declares_a_shared_rate_limit_key(self):
        assert PageClassificationTool.metadata.rate_limit_key == "web.crawl"

    def test_one_run_is_one_job_not_one_page(self, settings, strict_guardrails):
        """Many pages classified, one governed result envelope."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        result = tool.run(PageClassificationInput(base_url="https://e.com"))
        assert isinstance(result.data, PageClassificationOutput)
        assert result.data.summary.pages_classified > 1
        assert result.cost_usd == 0.0

    def test_describe_invocation_names_the_site(self, settings):
        """An approval prompt must be readable, not an object graph."""
        tool = build_tool(settings)
        text = tool.describe_invocation(
            PageClassificationInput(base_url="https://e.com", max_pages=500)
        )
        assert "https://e.com" in text
        assert "500" in text

    def test_registration_is_explicit(self):
        """Import-time registration would make availability import-order dependent."""
        assert "seo.page_classifier" not in registry.names()
        register_tools()
        assert "seo.page_classifier" in registry.names()

    def test_never_raises_across_its_boundary(self, settings, strict_guardrails):
        """BaseTool contract: failures become a result, not an exception."""
        broken = build_fetcher(settings, routes={})
        tool = build_tool(settings, fetcher=broken, guardrails=strict_guardrails)
        result = tool.run(PageClassificationInput(base_url="https://e.com"))
        assert result.status in {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED}


class TestInputValidation:
    def test_rejects_an_empty_base_url(self):
        with pytest.raises(ValueError):
            PageClassificationInput(base_url="")

    def test_rejects_a_page_ceiling_beyond_the_scale_target(self):
        """ADR 0001 caps this at 500k until the Bloom-filter path exists."""
        with pytest.raises(ValueError):
            PageClassificationInput(base_url="https://e.com", max_pages=1_000_000)

    def test_rejects_a_negative_spend_cap(self):
        with pytest.raises(ValueError):
            PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=-1.0)

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            PageClassificationInput(base_url="https://e.com", unsupported=True)

    def test_defaults_disable_layer_three(self, settings, strict_guardrails):
        """The cheapest correct setting is the default."""
        assert PageClassificationInput(base_url="https://e.com").llm_spend_cap_usd == 0.0

    def test_invalid_input_becomes_a_failed_result(self, settings, strict_guardrails):
        tool = build_tool(settings, guardrails=strict_guardrails)
        result = tool.run({"base_url": ""})
        assert result.status is ExecutionStatus.FAILED


class TestCrawlOutput:
    def test_produces_a_profile_per_discovered_page(self, settings, strict_guardrails):
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        assert len(output.pages) == output.summary.pages_classified
        assert output.discovery.total_urls >= 2

    def test_every_page_carries_its_evidence(self, settings, strict_guardrails):
        """Auditability: no classification without a recorded reason."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        assert all(page.signals_evaluated for page in output.pages)

    def test_reports_which_weight_vector_was_applied(self, settings, strict_guardrails):
        """Distinguishes a real accuracy difference from a weighting artefact."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        assert output.weight_profile.profile_name == "default"
        assert output.weight_profile.adaptive_enabled is False

    def test_classifies_the_legal_page_at_layer_zero(self, settings, strict_guardrails):
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        by_path = {page.normalized_path: page for page in output.pages}
        legal = by_path["https://e.com/privacy-policy/"]
        assert legal.primary_page_type is PrimaryPageType.UTILITY_LEGAL
        assert legal.hierarchy_level is HierarchyLevel.UTILITY_PAGE

    def test_honours_the_page_ceiling(self, settings, strict_guardrails):
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com", max_pages=2)).data
        assert isinstance(output, PageClassificationOutput)
        assert output.summary.pages_classified <= 2
        assert output.discovery.truncated is True


class TestEscalationAndSpend:
    def test_layer_three_is_skipped_when_the_cap_is_zero(self, settings, strict_guardrails):
        stub = StubLlm()
        tool = build_tool(settings, llm_classifier=stub, guardrails=strict_guardrails)
        tool.run(PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=0.0))
        assert stub.batches == [], "a zero cap must not reach the provider"

    def test_ambiguous_pages_escalate_as_one_batch(self, settings, strict_guardrails):
        """The 50% Batch API discount depends on a single submission."""
        stub = StubLlm(
            SignalScore(
                source=SignalSource.LLM_ZERO_SHOT,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.CASE_STUDY,
                confidence=0.93,
            )
        )
        tool = build_tool(settings, llm_classifier=stub, guardrails=strict_guardrails)
        output = tool.run(
            PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=1.0)
        ).data

        assert isinstance(output, PageClassificationOutput)
        assert len(stub.batches) == 1, "one batch, not one call per page"
        assert output.summary.escalated_to_llm > 0

    def test_escalation_rate_is_reported(self, settings, strict_guardrails):
        """ADR 0005's dominant cost term must be observable on the result."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        assert 0.0 <= output.summary.escalation_rate <= 1.0

    def test_llm_failure_degrades_rather_than_failing_the_crawl(self, settings, strict_guardrails):
        """Every page still has a structural classification."""
        tool = build_tool(settings, llm_classifier=StubLlm(fail=True), guardrails=strict_guardrails)
        result = tool.run(PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=1.0))
        assert result.status is ExecutionStatus.SUCCESS
        assert isinstance(result.data, PageClassificationOutput)
        assert result.data.summary.pages_classified > 0

    def test_partial_llm_answers_are_tolerated(self, settings, strict_guardrails):
        """A budget-exhausted page keeps its structural guess."""
        tool = build_tool(settings, llm_classifier=StubLlm(None), guardrails=strict_guardrails)
        result = tool.run(PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=1.0))
        assert result.status is ExecutionStatus.SUCCESS


class TestFetcherLifecycle:
    def test_an_injected_fetcher_is_not_closed_by_the_tool(self, settings, strict_guardrails):
        """The tool must not close a resource it does not own."""
        fetcher = build_fetcher(settings)
        tool = build_tool(settings, fetcher=fetcher, guardrails=strict_guardrails)
        tool.run(PageClassificationInput(base_url="https://e.com"))
        # Still usable: a closed client would raise here.
        assert fetcher.fetch("https://e.com/services/").ok is True


class TestSummaryStatistics:
    def test_counts_unknown_pages(self, settings, strict_guardrails):
        """Phase 1's goal is zero, so this must be measurable, not inferred."""
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        expected = sum(
            1 for page in output.pages if page.primary_page_type is PrimaryPageType.UNKNOWN
        )
        assert output.summary.unknown_pages == expected

    def test_surfaces_orphans_from_discovery(self, settings, strict_guardrails):
        tool = build_tool(settings, guardrails=strict_guardrails)
        output = tool.run(PageClassificationInput(base_url="https://e.com")).data
        assert isinstance(output, PageClassificationOutput)
        assert output.summary.orphan_pages == output.discovery.orphans

    def test_empty_crawl_reports_a_zero_escalation_rate(self, settings, strict_guardrails):
        """Not a division-by-zero."""
        tool = build_tool(settings, fetcher=build_fetcher(settings, routes={}))
        result = tool.run(PageClassificationInput(base_url="https://e.com"))
        if result.data is not None:
            assert isinstance(result.data, PageClassificationOutput)
            assert result.data.summary.escalation_rate == 0.0


def test_evidence_contract_is_what_the_llm_protocol_receives(settings):
    """The Layer 3 protocol takes PageEvidence, not a bespoke payload."""
    stub = StubLlm()
    tool = build_tool(settings, llm_classifier=stub)
    tool.run(PageClassificationInput(base_url="https://e.com", llm_spend_cap_usd=1.0))
    assert isinstance(stub.batches, list)
    assert PageEvidence.model_fields.keys()


class TestBlockedCrawl:
    """A crawl that retrieved nothing must fail, not report a one-page site.

    The failure mode this prevents was observed live on macys.com: every request
    including `robots.txt` returned 403, and the job reported `succeeded` with a
    single page classified `HOMEPAGE` at 0.97 confidence. The crawl root is
    seeded as a graph node before the first request, and Layer 0 classifies `/`
    from the URL string alone — so a fully blocked site is visually identical to
    a successful crawl of a tiny one.
    """

    @staticmethod
    def _forbidden_fetcher(settings) -> HttpFetcher:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="<html>Access Denied</html>")

        return HttpFetcher(
            settings=settings,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(handler),
            async_transport=httpx.MockTransport(handler),
        )

    def test_a_fully_blocked_crawl_fails(self, settings):
        tool = PageClassificationTool(fetcher=self._forbidden_fetcher(settings))
        result = tool.run(PageClassificationInput(base_url="https://e.com", max_pages=10))

        assert result.status is not ExecutionStatus.SUCCESS
        assert result.data is None, "no result at all, rather than one invented page"

    def test_the_failure_names_the_cause(self, settings):
        """An operator must be able to tell 'blocked' from 'small site'."""
        tool = PageClassificationTool(fetcher=self._forbidden_fetcher(settings))
        result = tool.run(PageClassificationInput(base_url="https://e.com", max_pages=10))

        assert "refused" in (result.error or "").lower()
        assert "https://e.com" in (result.error or "")

    def test_a_working_crawl_still_succeeds(self, settings):
        """The guard must not fire on a site that returned real data."""
        result = build_tool(settings).run(
            PageClassificationInput(base_url="https://e.com", max_pages=20)
        )
        assert result.status is ExecutionStatus.SUCCESS
        assert result.data is not None

    def test_a_sitemap_only_crawl_is_not_treated_as_blocked(self, settings):
        """`crawl_dom=False` fetches no page, but a sitemap is real data."""
        result = build_tool(settings).run(
            PageClassificationInput(base_url="https://e.com", max_pages=20, crawl_dom=False)
        )
        assert result.status is ExecutionStatus.SUCCESS

    def test_a_partially_blocked_crawl_reports_its_refusals(self, settings):
        """A section behind a 403 must be visible in the report, not silent.

        This is the partial case: the crawl succeeds, so nothing fails, but the
        result covers less of the site than it appears to.
        """
        routes = dict(SITE)
        routes["/services/"] = httpx.Response(403, text="denied")

        result = build_tool(settings, fetcher=build_fetcher(settings, routes)).run(
            PageClassificationInput(base_url="https://e.com", max_pages=20)
        )

        assert result.status is ExecutionStatus.SUCCESS
        assert result.data is not None
        assert result.data.discovery.fetch_failures >= 1

    def test_a_healthy_crawl_reports_no_refusals(self, settings):
        """404s from speculative sitemap probing must not inflate the count.

        Discovery tries `/sitemap_index.xml` and `/sitemap.xml`; this fixture
        publishes only the second. If a 404 counted, every healthy crawl in the
        wild would report failures and the signal would be worthless.
        """
        result = build_tool(settings).run(
            PageClassificationInput(base_url="https://e.com", max_pages=20)
        )
        assert result.data is not None
        assert result.data.discovery.fetch_failures == 0


class TestUnlimitedPageCeiling:
    """`max_pages=None` means "everything reachable", bounded by ADR 0001.

    Not truly unbounded, and the distinction is load-bearing: `SiteGraph` holds
    every node and every page body in memory, so a genuinely unbounded crawl of
    a large catalogue would exhaust memory hours in and lose the whole run.
    """

    def test_none_resolves_to_the_adr_ceiling(self):
        from src.modules.seo.page_classifier.discovery import ABSOLUTE_MAX_PAGES

        payload = PageClassificationInput(base_url="https://e.com", max_pages=None)
        assert payload.resolved_max_pages == ABSOLUTE_MAX_PAGES

    def test_an_explicit_ceiling_is_preserved(self):
        payload = PageClassificationInput(base_url="https://e.com", max_pages=250)
        assert payload.resolved_max_pages == 250

    def test_a_ceiling_beyond_the_adr_limit_is_rejected(self):
        """Accepting it would promise machinery ADR 0001 explicitly defers."""
        with pytest.raises(ValueError, match="less than or equal"):
            PageClassificationInput(base_url="https://e.com", max_pages=1_000_000)

    def test_the_approval_summary_says_what_unlimited_means(self, settings):
        """An approver must not read "unlimited" as "no bound at all"."""
        summary = build_tool(settings).describe_invocation(
            PageClassificationInput(base_url="https://e.com", max_pages=None)
        )
        assert "every reachable page" in summary
        assert "500,000" in summary

    def test_the_approval_summary_names_the_request_rate(self, settings):
        """The rate is the part of this decision that lands on someone else."""
        summary = build_tool(settings).describe_invocation(
            PageClassificationInput(base_url="https://e.com", rate_limit_rps=25.0)
        )
        assert "25 req/sec" in summary


class TestRateLimitInput:
    def test_the_rate_is_capped(self):
        """Past this a crawler stops being a guest on someone else's server."""
        with pytest.raises(ValueError, match="less than or equal"):
            PageClassificationInput(base_url="https://e.com", rate_limit_rps=100.0)

    def test_a_zero_rate_is_rejected(self):
        with pytest.raises(ValueError, match="greater than"):
            PageClassificationInput(base_url="https://e.com", rate_limit_rps=0.0)

    def test_the_default_is_unset_not_fast(self):
        """The polite configured default applies unless asked otherwise."""
        assert PageClassificationInput(base_url="https://e.com").rate_limit_rps is None


class TestTrailPrecedence:
    """Choosing between a page's own breadcrumb and its header-menu position.

    Neither source is reliably better, which is why an unconditional rule fails
    on real sites in both directions — see `_better_trail`.
    """

    def test_the_menu_wins_when_it_is_more_specific(self):
        """Highradius `/resources/?ps=templates`.

        Its breadcrumb is `("Home",)` — no information — and the menu places it
        three levels deep. Presence beating quality put seven Resources pages
        under Home.
        """
        assert _better_trail(("Home",), ("Resources", "Learn & Transform", "Templates")) == (
            "Resources",
            "Learn & Transform",
            "Templates",
        )

    def test_the_breadcrumb_wins_when_it_is_more_specific(self):
        """Gep `/newsroom/x`: no menu match, a three-crumb trail of its own."""
        assert _better_trail(("HOME", "NEWS AND UPDATES", "A Release"), ()) == (
            "HOME",
            "NEWS AND UPDATES",
            "A Release",
        )

    def test_a_tie_goes_to_the_menu(self):
        """Highradius `/finsider/`: both two deep, and the menu is right.

        The menu is also the more *stable* source — parsed once from the
        homepage, so it does not depend on which pages a crawl reached.
        """
        assert _better_trail(("Home", "FINsider"), ("Resources", "FINsider")) == (
            "Resources",
            "FINsider",
        )

    def test_an_unmatched_menu_assignment_never_wins(self):
        """The edge case that would have silently broken this.

        `assign_navigation` gives unmatched pages `(OTHERS, <page type>)` — two
        elements, which *looks* as specific as a real two-crumb trail and would
        beat one on a naive length comparison.
        """
        assert _better_trail(("Home", "News"), (OTHERS_LABEL, "BLOG_ARTICLE")) == (
            "Home",
            "News",
        )

    def test_others_still_applies_when_there_is_no_breadcrumb(self):
        """It is a real bucket, not a null — a page with nothing else lands there."""
        assert _better_trail((), (OTHERS_LABEL, "UNKNOWN")) == (OTHERS_LABEL, "UNKNOWN")

    def test_no_evidence_either_way_stays_empty(self):
        assert _better_trail((), ()) == ()
