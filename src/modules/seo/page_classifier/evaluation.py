"""Accuracy measurement and calibration against the golden corpus.

Answers the two questions the first live run left open:

* **What weight vector is right?** `compare_weight_profiles` scores each
  declared profile against the same labelled evidence, so ADR 0006's three
  uncalibrated profiles can be fitted rather than guessed.
* **Where should the escalation threshold sit?** `escalation_curve` reports, for
  each candidate threshold, how many pages would escalate and how accurate the
  survivors are — turning ADR 0005's cost model from an assumption into a
  measurement.

Per-archetype, always
---------------------
`AccuracyReport` has no bare "accuracy" attribute at the top level that can be
quoted without its breakdown. A blended figure hides exactly the failure that
matters to an agency: 100% on the archetype you happened to label and 70% on the
one your next client runs. `overall` exists, but `weakest_archetype` sits beside
it and `is_trustworthy` refuses to be true while any archetype is under-sampled.

Two axes, scored separately
---------------------------
`HierarchyLevel` and `PrimaryPageType` are deliberately decoupled (ADR 0002), so
they are scored separately *and* jointly. A run that gets the level right and the
type wrong is a different failure from one that inverts them, and a single
combined number cannot distinguish the two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.cascading_pipeline import classify_page
from src.modules.seo.page_classifier.corpus import (
    MIN_ENTRIES_PER_ARCHETYPE,
    CorpusEntry,
    GoldenCorpus,
    SiteArchetype,
)
from src.modules.seo.page_classifier.schemas import (
    LLM_FALLBACK_CONFIDENCE_THRESHOLD,
    FullPageIntelligenceProfile,
    PrimaryPageType,
)
from src.modules.seo.page_classifier.signal_parsers import PageEvidence
from src.modules.seo.page_classifier.weights import WEIGHT_PROFILES

__all__ = [
    "AccuracyReport",
    "ArchetypeAccuracy",
    "Confusion",
    "EscalationPoint",
    "ProfileScore",
    "compare_weight_profiles",
    "escalation_curve",
    "evaluate_predictions",
]

_logger = get_logger("modules.seo.evaluation")


class Confusion(StrictModel):
    """One expected/predicted pair the engine got wrong, with a count.

    Ranked confusions are the most actionable output here: "SERVICE_DETAIL_PAGE
    predicted as BLOG_ARTICLE, 34 times" names a fixable rule, where an overall
    accuracy figure names nothing.

    Attributes:
        expected: The correct page type.
        predicted: What the engine said.
        count: How often.
        sample_url: One example, for a human to go and look at.
    """

    expected: PrimaryPageType
    predicted: PrimaryPageType
    count: int = Field(default=0, ge=0)
    sample_url: str = ""


class ArchetypeAccuracy(StrictModel):
    """Accuracy over one archetype's labelled entries.

    Attributes:
        archetype: Which archetype, or `None` for the aggregate row.
        evaluated: Labels that had a matching prediction.
        missing: Labels with no prediction — the engine never discovered them.
            Distinct from a wrong answer and far more serious: a page that was
            never found cannot be classified at all.
        level_correct: Correct `HierarchyLevel`.
        type_correct: Correct `PrimaryPageType`.
        exact_correct: Both correct.
        unknown_predicted: Predictions of `UNKNOWN`. Phase 1 targets zero.
        escalated: Predictions that consumed a Layer 3 call.
        sufficient_sample: Whether `evaluated` reaches the corpus floor.
    """

    archetype: SiteArchetype | None = None
    evaluated: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    level_correct: int = Field(default=0, ge=0)
    type_correct: int = Field(default=0, ge=0)
    exact_correct: int = Field(default=0, ge=0)
    unknown_predicted: int = Field(default=0, ge=0)
    escalated: int = Field(default=0, ge=0)
    sufficient_sample: bool = False

    def _rate(self, numerator: int) -> float:
        return numerator / self.evaluated if self.evaluated else 0.0

    @property
    def level_accuracy(self) -> float:
        """Share with the correct hierarchy level."""
        return self._rate(self.level_correct)

    @property
    def type_accuracy(self) -> float:
        """Share with the correct page type."""
        return self._rate(self.type_correct)

    @property
    def exact_accuracy(self) -> float:
        """Share with both axes correct. The figure the ≥98% claim refers to."""
        return self._rate(self.exact_correct)

    @property
    def escalation_rate(self) -> float:
        """Share that reached the paid layer. ADR 0005's dominant cost term."""
        return self._rate(self.escalated)

    @property
    def recall(self) -> float:
        """Share of labelled pages the engine actually discovered."""
        total = self.evaluated + self.missing
        return self.evaluated / total if total else 0.0


