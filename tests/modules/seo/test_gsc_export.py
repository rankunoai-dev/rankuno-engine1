"""Tests for reading a Search Console page export.

The archives here are built the way Search Console builds them — six localised
tabs, the pages one not necessarily first and not necessarily named in English —
because every interesting failure in this parser is a failure to pick the right
table out of a file that contains five wrong ones.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook
from src.modules.seo.performance.gsc_export import (
    MAX_UNPACKED_BYTES,
    GscExport,
    load_gsc_export,
)

PAGES = (
    "Top pages,Clicks,Impressions,CTR,Position\n"
    "https://e.com/pricing/,120,4000,3%,4.2\n"
    "https://e.com/blog/post/,15,900,1.67%,18.4\n"
)
QUERIES = (
    "Top queries,Clicks,Impressions,CTR,Position\n"
    "invoice software,300,9000,3.33%,2.1\n"
    "accounts receivable,90,7000,1.29%,11.8\n"
)
DATES = "Date,Clicks,Impressions,CTR,Position\n2026-08-01,10,100,10%,5.0\n"
COUNTRIES = "Country,Clicks,Impressions,CTR,Position\nUnited States,50,500,10%,6.0\n"
DEVICES = "Device,Clicks,Impressions,CTR,Position\nDesktop,40,400,10%,7.0\n"


def archive(**files: str) -> bytes:
    """A ZIP of CSVs, as Export → CSV produces."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, text in files.items():
            handle.writestr(name.replace("__", " ").replace("_csv", ".csv"), text)
    return buffer.getvalue()


def workbook(**sheets: str) -> bytes:
    """An .xlsx of the same tabs, as Export → Excel produces."""
    book = Workbook()
    default = book.active
    if default is not None:
        book.remove(default)
    for name, text in sheets.items():
        sheet = book.create_sheet(name.replace("__", " "))
        for line in text.strip().splitlines():
            sheet.append(line.split(","))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class TestWhatAPersonActuallyDownloads:
    def test_the_zip_from_export_csv(self):
        """The default download is an archive, not a CSV.

        Rejecting it and asking for the bare CSV would reject the file every
        analyst actually has.
        """
        result = load_gsc_export(
            archive(
                Queries_csv=QUERIES,
                Pages_csv=PAGES,
                Dates_csv=DATES,
                Countries_csv=COUNTRIES,
                Devices_csv=DEVICES,
            )
        )
        assert [row.url for row in result.rows] == [
            "https://e.com/pricing/",
            "https://e.com/blog/post/",
        ]
        assert result.source_name == "Pages.csv"

    def test_the_workbook_from_export_excel(self):
        result = load_gsc_export(workbook(Queries=QUERIES, Pages=PAGES, Dates=DATES))
        assert [row.clicks for row in result.rows] == [120, 15]
        assert result.source_name == "Pages"

    def test_a_bare_csv_somebody_already_unpacked(self):
        result = load_gsc_export(PAGES)
        assert len(result.rows) == 2
        assert result.source_name == ""

    def test_raw_bytes_with_a_byte_order_mark(self):
        """Raw bytes with a byte order mark.

        Left in place the BOM becomes an invisible prefix on the first
        header, and the address column is never found.
        """
        result = load_gsc_export(b"\xef\xbb\xbf" + PAGES.encode())
        assert len(result.rows) == 2


