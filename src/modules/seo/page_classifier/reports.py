"""Master URL Report generation for crawl results.

Exports crawl results to Excel with 3 sheets:
1. All URLs — Complete data (GSC metrics, hierarchy, type, etc.)
2. By Indexability — URLs grouped by indexable/non-indexable/blocked status
3. By HTTP Status — URLs grouped by HTTP response code

`generate_pdf` produces a fourth format from the same "All URLs" columns, as
a flat table with no grouping — the by-indexability and by-HTTP-status views
are workbook-specific navigational aids, not part of "every URL this crawl
found".

Uses openpyxl for Excel generation and reportlab for PDF (ADR 0024).
"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as _xml_escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile
    from .tool import PageClassificationOutput

__all__ = ["MasterURLReport"]

# Points, not inches — reportlab's native unit. Widths favour the two
# free-text columns (URL, Discovery Method); the rest hold short enums or
# numbers. Sums to 795pt, inside a landscape A4 page's ~806pt usable width
# after the 18pt margins `generate_pdf` sets.
_PDF_COLUMN_WIDTHS = [170, 70, 70, 55, 50, 60, 50, 60, 40, 90, 80]


class MasterURLReport:
    """Generate Excel report with all URLs and GSC metrics."""

    def __init__(self, result: PageClassificationOutput) -> None:
        """Build report from crawl result."""
        self.result = result
        self.workbook = Workbook()
        self.workbook.remove(self.workbook.active)  # Remove default sheet

    def generate(self) -> BytesIO:
        """Generate Excel workbook and return as bytes."""
        self._sheet_all_urls()
        self._sheet_by_indexability()
        self._sheet_by_http_status()

        output = BytesIO()
        self.workbook.save(output)
        output.seek(0)
        return output

    def generate_pdf(self) -> BytesIO:
        """Generate a flat, one-row-per-page PDF and return it as bytes.

        Same eleven columns and row order as the "All URLs" sheet — no
        grouping. "Every URL this crawl found" is the promise the job-row
        menu's "Download URLs" entry makes; the by-indexability and
        by-HTTP-status sheets above are workbook-specific navigational aids
        layered on top of that list, not part of it.

        Landscape A4: eleven columns do not fit a portrait page at a
        readable size. Every cell is a `Paragraph`, not a bare string —
        `Table` does not wrap plain text, so a long URL would overflow into
        its neighbour column instead of wrapping onto a second line.
        """
        headers = [
            "URL",
            "Hierarchy Level",
            "Page Type",
            "HTTP Status",
            "GSC Clicks",
            "GSC Impressions",
            "GSC CTR %",
            "GSC Avg Position",
            "Depth",
            "Discovery Method",
            "Reachability Tier",
        ]
        header_style = ParagraphStyle(
            "pdf-header", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white
        )
        body_style = ParagraphStyle("pdf-cell", fontName="Helvetica", fontSize=7, leading=9)

        rows: list[list[Paragraph]] = [
            [Paragraph(_xml_escape(text), header_style) for text in headers]
        ]
        for page in self.result.pages:
            rows.append(
                [Paragraph(_xml_escape(value), body_style) for value in self._pdf_row(page)]
            )

        table = Table(rows, colWidths=_PDF_COLUMN_WIDTHS, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#366092")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F2F2F2")],
                    ),
                ]
            )
        )

        output = BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            leftMargin=18,
            rightMargin=18,
            topMargin=18,
            bottomMargin=18,
        )
        doc.build([table])
        output.seek(0)
        return output

    def _pdf_row(self, page: FullPageIntelligenceProfile) -> list[str]:
        """The eleven "All URLs" cell values for one page, as plain strings.

        Shared with nothing else in this file: openpyxl accepts the typed
        values (enums, ints, floats) directly and applies its own cell
        formatting, where `Paragraph` needs pre-formatted text. Kept as a
        column-for-column match to `_sheet_all_urls` regardless, so the two
        exports never drift into reporting different data for the same job.
        """
        status_code = self._extract_status_code(page)
        return [
            page.url,
            str(page.hierarchy_level),
            str(page.primary_page_type),
            str(status_code) if status_code is not None else "Unknown",
            str(page.gsc_clicks or 0),
            str(page.gsc_impressions or 0),
            f"{(page.gsc_ctr * 100):.2f}" if page.gsc_ctr else "0.00",
            str(page.gsc_avg_position or 0),
            str(page.depth_from_l0),
            str(page.navigation_discovery_method) if page.navigation_discovery_method else "—",
            str(page.navigation_reachability_tier) if page.navigation_reachability_tier else "—",
        ]

    def _sheet_all_urls(self) -> None:
        """Sheet 1: All URLs with complete data."""
        ws = self.workbook.create_sheet("All URLs", 0)

        headers = [
            "URL",
            "Hierarchy Level",
            "Page Type",
            "HTTP Status",
            "GSC Clicks",
            "GSC Impressions",
            "GSC CTR %",
            "GSC Avg Position",
            "Depth",
            "Discovery Method",
            "Reachability Tier",
        ]
        ws.append(headers)
        self._style_header_row(ws)

        for page in self.result.pages:
            status_code = self._extract_status_code(page)
            row = [
                page.url,
                page.hierarchy_level,
                page.primary_page_type,
                str(status_code) if status_code is not None else "Unknown",
                page.gsc_clicks or 0,
                page.gsc_impressions or 0,
                (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                page.gsc_avg_position or 0,
                page.depth_from_l0,
                page.navigation_discovery_method or "—",
                page.navigation_reachability_tier or "—",
            ]
            ws.append(row)

        self._auto_fit_columns(ws)

    def _sheet_by_indexability(self) -> None:
        """Sheet 2: URLs grouped by indexability.

        Indexability determined by HTTP status:
        - 2xx: Indexable
        - 3xx: Redirect (indexable)
        - 4xx: Blocked
        - 5xx: Server error (treat as blocked)
        - Other: Unknown
        """
        ws = self.workbook.create_sheet("By Indexability", 1)

        # Group pages by indexability
        indexable = []
        blocked = []
        unknown = []

        for page in self.result.pages:
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

        # Indexable section
        for page in indexable:
            row = [
                "Indexable",
                page.url,
                page.primary_page_type,
                page.gsc_clicks or 0,
                page.gsc_impressions or 0,
                (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                page.gsc_avg_position or 0,
            ]
            ws.append(row)

        # Blocked section
        for page in blocked:
            row = [
                "Blocked",
                page.url,
                page.primary_page_type,
                page.gsc_clicks or 0,
                page.gsc_impressions or 0,
                (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                page.gsc_avg_position or 0,
            ]
            ws.append(row)

        # Unknown section
        for page in unknown:
            row = [
                "Unknown",
                page.url,
                page.primary_page_type,
                page.gsc_clicks or 0,
                page.gsc_impressions or 0,
                (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                page.gsc_avg_position or 0,
            ]
            ws.append(row)

        self._auto_fit_columns(ws)

    def _sheet_by_http_status(self) -> None:
        """Sheet 3: URLs grouped by HTTP status code."""
        ws = self.workbook.create_sheet("By HTTP Status", 2)

        # Group by status code
        by_status: dict[str, list[FullPageIntelligenceProfile]] = defaultdict(list)
        for page in self.result.pages:
            status = self._extract_status_code(page)
            status_str = str(status) if status else "Unknown"
            by_status[status_str].append(page)

        headers = [
            "HTTP Status",
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

        # Sort status codes numerically - separate unknown from numeric statuses
        numeric_statuses: list[str] = sorted(
            [s for s in by_status if s != "Unknown"],
            key=lambda x: int(x),
        )
        all_statuses: list[str] = list(numeric_statuses)
        if "Unknown" in by_status:
            all_statuses.append("Unknown")

        for status in all_statuses:  # type: ignore[assignment]
            pages = by_status[status]  # type: ignore[index]
            for page in pages:
                row = [
                    status,
                    page.url,
                    page.primary_page_type,
                    page.hierarchy_level,
                    page.gsc_clicks or 0,
                    page.gsc_impressions or 0,
                    (page.gsc_ctr * 100) if page.gsc_ctr else 0,
                    page.gsc_avg_position or 0,
                ]
                ws.append(row)

        self._auto_fit_columns(ws)

    @staticmethod
    def _extract_status_code(page: FullPageIntelligenceProfile) -> int | None:
        """Extract HTTP status code from page, if one was ever recorded.

        Always `None`. This is not a placeholder awaiting a future field: the
        raw status is deliberately discarded after the fetcher derives
        `indexability` from it (see `discovery.py::SiteGraph.record_fetch`,
        "raw inputs are dropped") to avoid holding response headers for every
        page in a crawl that already keeps its whole graph in RAM.
        `FullPageIntelligenceProfile` has no field to carry it even for the
        cases (4xx, 3xx) where `indexability_reason` happens to mention the
        code in prose. Callers must treat `None` as "not tracked", never
        substitute another field (e.g. a URL) in its place.
        """
        return None

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
