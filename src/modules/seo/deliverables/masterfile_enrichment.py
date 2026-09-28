"""Enrichment maps and URL-column resolution for the masterfile services.

Split out of `masterfile_base.py` so that module stays under the 400-line
target once it gained the two rules this one exists to state:

**Which column holds the URL.** Most exports are page rows keyed by
`Address`. Twelve of the ninety-six allow-listed files are *edge lists* - the
`--bulk-export` inlink and outlink files, whose header is
`Type,Source,Destination,...` with no `Address` at all. Concatenating them
with page exports and then reading `Address` yields `nan` for every edge row,
silently, which is why each file is normalised to an `Address` column
*before* the frames are combined rather than after.

**"Not measured" is not zero** (ADR 0011 §5). `search_console_all.csv` and
`analytics_all.csv` are genuine Screaming Frog filenames, but they come from
the `Search Console:All` / `Analytics:All` tabs that
`screaming_frog_control/export_manifest.py` does not request and
`upload_manifest.ALLOWED_BUNDLE_FILENAMES` does not admit. They can therefore
never arrive today. A workbook must say so rather than print a column of
zeroes that reads as "this page gets no traffic".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

import pandas as pd  # type: ignore[import-untyped]

from src.core.logger import get_logger

__all__ = [
    "NOT_MEASURED",
    "URL_COLUMN",
    "Reader",
    "build_ga4_map",
    "build_gsc_map",
    "build_internal_map",
    "gc",
    "normalise_url_column",
    "url_column_for",
]

_logger = get_logger(__name__)

NOT_MEASURED: Final[str] = "Not measured by this crawl"
"""What a cell says when no export could have supplied it (ADR 0011 §5)."""

URL_COLUMN: Final[str] = "Address"
"""The column every service reads once its frames have been normalised."""

_EDGE_LIST_URL_COLUMN: Final[Mapping[str, str]] = MappingProxyType(
    {
        # `--bulk-export` inlink files list the *links into* a problem page.
        # The page the issue is about is the link's destination.
        "canonicalised_inlinks.csv": "Destination",
        "nonindexable_canonical_inlinks.csv": "Destination",
        "http_urls_inlinks.csv": "Destination",
        "internal_blocked_by_robots_txt_inlinks.csv": "Destination",
        "internal_blocked_resource_inlinks.csv": "Destination",
        "internal_client_error_(4xx)_inlinks.csv": "Destination",
        "internal_no_response_inlinks.csv": "Destination",
        "internal_redirection_(3xx)_inlinks.csv": "Destination",
        "internal_server_error_(5xx)_inlinks.csv": "Destination",
        # These three name a page that *contains* offending markup - an
        # insecure form action, a protocol-relative resource, an unsafe
        # cross-origin link. The fix belongs on the source page, so that is
        # the URL the workbook must list.
        "form_url_insecure.csv": "Source",
        "protocolrelative_outlinks.csv": "Source",
        "unsafe_crossorigin_links.csv": "Source",
    }
)
"""The twelve allow-listed exports with no `Address` column, and which of
their columns names the affected page. Confirmed against 49 real Screaming
Frog 19.4 export folders; every other allow-listed file has `Address`."""

Reader = Callable[[str], "pd.DataFrame | None"]
"""How these builders fetch a CSV: `MasterfileService._read_enrichment`."""


def gc(header: list[str], column_name: str) -> int:
    """Get column index: case-insensitive search for column name.

    Args:
        header: CSV header row.
        column_name: Column name to find (case-insensitive).

    Returns:
        0-based column index.

    Raises:
        KeyError: Column not found.
    """
    name_lower = column_name.lower()
    for i, col in enumerate(header):
        if col.lower() == name_lower:
            return i
    msg = f"Column not found: {column_name}"
    raise KeyError(msg)


def url_column_for(filename: str) -> str:
    """Which column of `filename` names the page an issue applies to."""
    return _EDGE_LIST_URL_COLUMN.get(filename, URL_COLUMN)


def normalise_url_column(frame: pd.DataFrame, filename: str) -> pd.DataFrame | None:
    """Return `frame` with its affected-page URL under `Address`.

    Args:
        frame: One export, as read.
        filename: The export's name, which is what decides the column for the
            edge-list files - their headers alone cannot.

    Returns:
        The frame, with an `Address` column, or `None` when the expected
        column is absent. `None` means "this file is not shaped like the
        export it is named after", which a service reports rather than
        silently treating as an empty result.
    """
    wanted = url_column_for(filename)
    try:
        index = gc(frame.columns.tolist(), wanted)
    except KeyError:
        _logger.warning(
            # `export`, not `filename`: `filename` is a reserved `LogRecord`
            # attribute and `logging.makeRecord` raises `KeyError` on it.
            "masterfile_url_column_missing",
            extra={"export": filename, "column": wanted},
        )
        return None
    if wanted == URL_COLUMN:
        return frame
    renamed = frame.copy()
    renamed.insert(0, URL_COLUMN, renamed.iloc[:, index])
    return renamed


def _indices(frame: pd.DataFrame | None, columns: tuple[str, ...]) -> list[int] | None:
    """Column indices for `columns`, or `None` if the frame cannot serve them."""
    if frame is None or frame.empty:
        return None
    try:
        return [gc(frame.columns.tolist(), name) for name in columns]
    except KeyError:
        return None


def _as_int(value: object) -> int:
    """A count from a CSV cell, or 0 when the cell is blank or not a number."""
    if pd.isna(value):
        return 0
    text = str(value)
    return int(float(text)) if text.replace(".", "", 1).lstrip("-").isdigit() else 0


def build_internal_map(read: Reader) -> dict[str, dict[str, Any]] | None:
    """`{url: {status_code, indexability, inlinks}}` from `internal_all.csv`.

    Args:
        read: Fetches a named CSV, or `None` when the source lacks it.

    Returns:
        The map, or `None` when the spine export is absent, empty, or lacks
        the columns this join needs.
    """
    frame = read("internal_all.csv")
    found = _indices(frame, ("Address", "Status Code", "Indexability", "Inlinks"))
    if found is None or frame is None:
        return None
    address_idx, status_idx, indexability_idx, inlinks_idx = found

    result: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        try:
            raw_inlinks = row.iloc[inlinks_idx]
            result[str(row.iloc[address_idx])] = {
                "status_code": (
                    str(row.iloc[status_idx]) if pd.notna(row.iloc[status_idx]) else None
                ),
                "indexability": (
                    str(row.iloc[indexability_idx])
                    if pd.notna(row.iloc[indexability_idx])
                    else None
                ),
                "inlinks": (
                    int(raw_inlinks)
                    if pd.notna(raw_inlinks) and str(raw_inlinks).isdigit()
                    else None
                ),
            }
        except (ValueError, IndexError):
            continue
    return result or None


def build_gsc_map(read: Reader) -> dict[str, dict[str, int]] | None:
    """`{url: {impressions, clicks}}` from `search_console_all.csv`.

    Returns `None` whenever that export is absent - which is always, today:
    no manifest requests the tab. Callers must render `NOT_MEASURED`, never 0.
    """
    frame = read("search_console_all.csv")
    found = _indices(frame, ("Address", "Impressions", "Clicks"))
    if found is None or frame is None:
        return None
    address_idx, impressions_idx, clicks_idx = found

    result: dict[str, dict[str, int]] = {}
    for _, row in frame.iterrows():
        try:
            result[str(row.iloc[address_idx])] = {
                "impressions": _as_int(row.iloc[impressions_idx]),
                "clicks": _as_int(row.iloc[clicks_idx]),
            }
        except (ValueError, IndexError):
            continue
    return result or None


def build_ga4_map(read: Reader) -> dict[str, int] | None:
    """`{url: sessions}` from `analytics_all.csv`; `None` when not measured."""
    frame = read("analytics_all.csv")
    found = _indices(frame, ("Address", "Sessions"))
    if found is None or frame is None:
        return None
    address_idx, sessions_idx = found

    result: dict[str, int] = {}
    for _, row in frame.iterrows():
        try:
            result[str(row.iloc[address_idx])] = _as_int(row.iloc[sessions_idx])
        except (ValueError, IndexError):
            continue
    return result or None
