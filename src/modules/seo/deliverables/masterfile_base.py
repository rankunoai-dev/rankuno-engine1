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

Two rules live here rather than in each of the twenty-one subclasses, because
build-log 0116 found both broken in all twenty-one at once:

* **A service never names its own input files.** `SOURCE_FILES` is derived
  from `ISSUE_CATALOGUE` through `contracts/sources.py`, so a filename can
  only reach a workbook by first being in the catalogue - which is also what
  `ALLOWED_BUNDLE_FILENAMES` derives from.
* **`INDEXABLE_ONLY` is a declaration, not a default.** Three services report
  on pages that are non-indexable *by definition* - a `noindex` directive, a
  4xx response, an inlink to a broken page - and filtering those to
  `Indexability == "Indexable"` is a rule that can never match a row.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Final

import pandas as pd  # type: ignore[import-untyped]
from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.deliverables.masterfile_enrichment import (
    NOT_MEASURED,
    URL_COLUMN,
    build_ga4_map,
    build_gsc_map,
    build_internal_map,
    gc,
    normalise_url_column,
)
from src.modules.seo.deliverables.masterfile_source import (
    DirectoryMasterfileSource,
    MasterfileSource,
    read_csv_safe,
)
from src.modules.seo.deliverables.rulebook import OTHERS_THEME

__all__ = [
    "NOT_MEASURED",
    "URL_COLUMN",
    "EnrichedURLRecord",
    "MasterfileMetadata",
    "MasterfileService",
    "MasterfileSource",
    "gc",
    "read_csv_safe",
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

    SOURCE_FILES: ClassVar[tuple[str, ...]] = ()
    """Every export this service reads, from `contracts/sources.py`. Empty
    means the service has no producible input today (`custom_extraction`
    discovers its files dynamically; the two Custom Search services and
    Functional Internal Links have no catalogue source at all)."""

    INDEXABLE_ONLY: ClassVar[bool] = True
    """Whether the detail table is restricted to `Indexability ==
    "Indexable"`, per build-log 0104's original spec. `False` where the issue
    is *defined* by non-indexability, which that spec already carved out for
    Response Codes and never implemented."""

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

    def _read_issue_frames(self, filenames: tuple[str, ...] | None = None) -> pd.DataFrame | None:
        """The named exports, concatenated, each keyed by `Address`.

        Normalising the URL column *per file* is the point: nine `_inlinks`
        and three outlink exports are edge lists with no `Address` at all, and
        concatenating them first would give every one of their rows a `nan`
        address that the caller would then write into the workbook as the
        string "nan".

        Args:
            filenames: Which exports to read. Defaults to `SOURCE_FILES`.

        Returns:
            One frame, or `None` when no named export was present and
            non-empty - which means "not measured", not "no issues".
        """
        frames = []
        for filename in self.SOURCE_FILES if filenames is None else filenames:
            frame = self._read_csv(filename)
            if frame is None or frame.empty:
                continue
            normalised = normalise_url_column(frame, filename)
            if normalised is None:
                # Present but not shaped like its name. Keep it in the
                # concatenation so the caller still reports "error reading",
                # rather than dropping it into a silent empty workbook.
                frames.append(frame)
                continue
            frames.append(normalised)

        if not frames:
            return None
        combined = pd.concat(frames, ignore_index=True)
        return combined if not combined.empty else None

    def _build_internal_map(self) -> dict[str, dict[str, Any]] | None:
        """`{url: {status_code, indexability, inlinks}}` from the spine."""
        return build_internal_map(self._read_enrichment)

    def _build_gsc_map(self) -> dict[str, dict[str, int]] | None:
        """`{url: {impressions, clicks}}`, or `None` when not measured."""
        return build_gsc_map(self._read_enrichment)

    def _build_ga4_map(self) -> dict[str, int] | None:
        """`{url: sessions}`, or `None` when not measured."""
        return build_ga4_map(self._read_enrichment)

    def _gsc_lookup(
        self, gsc_map: dict[str, dict[str, int]] | None, url: str
    ) -> dict[str, int | str]:
        """Impressions and clicks for `url`, distinguishing zero from unknown.

        A crawl that carried no `search_console_all.csv` did not measure
        impressions; a crawl that carried one and did not list `url` measured
        zero. ADR 0011 §5 requires a workbook to show the difference, so the
        first case yields `NOT_MEASURED` and only the second yields 0.
        """
        if gsc_map is None:
            return {"impressions": NOT_MEASURED, "clicks": NOT_MEASURED}
        found = gsc_map.get(url)
        if found is None:
            return {"impressions": 0, "clicks": 0}
        return dict(found)

    def _is_reportable(self, indexability: str | None) -> bool:
        """Whether a row survives this service's indexability rule."""
        return not self.INDEXABLE_ONLY or indexability == "Indexable"

    @abstractmethod
    def generate(self) -> bytes:
        """Generate the XLSX workbook bytes.

        Returns:
            XLSX file contents as bytes

        Raises:
            MasterfileError: On any generation failure
        """
        ...
