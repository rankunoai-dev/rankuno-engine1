"""Custom Extraction masterfile service (dynamic N sheets).

Generates N sheets dynamically, one per custom extractor registered at crawl time.
Each sheet contains:
1. Summary — extractor statistics
2. Detailed Data — one row per URL with extraction results, sorted by impressions

The number of sheets is determined by the number of custom extractors configured
in the crawl's extraction rules.

Source CSVs:
- custom_extraction_*.csv files (dynamic, one per extractor registered)
"""

from __future__ import annotations

import io
from pathlib import Path
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

__all__ = ["CustomExtractionService"]

_logger = get_logger(__name__)

_CUSTOM_EXTRACTION_PREFIX: Final[str] = "custom_extraction_"


class CustomExtractionService(MasterfileService):
    """Generate custom extraction masterfile (dynamic N sheets)."""

    @property
    def metadata(self) -> MasterfileMetadata:
        # Metadata will declare actual sheet count after discovering extractors
        sheet_count = self._count_extractor_csvs()
        return MasterfileMetadata(
            slug="custom_extraction",
            label="Custom Extraction",
            sheets=sheet_count,
            is_complex=True,
        )

    def _count_extractor_csvs(self) -> int:
        """Count the number of custom extraction CSVs to determine sheet count."""
        if not self.sf_export_dir.exists():
            return 1

        count = 0
        for file in self.sf_export_dir.glob(f"{_CUSTOM_EXTRACTION_PREFIX}*.csv"):
            count += 1

        return max(1, count)  # At least 1 sheet (summary)

    def _find_custom_extractors(self) -> list[str]:
        """Find all custom extraction CSV files and return extractor names."""
        if not self.sf_export_dir.exists():
            return []

        extractors = []
        for file in self.sf_export_dir.glob(f"{_CUSTOM_EXTRACTION_PREFIX}*.csv"):
            # Extract extractor name from filename: custom_extraction_<name>.csv
            extractor_name = file.stem[len(_CUSTOM_EXTRACTION_PREFIX) :]
            extractors.append(extractor_name)

        return sorted(extractors)

    def _read_extractor_csv(self, extractor_name: str) -> pd.DataFrame | None:
        """Read a specific extractor's CSV."""
        filename = f"{_CUSTOM_EXTRACTION_PREFIX}{extractor_name}.csv"
        return read_csv_safe(self.sf_export_dir / filename)

    def generate(self) -> bytes:
        """Generate custom extraction XLSX with dynamic sheets."""
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        extractors = self._find_custom_extractors()

        wb = Workbook()
        wb.remove(wb.active)  # Remove default sheet

        if not extractors:
            # No custom extractors
            ws = wb.create_sheet("Summary")
            ws.append(["No custom extractors configured"])
        else:
            # Create sheet for each extractor
            for extractor_name in extractors:
                extractor_df = self._read_extractor_csv(extractor_name)

                if extractor_df is None or extractor_df.empty:
                    ws = wb.create_sheet(extractor_name)
                    ws.append([f"No data for extractor: {extractor_name}"])
                    continue

                try:
                    address_idx = gc(extractor_df.columns.tolist(), "Address")
                except KeyError:
                    ws = wb.create_sheet(extractor_name)
                    ws.append([f"Error reading {extractor_name} CSV"])
                    continue

                # Enrich and filter data
                urls_with_data = []
                for _, row in extractor_df.iterrows():
                    url = str(row.iloc[address_idx])
                    internal_data = internal_map.get(url, {}) if internal_map else {}
                    gsc_data = gsc_map.get(url, {}) if gsc_map else {}

                    # Filter: indexable=True
                    indexability = internal_data.get("indexability")
                    if indexability != "Indexable":
                        continue

                    urls_with_data.append(
                        {
                            "url": url,
                            "indexability": indexability,
                            "inlinks": internal_data.get("inlinks"),
                            "impressions": gsc_data.get("impressions", 0),
                            "clicks": gsc_data.get("clicks", 0),
                        }
                    )

                # Create sheet for this extractor
                self._write_extractor_sheet(wb, extractor_name, urls_with_data)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _write_extractor_sheet(
        self, wb: Workbook, extractor_name: str, urls_with_data: list[dict[str, Any]]
    ) -> None:
        """Write sheet for a single extractor."""
        ws = wb.create_sheet(extractor_name)

        # Header
        ws.append([])
        ws.append([f"{extractor_name.upper()} EXTRACTION"])
        ws.append([])

        # Summary section
        ws.append(["Summary"])
        ws.append(["Total Pages with Data", len(urls_with_data)])
        ws.append([])

        # Detailed Data section
        ws.append(["Detailed Data"])
        ws.append(["URL", "Inlinks", "Impressions", "Clicks"])

        # Sort by impressions descending
        sorted_urls = sorted(urls_with_data, key=lambda x: x.get("impressions", 0), reverse=True)
        for url_data in sorted_urls:
            ws.append(
                [
                    safe_cell(url_data["url"]),
                    url_data.get("inlinks"),
                    url_data.get("impressions", 0),
                    url_data.get("clicks", 0),
                ]
            )
