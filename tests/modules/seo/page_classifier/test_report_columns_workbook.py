"""The trailing "All URLs" columns as a client receives them, in the xlsx and PDF.

Pins the column contract (A-L byte-stable, nine columns appended in order),
checks the new cells for the edge cases through the real workbook, and shows
the PDF still carries exactly its original twelve columns. The per-column rules
are in `test_report_columns.py`.
"""

from __future__ import annotations

import re

from openpyxl import load_workbook
from src.modules.seo.page_classifier.discovery import OUTCOME_NOT_FETCHED
from src.modules.seo.page_classifier.fetch_status import LABEL_NOT_RECORDED
from src.modules.seo.page_classifier.report_columns import (
    CTR_DECIMAL_FORMAT,
    CTR_DECIMAL_HEADER,
    TRAILING_HEADERS,
)
from src.modules.seo.page_classifier.reports import _PDF_COLUMN_WIDTHS, MasterURLReport
from src.modules.seo.page_classifier.schemas import DiscoverySource, FullPageIntelligenceProfile
from tests.modules.seo.page_classifier.report_profile_factory import (
    legacy_page,
    make_page,
    make_result,
    pdf_text,
)

# The twelve A-L headers as shipped. Pinned literally: a reordering or a rename
# of any of them breaks every downstream spreadsheet that reads by column.
LEGACY_HEADERS = [
    "URL",
    "Hierarchy Level",
    "Page Type",
    "HTTP Status",
    "First Redirect",
    "GSC Clicks",
    "GSC Impressions",
    "GSC CTR %",
    "GSC Avg Position",
    "Depth",
    "Discovery Method",
    "Reachability Tier",
]
NEW_HEADERS = [
    "Found Via",
    "In Sitemap",
    "Unique Inlinks",
    "Unique Outlinks",
    "Orphan",
    "GSC CTR (decimal)",
    "Final URL",
    "Indexability",
    "Indexability Reason",
]


def _all_urls(
    pages: tuple[FullPageIntelligenceProfile, ...],
) -> tuple[list[str], list[tuple[object, ...]]]:
    """Headers and data rows of the "All URLs" sheet for the given pages."""
    book = load_workbook(MasterURLReport(make_result(*pages)).generate())
    ws = book["All URLs"]
    headers = [str(cell.value) for cell in ws[1]]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    return headers, rows


class TestHeaders:
    """The column contract: A-L untouched, nine columns appended in order."""

    def test_trailing_headers_are_pinned_in_order(self) -> None:
        assert list(TRAILING_HEADERS) == NEW_HEADERS

    def test_all_urls_header_row_is_legacy_then_trailing(self) -> None:
        headers, _ = _all_urls((make_page(),))
        assert headers == LEGACY_HEADERS + NEW_HEADERS

    def test_the_twelve_legacy_headers_are_unchanged(self) -> None:
        headers, _ = _all_urls((make_page(),))
        assert headers[:12] == LEGACY_HEADERS
        assert len(headers) == 21

    def test_other_sheets_keep_their_headers(self) -> None:
        book = load_workbook(MasterURLReport(make_result(make_page())).generate())

        by_indexability = [cell.value for cell in book["By Indexability"][1]]
        by_status = [cell.value for cell in book["By HTTP Status"][1]]
        assert by_indexability == [
            "Status",
            "URL",
            "Page Type",
            "GSC Clicks",
            "GSC Impressions",
            "GSC CTR %",
            "GSC Avg Position",
        ]
        assert by_status == [
            "HTTP Status",
            "First Redirect",
            "URL",
            "Page Type",
            "Hierarchy Level",
            "GSC Clicks",
            "GSC Impressions",
            "GSC CTR %",
            "GSC Avg Position",
        ]


