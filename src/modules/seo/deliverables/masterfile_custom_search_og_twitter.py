"""Custom Search OpenGraph Twitter masterfile service.

Renders a single-sheet XLSX showing:
1. Summary: OpenGraph/Twitter card metadata extraction counts
2. Detailed Data: One row per URL with OG/Twitter metadata, sorted by impressions

Source CSVs: none. `CUSTOM_SEARCH_OG_TAGS / CUSTOM_SEARCH_TWITTER_CARD` carries no `sf_sources` in
`ISSUE_CATALOGUE`, so `SOURCE_FILES` stays empty and every build
renders "Not measured by this crawl" rather than an empty issue list.

RAE derived Open Graph and Twitter Card presence from
`custom_extraction_all.csv`, the `Custom Extraction:All` tab. That tab is
not in `export_manifest.EXPORT_TABS` and the filename is not
allow-listed, so no bundle can carry it. Phase 4.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from openpyxl import Workbook

from src.core.logger import get_logger
from src.modules.seo.deliverables.masterfile_base import (
    NOT_MEASURED,
    MasterfileMetadata,
    MasterfileService,
    gc,
    safe_cell,
)

__all__ = ["CustomSearchOGTwitterService"]

_logger = get_logger(__name__)


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
        """OG/Twitter tag presence, when an export can supply it.

        `SOURCE_FILES` is empty today, so this is always `None` and the
        workbook renders "not measured". Routed through the generic
        reader rather than hardcoding `None`, so the day a catalogue row
        gains an `sf_sources` this service starts working unchanged.
        """
        return self._read_issue_frames()

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
                ws.append([NOT_MEASURED])
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
