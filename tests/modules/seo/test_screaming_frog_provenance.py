"""Engine-only reasons come from how the URL was found, not from its spelling.

Every engine-only URL that was not a file, trap, malformed address or query
variant used to be `SITEMAP_ORPHAN`, whatever the crawl knew about it. Measured
on 21,910 saved orphan entries, only 17.6% were in fact sitemap-only (ADR 0026).

The decision this guards is "same URLs, honest labels": `orphans` is what
Screaming Frog list mode's "Orphans Only" sends, so its membership must not
move. Only each member's reason changes.
"""

from __future__ import annotations

from src.modules.seo.page_classifier.schemas import DiscoverySource
from src.modules.seo.page_classifier.screaming_frog_reconciler import (
    ORPHAN_REASONS,
    EngineGapReason,
    ReconciliationReport,
    UrlGap,
    reconcile,
)

BASE = "https://www.e.com/"

SOURCES: dict[str, DiscoverySource] = {
    f"{BASE}listed": DiscoverySource(sitemap=True),
    f"{BASE}listed-and-cms": DiscoverySource(sitemap=True, cms_api=True),
    f"{BASE}cms": DiscoverySource(cms_api=True),
    f"{BASE}linked": DiscoverySource(dom_link=True),
    f"{BASE}linked-and-listed": DiscoverySource(sitemap=True, dom_link=True),
    f"{BASE}no-flags": DiscoverySource(),
    f"{BASE}report.pdf": DiscoverySource(sitemap=True),
    f"{BASE}jobs?id=7": DiscoverySource(dom_link=True),
}
URLS = (*SOURCES, f"{BASE}not-in-the-map")

EXPECTED_ORPHANS = {
    f"{BASE}listed",
    f"{BASE}listed-and-cms",
    f"{BASE}cms",
    f"{BASE}linked",
    f"{BASE}linked-and-listed",
    f"{BASE}no-flags",
    f"{BASE}not-in-the-map",
}
"""Everything but the PDF and the query variant: the old fallback set."""


def test_membership_without_provenance_is_the_historical_set() -> None:
    """Runs unchanged on the pre-provenance reconciler, pinning the old set."""
    report = reconcile(BASE, URLS, ())
    assert set(report.orphans) == EXPECTED_ORPHANS


def test_membership_is_identical_when_provenance_is_supplied() -> None:
    with_sources = reconcile(BASE, URLS, (), engine_sources=SOURCES)
    without = reconcile(BASE, URLS, ())
    assert set(with_sources.orphans) == set(without.orphans) == EXPECTED_ORPHANS


def test_each_orphan_carries_the_reason_its_flags_support() -> None:
    report = reconcile(BASE, URLS, (), engine_sources=SOURCES)
    reasons = {gap.url: gap.reason for gap in report.engine_only}
    assert reasons == {
        f"{BASE}listed": EngineGapReason.SITEMAP_ONLY_NO_LINK,
        f"{BASE}listed-and-cms": EngineGapReason.SITEMAP_ONLY_NO_LINK,
        f"{BASE}cms": EngineGapReason.CMS_API_ONLY,
        f"{BASE}linked": EngineGapReason.LINKED_NOT_IN_EXPORT,
        f"{BASE}linked-and-listed": EngineGapReason.LINKED_NOT_IN_EXPORT,
        f"{BASE}no-flags": EngineGapReason.PROVENANCE_UNKNOWN,
        f"{BASE}not-in-the-map": EngineGapReason.PROVENANCE_UNKNOWN,
        # The earlier rules still win, whatever the flags say.
        f"{BASE}report.pdf": EngineGapReason.PDF_FILE,
        f"{BASE}jobs?id=7": EngineGapReason.QUERY_VARIANT,
    }
    assert sum(report.engine_reasons.values()) == len(report.engine_only)


def test_nothing_is_guessed_without_provenance() -> None:
    """A caller with no flags gets the explicit unknown, never a sitemap claim."""
    report = reconcile(BASE, (f"{BASE}page",), ())
    assert report.engine_only[0].reason == EngineGapReason.PROVENANCE_UNKNOWN


def test_spellings_that_fold_together_pool_their_evidence() -> None:
    """Two spellings of one URL are one gap; a link to either is a link."""
    report = reconcile(
        BASE,
        (f"{BASE}a/", "http://e.com/a"),
        (),
        engine_sources={
            f"{BASE}a/": DiscoverySource(sitemap=True),
            "http://e.com/a": DiscoverySource(dom_link=True),
        },
    )
    assert [gap.reason for gap in report.engine_only] == [EngineGapReason.LINKED_NOT_IN_EXPORT]


def test_a_saved_legacy_orphan_still_loads_and_still_counts() -> None:
    """Saved reconciliations are never rewritten; their lists must still serve."""
    gap = UrlGap.model_validate({"url": f"{BASE}old", "reason": "SITEMAP_ORPHAN"})
    report = ReconciliationReport(base_url=BASE, engine_only=(gap,))
    assert report.orphans == (f"{BASE}old",)
    assert EngineGapReason.SITEMAP_ORPHAN in ORPHAN_REASONS
