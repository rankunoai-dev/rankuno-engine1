"""H1 tag masterfile service (H1 tag analysis).

Reads h1_*.csv files and generates a single-sheet XLSX showing:
1. Summary: H1 issue types with counts
2. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs:
- h1_missing.csv
- h1_multiple.csv
- h1_empty.csv
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

__all__ = ["H1Service"]

_logger = get_logger(__name__)

_H1_FILES: Final[list[str]] = [
    "h1_missing.csv",
    "h1_multiple.csv",
    "h1_empty.csv",
]


class H1Service(MasterfileService):
    """Generate H1 tag masterfile."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="h1",
            label="H1 Tags",
            sheets=1,
            is_complex=False,
        )

    def _read_all_h1_data(self) -> pd.DataFrame | None:
        """Read and combine all H1 CSVs."""
        dfs = []
        for filename in _H1_FILES:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        if not dfs:
            return None

        combined = pd.concat(dfs, ignore_index=True)
        return combined if not combined.empty else None

    def generate(self) -> bytes:
        """Generate H1 tags XLSX."""
        # Read data
        h1_df = self._read_all_h1_data()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if h1_df is None or h1_df.empty:
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "H1 Tags"
                ws.append(["No H1 tag data found"])
        else:
            try:
                address_idx = gc(h1_df.columns.tolist(), "Address")
            except KeyError:
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "H1 Tags"
                    ws.append(["Error reading H1 tag CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_h1 = []
            for _, row in h1_df.iterrows():
                url = str(row.iloc[address_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                urls_with_h1.append(
                    {
                        "url": url,
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
                ws.title = "H1 Tags"
                self._write_h1_sheet(ws, urls_with_h1)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_h1_sheet(self, ws: object, urls_with_h1: list[dict[str, Any]]) -> None:
        """Write H1 tags sheet."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["H1 TAGS"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Total Affected Pages", len(urls_with_h1)])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(urls_with_h1, key=lambda x: x.get("impressions", 0), reverse=True)
        for url_data in sorted_urls:
            ws.append(  # type: ignore[attr-defined]
                [
                    safe_cell(url_data["url"]),
                    url_data.get("inlinks"),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )
