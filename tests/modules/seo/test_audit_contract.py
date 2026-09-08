"""Tests for the `AuditDataset` contract (plan P0-1).

The three invariants are the contract. Each has a test that constructs the
violating dataset directly, so the test fails whenever the validator is absent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from src.modules.seo.contracts.audit import (
    MAX_NOTE_LENGTH,
    AuditDataset,
    AuditLink,
    AuditPage,
    AuditSource,
    Coverage,
    external_urls_note,
)
from src.modules.seo.contracts.catalogue import IssueId

PRODUCED_AT = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
HOME = "https://example.com/"
ABOUT = "https://example.com/about/"
EXTERNAL = "https://elsewhere.net/"


def full_coverage(**overrides: Coverage) -> dict[IssueId, Coverage]:
    coverage = dict.fromkeys(IssueId, Coverage.NOT_MEASURED)
    for name, value in overrides.items():
        coverage[IssueId[name]] = value
    return coverage


def make_dataset(**kwargs: object) -> AuditDataset:
    base: dict[str, object] = {
        "source": "engine",
        "site": "example.com",
        "produced_at": PRODUCED_AT,
        "pages": (AuditPage(url=HOME), AuditPage(url=ABOUT)),
        "issues": {IssueId.H1_MISSING: frozenset({ABOUT})},
        "coverage": full_coverage(H1_MISSING=Coverage.MEASURED),
    }
    base.update(kwargs)
    return AuditDataset.model_validate(base)


# --------------------------------------------------------------------------
# Invariant 1: coverage has every IssueId
# --------------------------------------------------------------------------


def test_invariant_1_missing_coverage_key_is_rejected():
    coverage = full_coverage(H1_MISSING=Coverage.MEASURED)
    del coverage[IssueId.HREFLANG_MISSING]
    with pytest.raises(ValidationError, match="HREFLANG_MISSING"):
        make_dataset(coverage=coverage)


def test_invariant_1_empty_coverage_is_rejected():
    with pytest.raises(ValidationError, match="coverage"):
        make_dataset(coverage={})


# --------------------------------------------------------------------------
# Invariant 2: issue URLs are in pages unless a note admits external URLs
# --------------------------------------------------------------------------


def test_invariant_2_unknown_url_is_rejected():
    with pytest.raises(ValidationError, match="not in pages"):
        make_dataset(issues={IssueId.H1_MISSING: frozenset({EXTERNAL})})


def test_invariant_2_note_admits_external_urls_for_that_issue_only():
    issue = IssueId.INTERNAL_LINKS_4XX_INLINKS
    dataset = make_dataset(
        issues={issue: frozenset({EXTERNAL})},
        coverage=full_coverage(INTERNAL_LINKS_4XX_INLINKS=Coverage.MEASURED),
        notes=(external_urls_note(issue),),
    )
    assert dataset.issues[issue] == frozenset({EXTERNAL})

    # The note is per-issue; it does not license external URLs elsewhere.
    with pytest.raises(ValidationError, match="not in pages"):
        make_dataset(
            issues={IssueId.H1_MISSING: frozenset({EXTERNAL})},
            notes=(external_urls_note(issue),),
        )


# --------------------------------------------------------------------------
# Invariant 3: NOT_MEASURED implies an empty set
# --------------------------------------------------------------------------


def test_invariant_3_not_measured_with_members_is_rejected():
    with pytest.raises(ValidationError, match="NOT_MEASURED"):
        make_dataset(coverage=full_coverage(H1_MISSING=Coverage.NOT_MEASURED))


def test_invariant_3_measured_with_empty_set_is_distinct_and_valid():
    dataset = make_dataset(
        issues={IssueId.H1_MISSING: frozenset()},
        coverage=full_coverage(H1_MISSING=Coverage.MEASURED),
    )
    assert dataset.coverage[IssueId.H1_MISSING] is Coverage.MEASURED
    assert dataset.coverage[IssueId.H1_DUPLICATE] is Coverage.NOT_MEASURED
    assert dataset.issues.get(IssueId.H1_DUPLICATE, frozenset()) == frozenset()


# --------------------------------------------------------------------------
# Invariant 4: pages[].url is unique
# --------------------------------------------------------------------------


def test_invariant_4_duplicate_page_url_is_rejected():
    with pytest.raises(ValidationError, match="unique"):
        make_dataset(pages=(AuditPage(url=HOME), AuditPage(url=ABOUT), AuditPage(url=HOME)))


def test_invariant_4_distinct_urls_pass():
    dataset = make_dataset(pages=(AuditPage(url=HOME), AuditPage(url=ABOUT)))
    assert len(dataset.pages) == 2


# --------------------------------------------------------------------------
# AuditSource is an enum
# --------------------------------------------------------------------------


def test_source_is_a_str_enum():
    assert AuditSource.SCREAMING_FROG == "screaming_frog"
    assert AuditSource.ENGINE == "engine"
    dataset = make_dataset(source=AuditSource.SCREAMING_FROG)
    assert dataset.source is AuditSource.SCREAMING_FROG
    assert dataset.model_dump(mode="json")["source"] == "screaming_frog"
    assert AuditDataset.model_validate(dataset.model_dump(mode="json")) == dataset


# --------------------------------------------------------------------------
# Serialisation and strictness
# --------------------------------------------------------------------------


def test_json_round_trip_is_lossless():
    dataset = make_dataset(
        links=(AuditLink(source=HOME, destination=ABOUT),),
        notes=("denominator: internal HTML pages",),
    )
    payload = dataset.model_dump(mode="json")
    assert payload["coverage"]["H1_MISSING"] == "MEASURED"
    assert AuditDataset.model_validate(payload) == dataset
    assert AuditDataset.model_validate_json(dataset.model_dump_json()) == dataset


def test_formula_like_note_round_trips_unchanged():
    # Phase 2 must write this with write_string; the contract must not touch it.
    note = "=SUM(A1)"
    dataset = make_dataset(notes=(note,))
    assert dataset.notes == (note,)
    assert AuditDataset.model_validate(dataset.model_dump(mode="json")).notes == (note,)


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        make_dataset(score=42)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AuditPage.model_validate({"url": HOME, "title": "x"})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AuditLink.model_validate({"source": HOME, "destination": ABOUT, "anchor": "x"})


def test_validate_assignment_re_runs_invariants():
    dataset = make_dataset()
    with pytest.raises(ValidationError, match="not in pages"):
        dataset.issues = {IssueId.H1_MISSING: frozenset({EXTERNAL})}


# --------------------------------------------------------------------------
# Field bounds (Step 5 conditions)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "site", ["https://example.com", "example.com/", "example.com:443", "Example.com", "localhost"]
)
def test_site_must_be_bare_lowercase_hostname(site: str) -> None:
    with pytest.raises(ValidationError, match="bare lowercase hostname"):
        make_dataset(site=site)


def test_site_accepts_subdomains_and_hyphens():
    assert make_dataset(site="shop.my-site.co.uk").site == "shop.my-site.co.uk"


def test_produced_at_must_be_timezone_aware():
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_dataset(produced_at=datetime(2026, 9, 8, 12, 0))  # noqa: DTZ001


def test_strings_are_whitespace_stripped():
    assert AuditPage(url=f"  {HOME}  ").url == HOME
    assert make_dataset(site="  example.com  ").site == "example.com"


def test_length_caps():
    with pytest.raises(ValidationError, match="at most 2048"):
        AuditPage(url="https://example.com/" + "a" * 2048)
    with pytest.raises(ValidationError, match=str(MAX_NOTE_LENGTH)):
        make_dataset(notes=("n" * (MAX_NOTE_LENGTH + 1),))
    with pytest.raises(ValidationError, match="at most 253"):
        make_dataset(site="a" * 250 + ".com")


def test_source_is_a_closed_set():
    with pytest.raises(ValidationError, match="source"):
        make_dataset(source="rae")
