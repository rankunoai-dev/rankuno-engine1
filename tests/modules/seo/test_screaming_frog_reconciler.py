"""Tests for the Screaming Frog reconciliation.

The property that matters most here is not any single reason but that the
reasons are *exclusive*: every disagreement gets exactly one, so the buckets sum
to the totals. An earlier ad-hoc version of this analysis counted subdomains as
their own bucket and again inside the status buckets, and overstated its own
total by 83 — a report that does not add up is worse than no report.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.screaming_frog_reconciler import (
    MIN_TAIL_REPEATS,
    EngineGapReason,
    FrogGapReason,
    MissedPageStatus,
    ReconciliationReport,
    ScreamingFrogRow,
    load_screaming_frog_csv,
    normalise,
    reconcile,
    verify_missed_pages,
)

BASE = "https://www.e.com/"

HEADER = "Address,Content Type,Status Code,Indexability,Redirect URL,Crawl Depth,Unique Inlinks"


def row(address: str, status: int = 200, indexability: str = "Indexable") -> ScreamingFrogRow:
    return ScreamingFrogRow(address=address, status_code=status, indexability=indexability)


class TestNormalise:
    """One canonical form, or the set arithmetic compares nothing."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.e.com/a/",
            "http://e.com/a",
            "https://E.com/a/#frag",
        ],
    )
    def test_cosmetic_differences_fold(self, url):
        assert normalise(url) == "https://e.com/a"

    def test_a_query_string_is_kept(self):
        """`?page=2` is a distinct URL to a search engine and to both crawlers.

        Folding it would hide a real difference in what each tool chose to
        crawl rather than reveal one.
        """
        assert normalise("https://e.com/a?page=2") != normalise("https://e.com/a")


class TestLoadCsv:
    def test_columns_are_read_by_name_not_position(self):
        """The export carries 145 columns and reorders between versions.

        An index would survive the upgrade and produce wrong numbers, which is
        worse than an error.
        """
        text = "Unique Inlinks,Status Code,Address,Indexability\n7,200,https://e.com/a,Indexable\n"
        (parsed,) = load_screaming_frog_csv(text)
        assert parsed.address == "https://e.com/a"
        assert parsed.status_code == 200
        assert parsed.unique_inlinks == 7

    def test_blank_rows_are_dropped(self):
        """Screaming Frog exports end with blank lines."""
        text = f"{HEADER}\nhttps://e.com/a,text/html,200,Indexable,,1,3\n,,,,,,\n"
        assert len(load_screaming_frog_csv(text)) == 1

    def test_unparseable_numbers_do_not_raise(self):
        """`Crawl Depth` is empty on the start URL and `N/A` on some rows."""
        text = f"{HEADER}\nhttps://e.com/a,text/html,,Indexable,,N/A,\n"
        (parsed,) = load_screaming_frog_csv(text)
        assert parsed.status_code == 0
        assert parsed.crawl_depth == 0

    def test_missing_optional_columns_are_tolerated(self):
        """A user can export a reduced column set."""
        (parsed,) = load_screaming_frog_csv("Address\nhttps://e.com/a\n")
        assert parsed.address == "https://e.com/a"
        assert parsed.indexability == ""


class TestReasonsAreExclusive:
    def test_every_gap_has_exactly_one_reason_and_they_sum(self):
        frog = (
            row("https://www.e.com/live-miss"),
            row("https://www.e.com/gone", status=301),
            row("https://other.e.com/x", status=404),
            row("https://www.e.com/pic.jpg"),
            row("https://www.e.com/canon", indexability="Non-Indexable"),
        )
        report = reconcile(BASE, ("https://www.e.com/kept",), frog)

        assert len(report.frog_only) == 5
        assert sum(report.frog_reasons.values()) == len(report.frog_only)
        assert sum(report.engine_reasons.values()) == len(report.engine_only)

    def test_off_site_outranks_status(self):
        """A 404 on a subdomain is explained by the subdomain, not the 404.

        This engine never crawls that host, so its status code is not the
        reason the URL is missing.
        """
        report = reconcile(BASE, (), (row("https://other.e.com/x", status=404),))
        assert report.frog_only[0].reason == FrogGapReason.OFF_SITE

    def test_a_redirect_is_not_judged_on_its_extension(self):
        """A redirect source has no content to judge."""
        report = reconcile(BASE, (), (row("https://www.e.com/old.jpg", status=301),))
        assert report.frog_only[0].reason == FrogGapReason.REDIRECT

    def test_only_a_live_indexable_in_scope_page_is_a_miss(self):
        report = reconcile(BASE, (), (row("https://www.e.com/real"),))
        assert report.frog_only[0].reason == FrogGapReason.MISSED_PAGE
        assert report.missed_pages == ("https://www.e.com/real",)


