"""Meta Description masterfile service (title tag issues).

Reads meta_description_*.csv files and generates a single-sheet XLSX showing:
1. Summary: Issue types with counts
2. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs:
- meta_description_missing.csv
- meta_description_too_long.csv
- meta_description_too_short.csv
- meta_description_duplicate.csv
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

__all__ = ["MetaDescriptionService"]

_logger = get_logger(__name__)

_META_DESCRIPTION_FILES: Final[list[str]] = [
    "meta_description_missing.csv",
    "meta_description_too_long.csv",
    "meta_description_too_short.csv",
    "meta_description_duplicate.csv",
]


class MetaDescriptionService(MasterfileService):
    """Generate meta description masterfile."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="meta_description",
            label="Meta Description",
            sheets=1,
            is_complex=False,
        )

    def _read_all_meta_descriptions(self) -> pd.DataFrame | None:
        """Read and combine all meta description CSVs."""
        dfs = []
        for filename in _META_DESCRIPTION_FILES:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        if not dfs:
            return None

        combined = pd.concat(dfs, ignore_index=True)
        return combined if not combined.empty else None

    def generate(self) -> bytes:
        """Generate meta description XLSX."""
        # Read data
        meta_df = self._read_all_meta_descriptions()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if meta_df is None or meta_df.empty:
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "Meta Descriptions"
                ws.append(["No meta description data found"])
        else:
            try:
                address_idx = gc(meta_df.columns.tolist(), "Address")
            except KeyError:
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "Meta Descriptions"
                    ws.append(["Error reading meta description CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_meta = []
            for _, row in meta_df.iterrows():
                url = str(row.iloc[address_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                urls_with_meta.append(
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
                ws.title = "Meta Descriptions"
                self._write_meta_description_sheet(ws, urls_with_meta)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_meta_description_sheet(
        self, ws: object, urls_with_meta: list[dict[str, Any]]
    ) -> None:
        """Write meta description sheet."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["META DESCRIPTIONS"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Total Affected Pages", len(urls_with_meta)])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(
            urls_with_meta, key=lambda x: x.get("impressions", 0), reverse=True
        )
        for url_data in sorted_urls:
            ws.append(  # type: ignore[attr-defined]
                [
                    safe_cell(url_data["url"]),
                    url_data.get("inlinks"),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )
