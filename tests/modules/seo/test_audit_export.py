"""Tests for the engine adapter (plan P0-4, ADR 0011).

The number that matters most is the one asserted first: sixteen issues are
measured and ninety-four are not, and every NOT_MEASURED set is empty. A rule
that quietly starts flagging something the profile cannot support would move
that count, and the test would say so.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from src.modules.seo.contracts.audit import AuditDataset, AuditSource, Coverage, IssueId
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE, IssueCategory
from src.modules.seo.page_classifier import audit_export
from src.modules.seo.page_classifier.audit_export import (
    LINKS_NOT_RETAINED_NOTE,
    SITEMAP_LIMIT,
    SITEMAP_NOT_READ_NOTE,
    SITEMAP_TRUNCATION_NOTE,
    STATUS_RE,
    AuditExportError,
    to_audit_dataset,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    DiscoverySource,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    Indexability,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import indexability_of
from src.modules.seo.page_classifier.url_rules import normalize_url

PRODUCED_AT = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
HOME = "https://example.com/"
ABOUT = "https://example.com/about/"
SENTINEL = "https://example.com/?token=SENTINEL"

EXPECTED_MEASURED = frozenset(
    {
        IssueId.SITEMAPS_URLS_NOT_IN_SITEMAP,
        IssueId.SITEMAPS_ORPHAN_URLS,
        IssueId.SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP,
        IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS,
        IssueId.DIRECTIVES_NOINDEX,
        IssueId.CANONICALS_CANONICALISED,
        IssueId.RESPONSE_CODES_3XX_REDIRECTION,
        IssueId.RESPONSE_CODES_INTERNAL_REDIRECT_CHAIN,
        IssueId.RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX,
        IssueId.RESPONSE_CODES_INTERNAL_SERVER_ERROR_5XX,
        IssueId.URL_UPPERCASE,
        IssueId.URL_UNDERSCORES,
        IssueId.URL_PARAMETERS,
        IssueId.URL_MULTIPLE_SLASHES,
        IssueId.URL_REPETITIVE_PATH,
        IssueId.URL_CONTAINS_SPACE,
    }
)


def profile(
    url: str,
    *,
    sitemap: bool = False,
    dom_link: bool = True,
    sitemap_source: str | None = None,
    indexability: Indexability = Indexability.INDEXABLE,
    reason: str = "",
    redirect_chain: tuple[str, ...] = (),
) -> FullPageIntelligenceProfile:
    """A minimal valid profile; built in full because the model validates itself."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.UNKNOWN,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.UNKNOWN,
                confidence=0.5,
            ),
        ),
        final_confidence_score=0.5,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        discovery_sources=DiscoverySource(sitemap=sitemap, dom_link=dom_link),
        sitemap_source=sitemap_source,
        indexability=indexability,
        indexability_reason=reason,
        redirect_chain=redirect_chain,
    )


def export(*profiles: FullPageIntelligenceProfile) -> AuditDataset:
    return to_audit_dataset(profiles, produced_at=PRODUCED_AT)


def with_sitemap(*profiles: FullPageIntelligenceProfile) -> AuditDataset:
    """Add one sitemap-discovered page so the SITEMAPS category is measured."""
    return export(profile(HOME, sitemap=True), *profiles)


# --------------------------------------------------------------------------
# Shape and coverage
# --------------------------------------------------------------------------


def test_source_is_engine_and_links_are_empty():
    dataset = with_sitemap()
    assert dataset.source is AuditSource.ENGINE
    assert dataset.links == ()
    assert dataset.produced_at == PRODUCED_AT
    assert LINKS_NOT_RETAINED_NOTE in dataset.notes


def test_sixteen_measured_ninety_four_not():
    dataset = with_sitemap()
    measured = {i for i, c in dataset.coverage.items() if c is Coverage.MEASURED}
    assert measured == EXPECTED_MEASURED
    assert len(measured) == 16
    assert len(dataset.coverage) == len(IssueId) == 110
    assert sum(1 for c in dataset.coverage.values() if c is Coverage.NOT_MEASURED) == 94


