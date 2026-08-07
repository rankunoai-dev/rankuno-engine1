"""Tests for the accuracy and calibration harness.

Two things matter more than the arithmetic: that a per-archetype breakdown can
never be dropped in favour of a single blended number, and that a report over
too few labels refuses to describe itself as evidence.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.corpus import (
    MIN_ENTRIES_PER_ARCHETYPE,
    CorpusEntry,
    CorpusSite,
    GoldenCorpus,
    SiteArchetype,
)
from src.modules.seo.page_classifier.evaluation import (
    compare_weight_profiles,
    escalation_curve,
    evaluate_predictions,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import CmsRecord, PageEvidence


def label(
    url: str,
    level: HierarchyLevel = HierarchyLevel.L3_LEAF_PAGE,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
) -> CorpusEntry:
    """A labelled entry."""
    return CorpusEntry(url=url, expected_level=level, expected_page_type=page_type, source="test")


def corpus_of(archetype: SiteArchetype, *entries: CorpusEntry) -> CorpusSite:
    """A site holding the given entries."""
    return CorpusSite(
        name=f"site-{archetype.value}",
        base_url="https://e.com",
        archetype=archetype,
        entries=entries,
    )


def prediction(
    url: str,
    level: HierarchyLevel = HierarchyLevel.L3_LEAF_PAGE,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
    confidence: float = 0.9,
    method: ConsensusMethod = ConsensusMethod.WEIGHTED_CONSENSUS,
) -> FullPageIntelligenceProfile:
    """A classified page."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=level,
        primary_page_type=page_type,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=level,
                suggested_page_type=page_type,
                confidence=confidence,
            ),
        ),
        final_confidence_score=confidence,
        consensus_method=method,
    )


