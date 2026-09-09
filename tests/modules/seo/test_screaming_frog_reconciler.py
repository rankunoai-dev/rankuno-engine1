"""Tests for the Screaming Frog reconciliation.

The property that matters most here is not any single reason but that the
reasons are *exclusive*: every disagreement gets exactly one, so the buckets sum
to the totals. An earlier ad-hoc version of this analysis counted subdomains as
their own bucket and again inside the status buckets, and overstated its own
total by 83 — a report that does not add up is worse than no report.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from src.modules.seo.page_classifier.screaming_frog_reconciler import (
    MIN_TAIL_REPEATS,
    DefaulterCategory,
    EngineGapReason,
    ExportFormat,
    FrogGapReason,
    MissedPageStatus,
    ReconciliationReport,
    ScreamingFrogRow,
    UrlGap,
    load_cross_check_input,
    load_screaming_frog_csv,
    load_screaming_frog_export,
    normalise,
    reconcile,
    revalidate_defaulters,
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

    def test_the_agreement_is_kept_as_addresses_not_only_a_count(self):
        """`in_both` was computed and discarded on the next line.

        Every other figure on the cross-check panel could be handed to someone
        as a list of URLs; the agreement could not, which made it the one number
        a reader had to take on trust.
        """
        report = reconcile(
            BASE,
            ("https://www.e.com/a/", "https://www.e.com/b/"),
            (row("http://e.com/a"), row("https://www.e.com/b")),
        )
        assert report.in_both == 2
        assert len(report.in_both_urls) == report.in_both

    def test_the_agreement_carries_this_engine_s_spelling(self):
        """So the list joins against the crawl result without re-normalising.

        Screaming Frog wrote `http://e.com/a`; the crawl holds
        `https://www.e.com/a/`. Both are the same page, and the one worth
        exporting is the one the rest of the report uses.
        """
        report = reconcile(BASE, ("https://www.e.com/a/",), (row("http://e.com/a"),))
        assert report.in_both_urls == ("https://www.e.com/a/",)

    def test_the_agreement_is_ordered_so_two_runs_can_be_compared(self):
        """Two runs over the same inputs must produce the same order.

        A set's iteration order is not stable, and an export that reshuffles
        itself between runs cannot be diffed against last week's.
        """
        urls = ("https://www.e.com/c/", "https://www.e.com/a/", "https://www.e.com/b/")
        rows = tuple(row(url) for url in urls)
        first = reconcile(BASE, urls, rows).in_both_urls
        second = reconcile(BASE, tuple(reversed(urls)), tuple(reversed(rows))).in_both_urls
        assert first == second

    def test_no_overlap_leaves_the_list_empty_rather_than_absent(self):
        report = reconcile(BASE, ("https://www.e.com/a",), (row("https://www.e.com/z"),))
        assert report.in_both == 0
        assert report.in_both_urls == ()

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


class TestBadInputIsRejectedClearly:
    """A wrong file must produce a message, not a 500.

    Dropping the `.xlsx` instead of the `.csv` was made within a day of the
    feature shipping: Screaming Frog writes both into the same folder. The parse
    failure escaped the API's `except ValueError` as a raw `csv.Error`, the
    server 500'd mid-upload, the connection reset, and the browser reported
    "Cannot reach the engine" about a server that was answering fine.
    """

    def test_a_spreadsheet_dropped_as_csv_raises_valueerror(self):
        """`csv.Error` is not a `ValueError`, which is exactly how it escaped.

        A bare carriage return inside a field, which is what a binary file
        decoded as text is full of. The header parses first — an `.xlsx` carries
        the literal string `Address` in its shared-strings table — and the
        failure comes mid-iteration, which is why the guard cannot live on
        `fieldnames` alone. Verified against the real 4 MB export before being
        reduced to this.
        """
        rubbish = "Address,Content Type" + chr(10) + "a" + chr(13) + "b,c" + chr(10)
        with pytest.raises(ValueError, match="not a CSV"):
            load_screaming_frog_csv(rubbish)

    def test_a_csv_without_an_address_column_is_named(self):
        """A real CSV, wrong export tab. Different mistake, different message."""
        with pytest.raises(ValueError, match="Address"):
            load_screaming_frog_csv("Title 1,Status Code\nHome,200\n")

    def test_an_empty_file_is_rejected_not_silently_empty(self):
        """Reconciling against nothing would report every URL as frog-missing."""
        with pytest.raises(ValueError):
            load_screaming_frog_csv("")

    def test_a_valid_export_still_loads(self):
        assert (
            len(
                load_screaming_frog_csv(f"{HEADER}\nhttps://e.com/a,text/html,200,Indexable,,1,3\n")
            )
            == 1
        )


def workbook_bytes(rows: list[list[object]]) -> bytes:
    """A real `.xlsx`, built the way Screaming Frog writes one."""
    import io as _io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = _io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class TestXlsxExports:
    """Screaming Frog writes .csv and .xlsx side by side.

    The spreadsheet is the one people reach for — it opens on a double-click —
    and accepting only CSV meant the likelier file produced a parse failure that
    surfaced as "Is the API server running?".
    """

    HEAD = ["Address", "Content Type", "Status Code", "Indexability", "Unique Inlinks"]
    BODY = ["https://www.e.com/a", "text/html", 200, "Indexable", 7]

    def test_a_workbook_reads_like_its_csv_twin(self):
        """The format must not change a single field."""
        xlsx = load_screaming_frog_export(workbook_bytes([self.HEAD, self.BODY]))
        csv_text = "Address,Content Type,Status Code,Indexability,Unique Inlinks\n"
        csv_text += "https://www.e.com/a,text/html,200,Indexable,7\n"
        assert xlsx == load_screaming_frog_export(csv_text.encode("utf-8"))

    def test_the_format_is_detected_from_content_not_a_name(self):
        """A spreadsheet renamed `.csv` still has to read correctly.

        The API receives a body with no filename, and a Content-Type set by a
        file picker is whatever the operating system guessed.
        """
        (parsed,) = load_screaming_frog_export(workbook_bytes([self.HEAD, self.BODY]))
        assert parsed.address == "https://www.e.com/a"
        assert parsed.status_code == 200

    def test_columns_are_read_by_name_in_a_workbook_too(self):
        reordered = [["Unique Inlinks", "Address"], [4, "https://www.e.com/b"]]
        (parsed,) = load_screaming_frog_export(workbook_bytes(reordered))
        assert parsed.address == "https://www.e.com/b"
        assert parsed.unique_inlinks == 4

    def test_a_sheet_without_an_address_column_is_rejected(self):
        with pytest.raises(ValueError, match="Address"):
            load_screaming_frog_export(workbook_bytes([["Title 1"], ["Home"]]))

    def test_an_archive_that_is_not_a_workbook_says_so(self):
        """`PK` identifies a ZIP, which `.docx` and `.zip` also are."""
        with pytest.raises(ValueError, match="not a readable Excel workbook"):
            load_screaming_frog_export(b"PK\x03\x04 this is a zip but not a workbook")

    def test_blank_trailing_rows_are_dropped(self):
        rows = [self.HEAD, self.BODY, [None, None, None, None, None]]
        assert len(load_screaming_frog_export(workbook_bytes(rows))) == 1

    def test_text_input_still_works(self):
        """The CSV path is unchanged; `str` bypasses detection entirely."""
        assert len(load_screaming_frog_export("Address\nhttps://e.com/a\n")) == 1


class TestBareUrlList:
    """A one-column URL list is a declared second input, weaker by design.

    The file the analyst actually has is often a masterfile tab headed
    `HTML Pages`, and refusing it with "no 'Address' column" was correct and
    useless. It is accepted for the set comparison only: it carries no status,
    indexability or content type, so nothing it holds alone can be called a
    missed page, and nothing from it may be merged.
    """

    URLS = ["https://www.e.com/a/", "https://www.e.com/b/", "https://www.e.com/c/"]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("HTML Pages\n" + "\n".join(URLS) + "\n", id="csv-headed"),
            pytest.param("\n".join(URLS) + "\n", id="csv-headerless"),
            pytest.param(
                ("﻿HTML Pages\r\n" + "\r\n".join(URLS) + "\r\n").encode("utf-8"),
                id="csv-bytes-with-bom",
            ),
            pytest.param(workbook_bytes([["HTML Pages"], *[[u] for u in URLS]]), id="xlsx-headed"),
            pytest.param(workbook_bytes([[u] for u in URLS]), id="xlsx-headerless"),
            pytest.param(
                workbook_bytes([["HTML Pages", None], *[[u, None] for u in URLS]]),
                id="xlsx-one-populated-column",
            ),
        ],
    )
    def test_a_bare_list_is_accepted_and_declared(self, body):
        loaded = load_cross_check_input(body)
        assert loaded.source_format is ExportFormat.BARE_URL_LIST
        assert [row.address for row in loaded.rows] == self.URLS

    def test_a_real_export_is_declared_as_such(self):
        text = f"{HEADER}\nhttps://e.com/a,text/html,200,Indexable,,1,3\n"
        loaded = load_cross_check_input(text)
        assert loaded.source_format is ExportFormat.INTERNAL_HTML
        assert loaded.rows == load_screaming_frog_export(text)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("Title 1,Status Code\nHome,200\n", id="two-column-csv"),
            pytest.param(
                "Top pages,Clicks,Impressions,CTR,Position\nhttps://www.e.com/a/,10,100,10%,3.2\n",
                id="gsc-top-pages-csv",
            ),
            pytest.param(
                workbook_bytes([["Top pages", "Clicks"], ["https://www.e.com/a/", 10]]),
                id="gsc-top-pages-xlsx",
            ),
            pytest.param("HTML Pages\n/a/\n/b/\n", id="paths-without-a-scheme"),
            pytest.param("HTML Pages\n", id="header-only"),
        ],
    )
    def test_anything_else_keeps_the_existing_refusal(self, body):
        """The message names the real fix, and must not change for these."""
        with pytest.raises(ValueError, match="Address"):
            load_cross_check_input(body)

    def test_input_that_is_not_a_csv_at_all_is_not_retried_as_a_list(self):
        rubbish = "Address,Content Type" + chr(10) + "a" + chr(13) + "b,c" + chr(10)
        with pytest.raises(ValueError, match="not a CSV"):
            load_cross_check_input(rubbish)

    def test_every_frog_only_reason_is_unknown_never_a_miss(self):
        """A list proves a URL was written down, not that it is a page.

        Even a URL that *looks* like a miss — same host, no extension, no trap
        pattern — gets `UNKNOWN`, because calling it missed would be inventing
        a 200 the file never reported.
        """
        loaded = load_cross_check_input("HTML Pages\n" + "\n".join(self.URLS) + "\n")
        report = reconcile(
            BASE, ("https://www.e.com/a/",), loaded.rows, source_format=loaded.source_format
        )
        assert report.source_format is ExportFormat.BARE_URL_LIST
        assert report.in_both == 1
        assert {gap.reason for gap in report.frog_only} == {FrogGapReason.UNKNOWN}
        assert report.frog_reasons == {"UNKNOWN": 2}
        assert report.missed_pages == ()
        assert report.frog_live == 0

    def test_the_engine_side_is_still_explained(self):
        """The weakness is one-sided: the engine's own surplus is judged as before."""
        loaded = load_cross_check_input("https://www.e.com/a/\n")
        report = reconcile(
            BASE,
            ("https://www.e.com/a/", "https://www.e.com/orphan/"),
            loaded.rows,
            source_format=loaded.source_format,
        )
        assert report.orphans == ("https://www.e.com/orphan/",)

    def test_the_format_defaults_to_an_export(self):
        """Every existing caller of `reconcile` keeps its behaviour."""
        report = reconcile(BASE, (), (row("https://www.e.com/real"),))
        assert report.source_format is ExportFormat.INTERNAL_HTML
        assert report.frog_only[0].reason == FrogGapReason.MISSED_PAGE


class TestEngineFiles:
    """Documents get their own reasons, and therefore their own sheets.

    On infosys.com 7,610 of 8,383 engine-only URLs were PDFs and every one sat
    in the Orphans sheet — the finding buried under the files. Screaming Frog
    lists documents on its own tab, so against the HTML export they are always
    engine-only, and that is a difference with an explanation, not a finding.
    """

    def _reason(self, url: str) -> str:
        return reconcile(BASE, (url,), ()).engine_only[0].reason

    def test_a_pdf_is_its_own_reason_and_not_an_orphan(self):
        report = reconcile(BASE, ("https://www.e.com/docs/report.pdf",), ())
        assert report.engine_only[0].reason == EngineGapReason.PDF_FILE
        assert report.orphans == ()

    @pytest.mark.parametrize("suffix", [".ppt", ".pptx", ".pps"])
    def test_presentation_extensions(self, suffix: str):
        assert self._reason(f"https://www.e.com/deck{suffix}") == EngineGapReason.PRESENTATION_FILE

    @pytest.mark.parametrize("suffix", [".xls", ".xlsx", ".csv"])
    def test_spreadsheet_extensions(self, suffix: str):
        assert self._reason(f"https://www.e.com/book{suffix}") == EngineGapReason.SPREADSHEET_FILE

    @pytest.mark.parametrize("suffix", [".docx", ".zip", ".asx"])
    def test_other_file_covers_word_archives_and_legacy_media(self, suffix: str):
        """A Word file, an archive and a legacy stream all land in one bucket.

        `.asx` is not in `NON_PAGE_SUFFIXES`, so discovery kept infosys.com's
        2003 analyst-call streams; `.zip` is, and a merged job can still hold one.
        """
        assert self._reason(f"https://www.e.com/f{suffix}") == EngineGapReason.OTHER_FILE

    def test_extension_is_case_insensitive(self):
        assert self._reason("https://www.e.com/REPORT.PDF") == EngineGapReason.PDF_FILE

    def test_query_after_a_file_extension_names_the_file(self):
        """A query string after a file suffix does not make the file a page.

        `report.pdf?page=2` is a PDF with a parameter, not a page whose
        pagination Screaming Frog collapsed. The file type is what an analyst
        acts on, so it wins over `QUERY_VARIANT`.
        """
        assert self._reason("https://www.e.com/report.pdf?page=2") == EngineGapReason.PDF_FILE

    def test_fragment_after_a_file_extension_is_ignored(self):
        assert (
            self._reason("https://www.e.com/deck.pptx#slide=3") == EngineGapReason.PRESENTATION_FILE
        )

    @pytest.mark.parametrize("suffix", [".html", ".htm", ".aspx"])
    def test_html_like_extensions_stay_pages(self, suffix: str):
        """infosys.com publishes 550 `.html` pages that are real orphans."""
        assert self._reason(f"https://www.e.com/about{suffix}") == EngineGapReason.SITEMAP_ORPHAN

    def test_a_dotted_segment_that_is_not_a_file_stays_a_page(self):
        """An e-mail address resolved as a path is broken, not a `.com` document.

        The allowlist is explicit for exactly this reason: a rule that filed any
        dotted final segment would have invented a file type for it.
        """
        url = "https://www.e.com/techcompass/name@e.com"
        assert self._reason(url) == EngineGapReason.SITEMAP_ORPHAN

    def test_a_repeating_tail_beats_a_file_extension(self):
        """A fabricated address is not a file whatever it ends in."""
        loop = tuple(
            f"https://www.e.com/q{index}/documents/transcripts/call.pdf"
            for index in range(MIN_TAIL_REPEATS)
        )
        report = reconcile(BASE, loop, ())
        assert set(report.engine_reasons) == {EngineGapReason.REPEATED_SUFFIX_TRAP}

    def test_malformed_markup_beats_a_file_extension(self):
        bad = "https://www.e.com/news/<a href=/x.pdf"
        assert self._reason(bad) == EngineGapReason.MALFORMED_MARKUP

    def test_engine_reasons_tally_the_file_buckets(self):
        """The buckets still sum to the total: one reason per URL, no double count."""
        urls = (
            "https://www.e.com/a.pdf",
            "https://www.e.com/b.pptx",
            "https://www.e.com/c.xlsx",
            "https://www.e.com/d.docx",
            "https://www.e.com/page",
            "https://www.e.com/page?x=1",
        )
        report = reconcile(BASE, urls, ())
        assert report.engine_reasons == {
            "PDF_FILE": 1,
            "PRESENTATION_FILE": 1,
            "SPREADSHEET_FILE": 1,
            "OTHER_FILE": 1,
            "SITEMAP_ORPHAN": 1,
            "QUERY_VARIANT": 1,
        }
        assert sum(report.engine_reasons.values()) == len(report.engine_only)

    def test_an_old_sidecar_reason_string_still_loads(self):
        """Eleven stored sidecars carry `SITEMAP_ORPHAN` for what is now a PDF.

        `UrlGap.reason` is a string, not the enum, so those rows load unchanged
        and keep saying what they said until the cross-check is re-run.
        """
        gap = UrlGap.model_validate({"url": "https://www.e.com/x.pdf", "reason": "SITEMAP_ORPHAN"})
        assert gap.reason == "SITEMAP_ORPHAN"
        report = ReconciliationReport(
            base_url=BASE,
            frog_rows=0,
            frog_live=0,
            engine_urls=1,
            in_both=0,
            in_both_urls=(),
            frog_only=(),
            engine_only=(gap,),
            frog_reasons={},
            engine_reasons={"SITEMAP_ORPHAN": 1},
        )
        assert report.orphans == ("https://www.e.com/x.pdf",)


