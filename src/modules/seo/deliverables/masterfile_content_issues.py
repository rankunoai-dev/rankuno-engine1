"""Content Issues masterfile service (thin content, boilerplate, duplication warnings).

Reads its catalogue sources and generates a single-sheet XLSX showing:
1. Summary: Content issue counts
2. Detailed Data: One row per affected URL, sorted by impressions

Source CSVs: `SOURCE_FILES`, derived through `contracts/sources.py` from
the six CONTENT_ISSUES issues that are neither duplicate content nor
placeholder text (those two have their own workbooks). Never written out here - a hand-kept second
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

__all__ = ["ContentIssuesService"]

_logger = get_logger(__name__)


class ContentIssuesService(MasterfileService):
    """Generate content issues masterfile."""

    SOURCE_FILES = sources_for_issues(
        IssueId.CONTENT_LOW_CONTENT_PAGES,
        IssueId.CONTENT_SOFT_404_PAGES,
        IssueId.CONTENT_SPELLING_ERRORS,
        IssueId.CONTENT_GRAMMAR_ERRORS,
        IssueId.CONTENT_READABILITY_DIFFICULT,
        IssueId.CONTENT_READABILITY_VERY_DIFFICULT,
    )

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="content_issues",
            label="Content Issues",
            sheets=1,
            is_complex=False,
        )

    def _read_all_content_issues(self) -> pd.DataFrame | None:
        """Read and combine all content issues CSVs."""
        return self._read_issue_frames()

    def generate(self) -> bytes:
        """Generate content issues XLSX."""
        # Read data
        content_df = self._read_all_content_issues()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        if content_df is None or content_df.empty:
            wb = Workbook()
            ws = wb.active
            if ws:
                ws.title = "Content Issues"
                ws.append(["No content issues data found"])
        else:
            try:
                address_idx = gc(content_df.columns.tolist(), "Address")
            except KeyError:
                wb = Workbook()
                ws = wb.active
                if ws:
                    ws.title = "Content Issues"
                    ws.append(["Error reading content issues CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            urls_with_content_issues = []
            for _, row in content_df.iterrows():
                url = str(row.iloc[address_idx])

                # Enrich
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = self._gsc_lookup(gsc_map, url)

                indexability = internal_data.get("indexability")
                if not self._is_reportable(indexability):
                    continue

                urls_with_content_issues.append(
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
                ws.title = "Content Issues"
                self._write_content_issues_sheet(ws, urls_with_content_issues)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_content_issues_sheet(
        self, ws: object, urls_with_content_issues: list[dict[str, Any]]
    ) -> None:
        """Write content issues sheet."""
        ws.append([])  # type: ignore[attr-defined]
        ws.append(["CONTENT ISSUES"])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Summary section
        ws.append(["Summary"])  # type: ignore[attr-defined]
        ws.append(["Total Affected Pages", len(urls_with_content_issues)])  # type: ignore[attr-defined]
        ws.append([])  # type: ignore[attr-defined]

        # Detailed Data section
        ws.append(["Detailed Data"])  # type: ignore[attr-defined]
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])  # type: ignore[attr-defined]

        # Sort by impressions descending
        sorted_urls = sorted(
            urls_with_content_issues, key=lambda x: x.get("impressions", 0), reverse=True
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
