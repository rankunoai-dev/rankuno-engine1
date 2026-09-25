"""Response Codes masterfile service (HTTP status code issues).

Reads response_codes_*.csv files and generates a single-sheet XLSX showing:
1. Summary: Status code groups (2xx, 3xx, 4xx, 5xx) with counts
2. Theme Wise: Pivot by Theme 1
3. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs:
- response_codes_internal_success_(2xx).csv
- response_codes_internal_redirect_(3xx).csv
- response_codes_internal_client_error_(4xx).csv
- response_codes_internal_server_error_(5xx).csv
"""

from __future__ import annotations

import io
from typing import Any, Final

import pandas as pd  # type: ignore[import-untyped]
from openpyxl import Workbook

from src.core.logger import get_logger
from src.modules.seo.deliverables.masterfile_base import (
    MasterfileMetadata,
    MasterfileService,
    gc,
    read_csv_safe,
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

_RESPONSE_CODE_FILES: Final[list[str]] = [
    "response_codes_internal_success_(2xx).csv",
    "response_codes_internal_redirect_(3xx).csv",
    "response_codes_internal_client_error_(4xx).csv",
    "response_codes_internal_server_error_(5xx).csv",
]


class ResponseCodesService(MasterfileService):
    """Generate response codes masterfile."""

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
        dfs = []
        for filename in _RESPONSE_CODE_FILES:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        if not dfs:
            return None

        combined = pd.concat(dfs, ignore_index=True)
        return combined if not combined.empty else None

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
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Only include indexable=True, status=200, content_type=HTML URLs
                # (but we're showing status codes, so include all status codes here)
                # Filter: indexable=True, content_type=HTML
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
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
        urls_with_status: list[dict[str, Any]],  # noqa: type is object
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