def test_every_not_measured_issue_is_present_with_an_empty_set():
    dataset = with_sitemap(
        profile("https://example.com/Bad//path_x?y=1", indexability=Indexability.NOINDEX)
    )
    for issue in IssueId:
        if issue not in EXPECTED_MEASURED:
            assert dataset.coverage[issue] is Coverage.NOT_MEASURED
            assert dataset.issues[issue] == frozenset()


def test_canonicals_missing_is_not_measured_because_the_profile_cannot_express_it():
    """`canonical_url` falls back to the URL itself, so absence is invisible (D-A)."""
    dataset = with_sitemap(profile(ABOUT))
    assert dataset.coverage[IssueId.CANONICALS_MISSING] is Coverage.NOT_MEASURED


def test_notes_name_every_category_with_something_unmeasured():
    dataset = with_sitemap()
    partly = {IssueCategory.SITEMAPS, IssueCategory.URL_ISSUES}
    for category in IssueCategory:
        if category in partly:
            continue
        assert any(f"not measured ({category.value}):" in n for n in dataset.notes), category


# --------------------------------------------------------------------------
# Sitemaps
# --------------------------------------------------------------------------


def test_sitemap_category_is_not_measured_when_no_sitemap_was_read():
    dataset = export(profile(HOME), profile(ABOUT))
    sitemap_ids = {s.id for s in ISSUE_CATALOGUE if s.category is IssueCategory.SITEMAPS}
    assert len(sitemap_ids) == 4
    for issue in sitemap_ids:
        assert dataset.coverage[issue] is Coverage.NOT_MEASURED
        assert dataset.issues[issue] == frozenset()
    assert SITEMAP_NOT_READ_NOTE in dataset.notes
    assert SITEMAP_TRUNCATION_NOTE not in dataset.notes


def test_urls_not_in_sitemap_flags_indexable_pages_only():
    dataset = with_sitemap(
        profile(ABOUT),
        profile("https://example.com/never-fetched/", indexability=Indexability.UNKNOWN),
        profile("https://example.com/gone/", indexability=Indexability.NOT_A_PAGE),
    )
    assert dataset.issues[IssueId.SITEMAPS_URLS_NOT_IN_SITEMAP] == {ABOUT}


def test_orphan_is_in_sitemap_and_never_linked():
    dataset = with_sitemap(
        profile("https://example.com/orphan/", sitemap=True, dom_link=False),
        profile("https://example.com/linked/", sitemap=True, dom_link=True),
        profile("https://example.com/cms-only/", sitemap=False, dom_link=False),
    )
    assert dataset.issues[IssueId.SITEMAPS_ORPHAN_URLS] == {"https://example.com/orphan/"}


def test_non_indexable_in_sitemap_excludes_unknown():
    dataset = with_sitemap(
        profile("https://example.com/n/", sitemap=True, indexability=Indexability.NOINDEX),
        profile(
            "https://example.com/c/", sitemap=True, indexability=Indexability.CANONICALISED_AWAY
        ),
        profile("https://example.com/x/", sitemap=True, indexability=Indexability.NOT_A_PAGE),
        profile("https://example.com/u/", sitemap=True, indexability=Indexability.UNKNOWN),
        profile("https://example.com/i/", sitemap=True),
    )
    assert dataset.issues[IssueId.SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP] == {
        "https://example.com/n/",
        "https://example.com/c/",
        "https://example.com/x/",
    }


def test_over_50k_counts_urls_per_grouped_sitemap():
    big = [
        profile(f"https://example.com/p/{i}/", sitemap=True, sitemap_source="big.xml")
        for i in range(SITEMAP_LIMIT + 1)
    ]
    small = profile("https://example.com/s/", sitemap=True, sitemap_source="small.xml")
    dataset = export(*big, small)
    members = dataset.issues[IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS]
    assert len(members) == SITEMAP_LIMIT + 1
    assert "https://example.com/s/" not in members
    assert SITEMAP_TRUNCATION_NOTE in dataset.notes


