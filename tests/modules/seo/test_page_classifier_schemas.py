"""Tests for the Phase 1 classification taxonomy and output contract.

Several tests here pin decisions recorded in `CLAUDE.md` §7 and
`docs/adr/0002-*.md`. If one fails, either the code drifted or a ruling changed
without its ADR being updated. Both are worth stopping for.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.schemas import (
    LLM_FALLBACK_CONFIDENCE_THRESHOLD,
    MAX_CRAWL_DEPTH,
    SIGNAL_WEIGHTS,
    ConsensusMethod,
    ConversionRole,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
    is_valid_taxonomy_pair,
)


def a_signal(
    source: SignalSource = SignalSource.SITEMAP_INDEX,
    level: HierarchyLevel = HierarchyLevel.L3_LEAF_PAGE,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
    confidence: float = 0.9,
) -> SignalScore:
    """Build a signal score with sensible defaults."""
    return SignalScore(
        source=source,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=confidence,
    )


def a_profile(**overrides: object) -> FullPageIntelligenceProfile:
    """Build a valid profile, overriding individual fields."""
    defaults: dict[str, object] = {
        "url": "https://www.highradius.com/resources/Blog/agentic-ai-invoice-processing/",
        "canonical_url": "https://www.highradius.com/resources/Blog/agentic-ai-invoice-processing/",
        "normalized_path": "/resources/blog/agentic-ai-invoice-processing/",
        "hierarchy_level": HierarchyLevel.L3_LEAF_PAGE,
        "primary_page_type": PrimaryPageType.BLOG_ARTICLE,
        "depth_from_l0": 3,
        "search_intent": SearchIntent.INFORMATIONAL,
        "signals_evaluated": (a_signal(),),
        "final_confidence_score": 0.92,
        "consensus_method": ConsensusMethod.WEIGHTED_CONSENSUS,
    }
    return FullPageIntelligenceProfile(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestTaxonomyEnums:
    def test_primary_page_type_has_fourteen_members(self):
        """CLAUDE.md §7 ruling 5: fourteen, not the blueprint's twelve."""
        assert len(PrimaryPageType) == 14

    def test_case_study_and_tool_application_exist(self):
        """Both are referenced by the tree visualizer and the HighRadius audit."""
        assert PrimaryPageType.CASE_STUDY
        assert PrimaryPageType.TOOL_APPLICATION

    def test_taxonomy_enums_are_upper_snake(self):
        """CLAUDE.md §7 ruling 3: domain enums UPPER, governance enums lowercase."""
        for enum_cls in (HierarchyLevel, PrimaryPageType, SearchIntent, SignalSource):
            for member in enum_cls:
                assert member.value == member.value.upper()
                assert member.value == member.name

    def test_six_signal_sources(self):
        assert len(SignalSource) == 6

    def test_five_hierarchy_levels(self):
        assert len(HierarchyLevel) == 5


class TestSignalWeights:
    def test_structural_weights_sum_to_one(self):
        """Pins the weights in CLAUDE_HANDOFF_DIRECTIVE §5.3."""
        assert sum(SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)

    def test_cms_endpoint_is_the_strongest_signal(self):
        """It reads the CMS database directly, so it resolves flat URLs outright."""
        assert max(SIGNAL_WEIGHTS, key=lambda s: SIGNAL_WEIGHTS[s]) is SignalSource.CMS_API_ENDPOINT

    def test_llm_fallback_carries_no_consensus_weight(self):
        """It replaces the structural consensus rather than voting inside it."""
        assert SignalSource.LLM_ZERO_SHOT not in SIGNAL_WEIGHTS
        assert a_signal(source=SignalSource.LLM_ZERO_SHOT).weight == pytest.approx(0.0)

    def test_weights_are_immutable(self):
        """Changing a weight is an architectural decision, not an assignment."""
        with pytest.raises(TypeError):
            SIGNAL_WEIGHTS[SignalSource.ARIA_NAV_TREE] = 0.99  # type: ignore[index]

    def test_weighted_confidence_multiplies_weight(self):
        signal = a_signal(source=SignalSource.SITEMAP_INDEX, confidence=0.5)
        assert signal.weighted_confidence == pytest.approx(0.5 * 0.20)


class TestSignalScore:
    def test_rejects_out_of_range_confidence(self):
        for bad in (-0.1, 1.1):
            with pytest.raises(ValueError):
                a_signal(confidence=bad)

    def test_rejects_unbounded_notes(self):
        """Notes are diagnostic metadata, not a place for LLM prose."""
        with pytest.raises(ValueError):
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.5,
                notes="x" * 501,
            )

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.5,
                reasoning="a prose field that ADR 0002 excluded",
            )


