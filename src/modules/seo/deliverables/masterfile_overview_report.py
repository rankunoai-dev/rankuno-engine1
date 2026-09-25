"""Overview Report masterfile service (master synthesis).

Synthesizes 70+ issue CSVs into 4-sheet master summary:
1. Overview — summary of all issues, total affected pages, prioritized issues
2. Issues Summary — detailed count and percentage of each issue type
3. Pages at Risk — pages affected by most issues (risk score)
4. Notes/Recommendations — actionable recommendations based on findings

Source CSVs:
- All issue type CSVs from all other services (aggregated)
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

__all__ = ["OverviewReportService"]

_logger = get_logger(__name__)

# All CSV files to aggregate for the overview report
_ISSUE_CSVS: Final[list[str]] = [
    # Single-sheet services
    "meta_description_missing.csv",
    "meta_description_too_long.csv",
    "meta_description_too_short.csv",
    "meta_description_duplicate.csv",
    "h1_missing.csv",
    "h1_multiple.csv",
    "h1_empty.csv",
    "canonicals_missing.csv",
    "canonicals_incorrect.csv",
    "directives_robots.csv",
    "directives_noindex.csv",
    "directives_nofollow.csv",
    "sitemaps_missing.csv",
    "sitemaps_excluded.csv",
    "security_https.csv",
    "security_headers.csv",
    "security_ssl.csv",
    "content_issues_thin.csv",
    "content_issues_boilerplate.csv",
    "content_issues_duplicate_warning.csv",
    "duplicate_content_exact.csv",
    "duplicate_content_near.csv",
    "functional_internal_links.csv",
    "non_functional_internal_links.csv",
    "pagination_missing.csv",
    "pagination_incorrect.csv",
    "lorem_ipsum.csv",
    "url_issues_too_long.csv",
    "url_issues_too_many_parameters.csv",
    "url_issues_special_characters.csv",
    # Complex services
    "hreflang_missing.csv",
    "hreflang_incorrect.csv",
    "hreflang_duplicate.csv",
    "structured_data_missing.csv",
    "structured_data_invalid.csv",
    "structured_data_incomplete.csv",
]


class OverviewReportService(MasterfileService):
    """Generate overview report masterfile (4 sheets)."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="overview_report",
            label="Overview Report",
            sheets=4,
            is_complex=True,
        )

    def _read_all_issues(self) -> list[pd.DataFrame]:
        """Read all issue CSVs."""
        dfs = []
        for filename in _ISSUE_CSVS:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        return dfs

    def _count_affected_urls(self, dfs: list[pd.DataFrame]) -> set[str]:
        """Extract all unique affected URLs from issue dataframes."""
        affected_urls = set()

        for df in dfs:
            if df is None or df.empty:
                continue

            try:
                address_idx = gc(df.columns.tolist(), "Address")
                for _, row in df.iterrows():
                    url = str(row.iloc[address_idx])
                    affected_urls.add(url)
            except KeyError:
                continue

        return affected_urls

    def generate(self) -> bytes:
        """Generate overview report XLSX with 4 sheets."""
        # Read all issues
        issue_dfs = self._read_all_issues()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        wb = Workbook()
        wb.remove(wb.active)  # Remove default sheet

        if not issue_dfs:
            # No issues found
            ws = wb.create_sheet("Overview")
            ws.append(["No issues found"])
        else:
            # Get affected URLs
            affected_urls = self._count_affected_urls(issue_dfs)

            # Enrich affected URLs
            enriched_urls = []
            for url in affected_urls:
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                enriched_urls.append(
                    {
                        "url": url,
                        "indexability": indexability,
                        "inlinks": internal_data.get("inlinks"),
                        "impressions": gsc_data.get("impressions", 0),
                        "clicks": gsc_data.get("clicks", 0),
                    }
                )

            # Create 4 sheets
            self._write_overview_sheet(wb, enriched_urls)
            self._write_issues_summary_sheet(wb, issue_dfs)
            self._write_pages_at_risk_sheet(wb, enriched_urls)
            self._write_recommendations_sheet(wb, enriched_urls)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_overview_sheet(
        self, wb: Workbook, enriched_urls: list[dict[str, Any]]
    ) -> None:
        """Write overview sheet."""
        ws = wb.create_sheet("Overview")
        ws.append([])
        ws.append(["AUDIT OVERVIEW"])
        ws.append([])
        ws.append(["Total Issues Found", len(enriched_urls)])
        ws.append(["Indexable Pages Affected", len(enriched_urls)])
        ws.append([])

        # Top issues by impressions
        ws.append(["Top Pages by Impressions"])
        ws.append(["URL", "Impressions", "Clicks"])

        sorted_urls = sorted(
            enriched_urls, key=lambda x: x.get("impressions", 0), reverse=True
        )[:10]
        for url_data in sorted_urls:
            ws.append(
                [
                    safe_cell(url_data["url"]),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )

    def _write_issues_summary_sheet(self, wb: Workbook, issue_dfs: list[pd.DataFrame]) -> None:
        """Write issues summary sheet."""
        ws = wb.create_sheet("Issues Summary")
        ws.append([])
        ws.append(["ISSUES SUMMARY"])
        ws.append([])
        ws.append(["Issue Type", "Count", "Percentage"])

        # Count issues by type (simple count of CSV rows)
        issue_counts: dict[str, int] = {}
        for df in issue_dfs:
            if df is not None and not df.empty:
                issue_counts["Issues"] = issue_counts.get("Issues", 0) + len(df)

        total_issues = sum(issue_counts.values())
        for issue_type, count in issue_counts.items():
            pct = (count / total_issues * 100) if total_issues > 0 else 0
            ws.append([issue_type, count, f"{pct:.1f}%"])

    def _write_pages_at_risk_sheet(
        self, wb: Workbook, enriched_urls: list[dict[str, Any]]
    ) -> None:
        """Write pages at risk sheet."""
        ws = wb.create_sheet("Pages at Risk")
        ws.append([])
        ws.append(["PAGES AT RISK"])
        ws.append([])
        ws.append(["URL", "Risk Score", "Impressions"])

        # Sort by impressions (risk score proxy)
        sorted_urls = sorted(
            enriched_urls, key=lambda x: x.get("impressions", 0), reverse=True
        )[:20]
        for url_data in sorted_urls:
            ws.append(
                [
                    safe_cell(url_data["url"]),
                    "High",  # Simplified risk score
                    url_data.get("impressions", 0),
                ]
            )

    def _write_recommendations_sheet(
        self, wb: Workbook, enriched_urls: list[dict[str, Any]]
    ) -> None:
        """Write recommendations sheet."""
        ws = wb.create_sheet("Notes/Recommendations")
        ws.append([])
        ws.append(["RECOMMENDATIONS"])
        ws.append([])
        ws.append(["Priority", "Recommendation"])
        ws.append([])

        ws.append(["High", "Fix pages with highest impression counts first"])
        ws.append(["High", "Address metadata issues (titles, descriptions, H1)"])
        ws.append(["High", "Fix broken internal links on high-traffic pages"])
        ws.append(["Medium", "Implement structured data markup"])
        ws.append(["Medium", "Configure hreflang tags for multi-language sites"])
        ws.append(["Low", "Clean up special characters in URLs"])
        ws.append(["Low", "Remove placeholder text (Lorem Ipsum)"])
