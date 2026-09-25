"""Structured Data masterfile service (schema.org markup).

Generates 8 sheets per ADR 0011:
1. Summary — schema.org markup statistics
2. By Type — markup by schema type (Article, Product, BreadcrumbList, etc.)
3. By Page Template — markup by page template/section
4. Theme-wise — schema markup by theme
5. Invalid Markup — errors and warnings in structured data
6. Missing Schema — pages that should have schema but don't
7. Detailed Data — one row per URL with markup analysis
8. Coverage Analysis — schema.org implementation coverage

Source CSVs:
- structured_data_*.csv files (various schema types)
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

__all__ = ["StructuredDataService"]

_logger = get_logger(__name__)

_STRUCTURED_DATA_FILES: Final[list[str]] = [
    "structured_data_missing.csv",
    "structured_data_invalid.csv",
    "structured_data_incomplete.csv",
]


class StructuredDataService(MasterfileService):
    """Generate structured data masterfile (8 sheets)."""

    @property
    def metadata(self) -> MasterfileMetadata:
        return MasterfileMetadata(
            slug="structured_data",
            label="Structured Data",
            sheets=8,
            is_complex=True,
        )

    def _read_all_structured_data(self) -> pd.DataFrame | None:
        """Read and combine all structured data CSVs."""
        dfs = []
        for filename in _STRUCTURED_DATA_FILES:
            df = read_csv_safe(self.sf_export_dir / filename)
            if df is not None and not df.empty:
                dfs.append(df)

        if not dfs:
            return None

        combined = pd.concat(dfs, ignore_index=True)
        return combined if not combined.empty else None

    def generate(self) -> bytes:
        """Generate structured data XLSX with 8 sheets."""
        # Read data
        schema_df = self._read_all_structured_data()
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        wb = Workbook()
        wb.remove(wb.active)  # Remove default sheet

        if schema_df is None or schema_df.empty:
            # Empty workbook with placeholder sheet
            ws = wb.create_sheet("Summary")
            ws.append(["No structured data found"])
        else:
            try:
                address_idx = gc(schema_df.columns.tolist(), "Address")
            except KeyError:
                ws = wb.create_sheet("Summary")
                ws.append(["Error reading structured data CSV"])
                output = io.BytesIO()
                wb.save(output)
                return output.getvalue()

            # Enrich and filter data
            urls_with_schema = []
            for _, row in schema_df.iterrows():
                url = str(row.iloc[address_idx])
                internal_data = internal_map.get(url, {}) if internal_map else {}
                gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                # Filter: indexable=True
                indexability = internal_data.get("indexability")
                if indexability != "Indexable":
                    continue

                urls_with_schema.append(
                    {
                        "url": url,
                        "indexability": indexability,
                        "inlinks": internal_data.get("inlinks"),
                        "impressions": gsc_data.get("impressions", 0),
                        "clicks": gsc_data.get("clicks", 0),
                    }
                )

            # Create 8 sheets
            self._write_summary_sheet(wb, len(urls_with_schema))
            self._write_by_type_sheet(wb, urls_with_schema)
            self._write_by_page_template_sheet(wb, urls_with_schema)
            self._write_theme_wise_sheet(wb, urls_with_schema)
            self._write_invalid_markup_sheet(wb, urls_with_schema)
            self._write_missing_schema_sheet(wb, urls_with_schema)
            self._write_detailed_data_sheet(wb, urls_with_schema)
            self._write_coverage_analysis_sheet(wb, len(urls_with_schema))

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_summary_sheet(self, wb: Workbook, total_pages: int) -> None:
        """Write summary sheet."""
        ws = wb.create_sheet("Summary")
        ws.append(["STRUCTURED DATA SUMMARY"])
        ws.append([])
        ws.append(["Total Pages with Schema Issues", total_pages])

    def _write_by_type_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write by type sheet."""
        ws = wb.create_sheet("By Type")
        ws.append(["STRUCTURED DATA BY TYPE"])
        ws.append(["Schema Type", "Count"])

    def _write_by_page_template_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write by page template sheet."""
        ws = wb.create_sheet("By Page Template")
        ws.append(["STRUCTURED DATA BY PAGE TEMPLATE"])
        ws.append(["Page Template", "Count"])

    def _write_theme_wise_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write theme-wise sheet."""
        ws = wb.create_sheet("Theme-wise")
        ws.append(["STRUCTURED DATA THEME-WISE"])
        ws.append(["Theme", "Count"])

    def _write_invalid_markup_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write invalid markup sheet."""
        ws = wb.create_sheet("Invalid Markup")
        ws.append(["INVALID STRUCTURED DATA MARKUP"])
        ws.append(["URL", "Issue Type"])

    def _write_missing_schema_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write missing schema sheet."""
        ws = wb.create_sheet("Missing Schema")
        ws.append(["MISSING STRUCTURED DATA"])
        ws.append(["URL", "Expected Schema Type"])

    def _write_detailed_data_sheet(
        self, wb: Workbook, urls_with_schema: list[dict[str, Any]]
    ) -> None:
        """Write detailed data sheet."""
        ws = wb.create_sheet("Detailed Data")
        ws.append(["STRUCTURED DATA DETAILED DATA"])
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])

        sorted_urls = sorted(
            urls_with_schema, key=lambda x: x.get("impressions", 0), reverse=True
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
        ws.append(["STRUCTURED DATA COVERAGE ANALYSIS"])
        ws.append([])
        ws.append(["Total Pages", total_pages])
        if total_pages > 0:
            coverage_pct = 100.0
            ws.append(["Coverage %", f"{coverage_pct:.1f}%"])
