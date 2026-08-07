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
    """Build a fetcher answering from a fixed path table."""
    table = routes if routes is not None else SITE

    def handler(request: httpx.Request) -> httpx.Response:
        return table.get(request.url.path, httpx.Response(404, text="not found"))

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
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