class TestCtrCell:
    def test_the_cell_carries_the_decimal_and_its_format(self) -> None:
        page = make_page(gsc_clicks=23, gsc_impressions=1000, gsc_ctr=0.023)
        book = load_workbook(MasterURLReport(make_result(page)).generate())
        ws = book["All URLs"]
        headers = [cell.value for cell in ws[1]]
        cell = ws.cell(row=2, column=headers.index(CTR_DECIMAL_HEADER) + 1)

        assert abs(cell.value - 0.023) < 1e-12
        assert cell.number_format == CTR_DECIMAL_FORMAT == "0.000"

    def test_the_existing_percent_column_is_untouched(self) -> None:
        """Still 2.3, not 0.023: the decimal is a new column, not a change."""
        page = make_page(gsc_clicks=23, gsc_impressions=1000, gsc_ctr=0.023)
        book = load_workbook(MasterURLReport(make_result(page)).generate())
        ws = book["All URLs"]
        headers = [cell.value for cell in ws[1]]
        percent = ws.cell(row=2, column=headers.index("GSC CTR %") + 1).value

        assert abs(percent - 2.3) < 1e-9


class TestWorkbookRows:
    """The new cells for each edge case, read back through the real workbook."""

    def test_each_edge_case_lands_in_its_own_row(self) -> None:
        redirect = make_page(
            "https://e.com/moved/",
            final_url="https://e.com/moved-to/",
            first_redirect_status=301,
            discovery_sources=DiscoverySource(sitemap=True, dom_link=True),
        )
        not_fetched = make_page(
            "https://e.com/sitemap-only/",
            http_status=None,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            final_url="",
            discovery_sources=DiscoverySource(sitemap=True),
            inbound_internal_links_count=0,
        )
        legacy = legacy_page("https://e.com/old/")

        headers, rows = _all_urls((redirect, not_fetched, legacy))
        by_url = {str(row[0]): dict(zip(headers, row, strict=True)) for row in rows}

        moved = by_url["https://e.com/moved/"]
        assert moved["Found Via"] == "Crawl link"
        assert moved["Final URL"] == "https://e.com/moved-to/"
        assert moved["Orphan"] == "No"

        sitemap_only = by_url["https://e.com/sitemap-only/"]
        assert sitemap_only["In Sitemap"] == "Yes"
        assert sitemap_only["Orphan"] == "Yes"
        assert sitemap_only["Unique Inlinks"] == 0
        assert sitemap_only["Unique Outlinks"] is None
        assert sitemap_only["Final URL"] is None
        assert sitemap_only[CTR_DECIMAL_HEADER] is None
        assert sitemap_only["Indexability"] == "UNKNOWN"

        old = by_url["https://e.com/old/"]
        for header in NEW_HEADERS:
            if header in (CTR_DECIMAL_HEADER, "Indexability Reason"):
                continue
            assert old[header] == LABEL_NOT_RECORDED, header

    def test_the_trailing_columns_do_not_move_legacy_values(self) -> None:
        headers, rows = _all_urls(
            (make_page("https://e.com/p/", gsc_clicks=4, gsc_impressions=80),)
        )
        row = rows[0]

        assert row[0] == "https://e.com/p/"
        assert row[headers.index("GSC Clicks")] == 4
        assert row[headers.index("GSC Impressions")] == 80
        assert len(row) == 21


class TestPdfUnchanged:
    def test_the_pdf_still_carries_exactly_its_twelve_columns(self) -> None:
        report = MasterURLReport(make_result(make_page()))
        text = pdf_text(report.generate_pdf().getvalue())
        joined = re.sub(rb"\) Tj T\* \(", b" ", text)

        for header in LEGACY_HEADERS:
            assert header.encode() in joined, header
        for header in NEW_HEADERS:
            assert header.encode() not in joined, header
        assert len(_PDF_COLUMN_WIDTHS) == 12
        assert sum(_PDF_COLUMN_WIDTHS) == 774

    def test_the_pdf_row_is_twelve_cells(self) -> None:
        page = make_page()
        assert len(MasterURLReport(make_result(page))._pdf_row(page)) == 12

    def test_the_pdf_is_still_a_pdf(self) -> None:
        pdf = MasterURLReport(make_result(make_page())).generate_pdf()
        assert pdf.getvalue().startswith(b"%PDF")
