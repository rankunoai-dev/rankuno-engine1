"""Tests for the scoring engine (Phase 2a, ADR 0011 D2).

`make_dataset` / `full_coverage` mirror `test_rulebook.py`'s fixtures so the
two Phase 1/2a test modules read the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from src.modules.seo.contracts.audit import AuditDataset, AuditPage, AuditSource, Coverage
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE, ISSUE_SPECS
from src.modules.seo.contracts.issue_ids import IssueCategory, IssueId, Severity
from src.modules.seo.deliverables.scoring import (
    SEVERITY_WEIGHTS,
    CategoryPenalty,
    IssuePenalty,
    ScoringResult,
    get_severity_weights,
    score_dataset,
)

PRODUCED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def full_coverage() -> dict[IssueId, Coverage]:
    return dict.fromkeys(IssueId, Coverage.NOT_MEASURED)


def make_dataset(**overrides: object) -> AuditDataset:
    base: dict[str, object] = {
        "source": AuditSource.ENGINE,
        "site": "example.com",
        "produced_at": PRODUCED_AT,
        "pages": (AuditPage(url="https://example.com/"),),
        "issues": {},
        "coverage": full_coverage(),
    }
    base.update(overrides)
    return AuditDataset.model_validate(base)


def test_all_not_measured_yields_zero_penalties_everywhere() -> None:
    """A dataset with nothing measured scores zero, not a missing/None value."""
    dataset = make_dataset()

    result = score_dataset(dataset)

    assert len(result.issue_penalties) == len(ISSUE_CATALOGUE)
    assert all(p.penalty == 0 for p in result.issue_penalties)
    assert all(p.coverage is Coverage.NOT_MEASURED for p in result.issue_penalties)
    assert all(cp.penalty_total == 0 for cp in result.category_penalties)
    assert all(cp.measured_issue_count == 0 for cp in result.category_penalties)
    assert all(cp.not_measured_issue_count > 0 for cp in result.category_penalties)


def test_measured_issue_with_zero_members_differs_from_not_measured() -> None:
    """Measured-but-clean and not-measured both score zero, but are distinguishable."""
    coverage = full_coverage()
    coverage[IssueId.H1_MISSING] = Coverage.MEASURED
    dataset = make_dataset(coverage=coverage)

    result = score_dataset(dataset)

    row = next(p for p in result.issue_penalties if p.issue_id is IssueId.H1_MISSING)
    assert row.coverage is Coverage.MEASURED
    assert row.affected_pages == 0
    assert row.penalty == 0

    category_row = next(cp for cp in result.category_penalties if cp.category is IssueCategory.H1)
    assert category_row.measured_issue_count == 1
    assert (
        category_row.not_measured_issue_count
        == len([s for s in ISSUE_CATALOGUE if s.category is IssueCategory.H1]) - 1
    )


def test_penalty_equals_affected_pages_times_severity_weight() -> None:
    """The core formula: affected_pages * SEVERITY_WEIGHTS[severity]."""
    spec = ISSUE_SPECS[IssueId.H1_MISSING]
    pages = (
        AuditPage(url="https://example.com/a"),
        AuditPage(url="https://example.com/b"),
        AuditPage(url="https://example.com/c"),
    )
    coverage = full_coverage()
    coverage[IssueId.H1_MISSING] = Coverage.MEASURED
    dataset = make_dataset(
        pages=pages,
        issues={IssueId.H1_MISSING: frozenset(p.url for p in pages)},
        coverage=coverage,
    )

    result = score_dataset(dataset)

    row = next(p for p in result.issue_penalties if p.issue_id is IssueId.H1_MISSING)
    assert row.affected_pages == 3
    assert row.penalty == 3 * SEVERITY_WEIGHTS[spec.severity]


def test_category_total_sums_only_its_own_issues() -> None:
    """A category's penalty_total is the sum of that category's rows, no others."""
    coverage = full_coverage()
    coverage[IssueId.H1_MISSING] = Coverage.MEASURED
    coverage[IssueId.PAGE_TITLES_MISSING] = Coverage.MEASURED
    pages = (AuditPage(url="https://example.com/a"),)
    dataset = make_dataset(
        pages=pages,
        issues={
            IssueId.H1_MISSING: frozenset({"https://example.com/a"}),
            IssueId.PAGE_TITLES_MISSING: frozenset({"https://example.com/a"}),
        },
        coverage=coverage,
    )

    result = score_dataset(dataset)

    h1_total = next(
        cp for cp in result.category_penalties if cp.category is IssueCategory.H1
    ).penalty_total
    title_total = next(
        cp for cp in result.category_penalties if cp.category is IssueCategory.PAGE_TITLES
    ).penalty_total
    assert h1_total == SEVERITY_WEIGHTS[ISSUE_SPECS[IssueId.H1_MISSING].severity]
    assert title_total == SEVERITY_WEIGHTS[ISSUE_SPECS[IssueId.PAGE_TITLES_MISSING].severity]


def test_custom_weights_are_honoured() -> None:
    """Passing `weights=` overrides `get_severity_weights()` for that call only."""
    coverage = full_coverage()
    coverage[IssueId.H1_MISSING] = Coverage.MEASURED
    pages = (AuditPage(url="https://example.com/a"),)
    dataset = make_dataset(
        pages=pages,
        issues={IssueId.H1_MISSING: frozenset({"https://example.com/a"})},
        coverage=coverage,
    )
    custom = {Severity.ISSUE: 100, Severity.WARNING: 10, Severity.OPPORTUNITY: 1}

    result = score_dataset(dataset, weights=custom)

    row = next(p for p in result.issue_penalties if p.issue_id is IssueId.H1_MISSING)
    assert row.penalty == 100  # H1_MISSING is Severity.ISSUE


def test_get_severity_weights_is_the_default_seam() -> None:
    """`get_severity_weights()` returns the module constant unconditionally today."""
    assert get_severity_weights() == SEVERITY_WEIGHTS


def test_issue_penalties_cover_every_catalogue_row_in_order() -> None:
    """`ScoringResult.issue_penalties` is 1:1 with `ISSUE_CATALOGUE`, same order."""
    dataset = make_dataset()

    result = score_dataset(dataset)

    assert [p.issue_id for p in result.issue_penalties] == [s.id for s in ISSUE_CATALOGUE]


def test_category_penalties_cover_every_category_once() -> None:
    """`ScoringResult.category_penalties` has exactly one row per `IssueCategory`."""
    dataset = make_dataset()

    result = score_dataset(dataset)

    categories = [cp.category for cp in result.category_penalties]
    assert len(categories) == len(set(categories)) == len(IssueCategory)


@pytest.mark.parametrize("model", [ScoringResult, CategoryPenalty, IssuePenalty])
def test_no_model_carries_an_aggregate_score_field(
    model: type[ScoringResult] | type[CategoryPenalty] | type[IssuePenalty],
) -> None:
    """ADR 0011 D2 as a structural guard: no field name suggests a single score.

    `penalty_total` and `penalty` name a *category*'s or *issue*'s own total,
    not a site-wide one; neither matches these banned substrings.
    """
    banned = ("total_penalty", "site_score", "overall_score", "score")
    for field_name in model.model_fields:
        assert not any(bad in field_name.lower() for bad in banned), (
            f"{model.__name__}.{field_name} looks like an aggregate site score"
        )


def test_scoring_result_rejects_unknown_fields() -> None:
    """`StrictModel` boundary: a stray field is a validation error, not silently kept."""
    with pytest.raises(ValidationError):
        ScoringResult(
            site="example.com",
            produced_at=PRODUCED_AT,
            issue_penalties=(),
            category_penalties=(),
            total_penalty=999,  # type: ignore[call-arg]
        )
