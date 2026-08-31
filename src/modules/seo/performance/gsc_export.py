r"""Read a Search Console page export in whatever shape it actually arrives.

What a person actually downloads
--------------------------------
"Export → CSV" in the Search Console UI does **not** produce a CSV. It produces
a **ZIP** holding one CSV per tab — pages, queries, countries, devices, dates,
search appearance — and the file an analyst drags into an upload box is that
archive. "Export → Excel" produces a workbook with the same tabs as sheets. Only
someone who has already unpacked the archive has a bare `.csv`.

All three are accepted, because rejecting the default download and asking for
the one shape nobody has is how an ingestion endpoint gets a reputation.

A ZIP is not a workbook, and both start `PK\\x03\\x04`
-----------------------------------------------------
`.xlsx` *is* a ZIP. Magic bytes cannot separate the two, so the archive is
opened and its entries are read: a workbook contains `xl/workbook.xml`, and the
Search Console archive contains `.csv` files. Guessing from the magic alone
would send every CSV archive into `openpyxl` and fail it as "not a readable
workbook", which is both wrong and unhelpable.

Which tab holds the pages cannot be read from its name
------------------------------------------------------
The archive is written in the account's display language, so the pages tab is
`Pages.csv`, `Seiten.csv`, `Páginas.csv` or `ページ.csv`. Matching names would
work for English accounts and silently fail for the rest.

The tables are chosen **by content**: the pages tab is the one whose first
column holds addresses. Queries hold search phrases, dates hold dates, countries
hold country names — none of them parse as URLs, so the discrimination is sharp
without knowing a single word of the language. The same reasoning applies to the
column headers, which are localised too: they are matched by keyword where
possible and fall back to **position**, because the column order is fixed across
locales even when the words are not.

CTR is read and discarded
-------------------------
Search Console reports CTR as a formatted percentage, and it is the one column
this module never needs: a section's CTR is recomputed from summed clicks over
summed impressions, and a page's from its own two counters. Parsing it would be
work in service of a number that must not be used.

Pure parsing: bytes in, contracts out. No I/O, no settings, no clock.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator, Sequence

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import safe_split
from src.modules.seo.performance.schemas import GscPageMetrics

__all__ = ["MAX_UNPACKED_BYTES", "GscExport", "load_gsc_export"]

_logger = get_logger("modules.seo.performance.gsc_export")

MAX_UNPACKED_BYTES = 64 * 1024 * 1024
"""Ceiling on what one archive may expand to.

A ZIP declares its own uncompressed size, and a hostile one declares a small
compressed body that expands without limit. The endpoint bounds the upload; only
this bounds what the upload becomes.
"""

_ADDRESS_SHARE = 0.6
"""Share of a table's first column that must parse as an address.

Not 1.0: a Search Console export can carry an anonymised or malformed row, and a
single bad cell must not disqualify the right table. Not lower either — a
queries tab occasionally holds a phrase that looks like a domain, and at 0.6 a
handful of those cannot outvote a genuine pages tab.
"""

_ZIP_MAGIC = b"PK\x03\x04"
_WORKBOOK_ENTRY = "xl/workbook.xml"

_CLICK_WORDS = ("click", "klick", "clic", "clique", "cliques", "クリック")
_IMPRESSION_WORDS = ("impression", "impressionen", "impresion", "impressão", "表示")
_POSITION_WORDS = ("position", "posición", "posição", "posizione", "掲載順位")

# Column order in the pages tab, fixed across every locale: address, clicks,
# impressions, CTR, position. Used when the headers are localised past
# recognition, or absent because the file was assembled by hand.
_FALLBACK = (0, 1, 2, 4)

_SEPARATORS = "    '"
"""Thousands separators seen in real exports: space, non-breaking space, narrow
no-break space, thin space, and the Swiss apostrophe."""

_DIGITS = re.compile(r"\d")

_NOT_AN_EXPORT = (
    "this file is not a readable Search Console page export. Upload the ZIP "
    "from Export → CSV, the workbook from Export → Excel, or the pages CSV "
    "from inside either one."
)

_WRONG_REPORT = (
    "no tab in this file holds page addresses, so there is nothing to attach "
    "to the crawl. Found: {tabs}. That looks like a different Search Console "
    "report — Page indexing, Sitemaps and Core Web Vitals all export counts "
    "rather than URLs. The one with pages in it is Performance: open "
    "Performance → search results, then Export at the top right."
)

_NO_METRICS = (
    "this table lists addresses but no clicks or impressions{where}. That is the "
    "shape of a Page indexing export — it says which URLs are indexed, not how "
    "they perform. The Performance report carries clicks and impressions per "
    "URL: open Performance → search results, then Export at the top right."
)

_NO_ADDRESSES = (
    "this file's first column holds no page addresses, so there is nothing to "
    "attach to the crawl. A Search Console Performance export lists one "
    "URL per row with its clicks and impressions; a queries, dates or "
    "countries tab does not, and neither does the Page indexing report."
)

_NEEDS_OPENPYXL = (
    "this looks like an Excel workbook, but openpyxl is not installed. Export "
    "the report as CSV instead."
)

_Table = tuple[str, list[Sequence[object]]]


class GscExport(StrictModel):
    """One parsed Search Console page export.

    Attributes:
        rows: One entry per page the export reported.
        source_name: The archive entry or worksheet the rows came from, or `""`
            for a bare CSV. Reported so an analyst who uploaded a six-tab
            archive can confirm the right tab was read — the choice is made by
            inspecting content, and a silent choice is one nobody can check.
        skipped_rows: Rows that carried no usable address. Counted rather than
            dropped quietly.
    """

    rows: tuple[GscPageMetrics, ...] = ()
    source_name: str = ""
    skipped_rows: int = Field(default=0, ge=0)


def _is_address(value: object) -> bool:
    """Whether a cell looks like a page address rather than a query or a date.

    This is the whole basis for picking the right tab out of a localised
    archive, so it is deliberately narrow: an absolute `http(s)` URL with a
    host, or a rooted path. A country name, a device name, a date and a search
    phrase all fail it.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text.startswith("/"):
        return True
    parts = safe_split(text)
    return parts is not None and parts.scheme in {"http", "https"} and bool(parts.netloc)