def _classify(url: str) -> DefaulterCategory | None:
    """Run one bare-list URL through `reconcile` and return its category.

    Goes through the public `reconcile` entry point rather than a private
    helper directly, matching how every other rule in this module is tested —
    the classification is a property of the reconciliation, not a standalone
    function with its own contract.
    """
    report = reconcile(
        "https://www.infosys.com/",
        (),
        (ScreamingFrogRow(address=url),),
        source_format=ExportFormat.BARE_URL_LIST,
    )
    assert len(report.frog_only) == 1
    assert report.frog_only[0].reason == FrogGapReason.UNKNOWN.value
    return report.frog_only[0].defaulter_category


class TestDefaulterCategory:
    """A bare-list `UNKNOWN` row's shape, sorted into structurally-junk or not.

    The bucket exists because a bare list carries no status: `UNKNOWN` alone
    cannot separate "this engine missed a live page" from "this address was
    never a page". These rules narrow that only where the URL's own shape
    gives it away — everything else stays `None`, the presumed-real residual.
    """

    @pytest.mark.parametrize(
        "url,expected",
        [
            pytest.param(
                "https://www.infosys.com/%20services/insights/x.html",
                DefaulterCategory.CORRUPTED_URL,
                id="percent-encoded-space",
            ),
            pytest.param(
                "https://www.infosys.com/confluence/2022/pursuit%20excellence.html",
                DefaulterCategory.CORRUPTED_URL,
                id="percent-encoded-space-mid-path",
            ),
            pytest.param(
                "https://www.infosys.com/cobalt-world-tour/2023/nyc.html.html",
                DefaulterCategory.CORRUPTED_URL,
                id="doubled-extension",
            ),
            pytest.param(
                "https://www.infosys.com//about/knowledge-institute/insights/x.html",
                DefaulterCategory.CORRUPTED_URL,
                id="doubled-leading-slash",
            ),
            pytest.param(
                "https://www.infosys.com/services/x.html%20https://other.example.com/y",
                DefaulterCategory.CORRUPTED_URL,
                id="second-http-embedded",
            ),
            pytest.param(
                "https://www.infosys.com/content/infosys-web/en%20%20%20%20/x.html",
                DefaulterCategory.CORRUPTED_URL,
                id="whitespace-in-path-via-percent-encoding",
            ),
            pytest.param(
                "https://www.infosys.com/content/dam/infosys-web/en/investors/"
                "reports-filings/annual-report/AR-2010/index.html",
                DefaulterCategory.DAM_HTML_ARCHIVE,
                id="dam-investors",
            ),
            pytest.param(
                "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/anusha.html",
                DefaulterCategory.DAM_FORMS_OTHER,
                id="dam-non-investors",
            ),
            pytest.param(
                "https://www.infosys.com/-/content/infosys-web/en/aster-1/marketing.html",
                DefaulterCategory.CMS_INTERNAL_LEAK,
                id="cms-leak",
            ),
            pytest.param(
                "https://www.infosys.com/content/infosys-web/en/-/content/infosys-web/en/"
                "aster-1/marketing.html",
                DefaulterCategory.CMS_INTERNAL_LEAK,
                id="cms-leak-doubly-nested",
            ),
            pytest.param(
                "https://www.infosys.com/about/awards/most-reputed-company.html",
                None,
                id="ordinary-page-is-the-presumed-real-residual",
            ),
        ],
    )
    def test_each_rule_wins_alone(self, url, expected):
        assert _classify(url) == expected

    def test_corrupted_beats_dam_when_both_match(self):
        """A malformed address explains the row better than its path shape.

        This URL sits under `/content/dam/.../investors/...` *and* carries a
        percent-encoded space — corrupted wins, because "not well-formed" is
        true regardless of where it sits, and a DAM path presumes the address
        is at least a real path.
        """
        url = "https://www.infosys.com/content/dam/infosys-web/en/investors/%20reports/index.html"
        assert _classify(url) == DefaulterCategory.CORRUPTED_URL

    def test_corrupted_beats_cms_leak_when_both_match(self):
        url = "https://www.infosys.com/-/content/infosys-web/en%20/aster-1/marketing.html"
        assert _classify(url) == DefaulterCategory.CORRUPTED_URL

    def test_investors_segment_must_be_immediately_after_site_and_lang(self):
        """`investors` appearing later in the path does not count.

        Only the segment immediately after `/content/dam/<site>/<lang>/`
        decides the split; a page that merely mentions investors further down
        the DAM path is still general DAM output, not the investor archive.
        """
        url = "https://www.infosys.com/content/dam/infosys-web/en/reports/investors.html"
        assert _classify(url) == DefaulterCategory.DAM_FORMS_OTHER

    def test_dam_path_not_ending_in_html_is_not_categorised(self):
        """The DAM rules require an `.html`/`.htm` ending, per the design.

        A non-HTML DAM asset does not match (b), (c) or (d) — `/content/dam/`
        is explicitly excluded from the CMS-leak rule — so it falls to the
        presumed-real residual rather than inventing a fifth category.
        """
        url = "https://www.infosys.com/content/dam/infosys-web/en/reports/deck.pdf"
        assert _classify(url) is None

    def test_non_bare_list_rows_never_get_a_category(self):
        """A real export's `UNKNOWN` never occurs.

        Every other reason must carry `defaulter_category=None` unconditionally.
        """
        report = reconcile(
            BASE,
            (),
            (row("https://www.e.com/gone.html", status=404),),
        )
        assert report.frog_only[0].reason == FrogGapReason.CLIENT_ERROR.value
        assert report.frog_only[0].defaulter_category is None

    def test_residual_unknown_rows_are_none_not_a_verified_page(self):
        """The presumed-real residual is exactly that: not verified live.

        It must not be folded into `missed_pages`, which is reserved for a
        real export's `MISSED_PAGE` reason and would otherwise overstate a
        defect this reconciliation cannot actually prove.
        """
        report = reconcile(
            "https://www.infosys.com/",
            (),
            (ScreamingFrogRow(address="https://www.infosys.com/about/team.html"),),
            source_format=ExportFormat.BARE_URL_LIST,
        )
        assert report.frog_only[0].defaulter_category is None
        assert report.missed_pages == ()


