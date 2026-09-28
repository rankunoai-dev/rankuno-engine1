"""A synthetic Screaming Frog 19.4 export that the masterfile services can read.

Nineteen of the twenty-one service test files used to point a service at an
*empty* temporary directory and assert `len(result) > 0`. An empty workbook is
several thousand bytes, so that assertion held while thirteen services
rendered nothing at all and one crashed - build-log 0116. This module exists so
those tests have real bytes to read and so the assertions can be row counts and
exact header rows instead.

**No RAE data enters the repository.** The rule `test_diff_against_rae.py`
states extends to data: every header here was *observed* in
`RAE/rankuno-reports/` and retyped; every row is invented. Nothing is copied.

The bytes are shaped like a real export, because each of these has already
caused a bug:

* a **UTF-8 BOM** on the first header cell - `utf-8-sig` exists in
  `masterfile_source.py` because bare `utf-8` glued the BOM to `Address` and
  `gc()` then silently found no column;
* **CRLF** line endings;
* **`QUOTE_ALL`** quoting, including a header that embeds a doubled quote
  (`rel=""next"" 1`);
* a URL that appears in **no** `internal_all.csv` row, so enrichment misses;
* a **non-indexable** row, which three services must keep and the rest drop;
* one URL in **several issue files at once**;
* a cell beginning with **`=`**, for the formula-injection guard.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

__all__ = [
    "ABSENT_FROM_SPINE",
    "EXPORT_FILES",
    "FORMULA_URL",
    "GONE",
    "HEADERS",
    "HOME",
    "NOINDEX",
    "SEARCH_CONSOLE",
    "ABOUT",
    "csv_bytes",
    "write_export",
]

HOME: Final[str] = "https://example.com/"
"""Indexable, and named by four different issue exports."""

ABOUT: Final[str] = "https://example.com/about"
"""Indexable, one issue each in several categories."""

GONE: Final[str] = "https://example.com/gone"
"""404, therefore `Non-Indexable`. Only the three services that declare
`INDEXABLE_ONLY = False` may report it."""

NOINDEX: Final[str] = "https://example.com/noindex"
"""`Non-Indexable` by directive - the row that made the Directives workbook
structurally empty before build-log 0116."""

ABSENT_FROM_SPINE: Final[str] = "https://example.com/orphan"
"""Named by an issue export but absent from `internal_all.csv`, so no
enrichment exists for it. Must not crash and must not be invented."""

FORMULA_URL: Final[str] = '=HYPERLINK("http://evil.example","click")'
"""What an untrusted `Address` cell can hold. `safe_cell` must neutralise it."""

HEADERS: Final[Mapping[str, tuple[str, ...]]] = {
    # Every header below was read from a real Screaming Frog 19.4 export in
    # `RAE/rankuno-reports/` and retyped here. Column order is theirs.
    "internal_all.csv": (
        "Address",
        "Content Type",
        "Status Code",
        "Status",
        "Indexability",
        "Indexability Status",
        "Inlinks",
    ),
    "search_console_all.csv": ("Address", "Clicks", "Impressions", "CTR", "Position"),
    "page_titles_missing.csv": (
        "Address",
        "Occurrences",
        "Title 1",
        "Title 1 Length",
        "Title 1 Pixel Width",
        "Indexability",
        "Indexability Status",
    ),
    "page_titles_duplicate.csv": (
        "Address",
        "Occurrences",
        "Title 1",
        "Title 1 Length",
        "Title 1 Pixel Width",
        "Indexability",
        "Indexability Status",
    ),
    "meta_description_missing.csv": (
        "Address",
        "Occurrences",
        "Meta Description 1",
        "Meta Description 1 Length",
        "Meta Description 1 Pixel Width",
        "Indexability",
        "Indexability Status",
    ),
    "h1_missing.csv": (
        "Address",
        "Occurrences",
        "H1-1",
        "H1-1 Length",
        "Indexability",
        "Indexability Status",
    ),
    "canonicals_missing.csv": (
        "Address",
        "Occurrences",
        "Indexability",
        "Indexability Status",
        "Canonical Link Element 1",
        "HTTP Canonical",
        "Meta Robots 1",
        "X-Robots-Tag 1",
        'rel="next" 1',
        'rel="prev" 1',
    ),
    "directives_noindex.csv": (
        "Address",
        "Occurrences",
        "Meta Robots 1",
        "Meta Robots 2",
        "X-Robots-Tag 1",
        "Meta Refresh 1",
        "Canonical Link Element 1",
        "HTTP Canonical",
    ),
    "response_codes_internal_client_error_(4xx).csv": (
        "Address",
        "Content Type",
        "Status Code",
        "Status",
        "Indexability",
        "Indexability Status",
        "Inlinks",
        "Response Time",
        "Redirect URL",
        "Redirect Type",
    ),
    "internal_client_error_(4xx)_inlinks.csv": (
        "Type",
        "Source",
        "Destination",
        "Size (Bytes)",
        "Alt Text",
        "Anchor",
        "Status Code",
        "Status",
        "Follow",
        "Target",
        "Rel",
        "Path Type",
        "Link Path",
        "Link Position",
        "Link Origin",
    ),
    "security_http_urls.csv": (
        "Address",
        "Content Type",
        "Status Code",
        "Status",
        "HTTP Version",
        "Indexability",
        "Indexability Status",
        "Canonical Link Element 1",
        "Meta Robots 1",
        "X-Robots-Tag 1",
    ),
    "form_url_insecure.csv": ("Source", "Form Action Link"),
    "url_uppercase.csv": (
        "Address",
        "Content Type",
        "Status Code",
        "Status",
        "Indexability",
        "Indexability Status",
        "Hash",
        "Length",
        "Canonical Link Element 1",
        "URL Encoded Address",
    ),
    "sitemaps_orphan_urls.csv": (
        "Address",
        "Content Type",
        "Status Code",
        "Status",
        "Indexability",
        "Indexability Status",
    ),
    "structured_data_validation_errors.csv": (
        "Address",
        "Errors",
        "Warnings",
        "Total Types",
        "Unique Types",
        "Type-1",
        "Indexability",
        "Indexability Status",
    ),
    "content_low_content_pages.csv": (
        "Address",
        "Word Count",
        "Indexability",
        "Indexability Status",
    ),
    "content_exact_duplicates.csv": ("Address", "Hash", "Indexability", "Indexability Status"),
    "content_lorem_ipsum_placeholder.csv": (
        "Address",
        "Word Count",
        "Indexability",
        "Indexability Status",
    ),
    "hreflang_missing.csv": ("Address", "Occurrences", "Indexability", "Indexability Status"),
    "pagination_nonindexable.csv": (
        "Address",
        "Indexability",
        "Indexability Status",
        'rel="next" 1',
        'rel="prev" 1',
    ),
    "pagination_sequence_error.csv": (
        "Address",
        "Indexability",
        "Indexability Status",
        'rel="next" 1',
        'rel="prev" 1',
    ),
}
"""Observed column headers, keyed by observed filename."""

_ROWS: Final[Mapping[str, tuple[tuple[str, ...], ...]]] = {
    "internal_all.csv": (
        (HOME, "text/html", "200", "OK", "Indexable", "", "12"),
        (ABOUT, "text/html", "200", "OK", "Indexable", "", "5"),
        (GONE, "text/html", "404", "Not Found", "Non-Indexable", "Client Error", "3"),
        (NOINDEX, "text/html", "200", "OK", "Non-Indexable", "Noindex", "2"),
        (FORMULA_URL, "text/html", "200", "OK", "Indexable", "", "1"),
    ),
    # HOME is named by four issue exports on purpose: nothing deduplicates,
    # and a test that did not know that would mis-read every row count here.
    "page_titles_missing.csv": ((HOME, "1", "", "0", "0", "Indexable", ""),),
    "page_titles_duplicate.csv": (
        (HOME, "2", "Example", "7", "56", "Indexable", ""),
        (ABOUT, "2", "Example", "7", "56", "Indexable", ""),
    ),
    "meta_description_missing.csv": ((HOME, "1", "", "0", "0", "Indexable", ""),),
    "h1_missing.csv": (
        (HOME, "1", "", "0", "Indexable", ""),
        (GONE, "1", "", "0", "Non-Indexable", "Client Error"),
    ),
    "canonicals_missing.csv": ((ABOUT, "1", "Indexable", "", "", "", "", "", "", ""),),
    "directives_noindex.csv": ((NOINDEX, "1", "noindex", "", "", "", "", ""),),
    "response_codes_internal_client_error_(4xx).csv": (
        (GONE, "text/html", "404", "Not Found", "Non-Indexable", "Client Error", "3", "12", "", ""),
    ),
    "internal_client_error_(4xx)_inlinks.csv": (
        (
            "Hyperlink",
            HOME,
            GONE,
            "512",
            "",
            "Gone",
            "404",
            "Not Found",
            "True",
            "",
            "",
            "Absolute",
            "/gone",
            "Content",
            "HTML",
        ),
    ),
    "security_http_urls.csv": (
        (ABOUT, "text/html", "200", "OK", "1.1", "Indexable", "", "", "", ""),
    ),
    "form_url_insecure.csv": ((HOME, "http://example.com/login"),),
    "url_uppercase.csv": (
        (ABOUT, "text/html", "200", "OK", "Indexable", "", "h", "24", "", ""),
        (FORMULA_URL, "text/html", "200", "OK", "Indexable", "", "h", "40", "", ""),
    ),
    "sitemaps_orphan_urls.csv": (
        (ABOUT, "text/html", "200", "OK", "Indexable", ""),
        (ABSENT_FROM_SPINE, "text/html", "200", "OK", "Indexable", ""),
    ),
    "structured_data_validation_errors.csv": ((HOME, "2", "0", "1", "1", "Organization", "", ""),),
    "content_low_content_pages.csv": (
        (HOME, "80", "Indexable", ""),
        (ABSENT_FROM_SPINE, "40", "Indexable", ""),
    ),
    "content_exact_duplicates.csv": (
        (HOME, "abc123", "Indexable", ""),
        (ABOUT, "abc123", "Indexable", ""),
    ),
    "content_lorem_ipsum_placeholder.csv": ((ABOUT, "300", "Indexable", ""),),
    "hreflang_missing.csv": ((HOME, "1", "Indexable", ""),),
    "pagination_nonindexable.csv": ((NOINDEX, "Non-Indexable", "Noindex", "", ""),),
    "pagination_sequence_error.csv": ((ABOUT, "Indexable", "", "", ""),),
}

EXPORT_FILES: Final[tuple[str, ...]] = tuple(
    name for name in _ROWS if name != "search_console_all.csv"
)
"""Every file `write_export` writes by default."""

SEARCH_CONSOLE: Final[str] = "search_console_all.csv"
"""Written only on request. It is a genuine Screaming Frog filename that no
manifest requests and the allow-list does not admit, so a default export must
*not* carry it - that absence is what `NOT_MEASURED` reports."""


def csv_bytes(header: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    """One export file's bytes: BOM, CRLF, `QUOTE_ALL`, exactly as SF writes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def write_export(
    root: Path,
    *,
    extra: Mapping[str, bytes] | None = None,
    only: Sequence[str] | None = None,
) -> Path:
    """Write the synthetic export into `root` and return it.

    Args:
        root: Directory to fill. Created if absent.
        extra: Further `{filename: bytes}` to write verbatim - a hostile
            custom-extraction name, say, or a `search_console_all.csv`.
        only: Restrict the default files to these names, for a test that needs
            a sparse bundle.

    Returns:
        `root`.
    """
    root.mkdir(parents=True, exist_ok=True)
    wanted = EXPORT_FILES if only is None else tuple(only)
    for name in wanted:
        (root / name).write_bytes(csv_bytes(HEADERS[name], _ROWS[name]))
    for name, payload in (extra or {}).items():
        (root / name).write_bytes(payload)
    return root


def search_console_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    """A `Search Console:All` export, for the "measured zero" half of §5."""
    return csv_bytes(HEADERS[SEARCH_CONSOLE], rows)