def test_exactly_50k_is_not_over():
    pages = [
        profile(f"https://example.com/p/{i}/", sitemap=True, sitemap_source="big.xml")
        for i in range(SITEMAP_LIMIT)
    ]
    dataset = export(*pages)
    assert dataset.coverage[IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS] is Coverage.MEASURED
    assert dataset.issues[IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS] == frozenset()


# --------------------------------------------------------------------------
# Directives, canonicals, response codes
# --------------------------------------------------------------------------


def test_noindex_and_canonicalised_read_the_verdict():
    dataset = with_sitemap(
        profile("https://example.com/n/", indexability=Indexability.NOINDEX),
        profile("https://example.com/c/", indexability=Indexability.CANONICALISED_AWAY),
    )
    assert dataset.issues[IssueId.DIRECTIVES_NOINDEX] == {"https://example.com/n/"}
    assert dataset.issues[IssueId.CANONICALS_CANONICALISED] == {"https://example.com/c/"}


def test_redirects_read_the_chain_length():
    one = profile("https://example.com/one/", redirect_chain=("https://example.com/one/",))
    two = profile(
        "https://example.com/two/",
        redirect_chain=("https://example.com/two/", "https://example.com/mid/"),
    )
    dataset = with_sitemap(one, two, profile(ABOUT))
    assert dataset.issues[IssueId.RESPONSE_CODES_3XX_REDIRECTION] == {one.url, two.url}
    assert dataset.issues[IssueId.RESPONSE_CODES_INTERNAL_REDIRECT_CHAIN] == {two.url}


def test_4xx_and_5xx_read_the_status_from_the_reason():
    _, r404 = indexability_of("https://example.com/a/", status_code=404)
    _, r503 = indexability_of("https://example.com/b/", status_code=503)
    dataset = with_sitemap(
        profile("https://example.com/a/", indexability=Indexability.NOT_A_PAGE, reason=r404),
        profile("https://example.com/b/", indexability=Indexability.NOT_A_PAGE, reason=r503),
        profile(
            "https://example.com/pdf/",
            indexability=Indexability.NOT_A_PAGE,
            reason="Answered with something that is not an HTML page.",
        ),
        profile("https://example.com/u/", indexability=Indexability.UNKNOWN),
    )
    assert dataset.issues[IssueId.RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX] == {
        "https://example.com/a/"
    }
    assert dataset.issues[IssueId.RESPONSE_CODES_INTERNAL_SERVER_ERROR_5XX] == {
        "https://example.com/b/"
    }


@pytest.mark.parametrize("status", [400, 404, 410, 500, 503])
def test_status_regex_is_bound_to_indexability_of(status: int):
    """The adapter reads prose `indexability_of` writes; a rewording must fail here."""
    verdict, reason = indexability_of("https://example.com/", status_code=status)
    assert verdict is Indexability.NOT_A_PAGE
    match = STATUS_RE.match(reason)
    assert match is not None and int(match.group(1)) == status


def test_unknown_lands_in_no_response_code_set():
    dataset = with_sitemap(profile("https://example.com/u/", indexability=Indexability.UNKNOWN))
    for issue in ISSUE_CATALOGUE:
        if issue.category is IssueCategory.RESPONSE_CODES_INTERNAL:
            assert "https://example.com/u/" not in dataset.issues[issue.id]


