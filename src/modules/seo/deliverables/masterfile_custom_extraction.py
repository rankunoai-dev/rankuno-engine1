r"""Custom Extraction masterfile service (dynamic N sheets).

Generates N sheets dynamically, one per custom extractor registered at crawl time.
Each sheet contains:
1. Summary — extractor statistics
2. Detailed Data — one row per URL with extraction results, sorted by impressions

The number of sheets is determined by the number of custom extractors configured
in the crawl's extraction rules.

Source CSVs: every `custom_extraction_*.csv` the source holds. This is the
one export whose filename set is not knowable in advance, so it is discovered
rather than derived from `ISSUE_CATALOGUE`.

**Unreachable through the supported input path today.** A real Screaming Frog
19.4 export writes exactly one such file, `custom_extraction_all.csv` -
confirmed present in all 45 populated export folders checked. That name is not
in `ALLOWED_BUNDLE_FILENAMES`, because no `CUSTOM_SEARCH` catalogue row
carries an `sf_sources`, and `Custom Extraction:All` is not in
`export_manifest.EXPORT_TABS`. So the glob only ever matches when a service is
pointed at a loose export directory, never at an uploaded bundle. Wiring the
tab is Phase 4; widening the allow-list is an ADR 0018 decision.

The extractor name reaching `create_sheet` is derived from a *client-supplied
filename*, which is why every sheet name here goes through
`sanitize_sheet_name`: a name over 31 characters, or holding any of
``[ ] : ? * / \``, makes openpyxl raise, and two names that truncate to the
same 31 characters make it raise on the second sheet.
"""

from __future__ import annotations

import io
from typing import Any, Final

import pandas as pd  # type: ignore[import-untyped]
from openpyxl import Workbook

from src.core.logger import get_logger
from src.modules.seo.deliverables.masterfile_base import (
    NOT_MEASURED,
    MasterfileMetadata,
    MasterfileService,
    gc,
    safe_cell,
    sanitize_sheet_name,
)

__all__ = ["NOT_REQUESTED", "CustomExtractionService"]

_logger = get_logger(__name__)

_CUSTOM_EXTRACTION_PREFIX: Final[str] = "custom_extraction_"

NOT_REQUESTED: Final[str] = (
    "This engine never asked for the extraction. Its export manifest does not "
    "request Screaming Frog's 'Custom Extraction:All' tab, so "
    "custom_extraction_all.csv is in no bundle it produces - however many "
    "extractors the crawl's configuration defines. The gap is in this engine, "
    "not in the Screaming Frog setup."
)
"""The reason line beside `NOT_MEASURED` when no extractor export arrived.

The cell used to read "No custom extractors configured", which names the wrong
cause: it is a claim about the operator's `.seospiderconfig`, a binary file
this codebase cannot read (ADR 0021), made on evidence that only ever showed
the export was absent. An operator who had set extraction up correctly read
that sentence and went looking for a fault in their own template.

`NOT_MEASURED` on the line above keeps the shared vocabulary ADR 0011 §5
requires; this says the part the generic phrase cannot, because "we never
asked for this export" is a different fact from "this crawl had none"."""


class CustomExtractionService(MasterfileService):
    """Generate custom extraction masterfile (dynamic N sheets)."""

    SOURCE_FILE_PREFIXES = (_CUSTOM_EXTRACTION_PREFIX,)
    """The one export family discovered rather than named. Declared so
    `reachable_sources` can see it: this service's `SOURCE_FILES` is empty,
    and an availability check reading only that would be right today for the
    wrong reason and wrong the day the tab is requested."""

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
        return max(1, len(self._find_custom_extractors()))  # At least 1 sheet (summary)

    def _find_custom_extractors(self) -> list[str]:
        """Find all custom extraction CSV files and return extractor names.

        Matched against the source's own name set rather than a filesystem
        glob: this is the one dynamic export (one file per configured
        extractor), and a source may be a zip with no directory to glob.
        """
        return sorted(
            name[len(_CUSTOM_EXTRACTION_PREFIX) : -len(".csv")]
            for name in self._csv_names()
            if name.startswith(_CUSTOM_EXTRACTION_PREFIX) and name.endswith(".csv")
        )

    def _read_extractor_csv(self, extractor_name: str) -> pd.DataFrame | None:
        """Read a specific extractor's CSV."""
        filename = f"{_CUSTOM_EXTRACTION_PREFIX}{extractor_name}.csv"
        return self._read_csv(filename)

    def _new_sheet(self, wb: Workbook, extractor_name: str) -> Any:
        """A sheet for `extractor_name`, named safely and uniquely.

        The name comes from an uploaded filename, so it is untrusted input on
        its way into openpyxl. `sanitize_sheet_name` both strips the six
        characters Excel forbids and dedupes against the names already used,
        which is what stops two extractors whose names share a 31-character
        prefix from colliding on the second `create_sheet`.
        """
        return wb.create_sheet(sanitize_sheet_name(extractor_name, set(wb.sheetnames)))

    def generate(self) -> bytes:
        """Generate custom extraction XLSX with dynamic sheets."""
        internal_map = self._build_internal_map()
        gsc_map = self._build_gsc_map()

        extractors = self._find_custom_extractors()

        wb = Workbook()
        wb.remove(wb.active)  # Remove default sheet

        if not extractors:
            # Absent, which is not the same as "none configured" - see
            # `NOT_REQUESTED`.
            ws = wb.create_sheet("Summary")
            ws.append([NOT_MEASURED])
            ws.append([NOT_REQUESTED])
        else:
            # Create sheet for each extractor
            for extractor_name in extractors:
                extractor_df = self._read_extractor_csv(extractor_name)

                if extractor_df is None or extractor_df.empty:
                    ws = self._new_sheet(wb, extractor_name)
                    ws.append([f"No data for extractor: {extractor_name}"])
                    continue

                try:
                    address_idx = gc(extractor_df.columns.tolist(), "Address")
                except KeyError:
                    ws = self._new_sheet(wb, extractor_name)
                    ws.append([f"Error reading {extractor_name} CSV"])
                    continue

                # Enrich and filter data
                urls_with_data = []
                for _, row in extractor_df.iterrows():
                    url = str(row.iloc[address_idx])
                    internal_data = internal_map.get(url, {}) if internal_map else {}
                    gsc_data = self._gsc_lookup(gsc_map, url)

                    indexability = internal_data.get("indexability")
                    if not self._is_reportable(indexability):
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
        ws = self._new_sheet(wb, extractor_name)

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
