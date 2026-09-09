"""Per-category penalty totals for an `AuditDataset` (Phase 2a, ADR 0011 D2).

RAE never defined a site score - its sheet lists per-row penalties nothing
sums - and inventing a single number is a product decision this module
deliberately does not make. `ScoringResult` carries category totals only;
there is no field anywhere in this module that could be mistaken for one
number a client reads as "the score" (a test pins that).

`score_dataset` walks `ISSUE_CATALOGUE`, not `dataset.issues`, so every
catalogue row is represented even when the dataset has nothing for it: a
`NOT_MEASURED` issue contributes zero and is counted separately from a
measured issue with zero affected pages, keeping ADR 0011 §5's "not measured
is a value" stance intact through scoring, not just through the contract.

Severity weights are a calibration seam, not a constant sprinkled through the
function body - matching the stance `page_classifier/weights.py` already
takes under ADR 0006: architecture is client-agnostic, calibration is not.
`SEVERITY_WEIGHTS` is the only calibrated vector; a second one needs a
measurement behind it, not a guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from src.core.schemas import StrictModel
from src.modules.seo.contracts.audit import AuditDataset, Coverage
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.contracts.issue_ids import IssueCategory, IssueId, Severity

__all__ = [
    "SEVERITY_WEIGHTS",
    "CategoryPenalty",
    "IssuePenalty",
    "ScoringResult",
    "get_severity_weights",
    "score_dataset",
]

SEVERITY_WEIGHTS: Mapping[Severity, int] = MappingProxyType(
    {Severity.ISSUE: 3, Severity.WARNING: 2, Severity.OPPORTUNITY: 1}
)
"""The only calibrated weight vector. Ordering matches D1's stricter-wins rule
(Issue > Warning > Opportunity); the specific integers are a defensible
default, not a measurement, exactly like `weights.WEIGHT_PROFILES["default"]`."""


def get_severity_weights() -> Mapping[Severity, int]:
    """Return the severity weight vector penalties are computed from.

    This is the seam: `score_dataset` calls this rather than reading
    `SEVERITY_WEIGHTS` directly, so a future calibrated vector (or a
    per-client override, if one is ever justified) is a change here, not a
    rewrite of the scoring loop - the same shape `get_weight_profile()` uses.
    """
    return SEVERITY_WEIGHTS


class IssuePenalty(StrictModel):
    """One catalogue row's contribution: how many pages, how much penalty.

    `penalty` is always `0` when `coverage` is `NOT_MEASURED` - the dataset
    invariant already guarantees `affected_pages` is `0` in that case, this
    just keeps the arithmetic visibly consistent with it.
    """

    issue_id: IssueId
    category: IssueCategory
    coverage: Coverage
    affected_pages: int
    penalty: int


class CategoryPenalty(StrictModel):
    """One `IssueCategory`'s penalty total and how much of it was measured.

    Deliberately has no field that could be summed across categories and
    presented as a site score - that composition is the decision ADR 0011 D2
    defers, not one this model should make by accident.
    """

    category: IssueCategory
    penalty_total: int
    measured_issue_count: int
    not_measured_issue_count: int


class ScoringResult(StrictModel):
    """The scoring output for one dataset: per-issue and per-category, only.

    No `total_penalty`, no `site_score`, no field of any name that aggregates
    across `category_penalties` - ADR 0011 D2 is a boundary this model
    enforces by omission, and `test_scoring.py` asserts the omission holds.
    """

    site: str
    produced_at: datetime
    issue_penalties: tuple[IssuePenalty, ...]
    category_penalties: tuple[CategoryPenalty, ...]


def score_dataset(
    dataset: AuditDataset, *, weights: Mapping[Severity, int] | None = None
) -> ScoringResult:
    """Compute per-category penalty totals for `dataset`.

    Args:
        dataset: The dataset to score. Themes set by `apply_rulebook` (or not)
            make no difference here - scoring is theme-agnostic by design;
            themes are a `Pages` sheet concern for the workbook, not a
            penalty-math concern (plan Phase 2a scope note).
        weights: Severity weight vector. Defaults to `get_severity_weights()`.

    Returns:
        A `ScoringResult` with one `IssuePenalty` per `ISSUE_CATALOGUE` row,
        in catalogue order, and one `CategoryPenalty` per `IssueCategory`, in
        the order each category is first seen in the catalogue.
    """
    active_weights = weights if weights is not None else get_severity_weights()

    issue_penalties: list[IssuePenalty] = []
    category_order: list[IssueCategory] = []
    totals: dict[IssueCategory, int] = {}
    measured_counts: dict[IssueCategory, int] = {}
    not_measured_counts: dict[IssueCategory, int] = {}

    for spec in ISSUE_CATALOGUE:
        if spec.category not in totals:
            category_order.append(spec.category)
            totals[spec.category] = 0
            measured_counts[spec.category] = 0
            not_measured_counts[spec.category] = 0

        coverage = dataset.coverage[spec.id]
        if coverage is Coverage.NOT_MEASURED:
            affected_pages = 0
            penalty = 0
            not_measured_counts[spec.category] += 1
        else:
            affected_pages = len(dataset.issues.get(spec.id, frozenset()))
            penalty = affected_pages * active_weights[spec.severity]
            measured_counts[spec.category] += 1

        totals[spec.category] += penalty
        issue_penalties.append(
            IssuePenalty(
                issue_id=spec.id,
                category=spec.category,
                coverage=coverage,
                affected_pages=affected_pages,
                penalty=penalty,
            )
        )

    category_penalties = tuple(
        CategoryPenalty(
            category=category,
            penalty_total=totals[category],
            measured_issue_count=measured_counts[category],
            not_measured_issue_count=not_measured_counts[category],
        )
        for category in category_order
    )

    return ScoringResult(
        site=dataset.site,
        produced_at=dataset.produced_at,
        issue_penalties=tuple(issue_penalties),
        category_penalties=category_penalties,
    )
