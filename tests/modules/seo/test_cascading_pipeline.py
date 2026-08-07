"""Tests for the four-layer cascading classification pipeline."""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.cascading_pipeline import (
    ConsensusOutcome,
    classify_page,
    infer_conversion_role,
    infer_search_intent,
    needs_llm_escalation,
    resolve_consensus,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    ConversionRole,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import (
    CmsRecord,
    NavLink,
    PageEvidence,
)


def evidence(**overrides: object) -> PageEvidence:
    """Build page evidence with sensible defaults."""
    defaults: dict[str, object] = {
        "url": "https://e.com/software/order-to-cash/",
        "normalized_path": "/software/order-to-cash/",
    }
    return PageEvidence(**{**defaults, **overrides})  # type: ignore[arg-type]


def signal(
    source: SignalSource,
    level: HierarchyLevel = HierarchyLevel.L3_LEAF_PAGE,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
    confidence: float = 0.9,
) -> SignalScore:
    """Build a signal score."""
    return SignalScore(
        source=source,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=confidence,
    )


class StubClassifier:
    """Layer 2 stand-in. The real one needs a GPU (ADR 0004)."""

    def __init__(self, result: SignalScore | None) -> None:
        """Prime the stub."""
        self._result = result
        self.calls = 0

    def classify(self, evidence: PageEvidence) -> SignalScore | None:
        """Return the primed result."""
        self.calls += 1
        return self._result


class TestConsensus:
    def test_no_signals_yields_no_outcome(self):
        assert resolve_consensus([]) is None

    def test_agreeing_signals_reinforce_each_other(self):
        signals = [
            signal(SignalSource.CMS_API_ENDPOINT),
            signal(SignalSource.SITEMAP_INDEX),
            signal(SignalSource.SCHEMA_JSONLD),
        ]
        outcome = resolve_consensus(signals)
        assert outcome is not None
        assert outcome.suggested_page_type is PrimaryPageType.BLOG_ARTICLE
        assert "3 of 3" in outcome.notes

    def test_heavier_signal_wins_a_disagreement(self):
        """CMS (0.30) outweighs link in-degree (0.10) on equal confidence."""
        signals = [
            signal(SignalSource.CMS_API_ENDPOINT, page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE),
            signal(SignalSource.LINK_IN_DEGREE, page_type=PrimaryPageType.BLOG_ARTICLE),
        ]
        outcome = resolve_consensus(signals)
        assert outcome is not None
        assert outcome.suggested_page_type is PrimaryPageType.PRODUCT_DETAIL_PAGE

    def test_lone_weak_signal_does_not_report_false_uncertainty(self):
        """Normalising against the full vector would make this look like 0.15.

        A page seen only by the sitemap signal at 0.75 confidence is 0.75
        confident, not 0.15. Getting this wrong escalates nearly every page to
        the paid layer, turning a missing signal into a bill.
        """
        outcome = resolve_consensus([signal(SignalSource.SITEMAP_INDEX, confidence=0.75)])
        assert outcome is not None
        assert outcome.confidence == pytest.approx(0.75)

    def test_confidence_never_exceeds_one(self):
        signals = [
            signal(s, confidence=1.0)
            for s in SignalSource
            if s
            in (
                SignalSource.CMS_API_ENDPOINT,
                SignalSource.ARIA_NAV_TREE,
                SignalSource.SITEMAP_INDEX,
            )
        ]
        outcome = resolve_consensus(signals)
        assert outcome is not None
        assert outcome.confidence <= 1.0

    def test_zero_weight_signals_are_ignored(self):
        """LLM_ZERO_SHOT carries no consensus weight by design."""
        assert resolve_consensus([signal(SignalSource.LLM_ZERO_SHOT)]) is None


class TestLayerZero:
    def test_homepage_exits_at_layer_zero(self):
        profile = classify_page(evidence(url="https://e.com/", normalized_path="/"))
        assert profile.consensus_method is ConsensusMethod.LAYER0_FAST_PATH
        assert profile.hierarchy_level is HierarchyLevel.L0_HOMEPAGE
        assert profile.primary_page_type is PrimaryPageType.HOMEPAGE

    def test_legal_page_exits_at_layer_zero(self):
        profile = classify_page(
            evidence(url="https://e.com/privacy-policy/", normalized_path="/privacy-policy/")
        )
        assert profile.consensus_method is ConsensusMethod.LAYER0_FAST_PATH
        assert profile.primary_page_type is PrimaryPageType.UTILITY_LEGAL

    def test_faceted_url_exits_before_any_fetch(self):
        profile = classify_page(
            evidence(url="https://e.com/shop?color=red&size=xl", normalized_path="/shop/")
        )
        assert profile.consensus_method is ConsensusMethod.LAYER0_FAST_PATH
        assert profile.primary_page_type is PrimaryPageType.FACETED_FILTER

    def test_layer_zero_result_still_carries_evidence(self):
        """Every profile must be auditable, including free ones."""
        profile = classify_page(evidence(url="https://e.com/", normalized_path="/"))
        assert len(profile.signals_evaluated) >= 1


class TestLayerOne:
    def test_strong_structural_consensus_settles_the_page(self):
        profile = classify_page(
            evidence(
                cms_record=CmsRecord(record_type="product"),
                sitemap_source="product-sitemap.xml",
            )
        )
        assert profile.consensus_method is ConsensusMethod.LAYER1_STRUCTURAL
        assert profile.primary_page_type is PrimaryPageType.PRODUCT_DETAIL_PAGE
        assert profile.escalated_to_llm is False

    def test_records_every_contributing_signal(self):
        profile = classify_page(
            evidence(
                cms_record=CmsRecord(record_type="product"),
                sitemap_source="product-sitemap.xml",
                nav_links=(NavLink(href="/software/order-to-cash/", nav_depth=0),),
            )
        )
        assert len(profile.signals_evaluated) == 3


class TestEscalation:
    def test_weak_evidence_reaches_layer_two(self):
        stub = StubClassifier(
            signal(SignalSource.LLM_ZERO_SHOT, page_type=PrimaryPageType.CASE_STUDY, confidence=0.9)
        )
        profile = classify_page(evidence(sitemap_source="sitemap1.xml"), local_classifier=stub)
        assert stub.calls == 1
        assert profile.consensus_method is ConsensusMethod.LAYER2_LOCAL_ML

    def test_layer_two_abstention_falls_through_to_layer_three(self):
        profile = classify_page(
            evidence(),
            local_classifier=StubClassifier(None),
            llm_signal=signal(SignalSource.LLM_ZERO_SHOT, confidence=0.93),
        )
        assert profile.consensus_method is ConsensusMethod.LAYER3_LLM_FALLBACK
        assert profile.escalated_to_llm is True

    def test_strong_pages_never_reach_the_paid_layer(self):
        stub = StubClassifier(signal(SignalSource.LLM_ZERO_SHOT))
        classify_page(evidence(url="https://e.com/", normalized_path="/"), local_classifier=stub)
        assert stub.calls == 0, "Layer 0 settled it; Layer 2 must not run"

    def test_unclassifiable_page_returns_unknown_rather_than_raising(self):
        """A crawl must not die on one page it cannot classify."""
        profile = classify_page(evidence())
        assert profile.primary_page_type is PrimaryPageType.UNKNOWN
        assert profile.final_confidence_score == pytest.approx(0.0)
        assert profile.is_confidently_classified is False


class TestEscalationPrediction:
    def test_predicts_no_escalation_for_layer_zero_pages(self):
        assert needs_llm_escalation(evidence(url="https://e.com/", normalized_path="/")) is False

    def test_predicts_no_escalation_for_strong_structural_evidence(self):
        assert (
            needs_llm_escalation(
                evidence(
                    cms_record=CmsRecord(record_type="product"),
                    sitemap_source="product-sitemap.xml",
                )
            )
            is False
        )

    def test_predicts_escalation_for_bare_evidence(self):
        """Enables batching: the 50% Batch API discount depends on knowing first."""
        assert needs_llm_escalation(evidence()) is True

    def test_layer_two_availability_changes_the_prediction(self):
        confident = StubClassifier(signal(SignalSource.LLM_ZERO_SHOT, confidence=0.95))
        assert needs_llm_escalation(evidence(), local_classifier=confident) is False


class TestDerivedFields:
    @pytest.mark.parametrize(
        ("page_type", "expected"),
        [
            (PrimaryPageType.PRODUCT_DETAIL_PAGE, SearchIntent.TRANSACTIONAL),
            (PrimaryPageType.COMMERCIAL_LEAD_GEN, SearchIntent.TRANSACTIONAL),
            (PrimaryPageType.PRODUCT_CATEGORY_HUB, SearchIntent.COMMERCIAL_INVESTIGATION),
            (PrimaryPageType.CASE_STUDY, SearchIntent.COMMERCIAL_INVESTIGATION),
            (PrimaryPageType.BLOG_ARTICLE, SearchIntent.INFORMATIONAL),
            (PrimaryPageType.HOMEPAGE, SearchIntent.NAVIGATIONAL),
        ],
    )
    def test_intent_follows_from_page_type(self, page_type, expected):
        assert infer_search_intent(HierarchyLevel.L3_LEAF_PAGE, page_type) is expected

    @pytest.mark.parametrize(
        ("page_type", "expected"),
        [
            (PrimaryPageType.PRODUCT_DETAIL_PAGE, ConversionRole.DIRECT_SALE),
            (PrimaryPageType.COMMERCIAL_LEAD_GEN, ConversionRole.LEAD_GENERATION),
            (PrimaryPageType.CASE_STUDY, ConversionRole.BRAND_AWARENESS),
            (PrimaryPageType.BLOG_ARTICLE, ConversionRole.INFORMATIONAL_SUPPORT),
            (PrimaryPageType.UTILITY_LEGAL, ConversionRole.NONE),
        ],
    )
    def test_conversion_role_follows_from_page_type(self, page_type, expected):
        assert infer_conversion_role(page_type) is expected


class TestTaxonomyReconciliation:
    def test_conflicting_signals_do_not_fail_the_crawl(self):
        """Independent signals can vote for a pair the taxonomy forbids.

        Rejecting it outright would fail a whole crawl over one disagreement, so
        it is reconciled instead — structural level is trusted over page type.
        """
        outcome = ConsensusOutcome(
            source=SignalSource.SITEMAP_INDEX,
            suggested_level=HierarchyLevel.L0_HOMEPAGE,
            suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
            confidence=0.9,
        )
        assert outcome.suggested_level is HierarchyLevel.L0_HOMEPAGE

    def test_pipeline_emits_only_valid_pairs(self):
        profile = classify_page(
            evidence(
                url="https://e.com/",
                normalized_path="/",
                sitemap_source="blog-pages-sitemap.xml",
            )
        )
        assert profile.hierarchy_level is HierarchyLevel.L0_HOMEPAGE
        assert profile.primary_page_type is PrimaryPageType.HOMEPAGE


class TestEscalationRateMeasurement:
    def test_escalation_rate_is_computable_from_a_result_set(self):
        """ADR 0005's dominant cost term must be observed, not estimated."""
        cheap = [
            classify_page(evidence(url=f"https://e.com/p{i}/privacy/", normalized_path="/privacy/"))
            for i in range(99)
        ]
        expensive = classify_page(
            evidence(), llm_signal=signal(SignalSource.LLM_ZERO_SHOT, confidence=0.9)
        )
        pages = [*cheap, expensive]
        rate = sum(p.escalated_to_llm for p in pages) / len(pages)
        assert rate == pytest.approx(0.01)
        assert sum(1 for p in pages if not p.escalated_to_llm) == 99