# --------------------------------------------------------------------------
# URL string rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("issue", "hit", "miss"),
    [
        (IssueId.URL_UPPERCASE, "https://example.com/Blog/", "https://example.com/news/"),
        (IssueId.URL_UPPERCASE, "https://example.com/blog/?Page=1", "https://Example.COM/blog/"),
        (IssueId.URL_UNDERSCORES, "https://example.com/my_page/", "https://example.com/my-page/"),
        (IssueId.URL_PARAMETERS, "https://example.com/p/?id=1", "https://example.com/p/"),
        (IssueId.URL_MULTIPLE_SLASHES, "https://example.com/a//b/", "https://example.com/a/c/"),
        (
            IssueId.URL_REPETITIVE_PATH,
            "https://example.com/blog/Blog/x/",
            "https://example.com/blog/x/",
        ),
        (IssueId.URL_CONTAINS_SPACE, "https://example.com/a%20b/", "https://example.com/a-b/"),
        (IssueId.URL_CONTAINS_SPACE, "https://example.com/a b/", "https://example.com/ab/"),
    ],
)
def test_url_rules(issue: IssueId, hit: str, miss: str) -> None:
    dataset = with_sitemap(profile(hit), profile(miss))
    members = dataset.issues[issue]
    assert normalize_url(hit) in members
    assert normalize_url(miss) not in members


def test_url_rules_read_the_raw_url_and_report_the_normalised_key():
    raw = "https://www.example.com/Blog//Post_A?utm_source=x"
    dataset = with_sitemap(profile(raw))
    key = "https://example.com/blog/post_a/"
    assert any(p.url == key for p in dataset.pages)
    for issue in (
        IssueId.URL_UPPERCASE,
        IssueId.URL_MULTIPLE_SLASHES,
        IssueId.URL_UNDERSCORES,
        IssueId.URL_PARAMETERS,
    ):
        assert dataset.issues[issue] == {key}


# --------------------------------------------------------------------------
# Dedupe, site, empty input
# --------------------------------------------------------------------------


def test_duplicates_collapse_to_one_page_and_issues_union():
    clean = profile("https://example.com/page/")
    dirty = profile("http://www.example.com/Page/", indexability=Indexability.NOINDEX)
    dataset = with_sitemap(clean, dirty)
    key = "https://example.com/page/"
    assert [p.url for p in dataset.pages] == [HOME, key]
    assert dataset.issues[IssueId.URL_UPPERCASE] == {key}
    assert dataset.issues[IssueId.DIRECTIVES_NOINDEX] == {key}


def test_site_is_majority_hostname_with_www_and_port_stripped():
    dataset = export(
        profile("https://www.example.com:8443/a/"),
        profile("https://example.com/b/"),
        profile("https://other.net/c/"),
    )
    assert dataset.site == "example.com"
    assert "site: 2 hostnames in spine; majority chosen" in dataset.notes


def test_single_host_adds_no_site_note():
    dataset = export(profile(HOME), profile(ABOUT))
    assert not any(note.startswith("site:") for note in dataset.notes)


def test_hostname_the_contract_rejects_raises_audit_export_error():
    with pytest.raises(AuditExportError):
        export(profile("https://localhost/a/"))


def test_empty_input_raises():
    with pytest.raises(AuditExportError, match="no profiles"):
        to_audit_dataset(())


def test_produced_at_defaults_to_aware_now():
    dataset = to_audit_dataset((profile(HOME),))
    assert dataset.produced_at.tzinfo is not None
    assert abs((datetime.now(UTC) - dataset.produced_at).total_seconds()) < 60


def test_logs_carry_counts_never_urls(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger(f"rankuno.{audit_export.__name__}")
    logger.propagate = True
    with caplog.at_level(logging.INFO, logger=logger.name):
        export(profile(SENTINEL), profile(SENTINEL))
    assert caplog.records, "capture is wired to the rankuno logger"
    for record in caplog.records:
        assert "SENTINEL" not in repr(record.__dict__)
    built = next(r for r in caplog.records if r.getMessage() == "audit_export_built")
    assert built.__dict__["pages"] == 1
    assert built.__dict__["duplicates_dropped"] == 1
    assert built.__dict__["coverage_measured"] == 12  # no sitemap read: 16 - 4