class TestScoring:
    def test_a_perfect_run_scores_one(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1"), label("u2")),))
        predictions = {"u1": prediction("u1"), "u2": prediction("u2")}
        report = evaluate_predictions(corpus, predictions)
        assert report.overall.exact_accuracy == pytest.approx(1.0)

    def test_scores_the_two_axes_separately(self):
        """Right level, wrong type is a different failure from the inverse."""
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        predictions = {
            "u1": prediction("u1", page_type=PrimaryPageType.CASE_STUDY),
        }
        report = evaluate_predictions(corpus, predictions)
        assert report.overall.level_accuracy == pytest.approx(1.0)
        assert report.overall.type_accuracy == pytest.approx(0.0)
        assert report.overall.exact_accuracy == pytest.approx(0.0)

    def test_a_missing_prediction_is_not_a_wrong_answer(self):
        """A page never discovered cannot be classified; recall records it."""
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1"), label("u2")),))
        report = evaluate_predictions(corpus, {"u1": prediction("u1")})
        assert report.overall.evaluated == 1
        assert report.overall.missing == 1
        assert report.overall.recall == pytest.approx(0.5)
        assert report.overall.exact_accuracy == pytest.approx(1.0), "scored on what was found"

    def test_counts_unknown_predictions(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        predictions = {"u1": prediction("u1", page_type=PrimaryPageType.UNKNOWN)}
        assert evaluate_predictions(corpus, predictions).overall.unknown_predicted == 1

    def test_counts_escalations(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        predictions = {"u1": prediction("u1", method=ConsensusMethod.LAYER3_LLM_FALLBACK)}
        report = evaluate_predictions(corpus, predictions)
        assert report.overall.escalated == 1
        assert report.overall.escalation_rate == pytest.approx(1.0)

    def test_empty_corpus_does_not_divide_by_zero(self):
        report = evaluate_predictions(GoldenCorpus(), {})
        assert report.overall.exact_accuracy == pytest.approx(0.0)
        assert report.overall.recall == pytest.approx(0.0)


class TestPerArchetypeReporting:
    def build(self) -> tuple[GoldenCorpus, dict[str, FullPageIntelligenceProfile]]:
        """A corpus where one archetype is handled perfectly and one badly."""
        good = corpus_of(SiteArchetype.B2B_SAAS, label("g1"), label("g2"))
        bad = corpus_of(SiteArchetype.ECOMMERCE, label("b1"), label("b2"))
        corpus = GoldenCorpus(sites=(good, bad))
        predictions = {
            "g1": prediction("g1"),
            "g2": prediction("g2"),
            "b1": prediction("b1", page_type=PrimaryPageType.UNKNOWN),
            "b2": prediction("b2", page_type=PrimaryPageType.UNKNOWN),
        }
        return corpus, predictions

    def test_blended_accuracy_hides_a_broken_archetype(self):
        """The exact failure mode the per-archetype breakdown exists to expose."""
        corpus, predictions = self.build()
        report = evaluate_predictions(corpus, predictions)
        assert report.overall.exact_accuracy == pytest.approx(0.5), "looks mediocre overall"

        weakest = report.weakest_archetype
        assert weakest is not None
        assert weakest.archetype is SiteArchetype.ECOMMERCE
        assert weakest.exact_accuracy == pytest.approx(0.0), "actually completely broken"

    def test_archetypes_are_ordered_worst_first(self):
        corpus, predictions = self.build()
        report = evaluate_predictions(corpus, predictions)
        assert report.per_archetype[0].archetype is SiteArchetype.ECOMMERCE

    def test_summary_line_always_names_the_weakest(self):
        corpus, predictions = self.build()
        assert "ECOMMERCE" in evaluate_predictions(corpus, predictions).summary_line()

    def test_unsampled_archetypes_are_omitted_not_scored_as_zero(self):
        """Scoring an unlabelled archetype as 0% would be a fabricated result."""
        corpus, predictions = self.build()
        report = evaluate_predictions(corpus, predictions)
        assert {item.archetype for item in report.per_archetype} == {
            SiteArchetype.B2B_SAAS,
            SiteArchetype.ECOMMERCE,
        }


class TestTrustworthiness:
    def test_a_thin_report_is_not_evidence(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        report = evaluate_predictions(corpus, {"u1": prediction("u1")})
        assert report.overall.exact_accuracy == pytest.approx(1.0)
        assert report.is_trustworthy is False, "100% over one label is not evidence"

    def test_the_caveat_appears_in_the_summary(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        summary = evaluate_predictions(corpus, {"u1": prediction("u1")}).summary_line()
        assert "UNDER-SAMPLED" in summary

    def test_a_well_sampled_report_is_trustworthy(self):
        entries = tuple(label(f"u{i}") for i in range(MIN_ENTRIES_PER_ARCHETYPE))
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, *entries),))
        predictions = {item.url: prediction(item.url) for item in entries}
        report = evaluate_predictions(corpus, predictions)
        assert report.is_trustworthy is True
        assert "UNDER-SAMPLED" not in report.summary_line()

    def test_one_thin_archetype_spoils_the_whole_report(self):
        """Trustworthiness is not an average; a weak bucket invalidates it."""
        many = tuple(label(f"a{i}") for i in range(MIN_ENTRIES_PER_ARCHETYPE))
        corpus = GoldenCorpus(
            sites=(
                corpus_of(SiteArchetype.B2B_SAAS, *many),
                corpus_of(SiteArchetype.ECOMMERCE, label("b1")),
            )
        )
        predictions = {item.url: prediction(item.url) for item in (*many, label("b1"))}
        assert evaluate_predictions(corpus, predictions).is_trustworthy is False


class TestConfusions:
    def test_ranks_the_most_frequent_mistake_first(self):
        entries = [label(f"u{i}") for i in range(5)]
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, *entries),))
        predictions = {
            "u0": prediction("u0", page_type=PrimaryPageType.CASE_STUDY),
            "u1": prediction("u1", page_type=PrimaryPageType.CASE_STUDY),
            "u2": prediction("u2", page_type=PrimaryPageType.CASE_STUDY),
            "u3": prediction("u3", page_type=PrimaryPageType.COMPANY_ABOUT),
            "u4": prediction("u4"),
        }
        confusions = evaluate_predictions(corpus, predictions).confusions
        assert confusions[0].predicted is PrimaryPageType.CASE_STUDY
        assert confusions[0].count == 3
        assert confusions[0].expected is PrimaryPageType.BLOG_ARTICLE

    def test_carries_a_sample_url_to_go_and_look_at(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        predictions = {"u1": prediction("u1", page_type=PrimaryPageType.CASE_STUDY)}
        assert evaluate_predictions(corpus, predictions).confusions[0].sample_url == "u1"

    def test_a_perfect_run_has_no_confusions(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("u1")),))
        assert evaluate_predictions(corpus, {"u1": prediction("u1")}).confusions == ()


