"""Abstract base and utilities for masterfile services (RAE porting, Phase 1).

Each masterfile service reads Screaming Frog CSVs from a `MasterfileSource` -
a directory of loose CSVs *or* a zip bundle held in memory, which is what lets
an encrypted worker upload feed a build without being extracted to disk
(`masterfile_source.py`). It applies enrichment (status codes, impressions,
GA4 sessions, themes) and generates a styled XLSX file. This module provides:

- MasterfileService: abstract base for all 21 services
- CSV reading with case-insensitive column lookup and graceful degradation
- Enrichment helpers: Status Code, Indexability, Impressions, GA4 Sessions, Themes
- XLSX output wrappers (xlsxwriter for standard, openpyxl for 2-pass)
- Formula injection guards (write_string, truncation, sanitization)
- Common constants (column widths, formatting, etc.)

The architecture follows ADR 0011: MasterfileService reads CSVs (read-only
transformations), no external API calls, one service == one workbook.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Final

import pandas as pd  # type: ignore[import-untyped]
from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.deliverables.masterfile_source import (
    DirectoryMasterfileSource,
    MasterfileSource,
    read_csv_safe,
)
from src.modules.seo.deliverables.rulebook import OTHERS_THEME

__all__ = [
    "MasterfileService",
    "MasterfileMetadata",
    "EnrichedURLRecord",
    "MasterfileSource",
    "read_csv_safe",
    "gc",
]

_logger = get_logger(__name__)

_FORMULA_TRIGGER_CHARS: Final[frozenset[str]] = frozenset({"=", "+", "-", "@", "\t", "\r"})
"""OWASP formula injection triggers. Guard every cell value."""

_SHEET_NAME_FORBIDDEN_CHARS: Final[re.Pattern[str]] = re.compile(r"[\\/?*:\[\]]")
"""Excel sheet name forbidden characters."""

_SHEET_NAME_MAX_LENGTH: Final[int] = 31
"""Excel sheet name length limit."""

_MAX_CELL_LENGTH: Final[int] = 32767
"""Excel cell content length limit."""

_MAX_HYPERLINKS_PER_SHEET: Final[int] = 65000
"""Switch to plain text beyond this."""

# Standard column widths (from RAE extract)
DEFAULT_COLUMN_WIDTHS: Final[dict[str, float]] = {
    "URL": 50,
    "Status Code": 12,
    "Indexability": 15,
    "Inlinks": 10,
    "Page Type": 15,
    "Impressions": 12,
    "Clicks": 10,
    "GA4 Sessions": 12,
    "Theme 1": 20,
    "Theme 2": 20,
    "Issue Type": 30,
    "Count": 10,
    "Percentage": 12,
}

# Standard colors (from RAE extract)
RED_HEADER_COLOR: Final[str] = "FFFF0000"
GRAY_SUBHEADER_COLOR: Final[str] = "FFF2F2F2"
WHITE_TEXT_COLOR: Final[str] = "FFFFFFFF"
BLACK_TEXT_COLOR: Final[str] = "FF000000"


class MasterfileMetadata(StrictModel):
    """Metadata about a masterfile service."""

    slug: str = Field(description="URL slug (e.g., 'response_codes')")
    label: str = Field(description="Human-readable label (e.g., 'Response Codes')")
    sheets: int = Field(default=1, description="Number of sheets in output")
    is_complex: bool = Field(default=False, description="Requires 2-pass styling (openpyxl)?")


class EnrichedURLRecord(StrictModel):
    """One URL with enriched data: status, indexability, impressions, GA4, themes."""

    url: str
    status_code: str | None = None
    indexability: str | None = None
    inlinks: int | None = None
    page_type: str | None = None
    impressions: int | None = None
    clicks: int | None = None
    ga4_sessions: int | None = None
    theme_1: str = OTHERS_THEME
    theme_2: str | None = None


def gc(header: list[str], column_name: str) -> int:
    """Get column index: case-insensitive search for column name.

    Args:
        header: CSV header row
        column_name: Column name to find (case-insensitive)

    Returns:
        0-based column index

    Raises:
        KeyError: Column not found
    """
    name_lower = column_name.lower()
    for i, col in enumerate(header):
        if col.lower() == name_lower:
            return i
    msg = f"Column not found: {column_name}"
    raise KeyError(msg)


def safe_cell(value: object) -> object:
    """Neutralise formula-injection trigger characters.

    Args:
        value: Cell value (any type)

    Returns:
        Safe value (string values starting with trigger chars are prefixed with ')
    """
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGER_CHARS:
        return f"'{value}"
    return value


def truncate_cell(value: str, max_length: int = _MAX_CELL_LENGTH) -> str:
    """Truncate string to Excel cell limit with marker.

    Args:
        value: Cell value
        max_length: Maximum length (default Excel limit)

    Returns:
        Truncated string with " ...[truncated]" if needed
    """
    if len(value) > max_length:
        marker = " ...[truncated]"
        return value[: max_length - len(marker)] + marker
    return value


def sanitize_sheet_name(name: str, existing_names: set[str] | None = None) -> str:
    """Sanitize a sheet name: remove forbidden chars, cap 31 chars, dedupe.

    Args:
        name: Proposed sheet name
        existing_names: Already-used names (for deduplication)

    Returns:
        Safe sheet name (31 chars max)
    """
    existing_names = existing_names or set()
    # Remove forbidden characters
    cleaned = _SHEET_NAME_FORBIDDEN_CHARS.sub("_", name)
    # Cap length
    if len(cleaned) > _SHEET_NAME_MAX_LENGTH:
        cleaned = cleaned[: _SHEET_NAME_MAX_LENGTH - 4] + "_"
    # Deduplicate
    if cleaned in existing_names:
        for i in range(1, 1000):
            candidate = f"{cleaned[:27]}_{i:03d}"
            if candidate not in existing_names:
                return candidate
    return cleaned


class MasterfileService(ABC):
    """Abstract base for all masterfile services.

    Each service:
    1. Reads one or more issue CSVs from its `MasterfileSource`
    2. Loads enrichment (internal_all.csv, search_console_all.csv, analytics_all.csv)
    3. Applies theme classification via rulebook
    4. Generates styled XLSX with 1+ sheets

    A subclass reads CSVs through `self._read_csv(filename)` and discovers
    dynamic ones through `self._csv_names()`. Neither joins a path: a source
    may be a zip in memory, where there is no path to join.
    """

    def __init__(
        self,
        job_id: str,
        source: MasterfileSource | Path | str,
        rulebook_path: Path | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            job_id: Job ID (used for logging)
            source: Where this build's Screaming Frog CSVs come from. A
                `Path` (or `str`) is wrapped in a `DirectoryMasterfileSource`
                for the caller, so every existing directory-based call site -
                `scripts/build_deliverable.py`, the 21 service tests - keeps
                working unchanged.
            rulebook_path: Optional rulebook for theme classification. Held
                for services that theme their output; no service reads it
                yet (build-log 0107, "explicitly not done").
        """
        self.job_id = job_id
        self.source: MasterfileSource = (
            DirectoryMasterfileSource(source) if isinstance(source, (str, Path)) else source
        )
        self.rulebook_path = rulebook_path
        self._logger = get_logger(self.__class__.__module__)
        self._enrichment_cache: dict[str, pd.DataFrame | None] = {}

    def _read_csv(self, filename: str) -> pd.DataFrame | None:
        """One export CSV, or `None` when this source does not hold it.

        Absent is never an error: an export a crawl did not produce means
        "not measured", the distinction `screaming_frog_adapter` already
        keeps, and a masterfile that raised on it would report nothing at
        all rather than the issues it did find.
        """
        return self.source.read_csv(filename)

    def _csv_names(self) -> frozenset[str]:
        """Every CSV filename this source holds, for the dynamic exports."""
        return self.source.names()

    @property
    @abstractmethod
    def metadata(self) -> MasterfileMetadata:
        """Service metadata (slug, label, sheet count, etc.)."""
        ...

    def _read_enrichment(self, filename: str) -> pd.DataFrame | None:
        """Read enrichment CSV with caching."""
        if filename in self._enrichment_cache:
            return self._enrichment_cache[filename]
        df = self._read_csv(filename)
        self._enrichment_cache[filename] = df
        return df

    def _build_internal_map(self) -> dict[str, dict[str, Any]] | None:
        """Build enrichment map from internal_all.csv.

        Returns:
            {url: {status_code, indexability, inlinks, page_type}} or None
        """
        df = self._read_enrichment("internal_all.csv")
        if df is None or df.empty:
            return None

        result: dict[str, dict[str, Any]] = {}
        try:
            address_idx = gc(df.columns.tolist(), "Address")
            status_idx = gc(df.columns.tolist(), "Status Code")
            indexability_idx = gc(df.columns.tolist(), "Indexability")
            inlinks_idx = gc(df.columns.tolist(), "Inlinks")
        except KeyError:
            return None

        for _, row in df.iterrows():
            try:
                url = str(row.iloc[address_idx])
                status = str(row.iloc[status_idx]) if pd.notna(row.iloc[status_idx]) else None
                indexability = (
                    str(row.iloc[indexability_idx])
                    if pd.notna(row.iloc[indexability_idx])
                    else None
                )
                inlinks = (
                    int(row.iloc[inlinks_idx])
                    if pd.notna(row.iloc[inlinks_idx]) and str(row.iloc[inlinks_idx]).isdigit()
                    else None
                )
                result[url] = {
                    "status_code": status,
                    "indexability": indexability,
                    "inlinks": inlinks,
                }
            except (ValueError, IndexError):
                continue

        return result if result else None

    def _build_gsc_map(self) -> dict[str, dict[str, int]] | None:
        """Build enrichment map from search_console_all.csv.

        Returns:
            {url: {impressions, clicks}} or None
        """
        df = self._read_enrichment("search_console_all.csv")
        if df is None or df.empty:
            return None

        result: dict[str, dict[str, int]] = {}
        try:
            address_idx = gc(df.columns.tolist(), "Address")
            impressions_idx = gc(df.columns.tolist(), "Impressions")
            clicks_idx = gc(df.columns.tolist(), "Clicks")
        except KeyError:
            return None

        for _, row in df.iterrows():
            try:
                url = str(row.iloc[address_idx])
                impressions = (
                    int(row.iloc[impressions_idx])
                    if pd.notna(row.iloc[impressions_idx])
                    and str(row.iloc[impressions_idx]).replace(".", "", 1).isdigit()
                    else 0
                )
                clicks = (
                    int(row.iloc[clicks_idx])
                    if pd.notna(row.iloc[clicks_idx])
                    and str(row.iloc[clicks_idx]).replace(".", "", 1).isdigit()
                    else 0
                )
                result[url] = {"impressions": impressions, "clicks": clicks}
            except (ValueError, IndexError):
                continue

        return result if result else None

    def _build_ga4_map(self) -> dict[str, int] | None:
        """Build enrichment map from analytics_all.csv (GA4 sessions).

        Returns:
            {url: sessions} or None
        """
        df = self._read_enrichment("analytics_all.csv")
        if df is None or df.empty:
            return None

        result: dict[str, int] = {}
        try:
            address_idx = gc(df.columns.tolist(), "Address")
            sessions_idx = gc(df.columns.tolist(), "Sessions")
        except KeyError:
            return None

        for _, row in df.iterrows():
            try:
                url = str(row.iloc[address_idx])
                sessions = (
                    int(row.iloc[sessions_idx])
                    if pd.notna(row.iloc[sessions_idx])
                    and str(row.iloc[sessions_idx]).replace(".", "", 1).isdigit()
                    else 0
                )
                result[url] = sessions
            except (ValueError, IndexError):
                continue

        return result if result else None

    @abstractmethod
    def generate(self) -> bytes:
        """Generate the XLSX workbook bytes.

        Returns:
            XLSX file contents as bytes

        Raises:
            MasterfileError: On any generation failure
        """
        ...