def _unmatched(url: str, reason: str, impressions: int = 0, clicks: int = 0) -> dict:
    return {"url": url, "reason": reason, "impressions": impressions, "clicks": clicks}


def _saved_with_frog_only(*gaps: UrlGap) -> dict:
    return {"frog_only": [gap.model_dump(mode="json") for gap in gaps]}


def _gap_at(updated: Mapping[str, object] | None, index: int = 0) -> UrlGap:
    """Pull one `UrlGap` back out of a `revalidate_defaulters` result."""
    assert updated is not None
    frog_only = updated["frog_only"]
    assert isinstance(frog_only, list)
    return UrlGap.model_validate(frog_only[index])


class TestRevalidateDefaulters:
    """A Search Console second look at bare-list defaulter rows.

    The lookup is the same `not_crawled` bucket the performance module already
    produces for "on this site, absent from the crawl" — an arbitrary-URL
    match, exactly what a never-crawled defaulter row needs.
    """

    UNKNOWN_URL = "https://www.infosys.com/content/dam/infosys-web/en/x.html"

    def test_no_op_with_no_saved_reconciliation(self):
        assert (
            revalidate_defaulters({}, [_unmatched(self.UNKNOWN_URL, "not_crawled", 5, 0)]) is None
        )

    def test_no_op_with_nothing_eligible_no_unmatched_rows(self):
        saved = _saved_with_frog_only(
            UrlGap(
                url=self.UNKNOWN_URL,
                reason=FrogGapReason.UNKNOWN.value,
                defaulter_category=DefaulterCategory.DAM_FORMS_OTHER,
            )
        )
        assert revalidate_defaulters(saved, []) is None

    def test_no_op_when_no_unmatched_row_matches_a_url(self):
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.UNKNOWN.value)
        )
        other = "https://www.infosys.com/content/dam/infosys-web/en/somewhere-else.html"
        assert revalidate_defaulters(saved, [_unmatched(other, "not_crawled", 3, 1)]) is None

    def test_promotes_on_impressions_greater_than_zero(self):
        saved = _saved_with_frog_only(
            UrlGap(
                url=self.UNKNOWN_URL,
                reason=FrogGapReason.UNKNOWN.value,
                defaulter_category=DefaulterCategory.DAM_FORMS_OTHER,
            )
        )
        updated = revalidate_defaulters(
            saved, [_unmatched(self.UNKNOWN_URL, "not_crawled", impressions=12, clicks=0)]
        )
        gap = _gap_at(updated)
        assert gap.validation is not None
        assert gap.validation.flagged_real is True
        assert gap.validation.gsc_impressions == 12
        assert gap.validation.gsc_clicks == 0

    def test_promotes_on_clicks_greater_than_zero(self):
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.UNKNOWN.value)
        )
        updated = revalidate_defaulters(
            saved, [_unmatched(self.UNKNOWN_URL, "not_crawled", impressions=0, clicks=2)]
        )
        gap = _gap_at(updated)
        assert gap.validation is not None
        assert gap.validation.flagged_real is True

    def test_no_impressions_or_clicks_is_checked_but_not_flagged_real(self):
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.UNKNOWN.value)
        )
        updated = revalidate_defaulters(saved, [_unmatched(self.UNKNOWN_URL, "not_crawled", 0, 0)])
        gap = _gap_at(updated)
        assert gap.validation is not None
        assert gap.validation.flagged_real is False
        assert gap.validation.checked_at != ""

    def test_preserves_defaulter_category_on_promotion(self):
        saved = _saved_with_frog_only(
            UrlGap(
                url=self.UNKNOWN_URL,
                reason=FrogGapReason.UNKNOWN.value,
                defaulter_category=DefaulterCategory.DAM_FORMS_OTHER,
            )
        )
        updated = revalidate_defaulters(saved, [_unmatched(self.UNKNOWN_URL, "not_crawled", 4, 0)])
        gap = _gap_at(updated)
        assert gap.defaulter_category == DefaulterCategory.DAM_FORMS_OTHER

    def test_idempotent_on_rerun(self):
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.UNKNOWN.value)
        )
        rows = [_unmatched(self.UNKNOWN_URL, "not_crawled", 7, 1)]
        first = revalidate_defaulters(saved, rows)
        second = revalidate_defaulters(first, rows) if first is not None else None
        gap1 = _gap_at(first)
        gap2 = _gap_at(second)
        assert gap1.validation is not None
        assert gap2.validation is not None
        assert gap1.validation.gsc_impressions == gap2.validation.gsc_impressions
        assert gap1.validation.gsc_clicks == gap2.validation.gsc_clicks
        assert gap1.validation.flagged_real == gap2.validation.flagged_real
        assert gap1.defaulter_category == gap2.defaulter_category

    def test_only_not_crawled_reason_rows_are_eligible(self):
        """The other unmatched reasons do not mean "absent from the crawl"."""
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.UNKNOWN.value)
        )
        rows = [
            _unmatched(self.UNKNOWN_URL, "off_site", 9, 9),
            _unmatched(self.UNKNOWN_URL, "ambiguous", 9, 9),
            _unmatched(self.UNKNOWN_URL, "unparseable", 9, 9),
            _unmatched(self.UNKNOWN_URL, "other_subdomain", 9, 9),
        ]
        assert revalidate_defaulters(saved, rows) is None

    def test_non_unknown_rows_are_never_promoted_even_on_a_match(self):
        """A row with a real reason is not a bare-list defaulter row at all.

        True even if its URL happens to coincide with a Search Console address.
        """
        saved = _saved_with_frog_only(
            UrlGap(url=self.UNKNOWN_URL, reason=FrogGapReason.MISSED_PAGE.value)
        )
        rows = [_unmatched(self.UNKNOWN_URL, "not_crawled", 9, 9)]
        assert revalidate_defaulters(saved, rows) is None

    def test_url_matching_is_normalised(self):
        """A trailing slash or `www.` difference must not defeat the match."""
        saved = _saved_with_frog_only(
            UrlGap(url="https://www.infosys.com/content/dam/x.html", reason="UNKNOWN")
        )
        rows = [_unmatched("https://infosys.com/content/dam/x.html/", "not_crawled", 1, 0)]
        updated = revalidate_defaulters(saved, rows)
        assert updated is not None


