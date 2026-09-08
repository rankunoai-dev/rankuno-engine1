"""Tests for the issue catalogue (plan P0-2).

The D1 and D3 resolutions are pinned row by row so that a future edit to a
severity is a deliberate, reviewed change rather than drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from src.modules.seo.contracts.catalogue import (
    ISSUE_CATALOGUE,
    ISSUE_SPECS,
    RAE_LABELS,
    IssueCategory,
    IssueId,
    IssueSpec,
    Priority,
    Severity,
)

FIXTURE_LISTING = (
    Path(__file__).resolve().parents[2] / "fixtures" / "deliverables" / "sf_export_filenames.txt"
)


def sf_export_filenames() -> frozenset[str]:
    lines = FIXTURE_LISTING.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def test_catalogue_has_110_rows_matching_enum_one_to_one():
    assert len(ISSUE_CATALOGUE) == 110
    ids = [spec.id for spec in ISSUE_CATALOGUE]
    assert len(set(ids)) == len(ids)
    assert set(ids) == set(IssueId)
    assert set(ISSUE_SPECS) == set(IssueId)


def test_every_category_is_used():
    assert {spec.category for spec in ISSUE_CATALOGUE} == set(IssueCategory)


def test_category_and_label_pairs_are_unique():
    pairs = [(spec.category, spec.label) for spec in ISSUE_CATALOGUE]
    assert len(set(pairs)) == len(pairs)


def test_blank_severity_or_priority_is_unrepresentable():
    base = {"id": IssueId.H1_MISSING, "category": IssueCategory.H1, "label": "Missing"}
    with pytest.raises(ValidationError):
        IssueSpec.model_validate({**base, "severity": "", "priority": Priority.HIGH})
    with pytest.raises(ValidationError):
        IssueSpec.model_validate({**base, "severity": Severity.ISSUE, "priority": ""})
    with pytest.raises(ValidationError):
        IssueSpec.model_validate({**base, "severity": "Issue"})


def test_catalogue_rows_forbid_extra_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        IssueSpec(
            id=IssueId.H1_MISSING,
            category=IssueCategory.H1,
            label="Missing",
            severity=Severity.ISSUE,
            priority=Priority.HIGH,
            weight=5,  # type: ignore[call-arg]
        )


# --------------------------------------------------------------------------
# Source filenames (D3, plan §8 "hard-coded and partly wrong")
# --------------------------------------------------------------------------


def test_every_sf_source_exists_in_reference_export_listing():
    listing = sf_export_filenames()
    assert len(listing) == 118
    missing = {
        (spec.id, name)
        for spec in ISSUE_CATALOGUE
        for name in spec.sf_sources
        if name not in listing
    }
    assert missing == set()


def test_no_sf_source_is_shared_between_rows():
    seen: dict[str, IssueId] = {}
    for spec in ISSUE_CATALOGUE:
        for name in spec.sf_sources:
            assert name not in seen, f"{name} used by both {seen[name]} and {spec.id}"
            seen[name] = spec.id


def test_d3_security_rows_are_wired_to_real_files():
    expected = {
        IssueId.SECURITY_FORM_URL_INSECURE: ("form_url_insecure.csv",),
        IssueId.SECURITY_FORM_ON_HTTP_URL: ("security_form_on_http_url.csv",),
        IssueId.SECURITY_MISSING_HSTS_HEADER: ("security_missing_hsts_header.csv",),
        IssueId.SECURITY_UNSAFE_CROSS_ORIGIN_LINKS: ("unsafe_crossorigin_links.csv",),
        IssueId.SECURITY_PROTOCOL_RELATIVE_RESOURCE_LINKS: ("protocolrelative_outlinks.csv",),
        IssueId.SECURITY_MISSING_CONTENT_SECURITY_POLICY_HEADER: (
            "security_missing_contentsecuritypolicy_header.csv",
        ),
        IssueId.SECURITY_MISSING_X_CONTENT_TYPE_OPTIONS_HEADER: (
            "security_missing_xcontenttypeoptions_header.csv",
        ),
        IssueId.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER: (
            "security_missing_xframeoptions_header.csv",
        ),
        IssueId.SECURITY_MISSING_SECURE_REFERRER_POLICY_HEADER: (
            "security_missing_secure_referrerpolicy_header.csv",
        ),
        IssueId.SECURITY_BAD_CONTENT_TYPE: ("security_bad_content_type.csv",),
    }
    assert len(expected) == 10
    for issue, sources in expected.items():
        assert ISSUE_SPECS[issue].sf_sources == sources


def test_inlinks_rows_use_the_filenames_screaming_frog_actually_writes():
    # RAE's catalogue named these without the `internal_` prefix; no such files exist.
    assert ISSUE_SPECS[IssueId.INTERNAL_LINKS_4XX_INLINKS].sf_sources == (
        "internal_client_error_(4xx)_inlinks.csv",
    )
    assert ISSUE_SPECS[IssueId.INTERNAL_LINKS_3XX_INLINKS].sf_sources == (
        "internal_redirection_(3xx)_inlinks.csv",
    )


def test_unproducible_rows_have_no_sources():
    unproducible = {spec.id for spec in ISSUE_CATALOGUE if not spec.sf_sources}
    assert unproducible == {
        IssueId.CANONICALS_INVALID_ATTRIBUTE_IN_ANNOTATION,
        IssueId.CANONICALS_CONTAINS_FRAGMENT_URL,
        IssueId.PAGE_SPEED_LCP,
        IssueId.PAGE_SPEED_INP,
        IssueId.PAGE_SPEED_CLS,
        IssueId.PAGE_SPEED_FCP,
        IssueId.PAGE_SPEED_TTFB,
        IssueId.STRUCTURED_DATA_RICH_RESULT_VALIDATION_ERRORS,
        IssueId.STRUCTURED_DATA_RICH_RESULT_VALIDATION_WARNINGS,
        IssueId.INTERNAL_LINKS_FUNCTIONAL_ANALYSIS,
        IssueId.CONTENT_READABILITY_DIFFICULT,
        IssueId.CONTENT_READABILITY_VERY_DIFFICULT,
        IssueId.CUSTOM_SEARCH_GA4_TAGS,
        IssueId.CUSTOM_SEARCH_GTM_TAGS,
        IssueId.CUSTOM_SEARCH_OG_TAGS,
        IssueId.CUSTOM_SEARCH_TWITTER_CARD,
    }


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def test_labels_are_cleaned_and_originals_preserved():
    assert IssueCategory.STRUCTURED_DATA in {spec.category for spec in ISSUE_CATALOGUE}
    assert RAE_LABELS[IssueId.STRUCTURED_DATA_MISSING].category == "Strucured Tags"
    assert RAE_LABELS[IssueId.CUSTOM_SEARCH_OG_TAGS].category == "Custom Search "
    assert ISSUE_SPECS[IssueId.CONTENT_READABILITY_DIFFICULT].label == "Readability Difficult"
    assert RAE_LABELS[IssueId.CONTENT_READABILITY_DIFFICULT].label == "Redability Difficult"
    xfo = IssueId.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER
    assert ISSUE_SPECS[xfo].label == "Missing X-Frame-Options Header"
    assert RAE_LABELS[xfo].label == "Missing X-Frames-Options Header"
    assert set(RAE_LABELS) == set(IssueId)


def test_no_label_or_category_carries_stray_whitespace():
    for spec in ISSUE_CATALOGUE:
        assert spec.label == spec.label.strip()
        assert "  " not in spec.label


# --------------------------------------------------------------------------
# D1: the 30 disagreements, row by row
# --------------------------------------------------------------------------

# (id, dashboard (issues_*) severity/priority, score (overview_*) severity/priority,
#  rule, resolved severity/priority). "-" is a blank cell; "NA" is never-scored.
# fmt: off
D1_RESOLUTIONS = [
    (IssueId.RESPONSE_CODES_3XX_REDIRECTION, "Warning/High", "NA/NA", "b",
     Severity.WARNING, Priority.HIGH),
    (IssueId.URL_CONTAINS_SPACE, "Issue/Medium", "Issue/Low", "c",
     Severity.ISSUE, Priority.MEDIUM),
    (IssueId.META_DESCRIPTION_MISSING, "Opportunity/Medium", "Opportunity/Low", "c",
     Severity.OPPORTUNITY, Priority.MEDIUM),
    (IssueId.H1_MISSING, "Issue/High", "Issue/Medium", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.H1_MULTIPLE, "Warning/Low", "Warning/Medium", "c",
     Severity.WARNING, Priority.MEDIUM),
    (IssueId.CANONICALS_MISSING, "Issue/High", "Warning/Medium", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.CANONICALS_MULTIPLE, "Issue/High", "Warning/Low", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.CANONICALS_CANONICAL_IS_RELATIVE, "Warning/High", "Warning/Medium", "c",
     Severity.WARNING, Priority.HIGH),
    (IssueId.CANONICALS_CONTAINS_FRAGMENT_URL, "Issue/High", "Issue/Medium", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.CANONICALS_OUTSIDE_HEAD, "Issue/High", "Issue/Medium", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.DIRECTIVES_NOFOLLOW, "Warning/Medium", "Warning/High", "c",
     Severity.WARNING, Priority.HIGH),
    (IssueId.SITEMAPS_ORPHAN_URLS, "Issue/Medium", "Issue/High", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP, "Issue/Medium", "NA/NA", "b",
     Severity.ISSUE, Priority.MEDIUM),
    (IssueId.SECURITY_FORM_URL_INSECURE, "-/-", "Issue/High", "a",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.SECURITY_FORM_ON_HTTP_URL, "-/-", "Issue/High", "a",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.SECURITY_MISSING_HSTS_HEADER, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.SECURITY_PROTOCOL_RELATIVE_RESOURCE_LINKS, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.SECURITY_MISSING_CONTENT_SECURITY_POLICY_HEADER, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.SECURITY_MISSING_X_CONTENT_TYPE_OPTIONS_HEADER, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.SECURITY_MISSING_SECURE_REFERRER_POLICY_HEADER, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.SECURITY_BAD_CONTENT_TYPE, "-/-", "Warning/Low", "a",
     Severity.WARNING, Priority.LOW),
    (IssueId.CONTENT_SOFT_404_PAGES, "Warning/High", "Warning/Medium", "c",
     Severity.WARNING, Priority.HIGH),
    (IssueId.CONTENT_READABILITY_DIFFICULT, "Warning/Medium", "Warning/Low", "c",
     Severity.WARNING, Priority.MEDIUM),
    (IssueId.CONTENT_READABILITY_VERY_DIFFICULT, "Warning/Medium", "Opportunity/Medium", "c",
     Severity.WARNING, Priority.MEDIUM),
    (IssueId.CONTENT_LOREM_IPSUM_PLACEHOLDER, "Opportunity/Medium", "Opportunity/Low", "c",
     Severity.OPPORTUNITY, Priority.MEDIUM),
    (IssueId.CONTENT_NEAR_DUPLICATES, "-/Medium", "Issue/Medium", "a",
     Severity.ISSUE, Priority.MEDIUM),
    (IssueId.CONTENT_EXACT_DUPLICATES, "-/High", "Issue/Medium", "a+c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.HREFLANG_NON_200_URLS, "Issue/Medium", "Issue/High", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.HREFLANG_MISSING, "Issue/High", "Warning/High", "c",
     Severity.ISSUE, Priority.HIGH),
    (IssueId.HREFLANG_OUTSIDE_HEAD, "Issue/High", "Warning/Low", "c",
     Severity.ISSUE, Priority.HIGH),
]
# fmt: on


def test_d1_table_covers_all_thirty_disagreements():
    assert len(D1_RESOLUTIONS) == 30
    assert len({row[0] for row in D1_RESOLUTIONS}) == 30
    rules = [row[3] for row in D1_RESOLUTIONS]
    assert sum(rule.startswith("a") for rule in rules) == 10
    assert rules.count("b") == 2
    assert rules.count("c") == 18


@pytest.mark.parametrize(
    ("issue", "dashboard", "score", "rule", "severity", "priority"),
    D1_RESOLUTIONS,
    ids=[row[0].value for row in D1_RESOLUTIONS],
)
def test_d1_resolution(issue, dashboard, score, rule, severity, priority):
    spec = ISSUE_SPECS[issue]
    assert (spec.severity, spec.priority) == (severity, priority), (dashboard, score, rule)


def test_d1_rule_c_is_stricter_wins():
    # Re-derive rule (c) rows from the raw cells so the table itself is checked.
    sev_rank = {"Issue": 0, "Warning": 1, "Opportunity": 2}
    pri_rank = {"High": 0, "Medium": 1, "Low": 2}
    for issue, dashboard, score, rule, severity, priority in D1_RESOLUTIONS:
        if rule != "c":
            continue
        d_sev, d_pri = dashboard.split("/")
        s_sev, s_pri = score.split("/")
        expected_sev = min(d_sev, s_sev, key=sev_rank.__getitem__)
        expected_pri = min(d_pri, s_pri, key=pri_rank.__getitem__)
        assert severity.value == expected_sev.upper(), issue
        assert priority.value == expected_pri.upper(), issue


def test_two_rows_blank_in_both_rae_tables_follow_their_security_siblings():
    # Neither RAE table scored these; they take the value of every other
    # Security header/link row (Warning/Low). Flagged in build-log 0073;
    # confirmed by the operator 2026-09-08.
    for issue in (
        IssueId.SECURITY_UNSAFE_CROSS_ORIGIN_LINKS,
        IssueId.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER,
    ):
        assert (ISSUE_SPECS[issue].severity, ISSUE_SPECS[issue].priority) == (
            Severity.WARNING,
            Priority.LOW,
        )
