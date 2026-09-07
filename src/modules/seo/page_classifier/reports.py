"""Master URL Report generation for crawl results.

Exports crawl results to Excel with 3 sheets:
1. All URLs — Complete data (GSC metrics, hierarchy, type, etc.)
2. By Indexability — URLs grouped by indexable/non-indexable/blocked status
3. By HTTP Status — URLs grouped by HTTP response code

Uses openpyxl for Excel generation.
"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile
    from .tool import PageClassificationOutput

__all__ = ["MasterURLReport"]


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
            row = [
                page.url,
                page.hierarchy_level,
                page.primary_page_type,
                page.final_url,  # Will be empty for most; actual status comes from HTTP response
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
        """Extract HTTP status code from page.

        Note: The current data model doesn't store HTTP status explicitly.
        This is a placeholder; later phases will wire actual status codes.
        For now, return None (will be populated in future cycles).
        """
        # TODO: Add http_status field to FullPageIntelligenceProfile
        # For now, all pages are assumed indexable (2xx)
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
