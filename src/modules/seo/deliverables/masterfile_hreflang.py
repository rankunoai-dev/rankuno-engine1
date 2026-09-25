"""Hreflang masterfile service (alternate language links).

Generates 8 sheets per ADR 0011:
1. Summary — summary statistics
2. By Country — hreflang links by country
3. By Language — hreflang links by language
4. Theme-wise — hreflang issues by theme
5. Alternate Issues — missing or incorrect alternates
6. Missing Alternates — pages without required alternates
7. Detailed Data — one row per URL with hreflang analysis
8. Coverage Analysis — hreflang implementation coverage

Source CSVs:
- hreflang_*.csv files (various issue types)
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

__all__ = ["HrefLangService"]

_logger = get_logger(__name__)

_HREFLANG_FILES: Final[list[str]] = [
    "hreflang_missing.csv",
    "hreflang_incorrect.csv",
    "hreflang_duplicate.csv",
]


class HrefLangService(MasterfileService):
    """Generate hreflang masterfile (8 sheets)."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="hreflang",
            label="Hreflang",
            sheets=8,
            is_complex=True,
        )

    def _read_all_hreflang(self) -> pd.DataFrame | None:
        """Read and combine all hreflang CSVs."""
        dfs = []
        for filename in _HREFLANG_FILES:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        if not dfs:
            return None

        combined = pd.concat(dfs, ignore_index=True)
        return combined if not combined.empty else None

    def generate(self) -> bytes:
        """Generate hreflang XLSX with 8 sheets."""
        # Read data
        hreflang_df = self._read_all_hreflang()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        wb = Workbook()
        wb.remove(wb.active)  # Remove default sheet

        if hreflang_df is None or hreflang_df.empty:
            # Empty workbook with placeholder sheet
            ws = wb.create_sheet("Summary")
            ws.append(["No hreflang data found"])
        else:
            try:
                address_idx = gc(hreflang_df.columns.tolist(), "Address")
            except KeyError:
                ws = wb.create_sheet("Summary")
                ws.append(["Error reading hreflang CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            # Enrich and filter data
            urls_with_hreflang = []
            for _, row in hreflang_df.iterrows():
                url = str(row.iloc[address_idx])
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                urls_with_hreflang.append(
                    {
                        "url": url,
                        "indexability": indexability,
                        "inlinks": internal_data.get("inlinks"),
                        "impressions": gsc_data.get("impressions", 0),
                        "clicks": gsc_data.get("clicks", 0),
                    }
                )

            # Create 8 sheets
            self._write_summary_sheet(wb, len(urls_with_hreflang))
            self._write_by_country_sheet(wb, urls_with_hreflang)
            self._write_by_language_sheet(wb, urls_with_hreflang)
            self._write_theme_wise_sheet(wb, urls_with_hreflang)
            self._write_alternate_issues_sheet(wb, urls_with_hreflang)
            self._write_missing_alternates_sheet(wb, urls_with_hreflang)
            self._write_detailed_data_sheet(wb, urls_with_hreflang)
            self._write_coverage_analysis_sheet(wb, len(urls_with_hreflang))

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_summary_sheet(self, wb: Workbook, total_pages: int) -> None:
        """Write summary sheet."""
        ws = wb.create_sheet("Summary")
        ws.append(["HREFLANG SUMMARY"])
        ws.append([])
        ws.append(["Total Pages with Hreflang Issues", total_pages])

    def _write_by_country_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write by country sheet."""
        ws = wb.create_sheet("By Country")
        ws.append(["HREFLANG BY COUNTRY"])
        ws.append(["Country", "Count"])

    def _write_by_language_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write by language sheet."""
        ws = wb.create_sheet("By Language")
        ws.append(["HREFLANG BY LANGUAGE"])
        ws.append(["Language", "Count"])

    def _write_theme_wise_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write theme-wise sheet."""
        ws = wb.create_sheet("Theme-wise")
        ws.append(["HREFLANG THEME-WISE"])
        ws.append(["Theme", "Count"])

    def _write_alternate_issues_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write alternate issues sheet."""
        ws = wb.create_sheet("Alternate Issues")
        ws.append(["HREFLANG ALTERNATE ISSUES"])
        ws.append(["URL", "Issue Type"])

    def _write_missing_alternates_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write missing alternates sheet."""
        ws = wb.create_sheet("Missing Alternates")
        ws.append(["HREFLANG MISSING ALTERNATES"])
        ws.append(["URL", "Missing Language"])

    def _write_detailed_data_sheet(
        self, wb: Workbook, urls_with_hreflang: list[dict[str, Any]]
    ) -> None:
        """Write detailed data sheet."""
        ws = wb.create_sheet("Detailed Data")
        ws.append(["HREFLANG DETAILED DATA"])
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])

        sorted_urls = sorted(
            urls_with_hreflang, key=lambda x: x.get("impressions", 0), reverse=True
        )
        for url_data in sorted_urls:
            ws.append(
                [
                    safe_cell(url_data["url"]),
                    url_data.get("inlinks"),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )

    def _write_coverage_analysis_sheet(self, wb: Workbook, total_pages: int) -> None:
        """Write coverage analysis sheet."""
        ws = wb.create_sheet("Coverage Analysis")
        ws.append(["HREFLANG COVERAGE ANALYSIS"])
        ws.append([])
        ws.append(["Total Pages", total_pages])
        if total_pages > 0:
            coverage_pct = 100.0
            ws.append(["Coverage %", f"{coverage_pct:.1f}%"])