class TestPickingTheRightTab:
    def test_the_queries_tab_is_not_mistaken_for_pages(self):
        """The queries tab is not mistaken for pages.

        It carries identical numeric columns. Only the first column differs,
        and reading it would produce an export where nothing resolves.
        """
        result = load_gsc_export(archive(Queries_csv=QUERIES, Pages_csv=PAGES))
        assert all(row.url.startswith("https://") for row in result.rows)

    def test_a_localised_archive_is_read_by_content_not_by_name(self):
        """The archive is written in the account's display language.

        Matching `Pages.csv` works for English accounts and silently fails for
        every other one, which is the worst possible distribution of a bug.
        """
        german = (
            "Haufigste Seiten,Klicks,Impressionen,CTR,Position\n"
            "https://e.com/preise/,80,2000,4%,3.1\n"
        )
        result = load_gsc_export(
            archive(Suchanfragen_csv=QUERIES, Seiten_csv=german, Lander_csv=COUNTRIES)
        )
        assert [row.url for row in result.rows] == ["https://e.com/preise/"]
        assert result.rows[0].clicks == 80
        assert result.source_name == "Seiten.csv"

    def test_an_archive_of_only_wrong_tabs_is_refused(self):
        """Better to say the file holds no pages than to report on queries.

        And to name the tabs it does hold, so the reader can see they have the
        wrong export rather than a broken one.
        """
        with pytest.raises(ValueError, match="no tab in this file holds page") as caught:
            load_gsc_export(archive(Queries_csv=QUERIES, Dates_csv=DATES))
        assert "Queries.csv" in str(caught.value)

    def test_the_page_indexing_report_says_which_report_to_use(self):
        """The wrong Search Console report, named by what it contains.

        A real upload, 2026-08-21: `rankuno.com-Coverage-2026-08-21.xlsx`, the
        Page indexing report. Four sheets, not one URL in any of them — Chart is
        dates against counts, both issues sheets are reasons against page
        *counts*, and Metadata is a property list.

        Refusing it is right. The first version of the refusal described the
        file it wanted and never the file it got, so somebody holding this one
        read a message that was true of every word and no help at all.
        """
        coverage = workbook(
            Chart="Date,Not indexed,Indexed,Impressions\n2026-05-23,98,62,88",
            Critical__issues=(
                "Reason,Source,Validation,Pages\nPage with redirect,Website,Not Started,26"
            ),
            Metadata="Property,Value\nSitemap,All known pages",
        )
        with pytest.raises(ValueError) as caught:
            load_gsc_export(coverage)
        message = str(caught.value)
        # What it found, so the reader can see it is holding the wrong export.
        assert "Chart" in message
        assert "Critical issues" in message
        # And which report does have pages in it.
        assert "Performance" in message
        # Plain text: this reaches a banner that does not render markdown.
        assert "**" not in message

    def test_a_page_indexing_url_list_is_refused_despite_holding_addresses(self):
        """Addresses without metrics is the dangerous wrong file.

        A real upload, 2026-08-21: `gep.com-Coverage-Valid-2026-08-21.xlsx`, the
        Page indexing "valid pages" export. Its `Table` sheet is `URL, Last
        crawled` — 1,000 genuine addresses and not one number.

        The address gate passes it, so it resolved against the crawl and
        produced a confident report of 967 matched pages with zero traffic,
        replacing a real one. Missing addresses is caught by the share gate;
        this is the case where the addresses are real and the report is not.
        """
        indexing = workbook(
            Chart="Date,Affected pages\n2026-05-25,5843",
            Table="URL,Last crawled\nhttps://e.com/a/,2026-08-18\nhttps://e.com/b/,2026-08-18",
            Metadata="Property,Value\nSitemap,All known pages",
        )
        with pytest.raises(ValueError, match="no clicks or impressions") as caught:
            load_gsc_export(indexing)
        message = str(caught.value)
        # Names the sheet it read, so the reader can see which one was tried.
        assert "Table" in message
        assert "Performance" in message

    def test_an_export_where_every_row_is_zero_is_refused_too(self):
        """The same guard, and the right answer.

        A Performance export with no impressions anywhere describes a property
        with nothing to report; saying so beats a page of zeroes that reads like
        a finding.
        """
        with pytest.raises(ValueError, match="no clicks or impressions"):
            load_gsc_export(
                "Top pages,Clicks,Impressions,CTR,Position\nhttps://e.com/a/,0,0,0%,0\n"
            )

    def test_a_one_row_tab_does_not_beat_the_real_one(self):
        """A one row tab does not beat the real one.

        A filters tab naming a single page is unanimous about its one row and
        would win on share alone. The tie breaks toward the larger table.
        """
        filters = "Filter,Value\nPage,https://e.com/only/\n"
        result = load_gsc_export(archive(Filters_csv=filters, Pages_csv=PAGES))
        assert len(result.rows) == 2

    def test_every_sheet_of_a_workbook_is_considered_not_just_the_active_one(self):
        """The active sheet is whichever tab was selected when it was saved."""
        result = load_gsc_export(workbook(Dates=DATES, Countries=COUNTRIES, Pages=PAGES))
        assert result.source_name == "Pages"