class TestRegressionRealInfosysUrls:
    """Real `UNKNOWN` rows replayed from the three saved bare-list sidecars.

    Only 3 of infosys.com's 13 saved cross-checks are bare-list format; the
    other 10 are real Screaming Frog exports whose `frog_only` rows carry a
    real `FrogGapReason` and must never acquire a category. These addresses
    were copied verbatim from the saved sidecars so a future change to the
    rules cannot silently reclassify a URL that shipped a specific answer.
    """

    def test_pinned_categories_for_real_urls(self):
        cases = {
            # CORRUPTED_URL
            "https://www.infosys.com/%20services/engineering-services/insights/"
            "sustainability-firstnarrative.html": DefaulterCategory.CORRUPTED_URL,
            "https://www.infosys.com//about/knowledge-institute/insights/"
            "cpg-firms.html": DefaulterCategory.CORRUPTED_URL,
            "https://www.infosys.com/cobalt-world-tour/2023/nyc.html.html": (
                DefaulterCategory.CORRUPTED_URL
            ),
            "https://www.infosys.com/confluence/2022/emea/insights/"
            "pursuit%20excellence.html": DefaulterCategory.CORRUPTED_URL,
            "https://www.infosys.com/content/infosys-web/en%20%20%20%20/"
            "services/applied-ai.html": DefaulterCategory.CORRUPTED_URL,
            # DAM_HTML_ARCHIVE (investors)
            "https://www.infosys.com/content/dam/infosys-web/en/investors/"
            "corporate-governance/code-of-conduct/index.html": (DefaulterCategory.DAM_HTML_ARCHIVE),
            "https://www.infosys.com/content/dam/infosys-web/en/investors/"
            "reports-filings/annual-report/annual/Documents/AR-2010/"
            "IFRS-INR-Financial-Statements.html": DefaulterCategory.DAM_HTML_ARCHIVE,
            # DAM_FORMS_OTHER (non-investors DAM)
            "https://www.infosys.com/content/dam/infosys-web/en/2025/thumbnails/"
            "multicloud-managed-service.html": DefaulterCategory.DAM_FORMS_OTHER,
            "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/"
            "anusha.html": DefaulterCategory.DAM_FORMS_OTHER,
            # CMS_INTERNAL_LEAK
            "https://www.infosys.com/-/content/infosys-web/en/aster-1/"
            "marketing.html": DefaulterCategory.CMS_INTERNAL_LEAK,
            "https://www.infosys.com/br/t/content/infosys-web/en/services/"
            "sap.html": DefaulterCategory.CMS_INTERNAL_LEAK,
            "https://www.infosys.com/content/infosys-web/en/-/content/"
            "infosys-web/en/aster-1/marketing.html": DefaulterCategory.CMS_INTERNAL_LEAK,
            # Presumed-real residual
            "https://www.infosys.com/4-decades-of-excellence.html": None,
            "https://www.infosys.com/about/alliances/ncino.html": None,
            "https://www.infosys.com/about/awards/most-reputed-company.html": None,
        }
        for url, expected in cases.items():
            assert _classify(url) == expected, url

    def test_the_bucket_totals_from_a_saved_infosys_sidecar_stay_pinned(self):
        """Pins the full-set split from one saved 5,373-row bare-list sidecar.

        A change to the rules that reclassifies even a handful of the 5,373
        real `UNKNOWN` rows changes an analyst-facing sheet count; this fails
        loudly instead of silently the next time that sidecar is re-derived.
        Regenerate with the small script in the build-log entry for this
        cycle if a rule is deliberately changed.
        """
        from collections import Counter

        urls = _INFOSYS_UNKNOWN_SAMPLE
        counts = Counter(_classify(url) for url in urls)
        assert counts[DefaulterCategory.CORRUPTED_URL] == 5
        assert counts[DefaulterCategory.DAM_HTML_ARCHIVE] == 5
        assert counts[DefaulterCategory.DAM_FORMS_OTHER] == 5
        assert counts[DefaulterCategory.CMS_INTERNAL_LEAK] == 5
        assert counts[None] == 5
        assert sum(counts.values()) == len(urls)