class TestEscalationCurve:
    def build(self) -> tuple[GoldenCorpus, dict[str, FullPageIntelligenceProfile]]:
        """Four pages spanning the confidence range, all correctly classified."""
        entries = [label(f"u{i}") for i in range(4)]
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, *entries),))
        predictions = {
            "u0": prediction("u0", confidence=0.55),
            "u1": prediction("u1", confidence=0.72),
            "u2": prediction("u2", confidence=0.88),
            "u3": prediction("u3", confidence=0.96),
        }
        return corpus, predictions

    def test_escalation_rises_with_the_threshold(self):
        corpus, predictions = self.build()
        points = escalation_curve(corpus, predictions, thresholds=(0.5, 0.75, 0.9, 0.99))
        rates = [point.escalation_rate for point in points]
        assert rates == sorted(rates), "a stricter threshold cannot escalate less"

    def test_a_low_threshold_escalates_nothing(self):
        corpus, predictions = self.build()
        point = escalation_curve(corpus, predictions, thresholds=(0.1,))[0]
        assert point.escalation_rate == pytest.approx(0.0)
        assert point.pages_escalated == 0

    def test_a_high_threshold_escalates_everything(self):
        corpus, predictions = self.build()
        point = escalation_curve(corpus, predictions, thresholds=(0.99,))[0]
        assert point.escalation_rate == pytest.approx(1.0)

    def test_reports_accuracy_of_the_pages_that_would_not_escalate(self):
        """The number that decides whether escalating is worth paying for."""
        corpus, predictions = self.build()
        point = escalation_curve(corpus, predictions, thresholds=(0.85,))[0]
        assert point.exact_accuracy == pytest.approx(1.0)
        assert point.pages_escalated == 2

    def test_points_are_returned_in_ascending_threshold_order(self):
        corpus, predictions = self.build()
        points = escalation_curve(corpus, predictions, thresholds=(0.9, 0.5, 0.7))
        assert [p.threshold for p in points] == [0.5, 0.7, 0.9]

    def test_the_specified_threshold_can_be_evaluated(self):
        """ADR 0005 specifies 0.85; the curve must be able to price it."""
        corpus, predictions = self.build()
        point = next(p for p in escalation_curve(corpus, predictions) if p.threshold == 0.85)
        assert point.pages_escalated == 2


class TestWeightProfileComparison:
    def test_scores_every_declared_profile(self):
        entry = label(
            "https://e.com/p/",
            HierarchyLevel.L3_LEAF_PAGE,
            PrimaryPageType.PRODUCT_DETAIL_PAGE,
        )
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.ECOMMERCE, entry),))
        evidence = {
            "https://e.com/p/": PageEvidence(
                url="https://e.com/p/",
                normalized_path="https://e.com/p/",
                cms_record=CmsRecord(record_type="product"),
                sitemap_source="product-sitemap.xml",
            )
        }
        scores = compare_weight_profiles(corpus, evidence)
        assert {score.profile_name for score in scores} == {
            "default",
            "wordpress",
            "shopify",
            "headless",
        }

    def test_results_are_ordered_best_first(self):
        entry = label("https://e.com/p/")
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, entry),))
        evidence = {
            "https://e.com/p/": PageEvidence(
                url="https://e.com/p/",
                normalized_path="https://e.com/p/",
                sitemap_source="blog-sitemap.xml",
            )
        }
        scores = compare_weight_profiles(corpus, evidence)
        accuracies = [score.report.overall.exact_accuracy for score in scores]
        assert accuracies == sorted(accuracies, reverse=True)

    def test_a_specific_subset_can_be_compared(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("https://e.com/p/")),))
        evidence = {
            "https://e.com/p/": PageEvidence(
                url="https://e.com/p/", normalized_path="https://e.com/p/"
            )
        }
        scores = compare_weight_profiles(corpus, evidence, profile_names=("default", "shopify"))
        assert len(scores) == 2

    def test_an_unknown_profile_name_is_skipped(self):
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.B2B_SAAS, label("https://e.com/p/")),))
        evidence = {
            "https://e.com/p/": PageEvidence(
                url="https://e.com/p/", normalized_path="https://e.com/p/"
            )
        }
        assert compare_weight_profiles(corpus, evidence, profile_names=("nope",)) == ()

    def test_the_headless_profile_genuinely_differs(self):
        """Proof the override reaches the consensus engine, not just the report.

        The headless vector zeroes CMS_API_ENDPOINT, so a page whose only strong
        signal is its CMS record must score differently under it.
        """
        entry = label(
            "https://e.com/p/",
            HierarchyLevel.L3_LEAF_PAGE,
            PrimaryPageType.PRODUCT_DETAIL_PAGE,
        )
        corpus = GoldenCorpus(sites=(corpus_of(SiteArchetype.ECOMMERCE, entry),))
        evidence = {
            "https://e.com/p/": PageEvidence(
                url="https://e.com/p/",
                normalized_path="https://e.com/p/",
                cms_record=CmsRecord(record_type="product"),
            )
        }
        scored = {
            s.profile_name: s.report.overall for s in compare_weight_profiles(corpus, evidence)
        }
        assert scored["shopify"].exact_correct == 1
        assert scored["headless"].exact_correct == 0, "CMS weight is zero under headless"