class AccuracyReport(StrictModel):
    """Full evaluation of one prediction set against the corpus.

    Attributes:
        overall: Aggregate across every archetype. **Do not quote without
            `weakest_archetype`** — see the module docstring.
        per_archetype: Per-archetype breakdown, worst first.
        confusions: Most frequent misclassifications, worst first.
        threshold: Confidence threshold in force when this was produced.
    """

    overall: ArchetypeAccuracy
    per_archetype: tuple[ArchetypeAccuracy, ...] = ()
    confusions: tuple[Confusion, ...] = ()
    threshold: float = Field(default=LLM_FALLBACK_CONFIDENCE_THRESHOLD, ge=0.0, le=1.0)

    @property
    def weakest_archetype(self) -> ArchetypeAccuracy | None:
        """The archetype the engine handles worst, among sampled ones."""
        sampled = [item for item in self.per_archetype if item.evaluated]
        return min(sampled, key=lambda item: item.exact_accuracy) if sampled else None

    @property
    def is_trustworthy(self) -> bool:
        """Whether this report may be quoted as evidence about the engine.

        False while any evaluated archetype is under-sampled. A figure computed
        over a handful of labels describes which pages happened to be labelled,
        not the engine, and publishing it would be worse than publishing nothing.
        """
        sampled = [item for item in self.per_archetype if item.evaluated]
        return bool(sampled) and all(item.sufficient_sample for item in sampled)

    def summary_line(self) -> str:
        """One-line verdict, always carrying the weakest archetype."""
        weakest = self.weakest_archetype
        tail = (
            f"weakest {weakest.archetype} at {weakest.exact_accuracy:.1%}"
            if weakest is not None
            else "no archetype sampled"
        )
        caveat = "" if self.is_trustworthy else "  [UNDER-SAMPLED — not evidence]"
        return (
            f"exact {self.overall.exact_accuracy:.1%} over "
            f"{self.overall.evaluated} labels; {tail}{caveat}"
        )


def _score(
    entries: Sequence[CorpusEntry],
    predictions: Mapping[str, FullPageIntelligenceProfile],
    archetype: SiteArchetype | None,
) -> tuple[ArchetypeAccuracy, list[tuple[PrimaryPageType, PrimaryPageType, str]]]:
    """Score one bucket, returning its accuracy and the mistakes it made."""
    evaluated = level_ok = type_ok = exact_ok = unknown = escalated = missing = 0
    mistakes: list[tuple[PrimaryPageType, PrimaryPageType, str]] = []

    for entry in entries:
        predicted = predictions.get(entry.url)
        if predicted is None:
            missing += 1
            continue

        evaluated += 1
        level_hit = predicted.hierarchy_level is entry.expected_level
        type_hit = predicted.primary_page_type is entry.expected_page_type
        level_ok += level_hit
        type_ok += type_hit
        exact_ok += level_hit and type_hit
        unknown += predicted.primary_page_type is PrimaryPageType.UNKNOWN
        escalated += predicted.escalated_to_llm

        if not type_hit:
            mistakes.append((entry.expected_page_type, predicted.primary_page_type, entry.url))

    accuracy = ArchetypeAccuracy(
        archetype=archetype,
        evaluated=evaluated,
        missing=missing,
        level_correct=level_ok,
        type_correct=type_ok,
        exact_correct=exact_ok,
        unknown_predicted=unknown,
        escalated=escalated,
        sufficient_sample=evaluated >= MIN_ENTRIES_PER_ARCHETYPE,
    )
    return accuracy, mistakes


def evaluate_predictions(
    corpus: GoldenCorpus,
    predictions: Mapping[str, FullPageIntelligenceProfile],
    *,
    threshold: float = LLM_FALLBACK_CONFIDENCE_THRESHOLD,
) -> AccuracyReport:
    """Score a prediction set against the corpus, per archetype.

    Args:
        corpus: Labelled ground truth.
        predictions: Profiles keyed by URL. A crawl's output keyed by
            `profile.url` is the expected input.
        threshold: Confidence threshold in force, recorded on the report.

    Returns:
        The evaluation, worst archetype first.
    """
    per_archetype: list[ArchetypeAccuracy] = []
    all_mistakes: list[tuple[PrimaryPageType, PrimaryPageType, str]] = []

    for archetype in SiteArchetype:
        entries = corpus.by_archetype(archetype)
        if not entries:
            continue
        accuracy, mistakes = _score(entries, predictions, archetype)
        per_archetype.append(accuracy)
        all_mistakes.extend(mistakes)

    overall, _ = _score(corpus.entries(), predictions, None)

    counts: dict[tuple[PrimaryPageType, PrimaryPageType], list[str]] = {}
    for expected, predicted, url in all_mistakes:
        counts.setdefault((expected, predicted), []).append(url)

    confusions = tuple(
        Confusion(expected=pair[0], predicted=pair[1], count=len(urls), sample_url=urls[0])
        for pair, urls in sorted(counts.items(), key=lambda item: -len(item[1]))
    )

    report = AccuracyReport(
        overall=overall,
        per_archetype=tuple(sorted(per_archetype, key=lambda item: item.exact_accuracy)),
        confusions=confusions,
        threshold=threshold,
    )
    _logger.info("corpus_evaluated", extra={"summary": report.summary_line()})
    return report