class TestTaxonomyPairValidity:
    def test_homepage_type_requires_l0(self):
        assert is_valid_taxonomy_pair(HierarchyLevel.L0_HOMEPAGE, PrimaryPageType.HOMEPAGE)
        assert not is_valid_taxonomy_pair(HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.HOMEPAGE)

    def test_l0_requires_homepage_type(self):
        assert not is_valid_taxonomy_pair(HierarchyLevel.L0_HOMEPAGE, PrimaryPageType.BLOG_ARTICLE)

    def test_faceted_filter_is_utility_only(self):
        assert is_valid_taxonomy_pair(HierarchyLevel.UTILITY_PAGE, PrimaryPageType.FACETED_FILTER)
        assert not is_valid_taxonomy_pair(
            HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.FACETED_FILTER
        )

    def test_lead_gen_is_permitted_at_utility_level(self):
        """HighRadius /demo-request/ is exactly this pair; it must stay legal."""
        assert is_valid_taxonomy_pair(
            HierarchyLevel.UTILITY_PAGE, PrimaryPageType.COMMERCIAL_LEAD_GEN
        )

    def test_category_hub_is_legal_at_both_l1_and_l2(self):
        """The whole point of decoupling: site structures genuinely differ."""
        for level in (HierarchyLevel.L1_PRIMARY_NAV_HUB, HierarchyLevel.L2_SUB_NAV_HUB):
            assert is_valid_taxonomy_pair(level, PrimaryPageType.PRODUCT_CATEGORY_HUB)

    def test_profile_rejects_an_incoherent_pair(self):
        with pytest.raises(ValueError, match="not a valid page type"):
            a_profile(
                hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
                primary_page_type=PrimaryPageType.HOMEPAGE,
            )


class TestProfileContract:
    def test_builds_a_valid_profile(self):
        profile = a_profile()
        assert profile.primary_page_type is PrimaryPageType.BLOG_ARTICLE
        assert profile.conversion_role is ConversionRole.NONE

    def test_requires_at_least_one_signal(self):
        """A classification with no evidence is not auditable."""
        with pytest.raises(ValueError):
            a_profile(signals_evaluated=())

    def test_rejects_depth_beyond_the_crawl_ceiling(self):
        with pytest.raises(ValueError):
            a_profile(depth_from_l0=MAX_CRAWL_DEPTH + 1)

    def test_depth_is_independent_of_hierarchy_level(self):
        """The click-depth fallacy: depth 1 does not make a page an L1 hub."""
        profile = a_profile(depth_from_l0=1, hierarchy_level=HierarchyLevel.L3_LEAF_PAGE)
        assert profile.depth_from_l0 == 1
        assert profile.hierarchy_level is HierarchyLevel.L3_LEAF_PAGE

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            a_profile(reasoning="free text excluded by ADR 0002")

    def test_rejects_out_of_range_confidence(self):
        with pytest.raises(ValueError):
            a_profile(final_confidence_score=1.5)

    def test_validates_on_assignment(self):
        """StrictModel sets validate_assignment, so mutation is checked too."""
        profile = a_profile()
        with pytest.raises(ValueError):
            profile.final_confidence_score = 2.0


class TestEscalationReporting:
    def test_llm_layer_marks_the_page_as_escalated(self):
        profile = a_profile(consensus_method=ConsensusMethod.LAYER3_LLM_FALLBACK)
        assert profile.escalated_to_llm is True

    def test_structural_layers_are_not_escalations(self):
        for method in (
            ConsensusMethod.LAYER0_FAST_PATH,
            ConsensusMethod.LAYER1_STRUCTURAL,
            ConsensusMethod.LAYER2_LOCAL_ML,
            ConsensusMethod.WEIGHTED_CONSENSUS,
        ):
            assert a_profile(consensus_method=method).escalated_to_llm is False

    def test_escalation_rate_is_measurable_from_a_result_set(self):
        """ADR 0005's dominant cost term must be observable, not estimated."""
        pages = [a_profile(consensus_method=ConsensusMethod.LAYER0_FAST_PATH) for _ in range(99)]
        pages.append(a_profile(consensus_method=ConsensusMethod.LAYER3_LLM_FALLBACK))
        rate = sum(p.escalated_to_llm for p in pages) / len(pages)
        assert rate == pytest.approx(0.01)

    def test_confident_classification_requires_clearing_the_threshold(self):
        assert a_profile(final_confidence_score=0.92).is_confidently_classified is True
        assert a_profile(final_confidence_score=0.5).is_confidently_classified is False

    def test_unknown_is_never_confident(self):
        """Phase 1's goal is zero UNKNOWN, so it cannot count as a success."""
        profile = a_profile(primary_page_type=PrimaryPageType.UNKNOWN, final_confidence_score=0.99)
        assert profile.is_confidently_classified is False

    def test_threshold_matches_the_specified_value(self):
        assert pytest.approx(0.85) == LLM_FALLBACK_CONFIDENCE_THRESHOLD


class TestHighRadiusSamples:
    """The classifications recorded in docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md §3.

    These are the first entries of the golden corpus and must stay expressible.
    """

    @pytest.mark.parametrize(
        ("level", "page_type"),
        [
            (HierarchyLevel.L0_HOMEPAGE, PrimaryPageType.HOMEPAGE),
            (HierarchyLevel.L1_PRIMARY_NAV_HUB, PrimaryPageType.PRODUCT_CATEGORY_HUB),
            (HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.PRODUCT_CATEGORY_HUB),
            (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.PRODUCT_DETAIL_PAGE),
            (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
            (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.CASE_STUDY),
            (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.COMMERCIAL_LEAD_GEN),
            (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.UTILITY_LEGAL),
        ],
    )
    def test_every_recorded_pair_is_valid(self, level, page_type):
        assert is_valid_taxonomy_pair(level, page_type)
