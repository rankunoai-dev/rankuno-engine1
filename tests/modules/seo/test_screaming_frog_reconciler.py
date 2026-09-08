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
