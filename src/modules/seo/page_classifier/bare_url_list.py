"""Read a one-column list of URLs, the way a client masterfile carries one.

Why this exists
---------------
The cross-check dialog asks for a Screaming Frog `Internal → HTML` export, but
the file an analyst actually has to hand is often a masterfile tab: one column
headed `HTML Pages`, or nothing at all, and a URL per row. Refusing it with
"no 'Address' column" was correct and useless — the list is still a perfectly
good second opinion on *which* URLs exist, and the set comparison needs nothing
more than that.

What it deliberately cannot tell you
------------------------------------
A bare list carries no status, no indexability and no content type. It says a
URL was written down, not that it is a live page. That is why the reconciler
labels every URL it holds alone as unknown rather than as a missed page, and
why nothing from a bare list is ever merged into a crawl. This module only
answers one question: *is this file a bare list, and if so which URLs?*

Detection is strict on purpose. Exactly one populated column, every value an
http(s) URL. A two-column sheet, a Search Console `Top pages` export with its
click counts, or a column of paths without a scheme is not a bare list, and
the caller keeps its original refusal for those.
"""

from __future__ import annotations

import csv
import io
from urllib.parse import urlsplit

__all__ = ["bare_url_list"]

_XLSX_MAGIC = b"PK"
"""ZIP local-file header. Same content sniff as the export loader uses."""


def _is_http_url(value: str) -> bool:
    """True for an absolute http(s) URL with a host, which is all a list may hold."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _grid_from_csv(text: str) -> list[list[str]]:
    """Every cell of a CSV, stripped. A parse failure is simply not a list."""
    try:
        return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    except csv.Error:
        return []


def _grid_from_xlsx(body: bytes) -> list[list[str]]:
    """Every cell of the active worksheet, stripped.

    Unreadable archives and a missing `openpyxl` both return an empty grid
    rather than raising: this reader runs *after* the export loader has already
    refused the file, and that refusal — which names the real problem — is the
    message the user should see.
    """
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - depends on the install
        return []
    try:
        book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - openpyxl raises several unrelated types
        return []
    try:
        sheet = book.active
        if sheet is None:
            return []
        return [
            ["" if cell is None else str(cell).strip() for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
    finally:
        book.close()


def bare_url_list(body: bytes | str) -> tuple[str, ...] | None:
    """Return the URLs if `body` is a one-column URL list, else `None`.

    A first row whose only populated cell is not itself a URL is taken as a
    header (`HTML Pages`, `URL`, anything) and dropped. A first row that *is* a
    URL means the file is headerless and every row counts.

    Args:
        body: Raw upload bytes, or CSV text already decoded.

    Returns:
        The URLs in file order, or `None` when the file is not a bare list — a
        second populated column, a value without an http(s) scheme, or nothing
        at all.
    """
    if isinstance(body, str):
        grid = _grid_from_csv(body)
    elif body.startswith(_XLSX_MAGIC):
        grid = _grid_from_xlsx(body)
    else:
        grid = _grid_from_csv(body.decode("utf-8-sig", errors="replace"))

    rows = [row for row in grid if any(row)]
    if not rows:
        return None

    first_populated = [cell for cell in rows[0] if cell]
    if len(first_populated) == 1 and not _is_http_url(first_populated[0]):
        rows = rows[1:]

    columns = {index for row in rows for index, cell in enumerate(row) if cell}
    if len(columns) != 1:
        return None
    (column,) = columns

    urls = tuple(row[column] for row in rows if column < len(row) and row[column])
    if not urls or not all(_is_http_url(url) for url in urls):
        return None
    return urls