class TestColumnsAndNumbers:
    def test_headers_are_matched_by_keyword_when_they_are_recognisable(self):
        reordered = "Top pages,Impressions,Clicks,CTR,Position\nhttps://e.com/a/,4000,120,3%,4.2\n"
        row = load_gsc_export(reordered).rows[0]
        assert row.clicks == 120
        assert row.impressions == 4000

    def test_unrecognisable_headers_fall_back_to_column_order(self):
        """Unrecognisable headers fall back to column order.

        Search Console writes the same column order in every language, so
        position survives translation where words do not.
        """
        japanese = "ページ,クリック数,表示回数,CTR,掲載順位\nhttps://e.com/a/,7,70,10%,9.5\n"
        row = load_gsc_export(japanese).rows[0]
        assert (row.clicks, row.impressions, row.position) == (7, 70, 9.5)

    def test_a_file_with_no_header_at_all(self):
        row = load_gsc_export("https://e.com/a/,5,50,10%,3.3\n").rows[0]
        assert (row.clicks, row.impressions) == (5, 50)

    def test_thousands_separators_of_either_convention(self):
        text = (
            "Top pages,Clicks,Impressions,CTR,Position\n"
            'https://e.com/a/,"1,234","56,789",2%,4.2\n'
            "https://e.com/b/,1.234,56.789,2%,4.2\n"
            "https://e.com/c/,1 234,56 789,2%,4.2\n"
        )
        rows = load_gsc_export(text).rows
        assert [row.clicks for row in rows] == [1234, 1234, 1234]
        assert [row.impressions for row in rows] == [56789, 56789, 56789]

    def test_a_decimal_comma_position(self):
        """`12,34` and `12.34` are one number written for two locales.

        Quoted, because a bare decimal comma in a comma-delimited file is a
        sixth column rather than a decimal — which is exactly why the locales
        writing it that way delimit with semicolons instead.
        """
        text = 'Top pages,Clicks,Impressions,CTR,Position\nhttps://e.com/a/,1,10,10%,"12,34"\n'
        assert load_gsc_export(text).rows[0].position == pytest.approx(12.34)

    def test_a_semicolon_delimited_export(self):
        """A semicolon delimited export.

        A locale that uses the comma as a decimal separator delimits with
        semicolons. Read as comma-separated it yields one column and no address.
        """
        text = "Seiten;Klicks;Impressionen;CTR;Position\nhttps://e.com/a/;80;2000;4%;3,1\n"
        row = load_gsc_export(text).rows[0]
        assert row.clicks == 80
        assert row.position == pytest.approx(3.1)

    def test_blank_and_dashed_cells_read_as_zero_not_as_an_error(self):
        """One empty row is a cell to parse, not a file to refuse.

        The second row exists because the whole-file guard rejects an export
        where *nothing* has clicks or impressions. That guard is about the file;
        this is about a cell, and a real export routinely carries both.
        """
        text = (
            "Top pages,Clicks,Impressions,CTR,Position\n"
            "https://e.com/a/,,-,,\n"
            "https://e.com/b/,9,90,10%,3.0\n"
        )
        row = load_gsc_export(text).rows[0]
        assert (row.clicks, row.impressions, row.position) == (0, 0, 0.0)

    def test_rows_with_no_address_are_counted_not_dropped_silently(self):
        text = (
            "Top pages,Clicks,Impressions,CTR,Position\n"
            "https://e.com/a/,1,10,10%,3.0\n"
            "https://e.com/b/,1,10,10%,3.0\n"
            "https://e.com/c/,1,10,10%,3.0\n"
            "https://e.com/d/,1,10,10%,3.0\n"
            ",5,50,10%,3.0\n"
            "(anonymised),5,50,10%,3.0\n"
        )
        result = load_gsc_export(text)
        assert len(result.rows) == 4
        assert result.skipped_rows == 2

    def test_a_table_that_is_mostly_not_addresses_is_refused_outright(self):
        """A table that is mostly not addresses is refused outright.

        The share gate is what stands between a queries export and a report
        in which every single row fails to resolve.

        It applies to a lone CSV as much as to a tab inside an archive: someone
        who unpacks the ZIP and picks the wrong file is told so, rather than
        handed a rollup of search phrases. With no tab names to list, the
        message names the column instead.
        """
        with pytest.raises(ValueError, match="first column holds no page addresses"):
            load_gsc_export(QUERIES)


class TestRefusals:
    def test_a_zip_that_is_not_a_zip(self):
        with pytest.raises(ValueError, match="not a readable Search Console"):
            load_gsc_export(b"PK\x03\x04 and then nonsense")

    def test_an_archive_with_no_csv_in_it(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as handle:
            handle.writestr("readme.txt", "nothing here")
        with pytest.raises(ValueError, match="not a readable Search Console"):
            load_gsc_export(buffer.getvalue())

    def test_a_declared_expansion_over_the_limit_is_refused(self):
        """A declared expansion over the limit is refused.

        A ZIP declares its own uncompressed size, and a hostile one declares
        a small body that expands without bound. The endpoint bounds the upload;
        only this bounds what the upload becomes.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("Pages.csv", "x" * (MAX_UNPACKED_BYTES + 1))
        with pytest.raises(ValueError, match="over the"):
            load_gsc_export(buffer.getvalue())

    def test_an_empty_body(self):
        with pytest.raises(ValueError, match="not a readable Search Console"):
            load_gsc_export("")

    def test_a_header_with_no_data_under_it(self):
        with pytest.raises(ValueError, match="first column holds no page addresses"):
            load_gsc_export("Top pages,Clicks,Impressions,CTR,Position\n")


class TestTheContract:
    def test_an_empty_export_model_is_constructible(self):
        assert GscExport().rows == ()

    def test_ctr_is_not_carried(self):
        """Ctr is not carried.

        It is the one column that must never be used — a section's CTR is
        recomputed from summed clicks over summed impressions.
        """
        row = load_gsc_export(PAGES).rows[0]
        assert row.ctr == pytest.approx(120 / 4000)