class TestEngineSurplus:
    def test_a_repeating_tail_is_a_relative_href_loop(self):
        """One page at many fabricated addresses, invisible per-URL.

        Every one of these is individually well-formed with no repeated segment
        inside it, which is exactly why `is_spider_trap` cannot see them — the
        loop only shows as one tail under many unrelated parents.
        """
        loop = tuple(
            f"https://www.e.com/s{index}/software/b2b/surcharge"
            for index in range(MIN_TAIL_REPEATS)
        )
        report = reconcile(BASE, loop, ())
        assert set(report.engine_reasons) == {EngineGapReason.REPEATED_SUFFIX_TRAP}

    def test_a_tail_below_the_threshold_is_left_alone(self):
        """`/product/x/overview` legitimately repeats on a real catalogue."""
        few = tuple(
            f"https://www.e.com/s{index}/product/overview" for index in range(MIN_TAIL_REPEATS - 1)
        )
        report = reconcile(BASE, few, ())
        assert set(report.engine_reasons) == {EngineGapReason.SITEMAP_ORPHAN}

    def test_broken_markup_is_named_before_anything_else(self):
        """A broken address can also carry a query or a repeating tail.

        "This is not a URL" explains it better than either.
        """
        bad = "https://www.e.com/news/launch/<a href=?x=1"
        report = reconcile(BASE, (bad,), ())
        assert report.engine_only[0].reason == EngineGapReason.MALFORMED_MARKUP

    def test_an_unlinked_published_page_is_the_finding(self):
        report = reconcile(BASE, ("https://www.e.com/orphan",), ())
        assert report.orphans == ("https://www.e.com/orphan",)

    def test_a_query_variant_is_separated_from_a_real_orphan(self):
        report = reconcile(BASE, ("https://www.e.com/jobs?id=7",), ())
        assert report.engine_only[0].reason == EngineGapReason.QUERY_VARIANT


class TestOverlap:
    def test_cosmetic_differences_do_not_create_gaps(self):
        """The two tools disagree about `www.` and trailing slashes constantly."""
        report = reconcile(BASE, ("https://www.e.com/a/",), (row("http://e.com/a"),))
        assert report.in_both == 1
        assert report.frog_only == ()
        assert report.engine_only == ()

    def test_counts_describe_the_inputs(self):
        report = reconcile(
            BASE,
            ("https://www.e.com/a",),
            (row("https://www.e.com/a"), row("https://www.e.com/b", status=301)),
        )
        assert report.frog_rows == 2
        assert report.frog_live == 1
        assert report.engine_urls == 1


class TestVerifyMissedPages:
    """The bucket that accuses the engine is the one worth checking twice.

    On highradius.com a 60-URL sample of 892 came back 50 redirects and 10 live
    pages, because the site moved `/value-creation/` under
    `/resources/value-creation/` after the export was captured. Unverified, that
    number would have justified building crawler reach for pages that no longer
    exist.
    """

    def _report(self, url: str = "https://www.e.com/moved") -> ReconciliationReport:
        return reconcile(BASE, (), (row(url),))

    def test_a_redirect_is_not_a_missed_page(self):
        report = self._report()
        (check,) = verify_missed_pages(report, (), lambda _u: (301, "https://www.e.com/new-home"))
        assert check.status == MissedPageStatus.REDIRECTED

    def test_a_redirect_to_a_held_url_is_named_as_such(self):
        """The common case: the same page under its old address."""
        report = self._report()
        (check,) = verify_missed_pages(
            report,
            ("https://www.e.com/new-home",),
            lambda _u: (301, "https://www.e.com/new-home/"),
        )
        assert check.destination_held is True

    def test_a_live_page_survives_verification(self):
        report = self._report()
        (check,) = verify_missed_pages(report, (), lambda _u: (200, ""))
        assert check.status == MissedPageStatus.LIVE

    def test_a_dead_page_is_not_a_miss(self):
        report = self._report()
        (check,) = verify_missed_pages(report, (), lambda _u: (404, ""))
        assert check.status == MissedPageStatus.GONE

    def test_a_failed_check_is_unknown_not_absent(self):
        """A network failure must not quietly clear the engine of a miss."""
        report = self._report()
        (check,) = verify_missed_pages(report, (), lambda _u: (0, ""))
        assert check.status == MissedPageStatus.UNREACHABLE