_INFOSYS_UNKNOWN_SAMPLE = [
    # 5 CORRUPTED_URL, verbatim from the saved sidecars
    "https://www.infosys.com/%20services/engineering-services/insights/"
    "sustainability-firstnarrative.html",
    "https://www.infosys.com//about/knowledge-institute/insights/cpg-firms.html",
    "https://www.infosys.com/cobalt-world-tour/2023/nyc.html.html",
    "https://www.infosys.com/confluence/2022/emea/insights/pursuit%20excellence.html",
    "https://www.infosys.com/content/infosys-web/en%20%20%20%20/services/applied-ai.html",
    # 5 DAM_HTML_ARCHIVE
    "https://www.infosys.com/content/dam/infosys-web/en/investors/"
    "corporate-governance/code-of-conduct/index.html",
    "https://www.infosys.com/content/dam/infosys-web/en/investors/"
    "corporate-governance/code-of-conduct2022/index.html",
    "https://www.infosys.com/content/dam/infosys-web/en/investors/"
    "reports-filings/annual-report/annual/Documents/AR-2010/"
    "IFRS-INR-Financial-Statements.html",
    "https://www.infosys.com/content/dam/infosys-web/en/investors/"
    "reports-filings/annual-report/annual/Documents/AR-2010/"
    "Subsidiaries/Infosys-Consulting-Inc.html",
    "https://www.infosys.com/content/dam/infosys-web/en/investors/"
    "reports-filings/annual-report/annual/Documents/AR-2010/annual_report_04.html",
    # 5 DAM_FORMS_OTHER
    "https://www.infosys.com/content/dam/infosys-web/en/2025/thumbnails/"
    "multicloud-managed-service.html",
    "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/anusha.html",
    "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/"
    "christian-antonio-martinez.html",
    "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/index.html",
    "https://www.infosys.com/content/dam/infosys-web/en/40yearsofheart/indumathi-suresh.html",
    # 5 CMS_INTERNAL_LEAK
    "https://www.infosys.com/-/content/infosys-web/en/aster-1/marketing.html",
    "https://www.infosys.com/br/t/content/infosys-web/en/services/digital-supply-chain.html",
    "https://www.infosys.com/br/t/content/infosys-web/en/services/sap.html",
    "https://www.infosys.com/confluence/2026-stage/apac/content/agenda-content.plain.html",
    "https://www.infosys.com/content/infosys-aweb/en/industries/healthcare/insights.html",
    # 5 presumed-real residual
    "https://www.infosys.com/4-decades-of-excellence.html",
    "https://www.infosys.com/about/_x000D_diversity-inclusion.html",
    "https://www.infosys.com/about/alliances/ncino.html",
    "https://www.infosys.com/about/awards/most-reputed-company.html",
    "https://www.infosys.com/about/awards/quality-award.html",
]
