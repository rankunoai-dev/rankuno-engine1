"""Duplicate Content masterfile service (exact and near-duplicate detection).

Reads its catalogue sources and generates a single-sheet XLSX showing:
1. Summary: Duplicate content counts
2. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs: `SOURCE_FILES`, derived through `contracts/sources.py` from
CONTENT_EXACT_DUPLICATES and CONTENT_NEAR_DUPLICATES. Never written out here - a hand-kept second
copy of that list is what build-log 0116 found wrong in this file.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from openpyxl import Workbook

from src.core.logger import get_logger
from src.modules.seo.contracts.issue_ids import IssueId
from src.modules.seo.contracts.sources import sources_for_issues
from src.modules.seo.deliverables.masterfile_base import (
    MasterfileMetadata,
    MasterfileService,
    gc,
    safe_cell,
)

__all__ = ["DuplicateContentService"]

_logger = get_logger(__name__)


class DuplicateContentService(MasterfileService):
    """Generate duplicate content masterfile."""

    SOURCE_FILES = sources_for_issues(
        IssueId.CONTENT_EXACT_DUPLICATES,
        IssueId.CONTENT_NEAR_DUPLICATES,
    )

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="duplicate_content",
            label="Duplicate Content",
            sheets=1,
            is_complex=False,
        )

    def _read_all_duplicate_content(self) -> pd.DataFrame | None:
        """Read and combine all duplicate content CSVs."""
        return self._read_issue_frames()

    def generate(self) -> bytes:
        """Generate duplicate content XLSX."""
        # Read data
        duplicate_df = self._read_all_duplicate_content()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if duplicate_df is None or duplicate_df.empty:
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "Duplicate Content"
                ws.append(["No duplicate content data found"])
        else:
            try:
                address_idx = gc(duplicate_df.columns.tolist(), "Address")
            except KeyError:
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "Duplicate Content"
                    ws.append(["Error reading duplicate content CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_duplicates = []
            for _, row in duplicate_df.iterrows():
                url = str(row.iloc[address_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = self._gsc_lookup(gsc_map, url)

                indexability = internal_data.get("indexability")
                if not self._is_reportable(indexability):
                    continue

                urls_with_duplicates.append(
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
                ws.title = "Duplicate Content"
                self._write_duplicate_content_sheet(ws, urls_with_duplicates)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_duplicate_content_sheet(
        self, ws: object, urls_with_duplicates: list[dict[str, Any]]
    ) -> None:
        """Write duplicate content sheet."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["DUPLICATE CONTENT"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Total Affected Pages", len(urls_with_duplicates)])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(
            urls_with_duplicates, key=lambda x: x.get("impressions", 0), reverse=True
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
