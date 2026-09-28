"""Response Codes masterfile service (HTTP status code issues).

Reads its catalogue sources and generates a single-sheet XLSX showing:
1. Summary: Status code groups (2xx, 3xx, 4xx, 5xx) with counts
2. Theme Wise: Pivot by Theme 1
3. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs: `SOURCE_FILES`, derived from IssueCategory.RESPONSE_CODES_INTERNAL through
`contracts/sources.py`. Never written out here - a hand-kept second
copy of that list is what build-log 0116 found wrong in this file.
"""

from __future__ import annotations

import io
from typing import Any, Final

import pandas as pd  # type: ignore[import-untyped]
from openpyxl import Workbook

from src.core.logger import get_logger
from src.modules.seo.contracts.issue_ids import IssueCategory
from src.modules.seo.contracts.sources import sources_for_categories
from src.modules.seo.deliverables.masterfile_base import (
    MasterfileMetadata,
    MasterfileService,
    gc,
    safe_cell,
)

__all__ = ["ResponseCodesService"]

_logger = get_logger(__name__)

_STATUS_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "2xx (Success)": ("200", "201", "202", "204", "206"),
    "3xx (Redirect)": ("300", "301", "302", "303", "304", "307", "308"),
    "4xx (Client Error)": ("400", "401", "403", "404", "405", "406", "408", "409", "410", "429"),
    "5xx (Server Error)": ("500", "501", "502", "503", "504", "505"),
}


class ResponseCodesService(MasterfileService):
    """Generate response codes masterfile."""

    SOURCE_FILES = sources_for_categories(IssueCategory.RESPONSE_CODES_INTERNAL)

    INDEXABLE_ONLY = False
    """A 4xx, 5xx or redirected URL is Non-Indexable. build-log 0104 §223
    already carved this service out of the indexable filter; the code
    carried the comment and applied the filter anyway."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="response_codes",
            label="Response Codes",
            sheets=1,
            is_complex=False,
        )

    def _read_all_response_codes(self) -> pd.DataFrame | None:
        """Read and combine all response code CSVs."""
        return self._read_issue_frames()

    def generate(self) -> bytes:
        """Generate response codes XLSX."""
        # Read data
        response_df = self._read_all_response_codes()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if response_df is None or response_df.empty:
            # Empty workbook
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "Response Codes"
                ws.append(["No response code data found"])
        else:
            # Extract URLs and enrich
            try:
                address_idx = gc(response_df.columns.tolist(), "Address")
                status_idx = gc(response_df.columns.tolist(), "Status Code")
            except KeyError:
                # Fallback: empty workbook
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "Response Codes"
                    ws.append(["Error reading response codes CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_status = []
            for _, row in response_df.iterrows():
                url = str(row.iloc[address_idx])
                status = str(row.iloc[status_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = self._gsc_lookup(gsc_map, url)

                indexability = internal_data.get("indexability")
                if not self._is_reportable(indexability):
                    continue

                urls_with_status.append(
                    {
                        "url": url,
                        "status_code": status,
                        "indexability": indexability,
                        "inlinks": internal_data.get("inlinks"),
                        "impressions": gsc_data.get("impressions", 0),
                        "clicks": gsc_data.get("clicks", 0),
                    }
                )

            # Build workbook
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "Response Codes"
                self._write_response_codes_sheet(ws, urls_with_status)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_response_codes_sheet(
        self,
        ws: object,
        urls_with_status: list[dict[str, Any]],
    ) -> None:
        """Write response codes sheet with summary, theme-wise, and detailed sections."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["RESPONSE CODES"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Status Code Group", "Count", "Percentage"])  # type: ignore[attr-defined]

        status_counts: dict[str, int] = {}
        for url_data in urls_with_status:
            status = url_data.get("status_code", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        total = len(urls_with_status)
        for status, count in sorted(status_counts.items()):
            pct = (count / total * 100) if total > 0 else 0
            ws.append([status, count, f"{pct:.1f}%"])  # type: ignore[attr-defined]

        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Status Code", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(urls_with_status, key=lambda x: x.get("impressions", 0), reverse=True)
        for url_data in sorted_urls:
            ws.append(  # type: ignore[attr-defined]
                [
                    safe_cell(url_data["url"]),
                    safe_cell(url_data.get("status_code", "")),
                    url_data.get("inlinks"),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )
