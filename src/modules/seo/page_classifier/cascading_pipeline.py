"""The four-layer cascading classification pipeline.

Each layer is progressively more expensive and progressively more capable, and
a page exits at the first layer confident enough to settle it:

    Layer 0  URL rules              ~0.0ms   $0      ~65% of pages
    Layer 1  Structural consensus   ~1-3ms   $0      ~25% of pages
    Layer 2  Local zero-shot ML     ~15ms    $0      ~8%  of pages
    Layer 3  Governed LLM           ~300ms   paid    <2%  of pages

The economics live in the exit rate, not the model. Per
`docs/adr/0005-llm-provider-strategy-and-cost-metering.md`, reaching the cost
target requires Layers 0-2 to settle 99.5% of pages, so every page one of them
resolves is the cheapest possible optimisation.

Layer 2 is an interface with no implementation. Per
`docs/adr/0004-local-first-deployment-swappable-ml-layer.md` it runs a local
ONNX model on the workstation GPU, which cannot run in CI. Absent an
implementation the cascade falls straight through to Layer 3, which is correct
but more expensive — the pipeline reports this rather than hiding it.

This module performs no I/O. Fetching, LLM invocation and persistence are the
caller's business; `classify_page` takes evidence and returns a profile.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from src.core.logger import get_logger
from src.modules.seo.page_classifier.schemas import (
    LLM_FALLBACK_CONFIDENCE_THRESHOLD,
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
from src.modules.seo.page_classifier.signal_parsers import (
    PageEvidence,
    collect_structural_signals,
)
from src.modules.seo.page_classifier.url_rules import depth_of, url_fast_path
from src.modules.seo.page_classifier.weights import SiteProfile, get_weight_profile

__all__ = [
    "ConsensusOutcome",
    "ZeroShotClassifier",
    "classify_page",
    "infer_conversion_role",
    "infer_search_intent",
    "needs_llm_escalation",
    "resolve_consensus",
]

_logger = get_logger("modules.seo.page_classifier")

# Layer 0 is decisive by construction: it only fires on patterns that are
# unambiguous on any site, so a match is near-certain.
_FAST_PATH_CONFIDENCE = 0.97


@runtime_checkable
class ZeroShotClassifier(Protocol):
    """Layer 2 — local zero-shot model. Interface only; see ADR 0004.

    Implementations run on the workstation GPU and cost nothing per call. A
    cloud implementation can substitute here without the pipeline changing.
    """

    def classify(self, evidence: PageEvidence) -> SignalScore | None:
        """Return a scored suggestion, or `None` if the model abstains."""
        ...


class ConsensusOutcome(SignalScore):
    """A resolved classification plus how it was reached.

    Extends `SignalScore` because the outcome of consensus is structurally the
    same thing as one signal's opinion — a level, a type and a confidence — and
    duplicating that shape would invite the two to drift.

    Attributes:
        method: Which cascade layer settled it.
    """

    method: ConsensusMethod = ConsensusMethod.WEIGHTED_CONSENSUS


def resolve_consensus(
    signals: Sequence[SignalScore],
    weights: Mapping[SignalSource, float] | None = None,
) -> ConsensusOutcome | None:
    """Combine structural signals into one weighted decision.

    Each signal votes for a `(level, page_type)` pair with its confidence scaled
    by its weight. The pair with the highest total wins, and the winning score
    is normalised against the weight that actually participated rather than
    against 1.0.

    That normalisation matters: a page seen only by the sitemap signal
    (weight 0.20) at confidence 0.75 should report ~0.75 confidence, not 0.15.
    Dividing by the full weight vector would make every page look uncertain and
    escalate almost all of them to the paid layer — turning a missing signal
    into a bill.

    Args:
        signals: Structural signal opinions.
        weights: Weight vector. Defaults to the profile from the seam.

    Returns:
        The winning classification, or `None` when no signal had an opinion.
    """
    if not signals:
        return None

    active = weights if weights is not None else get_weight_profile()

    tally: dict[tuple[HierarchyLevel, PrimaryPageType], float] = {}
    participating_weight = 0.0

    for signal in signals:
        weight = active.get(signal.source, 0.0)
        if weight <= 0.0:
            continue
        key = (signal.suggested_level, signal.suggested_page_type)
        tally[key] = tally.get(key, 0.0) + signal.confidence * weight
        participating_weight += weight

    if not tally or participating_weight <= 0.0:
        return None

    (level, page_type), score = max(tally.items(), key=lambda item: item[1])

    # Agreement between independent signals is itself evidence, so a pair backed
    # by several signals should not be penalised relative to a lone strong one.
    confidence = min(1.0, score / participating_weight)

    supporters = sum(
        1
        for s in signals
        if (s.suggested_level, s.suggested_page_type) == (level, page_type)
        and active.get(s.source, 0.0) > 0
    )

    return ConsensusOutcome(
        source=SignalSource.CMS_API_ENDPOINT if supporters else SignalSource.SITEMAP_INDEX,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=confidence,
        notes=f"{supporters} of {len(signals)} signals agreed",
        method=ConsensusMethod.WEIGHTED_CONSENSUS,
    )


def infer_search_intent(level: HierarchyLevel, page_type: PrimaryPageType) -> SearchIntent:
    """Derive search intent from the resolved taxonomy.

    Intent follows from what a page is for. Deriving it rather than classifying
    it separately keeps the two consistent — a product detail page reporting
    `INFORMATIONAL` intent would be a contradiction, not a nuance.

    Args:
        level: Structural position.
        page_type: Functional purpose.

    Returns:
        The intent a searcher landing here most likely has.
    """
    if page_type in {PrimaryPageType.PRODUCT_DETAIL_PAGE, PrimaryPageType.COMMERCIAL_LEAD_GEN}:
        return SearchIntent.TRANSACTIONAL
    if page_type in {
        PrimaryPageType.PRODUCT_CATEGORY_HUB,
        PrimaryPageType.SERVICE_CATEGORY_HUB,
        PrimaryPageType.SERVICE_DETAIL_PAGE,
        PrimaryPageType.CASE_STUDY,
        PrimaryPageType.TOOL_APPLICATION,
    }:
        return SearchIntent.COMMERCIAL_INVESTIGATION
    if page_type in {PrimaryPageType.HOMEPAGE, PrimaryPageType.COMPANY_ABOUT}:
        return SearchIntent.NAVIGATIONAL
    if level is HierarchyLevel.UTILITY_PAGE:
        return SearchIntent.NAVIGATIONAL
    return SearchIntent.INFORMATIONAL


def infer_conversion_role(page_type: PrimaryPageType) -> ConversionRole:
    """Derive the page's funnel role from its type.

    Args:
        page_type: Functional purpose.

    Returns:
        Where this page sits in the conversion funnel.
    """
    if page_type is PrimaryPageType.PRODUCT_DETAIL_PAGE:
        return ConversionRole.DIRECT_SALE
    if page_type in {
        PrimaryPageType.COMMERCIAL_LEAD_GEN,
        PrimaryPageType.SERVICE_DETAIL_PAGE,
        PrimaryPageType.TOOL_APPLICATION,
    }:
        return ConversionRole.LEAD_GENERATION
    if page_type in {PrimaryPageType.CASE_STUDY, PrimaryPageType.COMPANY_ABOUT}:
        return ConversionRole.BRAND_AWARENESS
    if page_type in {PrimaryPageType.BLOG_ARTICLE, PrimaryPageType.BLOG_HUB}:
        return ConversionRole.INFORMATIONAL_SUPPORT
    return ConversionRole.NONE


def _layer0(evidence: PageEvidence) -> ConsensusOutcome | None:
    """Layer 0 — settle the page from its URL alone, if that is conclusive."""
    decided = url_fast_path(evidence.url)
    if decided is None:
        return None
    level, page_type = decided
    return ConsensusOutcome(
        source=SignalSource.SITEMAP_INDEX,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=_FAST_PATH_CONFIDENCE,
        notes="resolved by URL rules before fetch",
        method=ConsensusMethod.LAYER0_FAST_PATH,
    )


def classify_page(
    evidence: PageEvidence,
    *,
    site_profile: SiteProfile | None = None,
    local_classifier: ZeroShotClassifier | None = None,
    llm_signal: SignalScore | None = None,
    weights_override: Mapping[SignalSource, float] | None = None,
) -> FullPageIntelligenceProfile:
    """Classify one page through the cascade.

    Args:
        evidence: Everything known about the page.
        site_profile: Discovered site characteristics, used to select the weight
            vector through the seam in `weights.get_weight_profile`.
        local_classifier: Layer 2 implementation. `None` means the layer is
            unavailable and the cascade falls through to Layer 3.
        llm_signal: Layer 3 result, supplied by the caller because the LLM call
            is I/O and this module performs none. Callers should invoke the LLM
            only when `needs_llm_escalation` would be true — see that helper.
        weights_override: Force a specific weight vector, bypassing the seam.
            The calibration hook: scoring the same evidence under several
            profiles is how the uncalibrated ones in ADR 0006 get fitted. Not
            for production use — a crawl should let the seam choose.

    Returns:
        A complete profile. Never raises for an unclassifiable page: it returns
        `UNKNOWN` with low confidence, which is a measurable defect signal
        rather than a crash mid-crawl.
    """
    weights = weights_override if weights_override is not None else get_weight_profile(site_profile)
    signals: list[SignalScore] = []

    # Layer 0 — free, and decisive when it fires.
    outcome = _layer0(evidence)

    # Layer 1 — structural consensus over the five parsers.
    if outcome is None:
        signals = list(collect_structural_signals(evidence))
        outcome = resolve_consensus(signals, weights)
        if outcome is not None and outcome.confidence >= LLM_FALLBACK_CONFIDENCE_THRESHOLD:
            outcome = outcome.model_copy(update={"method": ConsensusMethod.LAYER1_STRUCTURAL})

    # Layer 2 — local zero-shot ML. Interface only; see ADR 0004.
    if _needs_escalation(outcome) and local_classifier is not None:
        local = local_classifier.classify(evidence)
        if local is not None:
            signals.append(local)
            outcome = ConsensusOutcome(
                source=local.source,
                suggested_level=local.suggested_level,
                suggested_page_type=local.suggested_page_type,
                confidence=local.confidence,
                notes=local.notes,
                method=ConsensusMethod.LAYER2_LOCAL_ML,
            )

    # Layer 3 — governed LLM. Paid, so it only runs on what survived.
    if _needs_escalation(outcome) and llm_signal is not None:
        signals.append(llm_signal)
        outcome = ConsensusOutcome(
            source=SignalSource.LLM_ZERO_SHOT,
            suggested_level=llm_signal.suggested_level,
            suggested_page_type=llm_signal.suggested_page_type,
            confidence=llm_signal.confidence,
            notes=llm_signal.notes,
            method=ConsensusMethod.LAYER3_LLM_FALLBACK,
        )

    if outcome is None:
        outcome = _unresolved()
        _logger.debug("page_unresolved", extra={"url": evidence.url})

    level, page_type = _coerce_valid_pair(outcome)

    # A profile must carry at least one signal to stay auditable. When Layer 0
    # settled the page there are no parser signals, so the outcome itself is the
    # evidence — which is accurate: the URL rule *was* the evidence.
    evaluated = tuple(signals) if signals else (_as_signal(outcome, level, page_type),)

    return FullPageIntelligenceProfile(
        url=evidence.url,
        canonical_url=evidence.url,
        normalized_path=evidence.normalized_path,
        hierarchy_level=level,
        primary_page_type=page_type,
        depth_from_l0=depth_of(evidence.normalized_path),
        breadcrumb_path=evidence.breadcrumb_path,
        # The same value, kept where the navigation pass cannot overwrite it.
        own_breadcrumb=evidence.breadcrumb_path,
        search_intent=infer_search_intent(level, page_type),
        conversion_role=infer_conversion_role(page_type),
        inbound_internal_links_count=evidence.inbound_internal_links,
        outbound_internal_links_count=evidence.outbound_internal_links,
        signals_evaluated=evaluated,
        final_confidence_score=outcome.confidence,
        consensus_method=outcome.method,
    )


def needs_llm_escalation(
    evidence: PageEvidence,
    *,
    site_profile: SiteProfile | None = None,
    local_classifier: ZeroShotClassifier | None = None,
) -> bool:
    """Report whether this page would reach the paid Layer 3.

    Lets a caller batch every escalating page into one Batch API submission
    instead of issuing calls one at a time — the 50% discount in ADR 0005
    depends on this being knowable before any LLM call is made.

    Args:
        evidence: Page evidence.
        site_profile: Site characteristics for weight selection.
        local_classifier: Layer 2 implementation, if available.

    Returns:
        True when Layers 0-2 could not settle the page confidently.
    """
    outcome = _layer0(evidence)
    if outcome is None:
        outcome = resolve_consensus(
            collect_structural_signals(evidence), get_weight_profile(site_profile)
        )
    if _needs_escalation(outcome) and local_classifier is not None:
        local = local_classifier.classify(evidence)
        if local is not None:
            return local.confidence < LLM_FALLBACK_CONFIDENCE_THRESHOLD
    return _needs_escalation(outcome)


# -- internals -------------------------------------------------------------


def _needs_escalation(outcome: ConsensusOutcome | None) -> bool:
    """Whether the current outcome is too weak to stand."""
    return outcome is None or outcome.confidence < LLM_FALLBACK_CONFIDENCE_THRESHOLD


def _unresolved() -> ConsensusOutcome:
    """The outcome for a page no layer could settle."""
    return ConsensusOutcome(
        source=SignalSource.LLM_ZERO_SHOT,
        suggested_level=HierarchyLevel.L3_LEAF_PAGE,
        suggested_page_type=PrimaryPageType.UNKNOWN,
        confidence=0.0,
        notes="no layer produced a classification",
        method=ConsensusMethod.WEIGHTED_CONSENSUS,
    )


def _as_signal(
    outcome: ConsensusOutcome, level: HierarchyLevel, page_type: PrimaryPageType
) -> SignalScore:
    """Project a consensus outcome back onto a plain `SignalScore`.

    Uses the reconciled level and type rather than the outcome's raw pair, so
    the recorded evidence matches the classification that was actually issued.
    """
    return SignalScore(
        source=outcome.source,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=outcome.confidence,
        notes=outcome.notes,
    )


def _coerce_valid_pair(
    outcome: ConsensusOutcome,
) -> tuple[HierarchyLevel, PrimaryPageType]:
    """Force the winning pair into a combination the taxonomy permits.

    Independent signals can vote for a level and a type that cannot coexist —
    a sitemap saying `BLOG_ARTICLE` while nav depth says `L0_HOMEPAGE`. The
    profile validator would reject that outright, failing a whole crawl over one
    disagreement, so it is reconciled here instead. Structural level is trusted
    over page type, because level comes from graph position while type is often
    inferred from a slug.
    """
    level, page_type = outcome.suggested_level, outcome.suggested_page_type
    if is_valid_taxonomy_pair(level, page_type):
        return level, page_type

    if level is HierarchyLevel.L0_HOMEPAGE:
        return level, PrimaryPageType.HOMEPAGE
    if page_type is PrimaryPageType.HOMEPAGE:
        return HierarchyLevel.L0_HOMEPAGE, page_type
    if page_type in {PrimaryPageType.FACETED_FILTER, PrimaryPageType.UTILITY_LEGAL}:
        return HierarchyLevel.UTILITY_PAGE, page_type
    return level, PrimaryPageType.UNKNOWN
