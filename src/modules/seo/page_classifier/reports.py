"""Master URL Report generation for crawl results.

Exports crawl results to Excel with up to 4 sheets:
1. All URLs — Complete data (GSC metrics, hierarchy, type, top queries, category)
2. By Indexability — URLs grouped by indexable/non-indexable/blocked status
3. By HTTP Status — URLs grouped by HTTP response code
4. Top Queries — long format, one row per URL and rank; only when a query fetch exists

Every sheet lists pages in path-category order (see `contracts.url_category`),
and the two grouped sheets keep that order inside each group. `generate_pdf`
renders the same rows as a flat table with no grouping, in the same order.

Every text cell passes through `safe_cell`, so a URL or query that a spreadsheet
would run as a formula is written inert. The PDF and the sheets share that rule.

Uses openpyxl for Excel generation and reportlab for PDF (ADR 0024).
"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.integrations.gsc_schemas import GscPageQueries, GscQueryRow
from src.modules.seo.contracts.cell_guard import safe_cell
from src.modules.seo.contracts.url_category import category_key, category_sort_key
from src.modules.seo.performance.query_by_url import top_queries_by_crawl_url
from src.modules.seo.performance.query_sheet import (
    CATEGORY_HEADER,
    TOP_QUERIES_HEADER,
    TOP_QUERIES_SHEET,
    partial_banner,
    top_queries_cell,
    write_top_queries_sheet,
)

from .fetch_status import (
    LABEL_NO_RESPONSE,
    LABEL_NOT_FETCHED,
    LABEL_NOT_RECORDED,
    STATUS_LEGEND,
    first_redirect_label,
    http_status_label,
)
from .report_columns import (
    CONTENT_INLINKS_NOTE,
    CTR_DECIMAL_FORMAT,
    CTR_DECIMAL_HEADER,
    TRAILING_HEADERS,
    UNIQUE_CONTENT_INLINKS_HEADER,
    trailing_cells,
)
from .report_pdf import pdf_row as _pdf_cells
from .report_pdf import render_url_pdf
from .url_rules import normalize_url

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile
    from .tool import PageClassificationOutput

__all__ = ["MasterURLReport"]

# The no-status labels sort after the numeric codes on "By HTTP Status".
_LABEL_ORDER = (LABEL_NOT_FETCHED, LABEL_NO_RESPONSE, LABEL_NOT_RECORDED)


class MasterURLReport:
    """Generate the Excel and PDF URL reports for one finished crawl."""

    def __init__(
        self,
        result: PageClassificationOutput,
        queries: GscPageQueries | None = None,
    ) -> None:
        """Build the report from a crawl result and, optionally, a query fetch.

        Args:
            result: The finished crawl.
            queries: The query-by-page fetch saved against the job, or `None`.
                With `None` the Top Queries column is blank and no Top Queries
                sheet is written, so an export made before any fetch is unchanged
                apart from the appended Category column.
        """
        self.result = result
        self._queries = queries
        # The join returns each query set under the surviving copy's URL. Export rows
        # walk every page, including the copies the dedupe dropped, so both sides are
        # keyed by the dedupe's own key (`normalize_url`). Otherwise a dropped copy
        # would find nothing under its raw URL.
        top_by_url = top_queries_by_crawl_url(result.pages, queries)
        self._top_by_key = {normalize_url(url): rows for url, rows in top_by_url.items()}
        self.workbook = Workbook()
        self.workbook.remove(self.workbook.active)  # Remove default sheet

    def generate(self) -> BytesIO:
        """Generate Excel workbook and return as bytes."""
        self._sheet_all_urls()
        self._sheet_by_indexability()
        self._sheet_by_http_status()
        if self._queries is not None:
            self._sheet_top_queries()

        output = BytesIO()
        self.workbook.save(output)
        output.seek(0)
        return output

    def generate_pdf(self) -> BytesIO:
        """Generate a flat, one-row-per-page PDF and return it as bytes.

        Same twelve columns as the "All URLs" sheet, in the same category order,
        with no grouping. "Every URL this crawl found" is the promise the job-row
        menu's "Download URLs" entry makes; the by-indexability and by-HTTP-status
        sheets are workbook-specific navigational aids layered on top of that list.
        """
        return render_url_pdf(self._ordered_pages(), self._banner())

    def _ordered_pages(self) -> list[FullPageIntelligenceProfile]:
        """Every page in category order: the order all four exports share.

        Sorted on the raw URL, before any cell is guarded, so the order is the one
        the URLs themselves imply and not the one a formula guard happens to leave.
        """
        return sorted(self.result.pages, key=lambda page: category_sort_key(page.url))

    def _banner(self) -> str | None:
        """The partial-data banner for this report, or `None` when everything arrived."""
        gsc = self.result.gsc
        return partial_banner(
            page_metrics_complete=gsc.complete if gsc is not None else True,
            queries=self._queries,
        )

    def _top_queries_for(self, page: FullPageIntelligenceProfile) -> tuple[GscQueryRow, ...]:
        """The page's ranked queries, found by the same key the dedupe uses.

        Returns an empty tuple when no query row matched this page, so the cell is
        blank rather than attached to a guess.
        """
        return self._top_by_key.get(normalize_url(page.url), ())

    def _pdf_row(self, page: FullPageIntelligenceProfile) -> list[str]:
        """The twelve "All URLs" cell values for one page, as plain strings.

        Delegates to `report_pdf.pdf_row`. Kept as a method so the parity test
        that compares it with the sheet's cells reads the same as it always has.
        """
        return _pdf_cells(page)

    def _sheet_all_urls(self) -> None:
        """Sheet 1: All URLs with complete data."""
        ws = self.workbook.create_sheet("All URLs", 0)

        # Columns A-L are the original contract and keep their order. The
        # trailing columns are appended and must never move an existing one.
        headers = [
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
            *TRAILING_HEADERS,
            TOP_QUERIES_HEADER,
            CATEGORY_HEADER,
        ]
        ws.append(headers)
        self._style_header_row(ws)
        ws["D1"].comment = Comment(STATUS_LEGEND, "Rankuno", width=420, height=180)
        content_inlinks_header = headers.index(UNIQUE_CONTENT_INLINKS_HEADER) + 1
        ws.cell(row=1, column=content_inlinks_header).comment = Comment(
            CONTENT_INLINKS_NOTE, "Rankuno", width=420, height=140
        )
        top_header = headers.index(TOP_QUERIES_HEADER) + 1
        banner = self._banner()
        if banner is not None:
            # A comment, not a row: a note row under the data would be read as a
            # page by anyone who sorts or filters the table.
            ws.cell(row=1, column=top_header).comment = Comment(
                banner, "Rankuno", width=420, height=120
            )
        ctr_decimal_column = headers.index(CTR_DECIMAL_HEADER) + 1

        for page in self._ordered_pages():
            row: list[object] = [
                page.url,
                page.hierarchy_level,
                page.primary_page_type,
                http_status_label(page),
                first_redirect_label(page),
                page.gsc_clicks or 0,
                page.gsc_impressions or 0,
                (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                page.gsc_avg_position or 0,
                page.depth_from_l0 if page.depth_from_l0 is not None else "—",
                page.navigation_discovery_method or "—",
                page.navigation_reachability_tier or "—",
            ]
            row.extend(trailing_cells(page))
            row.append(top_queries_cell(self._top_queries_for(page)))
            row.append(category_key(page.url))
            ws.append([safe_cell(value) for value in row])
            ws.cell(row=ws.max_row, column=ctr_decimal_column).number_format = CTR_DECIMAL_FORMAT

        self._auto_fit_columns(ws)

    def _sheet_by_indexability(self) -> None:
        """Sheet 2: URLs grouped by indexability.

        Indexability determined by HTTP status:
        - 2xx: Indexable
        - 3xx: Redirect (indexable)
        - 4xx: Blocked
        - 5xx: Server error (treat as blocked)
        - No status (not fetched, no response, older crawl): Unknown

        Category order is kept inside each group, because the pages are already
        category-sorted and the grouping below is a stable partition.
        """
        ws = self.workbook.create_sheet("By Indexability", 1)

        # Group pages by indexability
        indexable = []
        blocked = []
        unknown = []

        for page in self._ordered_pages():
            status_code = self._extract_status_code(page)
            if status_code is None:
                unknown.append(page)
            elif 200 <= status_code < 400:
                indexable.append(page)
            elif status_code >= 400:
                blocked.append(page)
            else:
                unknown.append(page)

        headers = [
            "Status",
            "URL",
            "Page Type",
            "GSC Clicks",
            "GSC Impressions",
            "GSC CTR %",
            "GSC Avg Position",
        ]
        ws.append(headers)
        self._style_header_row(ws)

        for label, pages in (("Indexable", indexable), ("Blocked", blocked), ("Unknown", unknown)):
            for page in pages:
                row = [
                    label,
                    page.url,
                    page.primary_page_type,
                    page.gsc_clicks or 0,
                    page.gsc_impressions or 0,
                    (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                    page.gsc_avg_position or 0,
                ]
                ws.append([safe_cell(value) for value in row])

        self._auto_fit_columns(ws)

    def _sheet_by_http_status(self) -> None:
        """Sheet 3: URLs grouped by HTTP status code, category order inside each group."""
        ws = self.workbook.create_sheet("By HTTP Status", 2)

        # Group by status code, keeping the category order within each group.
        by_status: dict[str, list[FullPageIntelligenceProfile]] = defaultdict(list)
        for page in self._ordered_pages():
            by_status[http_status_label(page)].append(page)

        headers = [
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
        ws.append(headers)
        self._style_header_row(ws)

        # Numeric codes first, ascending; the three no-status labels after them.
        all_statuses: list[str] = sorted((s for s in by_status if s.isdigit()), key=int)
        all_statuses += [label for label in _LABEL_ORDER if label in by_status]

        for status in all_statuses:
            for page in by_status[status]:
                row = [
                    status,
                    first_redirect_label(page),
                    page.url,
                    page.primary_page_type,
                    page.hierarchy_level,
                    page.gsc_clicks or 0,
                    page.gsc_impressions or 0,
                    (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                    page.gsc_avg_position or 0,
                ]
                ws.append([safe_cell(value) for value in row])

        self._auto_fit_columns(ws)

    def _sheet_top_queries(self) -> None:
        """Sheet 4: the long-format top-queries table, in category order.

        Only written when a query fetch exists, so an export made without one keeps
        the three sheets it always had.
        """
        ws = self.workbook.create_sheet(TOP_QUERIES_SHEET)
        rows_by_url: dict[str, tuple[GscQueryRow, ...]] = {}
        for page in self._ordered_pages():
            ranked = self._top_queries_for(page)
            if ranked:
                rows_by_url.setdefault(page.url, ranked)
        write_top_queries_sheet(ws, list(rows_by_url), rows_by_url, self._banner())
        self._auto_fit_columns(ws)

    @staticmethod
    def _extract_status_code(page: FullPageIntelligenceProfile) -> int | None:
        """The page's recorded HTTP status, or `None` if there is none.

        `None` covers three different facts (never requested, no response,
        result predates the capture); `fetch_status.http_status_label` tells
        them apart. Callers must never substitute another field (e.g. a URL)
        in its place.
        """
        return page.http_status

    @staticmethod
    def _style_header_row(ws: Worksheet) -> None:
        """Apply header styling."""
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")

        for cell in ws[1]:
            if cell.value is not None:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

    @staticmethod
    def _auto_fit_columns(ws: Worksheet) -> None:
        """Auto-fit column widths based on content."""
        for column in ws.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                if cell.value:
                    try:
                        max_length = max(max_length, len(str(cell.value)))
                    except (ValueError, TypeError):
                        continue
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