class ProfileScore(StrictModel):
    """One weight profile's accuracy over the same evidence.

    Attributes:
        profile_name: The weight vector scored.
        report: Its evaluation.
    """

    profile_name: str
    report: AccuracyReport


def compare_weight_profiles(
    corpus: GoldenCorpus,
    evidence: Mapping[str, PageEvidence],
    *,
    profile_names: Sequence[str] | None = None,
) -> tuple[ProfileScore, ...]:
    """Score every weight profile against the same labelled evidence.

    This is the calibration primitive ADR 0006 defers to. The three non-default
    profiles are currently informed guesses; running them over labelled evidence
    is what turns them into measurements.

    Args:
        corpus: Labelled ground truth.
        evidence: `PageEvidence` keyed by URL, for the labelled pages.
        profile_names: Profiles to score. Defaults to all declared ones.

    Returns:
        One score per profile, best exact accuracy first.
    """
    names = tuple(profile_names) if profile_names else tuple(WEIGHT_PROFILES)
    scores: list[ProfileScore] = []

    for name in names:
        weights = WEIGHT_PROFILES.get(name)
        if weights is None:
            continue
        predictions = {
            url: classify_page(item, weights_override=weights) for url, item in evidence.items()
        }
        scores.append(
            ProfileScore(profile_name=name, report=evaluate_predictions(corpus, predictions))
        )

    return tuple(sorted(scores, key=lambda item: -item.report.overall.exact_accuracy))


class EscalationPoint(StrictModel):
    """What one confidence threshold would cost and buy.

    Attributes:
        threshold: The candidate threshold.
        escalation_rate: Share of pages that would reach the paid layer.
        exact_accuracy: Accuracy of the pages that would *not* escalate.
        pages_escalated: Absolute count.
    """

    threshold: float = Field(ge=0.0, le=1.0)
    escalation_rate: float = Field(ge=0.0, le=1.0)
    exact_accuracy: float = Field(ge=0.0, le=1.0)
    pages_escalated: int = Field(default=0, ge=0)


def escalation_curve(
    corpus: GoldenCorpus,
    predictions: Mapping[str, FullPageIntelligenceProfile],
    thresholds: Sequence[float] = (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95),
) -> tuple[EscalationPoint, ...]:
    """Trace escalation rate and retained accuracy across candidate thresholds.

    The measurement ADR 0005's cost model needs. The live run showed 98%
    escalation at the specified 0.85; this shows what the alternatives cost.

    Reading it: escalation rate is the bill, `exact_accuracy` is what the free
    layers get right unaided. A threshold worth choosing is one where accuracy
    is already high enough that escalating adds little.

    Args:
        corpus: Labelled ground truth.
        predictions: Profiles keyed by URL, with confidence scores intact.
        thresholds: Candidate thresholds.

    Returns:
        One point per threshold, in ascending threshold order.
    """
    expected = corpus.expected()
    points: list[EscalationPoint] = []

    for threshold in sorted(thresholds):
        escalating = 0
        confident_total = 0
        confident_correct = 0

        for url, entry in expected.items():
            predicted = predictions.get(url)
            if predicted is None:
                continue
            if predicted.final_confidence_score < threshold:
                escalating += 1
                continue
            confident_total += 1
            if (
                predicted.hierarchy_level is entry.expected_level
                and predicted.primary_page_type is entry.expected_page_type
            ):
                confident_correct += 1

        evaluated = escalating + confident_total
        points.append(
            EscalationPoint(
                threshold=threshold,
                escalation_rate=escalating / evaluated if evaluated else 0.0,
                exact_accuracy=confident_correct / confident_total if confident_total else 0.0,
                pages_escalated=escalating,
            )
        )

    return tuple(points)
