"""Custom Search OpenGraph Twitter masterfile service.

Reads custom_search_og_twitter.csv file and generates a single-sheet XLSX showing:
1. Summary: OpenGraph/Twitter card metadata extraction counts
2. Detailed Data: One row per URL with OG/Twitter metadata, sorted by impressions

Source CSV:
- custom_search_og_twitter.csv
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

__all__ = ["CustomSearchOGTwitterService"]

_logger = get_logger(__name__)

_CUSTOM_SEARCH_OG_TWITTER_FILE: Final[str] = "custom_search_og_twitter.csv"


class CustomSearchOGTwitterService(MasterfileService):
    """Generate custom search OG Twitter masterfile."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="custom_search_og_twitter",
            label="Custom Search OG Twitter",
            sheets=1,
            is_complex=False,
        )

    def _read_og_twitter(self) -> pd.DataFrame | None:
        """Read OG Twitter CSV."""
        return read_csv_safe(self.sf_export_dir / _CUSTOM_SEARCH_OG_TWITTER_FILE)

    def generate(self) -> bytes:
        """Generate OG Twitter XLSX."""
        # Read data
        og_df = self._read_og_twitter()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if og_df is None or og_df.empty:
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "OG Twitter"
                ws.append(["No OG/Twitter data found"])
        else:
            try:
                address_idx = gc(og_df.columns.tolist(), "Address")
            except KeyError:
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "OG Twitter"
                    ws.append(["Error reading OG/Twitter CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_og_twitter = []
            for _, row in og_df.iterrows():
                url = str(row.iloc[address_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                urls_with_og_twitter.append(
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
                ws.title = "OG Twitter"
                self._write_og_twitter_sheet(ws, urls_with_og_twitter)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_og_twitter_sheet(
        self, ws: object, urls_with_og_twitter: list[dict[str, Any]]
    ) -> None:
        """Write OG/Twitter sheet."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["CUSTOM SEARCH OG TWITTER"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Total Pages with OG/Twitter Data", len(urls_with_og_twitter)])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(
            urls_with_og_twitter, key=lambda x: x.get("impressions", 0), reverse=True
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