def _number(value: object) -> str:
    """Normalise a cell to a bare numeric string, or `""` when there is none."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip().rstrip("%").strip()
    for separator in _SEPARATORS:
        text = text.replace(separator, "")
    return text if _DIGITS.search(text) else ""


def _as_int(value: object) -> int:
    """Read a whole number, dropping thousands separators of either convention.

    Both `1,234` and `1.234` mean 1234 — the first in English, the second in
    German — and since clicks and impressions are counts, removing every
    separator is correct in both. The ambiguity that bites floats does not arise
    here.
    """
    text = _number(value).replace(",", "").replace(".", "")
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def _as_float(value: object) -> float:
    """Read a decimal, treating the **last** separator as the decimal point.

    `12.34` and `12,34` are the same position written for two locales, and the
    last separator identifies which character is doing the decimal job.

    The one genuinely ambiguous input is a lone comma before three digits:
    `1,234` is 1234 to an English reader and 1.234 to a German one. It resolves
    to 1.234 here, and that is the deliberate choice — an average position of
    1.234 is an ordinary ranking while 1234 is barely a real one, so the reading
    this rule produces is the plausible one.
    """
    text = _number(value)
    cut = max(text.rfind("."), text.rfind(","))
    if cut >= 0:
        text = text[:cut].replace(",", "").replace(".", "") + "." + text[cut + 1 :]
    try:
        return max(0.0, float(text))
    except ValueError:
        return 0.0


def _csv_rows(text: str) -> list[Sequence[object]]:
    """Parse CSV text, sniffing the delimiter rather than assuming a comma.

    A Search Console export written from a locale that uses the comma as a
    decimal separator is delimited with semicolons. Read as comma-separated it
    yields one column, no address is found, and the file is rejected as "not an
    export" when it is a perfectly ordinary one.
    """
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter) if row]


def _tables(body: bytes | str) -> list[_Table]:
    """Every table the payload contains, whatever container it arrived in."""
    if isinstance(body, str):
        return [("", _csv_rows(body))]
    if not body.startswith(_ZIP_MAGIC):
        # `utf-8-sig`: Search Console writes a byte-order mark, and left in place
        # it becomes an invisible prefix on the first header.
        return [("", _csv_rows(body.decode("utf-8-sig", errors="replace")))]
    return _from_archive(body)


def _from_archive(body: bytes) -> list[_Table]:
    """Unpack a ZIP, which may be a CSV archive or an Excel workbook."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise ValueError(_NOT_AN_EXPORT) from exc

    if any(name == _WORKBOOK_ENTRY for name in names):
        return _from_workbook(body)

    total = sum(entry.file_size for entry in archive.infolist())
    if total > MAX_UNPACKED_BYTES:
        raise ValueError(
            f"this archive expands to {total // (1024 * 1024)} MB, over the "
            f"{MAX_UNPACKED_BYTES // (1024 * 1024)} MB limit."
        )

    tables: list[_Table] = []
    for name in names:
        if not name.lower().endswith(".csv"):
            continue
        raw = archive.read(name)
        tables.append((name, _csv_rows(raw.decode("utf-8-sig", errors="replace"))))
    if not tables:
        raise ValueError(_NOT_AN_EXPORT)
    return tables


def _from_workbook(body: bytes) -> list[_Table]:
    """Read every sheet of an Excel export.

    Every sheet, not the active one: the active sheet of a Search Console
    workbook is whichever tab was last selected, and the pages tab is chosen by
    content further down.
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ValueError(_NEEDS_OPENPYXL) from exc

    try:
        book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises several unrelated types
        raise ValueError(_NOT_AN_EXPORT) from exc

    tables: list[_Table] = []
    try:
        for sheet in book.worksheets:
            rows: list[Sequence[object]] = [
                list(row) for row in sheet.iter_rows(values_only=True) if any(row)
            ]
            tables.append((str(sheet.title), rows))
    finally:
        book.close()
    return tables


def _address_share(rows: list[Sequence[object]]) -> float:
    """Share of a table's first column, header excluded, that is an address."""
    body = rows[1:] if len(rows) > 1 else rows
    if not body:
        return 0.0
    hits = sum(1 for row in body if row and _is_address(row[0]))
    return hits / len(body)


def _pick(tables: list[_Table]) -> _Table:
    """Choose the pages table by content, since its name is localised.

    Ties break toward the larger table. A Search Console archive can hold a
    filters tab that names one page, which would otherwise beat the real pages
    tab on share alone by being unanimous about its single row.
    """
    scored = [(_address_share(rows), len(rows), name, rows) for name, rows in tables if rows]
    best = max(scored, default=None, key=lambda item: (item[0], item[1]))
    if best is None:
        # Nothing readable at all — an empty body, or a file with no rows in it.
        # A message about which column holds addresses would be answering a
        # question this reader has not reached yet.
        raise ValueError(_NOT_AN_EXPORT)
    if best[0] < _ADDRESS_SHARE:
        # Name what was found. The first version of this message described the
        # file it wanted and not the file it got, which is no help at all to
        # somebody holding the Page indexing export — four tabs, not one URL in
        # any of them, and every word of the refusal still true of a file they
        # would never have produced. Real case, 2026-08-21.
        named = [name for _, _, name, _ in scored if name]
        if named:
            shown = ", ".join(named[:6])
            raise ValueError(_WRONG_REPORT.format(tabs=shown))
        raise ValueError(_NO_ADDRESSES)
    return best[2], best[3]


def _columns(rows: list[Sequence[object]]) -> tuple[tuple[int, int, int, int], int]:
    """Locate the address, clicks, impressions and position columns.

    Returns the indices and where the data starts — 1 when the first row is a
    header, 0 when it is already an address and the file therefore has none.

    Keyword matching is attempted first and covers the common locales. When it
    does not find both counters the fallback is **positional**, which is the
    reliable path: Search Console writes the same column order in every
    language, so position survives translation where words do not.
    """
    first = rows[0]
    if first and _is_address(first[0]):
        return _FALLBACK, 0

    headers = [str(cell).strip().lower() if cell is not None else "" for cell in first]

    def find(words: tuple[str, ...]) -> int | None:
        for index, header in enumerate(headers):
            if index and any(word in header for word in words):
                return index
        return None

    clicks = find(_CLICK_WORDS)
    impressions = find(_IMPRESSION_WORDS)
    if clicks is None or impressions is None:
        return _FALLBACK, 1
    position = find(_POSITION_WORDS)
    return (0, clicks, impressions, _FALLBACK[3] if position is None else position), 1


def _cell(row: Sequence[object], index: int) -> object:
    return row[index] if 0 <= index < len(row) else None


def load_gsc_export(body: bytes | str) -> GscExport:
    """Read a Search Console page export.

    Args:
        body: Raw bytes from an upload — a ZIP of CSVs, an `.xlsx` workbook, or
            a bare CSV — or text already decoded.

    Returns:
        The parsed rows, the table they came from, and how many rows carried no
        usable address.

    Raises:
        ValueError: If the payload holds no table whose first column is
            addresses, or is not a readable archive at all.
    """
    tables = _tables(body)
    name, rows = _pick(tables)
    (address, clicks, impressions, position), start = _columns(rows)

    parsed: list[GscPageMetrics] = []
    skipped = 0
    for row in rows[start:]:
        value = _cell(row, address)
        if not _is_address(value):
            skipped += 1
            continue
        parsed.append(
            GscPageMetrics(
                url=str(value).strip(),
                clicks=_as_int(_cell(row, clicks)),
                impressions=_as_int(_cell(row, impressions)),
                position=_as_float(_cell(row, position)),
            )
        )
    if not parsed:
        raise ValueError(_NOT_AN_EXPORT)
    if not any(row.clicks or row.impressions for row in parsed):
        # Addresses without metrics is a *different* wrong file from addresses
        # missing altogether, and it is the more dangerous one: the Page
        # indexing "valid pages" export is a list of real URLs, so it resolves
        # against the crawl and produces a confident report of 967 pages with
        # zero traffic. That one overwrote a real report before this guard
        # existed. A Performance export always carries at least one impression;
        # a site with none has nothing to report either way.
        where = f" — read from {name}" if name else ""
        raise ValueError(_NO_METRICS.format(where=where))
    _logger.info(
        "gsc_export_read",
        extra={"source": name, "rows": len(parsed), "skipped": skipped},
    )
    return GscExport(rows=tuple(parsed), source_name=name, skipped_rows=skipped)


def rows_of(body: bytes | str) -> Iterator[GscPageMetrics]:
    """Convenience iterator over a parsed export's rows."""
    yield from load_gsc_export(body).rows
