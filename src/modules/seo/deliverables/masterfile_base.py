"""Abstract base and utilities for masterfile services (RAE porting, Phase 1).

Each masterfile service reads Screaming Frog CSVs from a job's sf_export/
directory, applies enrichment (status codes, impressions, GA4 sessions, themes),
and generates a styled XLSX file. This module provides:

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
from src.modules.seo.deliverables.rulebook import OTHERS_THEME

__all__ = [
    "MasterfileService",
    "MasterfileMetadata",
    "EnrichedURLRecord",
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


def read_csv_safe(csv_path: str | Path, encoding: str = "utf-8") -> pd.DataFrame | None:
    """Read a CSV with fallback encoding; return None if file missing.

    Args:
        csv_path: Path to CSV file
        encoding: Initial encoding (default UTF-8)

    Returns:
        DataFrame or None if file missing

    Raises:
        Exception: On parse or encoding error after fallback attempts
    """
    if isinstance(csv_path, str):
        csv_path = Path(csv_path)

    if not csv_path.exists():
        return None

    encodings = [encoding, "latin-1", "iso-8859-1", "cp1252"]
    for enc in encodings:
        try:
            return pd.read_csv(csv_path, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    msg = f"Could not read {csv_path} with any encoding"
    raise ValueError(msg)


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
    1. Reads one or more issue CSVs from sf_export/
    2. Loads enrichment (internal_all.csv, search_console_all.csv, analytics_all.csv)
    3. Applies theme classification via rulebook
    4. Generates styled XLSX with 1+ sheets
    """

    def __init__(
        self,
        job_id: str,
        sf_export_dir: Path,
        rulebook_path: Path | None = None,
    ):
        """Initialize the service.

        Args:
            job_id: Job ID (used for logging)
            sf_export_dir: Path to sf_export/ directory
            rulebook_path: Optional rulebook for theme classification
        """
        self.job_id = job_id
        self.sf_export_dir = Path(sf_export_dir)
        self.rulebook_path = rulebook_path
        self._logger = get_logger(self.__class__.__module__)
        self._enrichment_cache: dict[str, pd.DataFrame | None] = {}

    @property
    @abstractmethod
    def metadata(self) -> MasterfileMetadata:
        """Service metadata (slug, label, sheet count, etc.)."""
        ...

    def _read_enrichment(self, filename: str) -> pd.DataFrame | None:
        """Read enrichment CSV with caching."""
        if filename in self._enrichment_cache:
            return self._enrichment_cache[filename]
        df = read_csv_safe(self.sf_export_dir / filename)
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
