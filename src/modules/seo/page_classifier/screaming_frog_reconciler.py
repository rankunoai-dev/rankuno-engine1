"""Reconcile a Screaming Frog export against a Rankuno crawl result.

Why this exists
---------------
The two tools disagree by thousands of URLs on the same site, and almost none of
that disagreement is error. Screaming Frog follows links; this engine merges
sitemaps, a CMS API and the link graph. On highradius.com they agreed on 7,825
URLs and each held roughly 4,000 the other did not — and reading either total as
"pages on the site" is wrong in both directions.

Neither list is ground truth, so this module does not pick a winner. It sorts
every disagreement into a reason, and the reasons are what an analyst acts on.

What the reasons are for
------------------------
Most of Screaming Frog's surplus is not a gap in this engine at all: 63% of it
on highradius.com was redirect *sources*, which Screaming Frog lists as rows in
their own right and this engine follows through to a destination it already
holds. What is left once the noise is subtracted is the number worth reading —
the live, indexable, in-scope pages this engine genuinely never reached.

The surplus in the other direction holds the engine's strongest finding and its
worst defect in the same column. Sitemap orphans — real published pages with no
internal link pointing at them — are invisible to a link-following crawler by
construction. Fabricated URLs from a relative-href loop are invisible to it for
a better reason: they are not pages.

Reasons are exclusive and ordered
---------------------------------
A URL gets exactly one reason, assigned by the first rule that matches, so the
buckets sum to the total and a report cannot double-count. An earlier ad-hoc
version of this analysis counted subdomains as a bucket *and* inside the status
buckets, and overstated its own total by 83.

CSV only, deliberately
----------------------
Screaming Frog exports both `.csv` and `.xlsx`. Only CSV is read here, because
`openpyxl` is not a declared dependency of this project — it is present in one
developer's environment through an unrelated package, and building on that would
fail a clean checkout with an ImportError instead of a message.

A bare URL list is a second, weaker input
-----------------------------------------
A one-column list of URLs — a client masterfile tab headed `HTML Pages`, or a
headerless dump — is accepted through `load_cross_check_input` as a declared
`ExportFormat.BARE_URL_LIST`. The set comparison runs unchanged, but the file
carries no status, indexability or content type, so every URL it holds alone
is `FrogGapReason.UNKNOWN` rather than a missed page, and nothing from it is
ever merged. A list proves a URL was written down, not that it is a page.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.bare_url_list import bare_url_list
from src.modules.seo.page_classifier.url_rules import (
    NON_PAGE_SUFFIXES,
    is_spider_trap,
    site_host,
)

__all__ = [
    "MIN_TAIL_REPEATS",
    "CrossCheckInput",
    "DefaulterCategory",
    "DefaulterValidation",
    "EngineGapReason",
    "ExportFormat",
    "FrogGapReason",
    "NotAnExportError",
    "ReconciliationReport",
    "ScreamingFrogRow",
    "UrlGap",
    "MissedPageCheck",
    "MissedPageStatus",
    "load_cross_check_input",
    "load_screaming_frog_csv",
    "load_screaming_frog_export",
    "normalise",
    "reconcile",
    "revalidate_defaulters",
    "verify_missed_pages",
]

_logger = get_logger("modules.seo.screaming_frog_reconciler")

MIN_TAIL_REPEATS = 25
"""Times a path tail must repeat before it is called a relative-href loop.

Measured rather than chosen. On highradius.com the two real loops repeated 650
and 624 times and the highest legitimate tail repeated 7, so anything in that
gap separates them. 25 is far enough above the noise to be safe and far enough
below the signal to catch a smaller site's loop.
"""

_TAIL_SEGMENTS = 3
"""Path segments compared when looking for a repeated tail.

Two is too weak: `/product/overview` legitimately repeats under many parents on
a large catalogue. Three is the shortest tail observed to be unambiguous.
"""

_MALFORMED_MARKERS = ("<", ">", "href=")
"""Substrings that mean a URL was built from broken markup rather than a link.

highradius.com publishes an unclosed anchor that the resolver turned into the
address `…/highradius-launches-livecube/<a href=`. 91 URLs on one crawl.
"""

_PDF_SUFFIXES = (".pdf",)
"""The one format big enough to own a sheet: 7,610 of infosys.com's 8,383
engine-only URLs were PDFs, and every one sat in the Orphans sheet."""

_PRESENTATION_SUFFIXES = (".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp", ".key")

_SPREADSHEET_SUFFIXES = (".xls", ".xlsx", ".xlsm", ".csv", ".ods")

_OTHER_FILE_SUFFIXES = NON_PAGE_SUFFIXES + (
    ".doc",
    ".docx",
    ".docm",
    ".rtf",
    ".odt",
    ".txt",
    ".epub",
    # Legacy streaming media, still linked from infosys.com's 2001-2004
    # investor archive. Not in `NON_PAGE_SUFFIXES`, so discovery kept them.
    ".asx",
    ".asf",
    ".rm",
)
"""Everything else that is a file rather than a page.

An explicit allowlist, not "any dotted final segment": `.html`, `.aspx` and
`.htm` are pages, and infosys.com publishes e-mail addresses as path segments
(`…/techcompass/name@infosys.com`) that a suffix-agnostic rule would file as
`.com` documents. Unlisted suffixes fall through to the page rules.
"""


class FrogGapReason(StrEnum):
    """Why Screaming Frog holds a URL this engine does not."""

    OFF_SITE = "OFF_SITE"
    """A different host. This engine is same-site by design; Screaming Frog can
    be configured to include subdomains, and on highradius.com was."""

    REDIRECT = "REDIRECT"
    """A redirect source. Not a page — the destination is in both sets."""

    CLIENT_ERROR = "CLIENT_ERROR"
    """4xx, 5xx, or no status at all. Not a page."""

    MEDIA_URL = "MEDIA_URL"
    """An image, stylesheet or script, refused by this engine by design."""

    SPIDER_TRAP = "SPIDER_TRAP"
    """Refused by this engine's trap rules, by design."""

    NON_INDEXABLE = "NON_INDEXABLE"
    """Live, but canonicalised elsewhere or marked noindex."""

    MISSED_PAGE = "MISSED_PAGE"
    """Live, indexable, in scope — and never found. The only reason here that
    describes a defect rather than a difference."""

    UNKNOWN = "UNKNOWN"
    """The input was a bare URL list, which carries no status, indexability or
    content type. Nothing can be said about the URL beyond its absence from the
    crawl — it is not a missed page, and must not be read as one."""


class ExportFormat(StrEnum):
    """What kind of file the cross-check was run against.

    Recorded on the report rather than inferred from the reasons, because a
    bare list whose every URL the crawl already holds produces no `UNKNOWN`
    row at all — and the reader would otherwise take a set comparison with no
    status evidence for a full export that found nothing.
    """

    INTERNAL_HTML = "INTERNAL_HTML"
    """A Screaming Frog `Internal → HTML` export, with per-URL status."""

    BARE_URL_LIST = "BARE_URL_LIST"
    """One column of URLs and nothing else. Set comparison only; no merge."""


class NotAnExportError(ValueError):
    """The file parsed, but has no `Address` column.

    A subclass rather than a bare `ValueError` so `load_cross_check_input` can
    tell "wrong export tab" — where a bare list is worth trying — from "not a
    CSV at all" or "not a workbook", where it is not. The message is unchanged;
    only the type is narrower.
    """


class EngineGapReason(StrEnum):
    """Why this engine holds a URL Screaming Frog does not."""

    MALFORMED_MARKUP = "MALFORMED_MARKUP"
    """Built from broken HTML on the site. Not a URL at all."""

    REPEATED_SUFFIX_TRAP = "REPEATED_SUFFIX_TRAP"
    """One page reachable at many fabricated addresses, from a relative href
    resolved against every parent. Not pages, and this engine's own defect."""

    QUERY_VARIANT = "QUERY_VARIANT"
    """The same path carrying a query string Screaming Frog collapsed."""

    SITEMAP_ORPHAN = "SITEMAP_ORPHAN"
    """A real published page with no internal link pointing at it. A
    link-following crawler cannot see these; this is the finding."""

    PDF_FILE = "PDF_FILE"
    """A PDF. Screaming Frog lists documents under its own tab, so a set
    comparison against the HTML export always shows them as engine-only."""

    PRESENTATION_FILE = "PRESENTATION_FILE"
    """A slide deck: `.ppt`, `.pptx` and their relatives."""

    SPREADSHEET_FILE = "SPREADSHEET_FILE"
    """A workbook or CSV."""

    OTHER_FILE = "OTHER_FILE"
    """Any other non-HTML file: Word documents, archives, media."""


class DefaulterCategory(StrEnum):
    """Why a bare-list `UNKNOWN` row looks structurally junk rather than a page.

    A bare URL list carries no status, so `FrogGapReason.UNKNOWN` cannot say
    whether a row is a live page this engine missed or an address that was
    never a page at all. This is the second, narrower question asked only of
    that bucket: does the URL's own shape give it away as an AEM asset path, a
    leaked author path, or a malformed address? A member here is a positive
    claim; its absence (`None` on `UrlGap.defaulter_category`) is not a claim
    that a URL is real, only that it did not match one of these patterns — see
    `UrlGap.defaulter_category` for the residual it is left in.
    """

    DAM_HTML_ARCHIVE = "DAM_HTML_ARCHIVE"
    """An AEM DAM asset path (`/content/dam/.../investors/...`) ending in
    `.html`. infosys.com's investor-relations archive is filed here; it is a
    document store, not a navigable page."""

    DAM_FORMS_OTHER = "DAM_FORMS_OTHER"
    """The same DAM asset path shape, ending in `.html`, but outside the
    investors subtree: thumbnails, form fragments and other CMS-managed HTML
    that was never meant to be a page in its own right."""

    CMS_INTERNAL_LEAK = "CMS_INTERNAL_LEAK"
    """An AEM author/publish repository path (`/content/<site>/<lang>/...`)
    leaked into a public list instead of the vanity URL it publishes under."""

    CORRUPTED_URL = "CORRUPTED_URL"
    """Not a well-formed address at all: percent-encoded whitespace or quotes,
    a doubled extension, a doubled path separator, an embedded second URL, or
    literal whitespace in the path. Whatever produced the list built this
    entry wrong."""


class ScreamingFrogRow(StrictModel):
    """One row of a Screaming Frog `internal_html` export.

    Only the columns this reconciliation reads are modelled. The export carries
    145 of them, and parsing the rest would couple this module to a spreadsheet
    layout that changes between Screaming Frog versions.
    """

    address: str = Field(min_length=1)
    status_code: int = 0
    content_type: str = ""
    indexability: str = ""
    redirect_url: str = ""
    crawl_depth: int | None = None
    unique_inlinks: int = Field(default=0, ge=0)


class DefaulterValidation(StrictModel):
    """A Search Console second look at a bare-list defaulter row.

    Absent (`None` on `UrlGap.validation`) means never checked — distinct from
    checked and still junk, which is a populated `DefaulterValidation` with
    `flagged_real=False`. Never overwritten with a guess: every field here
    either came from a matched Search Console row or was not set at all.

    Attributes:
        checked_at: ISO timestamp of the check. Empty until one has run.
        gsc_impressions: Impressions Search Console reported for this exact
            URL, or `None` if never looked up.
        gsc_clicks: Clicks reported for the same URL, or `None` if never
            looked up.
        flagged_real: True when Search Console shows traffic for a URL this
            module classified as structurally junk — the one signal strong
            enough to contradict a pattern match instead of merely confirming
            the absence the pattern already implied.
    """

    checked_at: str = ""
    gsc_impressions: int | None = None
    gsc_clicks: int | None = None
    flagged_real: bool = False


class UrlGap(StrictModel):
    """One URL that appears on a single side, and why.

    Attributes:
        url: The address as its own tool reported it, *not* normalised — an
            analyst pastes this into a browser.
        reason: The single rule that explains it.
        defaulter_category: Set only for a bare-list `UNKNOWN` row whose
            address matched a structurally-junk pattern (see
            `DefaulterCategory`). `None` for every other row, and also for a
            bare-list `UNKNOWN` row that matched no pattern — that residual is
            presumed real, not verified, and is reported as such rather than
            invented a category to fill.
        validation: A Search Console re-check of a defaulter row, or `None`
            if none has run yet.
    """

    url: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    defaulter_category: DefaulterCategory | None = None
    validation: DefaulterValidation | None = None


class ReconciliationReport(StrictModel):
    """What the two crawlers agree and disagree about.

    Attributes:
        base_url: The crawl root both sides are measured against.
        frog_rows: Rows read from the export.
        frog_live: Rows with a 200 status.
        engine_urls: Distinct URLs in the crawl result.
        in_both: URLs present on both sides after normalisation.
        in_both_urls: The addresses behind `in_both`, in the engine's own
            spelling. Kept because the count alone cannot be handed to anyone:
            an analyst asking "which 7,078 did we agree on?" had no answer, and
            the intersection was computed and thrown away on the next line.
            The engine's spelling rather than Screaming Frog's, so these join
            against the crawl result without re-normalising.
        frog_only: URLs Screaming Frog holds alone, each with a reason.
        engine_only: URLs this engine holds alone, each with a reason.
        frog_reasons: Counts per `FrogGapReason`, summing to `len(frog_only)`.
        engine_reasons: Counts per `EngineGapReason`, summing to
            `len(engine_only)`.
        source_format: What the other side of the comparison was. A bare list
            makes `frog_only` a list of unknowns and `missed_pages` empty by
            construction, and the summary must say so rather than let a zero
            read as "nothing missed".
    """

    base_url: str = Field(min_length=1)
    frog_rows: int = Field(default=0, ge=0)
    frog_live: int = Field(default=0, ge=0)
    engine_urls: int = Field(default=0, ge=0)
    in_both: int = Field(default=0, ge=0)
    in_both_urls: tuple[str, ...] = ()
    frog_only: tuple[UrlGap, ...] = ()
    engine_only: tuple[UrlGap, ...] = ()
    frog_reasons: dict[str, int] = Field(default_factory=dict)
    engine_reasons: dict[str, int] = Field(default_factory=dict)
    source_format: ExportFormat = ExportFormat.INTERNAL_HTML

    @property
    def missed_pages(self) -> tuple[str, ...]:
        """Live, in-scope pages this engine never found.

        The one figure in the report that is unambiguously a defect, and the one
        an analyst should read first.
        """
        return tuple(gap.url for gap in self.frog_only if gap.reason == FrogGapReason.MISSED_PAGE)

    @property
    def orphans(self) -> tuple[str, ...]:
        """Published pages no internal link reaches, which only this engine sees."""
        return tuple(
            gap.url for gap in self.engine_only if gap.reason == EngineGapReason.SITEMAP_ORPHAN
        )


def normalise(url: str) -> str:
    """Reduce a URL to a form both crawlers can be compared on.

    Host lowercased and `www.` folded, scheme forced to https, trailing slash
    dropped, fragment dropped — differences neither tool means anything by.

    The query is **kept**. `?page=2` is a distinct URL to a search engine and to
    both crawlers, and folding it would hide a real difference in what each tool
    chose to crawl rather than reveal one.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, parts.query, ""))


def _as_int(value: str | None) -> int:
    """Read a spreadsheet cell that should be a number and often is not."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def load_screaming_frog_csv(text: str) -> tuple[ScreamingFrogRow, ...]:
    """Read an `internal_html.csv` export.

    Columns are looked up by header name rather than position: the export
    carries 145 of them and reorders between versions, so an index would break
    on upgrade in a way that produces wrong numbers rather than an error.

    Args:
        text: The CSV file's contents.

    Returns:
        One row per address. Rows with no address are dropped — Screaming Frog
        exports end with blank lines.
    """
    reader = csv.DictReader(io.StringIO(text))
    try:
        headers = reader.fieldnames or []
    except csv.Error as exc:  # pragma: no cover - defensive, same cause as below
        raise ValueError(_NOT_A_CSV) from exc
    if "Address" not in headers:
        raise NotAnExportError(
            "this file has no 'Address' column, so it is not a Screaming Frog "
            "Internal → HTML export. Export that tab as CSV and try again."
        )

    rows: list[ScreamingFrogRow] = []
    for record in _records(reader):
        address = (record.get("Address") or "").strip()
        if not address:
            continue
        depth = (record.get("Crawl Depth") or "").strip()
        rows.append(
            ScreamingFrogRow(
                address=address,
                status_code=_as_int(record.get("Status Code")),
                content_type=(record.get("Content Type") or "").strip(),
                indexability=(record.get("Indexability") or "").strip(),
                redirect_url=(record.get("Redirect URL") or "").strip(),
                crawl_depth=_as_int(depth) if depth else None,
                unique_inlinks=_as_int(record.get("Unique Inlinks")),
            )
        )
    _logger.info("screaming_frog_loaded", extra={"rows": len(rows)})
    return tuple(rows)


_NOT_A_CSV = (
    "this file is not a CSV. Screaming Frog also exports .xlsx, and a spreadsheet "
    "dropped here arrives as binary. Use Export → Internal → HTML and choose CSV."
)
"""Message for input the CSV reader cannot parse at all.

Worth naming the real mistake rather than repeating Python's. A user who has
just exported from Screaming Frog has both files in the same folder, and
`_csv.Error: new-line character seen in unquoted field` tells them nothing about
which one to pick. Dropping the `.xlsx` is the mistake this text exists for, and
it was made within a day of the feature shipping.
"""


def _records(reader: csv.DictReader[str]) -> Iterator[dict[str, str | None]]:
    """Yield rows, turning a parse failure into a message a person can act on.

    `csv.Error` is not a `ValueError`, so without this it escaped the API's
    `except ValueError` handler and became a 500. The browser was still
    uploading when the server gave up, so the connection reset mid-request and
    `fetch` rejected — the UI then reported "Cannot reach the engine. Is the API
    server running?" about a server that was running perfectly and had answered
    a moment earlier.
    """
    try:
        yield from reader
    except csv.Error as exc:
        raise ValueError(_NOT_A_CSV) from exc


_XLSX_MAGIC = b"PK"
"""ZIP local-file header, which is how an `.xlsx` starts.

Detection is by content, not by filename. The API receives a body with no name
attached, and a user who renames a spreadsheet to `.csv` should still get the
right answer rather than a parse error about carriage returns.

It identifies a **ZIP archive**, not specifically a spreadsheet — `.docx`,
`.pptx` and a plain `.zip` share it. Anything else that gets this far fails in
`openpyxl` and is reported as such, which is the honest outcome: the file really
is an archive, and it really is not a workbook.
"""

_NEEDS_OPENPYXL = (
    "this looks like an .xlsx file, but openpyxl is not installed. Install the "
    "'seo' extra (pip install -e .[seo]) or export the sheet as CSV instead."
)

_COLUMNS = (
    "Address",
    "Content Type",
    "Status Code",
    "Indexability",
    "Redirect URL",
    "Crawl Depth",
    "Unique Inlinks",
)
"""Columns read from a workbook. The export carries 145; these are the modelled ones."""


def _rows_from_xlsx(body: bytes) -> tuple[ScreamingFrogRow, ...]:
    """Read the first worksheet of a Screaming Frog `.xlsx` export.

    `read_only=True` keeps openpyxl from building a cell object graph for the
    whole sheet, which matters at 12,000 rows by 145 columns. It does **not**
    make the request streaming: the caller already holds the entire body in
    memory, because that is what reading an HTTP request gives you. The saving
    is openpyxl's own overhead, not the upload's.

    Header lookup is by name for the same reason the CSV path does it: Screaming
    Frog reorders columns between versions, and an index would keep working
    while silently reading the wrong ones.
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ValueError(_NEEDS_OPENPYXL) from exc

    try:
        book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises several unrelated types
        raise ValueError(
            "this file is a ZIP archive but not a readable Excel workbook. "
            "Export Internal → HTML from Screaming Frog as .xlsx or .csv."
        ) from exc

    try:
        sheet = book.active
        if sheet is None:
            raise ValueError("this workbook has no sheets.")
        stream = sheet.iter_rows(values_only=True)
        try:
            header = [str(cell).strip() if cell is not None else "" for cell in next(stream)]
        except StopIteration:
            raise ValueError("this workbook's first sheet is empty.") from None

        index = {name: header.index(name) for name in _COLUMNS if name in header}
        if "Address" not in index:
            raise NotAnExportError(
                "this sheet has no 'Address' column, so it is not a Screaming Frog "
                "Internal → HTML export."
            )

        def cell(values: tuple[object, ...], name: str) -> str:
            position = index.get(name)
            if position is None or position >= len(values) or values[position] is None:
                return ""
            return str(values[position]).strip()

        rows: list[ScreamingFrogRow] = []
        for values in stream:
            address = cell(values, "Address")
            if not address:
                continue
            depth = cell(values, "Crawl Depth")
            rows.append(
                ScreamingFrogRow(
                    address=address,
                    status_code=_as_int(cell(values, "Status Code")),
                    content_type=cell(values, "Content Type"),
                    indexability=cell(values, "Indexability"),
                    redirect_url=cell(values, "Redirect URL"),
                    crawl_depth=_as_int(depth) if depth else None,
                    unique_inlinks=_as_int(cell(values, "Unique Inlinks")),
                )
            )
    finally:
        # A read-only workbook holds the archive open; without this the handle
        # survives the request on Windows and the file cannot be replaced.
        book.close()

    _logger.info("screaming_frog_loaded", extra={"rows": len(rows), "format": "xlsx"})
    return tuple(rows)


def load_screaming_frog_export(body: bytes | str) -> tuple[ScreamingFrogRow, ...]:
    """Read a Screaming Frog export in whichever format it arrived.

    Screaming Frog writes `.csv` and `.xlsx` side by side into the same folder,
    and the spreadsheet is the one a person reaches for first — it opens on a
    double-click. Accepting only CSV meant the likelier file produced a parse
    failure, and for one upload it surfaced as "Is the API server running?".

    Args:
        body: Raw bytes from an upload, or text already decoded.

    Returns:
        One row per address.

    Raises:
        ValueError: If the payload is neither a readable workbook nor a CSV, or
            if it is a workbook and `openpyxl` is not installed.
    """
    if isinstance(body, str):
        return load_screaming_frog_csv(body)
    if body.startswith(_XLSX_MAGIC):
        return _rows_from_xlsx(body)
    # `utf-8-sig`: Screaming Frog writes a byte-order mark, and without this the
    # first header keeps an invisible prefix, never matches "Address", and the
    # whole export reconciles to nothing.
    return load_screaming_frog_csv(body.decode("utf-8-sig", errors="replace"))


class CrossCheckInput(StrictModel):
    """What a cross-check upload turned out to be, and the rows it holds.

    Attributes:
        rows: One row per URL. From a bare list every field but `address` is
            its default, which is the honest encoding of "the file did not say".
        source_format: Which of the two accepted shapes the file had. Carried
            to `reconcile` so the reasons and the merge gate can honour it.
    """

    rows: tuple[ScreamingFrogRow, ...] = ()
    source_format: ExportFormat = ExportFormat.INTERNAL_HTML


def load_cross_check_input(body: bytes | str) -> CrossCheckInput:
    """Read an `Internal → HTML` export, or failing that a bare URL list.

    The export is tried first and its refusal is kept for everything that is
    neither: a two-column sheet, a Search Console `Top pages` export, a file
    that is not a CSV at all. The bare-list reader is consulted only after the
    specific "no `Address` column" refusal, because that is the one case where
    the file may still be a usable list rather than the wrong export tab.

    Args:
        body: Raw bytes from an upload, or CSV text already decoded.

    Returns:
        The rows and which format they came from.

    Raises:
        ValueError: With the export loader's own message, when the file is
            neither an export nor a bare list.
    """
    try:
        return CrossCheckInput(rows=load_screaming_frog_export(body))
    except NotAnExportError:
        urls = bare_url_list(body)
        if urls is None:
            raise
    rows = tuple(ScreamingFrogRow(address=url) for url in urls)
    _logger.info("bare_url_list_loaded", extra={"rows": len(rows)})
    return CrossCheckInput(rows=rows, source_format=ExportFormat.BARE_URL_LIST)


def _frog_reason(row: ScreamingFrogRow, base_host: str) -> FrogGapReason:
    """Explain one Screaming Frog URL this engine lacks.

    Ordered, and the order is the argument. Scope is settled before status: a
    404 on a subdomain this engine never crawls is explained by the subdomain,
    not by the 404. Status is settled before content, because a redirect source
    has no content to judge. Only a URL that survives every earlier rule — in
    scope, live, a real page, indexable — is a miss.
    """
    parts = urlsplit(row.address)
    if site_host(parts.netloc) != base_host:
        return FrogGapReason.OFF_SITE
    if 300 <= row.status_code < 400:
        return FrogGapReason.REDIRECT
    if row.status_code >= 400 or row.status_code == 0:
        return FrogGapReason.CLIENT_ERROR
    if parts.path.lower().endswith(NON_PAGE_SUFFIXES):
        return FrogGapReason.MEDIA_URL
    if is_spider_trap(row.address):
        return FrogGapReason.SPIDER_TRAP
    if row.indexability and row.indexability.strip().lower() != "indexable":
        return FrogGapReason.NON_INDEXABLE
    return FrogGapReason.MISSED_PAGE


_CORRUPT_ENCODED_MARKERS = ("%20", "%22", "%27")
"""Percent-encoded space and quote characters. A hand-written or scraped link
does not carry one of these; a URL that does was assembled wrong upstream of
the list, not merely unlinked."""

_CORRUPT_DOUBLED_EXTENSIONS = (".html.html", ".htm.htm", ".html.htm", ".htm.html")
"""A page suffix appended twice — the signature of a resolver defaulting an
extension onto an address that already carried one."""

_DAM_PREFIX = "/content/dam/"
"""AEM's asset-repository path. A URL under it names a binary or fragment in
the CMS's own storage layout, not an address a visitor navigates to."""

_DAM_INVESTORS_SEGMENT = "investors"
"""The segment that separates infosys.com's investor-relations archive from
every other DAM export, immediately after `/content/dam/<site>/<lang>/`."""


def _is_corrupted_url(url: str) -> bool:
    """True when a URL is malformed rather than merely unlinked or absent.

    Checked before the DAM and CMS-leak rules: a broken address can also sit
    under `/content/dam/` or `/content/`, and "this address is not well-formed"
    explains it better than either — a path rule presumes the URL is at least
    a real path, which a malformed one is not.
    """
    if any(marker in url for marker in _CORRUPT_ENCODED_MARKERS):
        return True
    if any(ext in url for ext in _CORRUPT_DOUBLED_EXTENSIONS):
        return True
    parts = urlsplit(url)
    # `urlsplit` already separates the scheme's own `//`, so any `//` left in
    # the path is either a leading doubled separator or an internal one — both
    # covered by one check.
    if "//" in parts.path:
        return True
    if url.count("http") >= 2:
        return True
    return bool(re.search(r"^\s|\s$|\s{2}", parts.path))


def _dam_investors(path: str) -> bool:
    """True when a DAM path's segment after `<site>/<lang>/` is `investors`.

    infosys.com's investor-relations archive is filed in its own DAM subtree;
    every other DAM export under the same prefix is a thumbnail, a form
    fragment, or another asset with no equivalent analyst action.
    """
    tail = path.split(_DAM_PREFIX, 1)[1]
    segments = tail.split("/")
    return len(segments) >= 3 and segments[2] == _DAM_INVESTORS_SEGMENT


def _defaulter_category(url: str) -> DefaulterCategory | None:
    """Classify a bare-list `UNKNOWN` row as structurally junk, or leave it.

    Called only for `FrogGapReason.UNKNOWN` rows sourced from a bare URL
    list — the one bucket the module's own invariant says nothing can be
    proven about beyond absence from the crawl. A category here is a stronger
    claim than that invariant allows on its own, so it is made only where the
    URL's shape gives it away outright. Everything else is left `None`: the
    presumed-real residual, not a verified-live page and not junk either.

    Order matters and mirrors `_frog_reason`: corrupted is checked first
    because a malformed address can also happen to sit under `/content/dam/`
    or `/content/`, and DAM is checked before the general CMS-leak rule
    because every DAM path is also a `/content/` path.
    """
    if _is_corrupted_url(url):
        return DefaulterCategory.CORRUPTED_URL
    path = urlsplit(url).path.lower()
    if _DAM_PREFIX in path and path.endswith((".html", ".htm")):
        return (
            DefaulterCategory.DAM_HTML_ARCHIVE
            if _dam_investors(path)
            else DefaulterCategory.DAM_FORMS_OTHER
        )
    if "/content/" in path and _DAM_PREFIX not in path:
        return DefaulterCategory.CMS_INTERNAL_LEAK
    return None


def _repeated_tails(urls: list[str]) -> set[str]:
    """Path tails repeating often enough to be a relative-href loop.

    Counted across the whole set because a single URL cannot show this: every
    fabricated address is individually well-formed, with no repeated segment
    inside it. The loop is visible only as one tail appearing under many
    unrelated parents, which is exactly why the per-URL trap rules miss it.
    """
    tails: Counter[str] = Counter()
    for url in urls:
        segments = [s for s in urlsplit(url).path.split("/") if s]
        if len(segments) >= _TAIL_SEGMENTS:
            tails["/".join(segments[-_TAIL_SEGMENTS:])] += 1
    return {tail for tail, count in tails.items() if count >= MIN_TAIL_REPEATS}


def _engine_reason(url: str, loops: set[str]) -> EngineGapReason:
    """Explain one engine URL Screaming Frog lacks.

    Malformed markup is tested first: a broken address can also carry a query
    string or a repeating tail, and "this is not a URL" explains it better than
    either. A repeating tail is tested before the file suffix because a
    fabricated address is not a file whatever it ends in. The file suffix is
    tested before the query string because `report.pdf?page=2` is a PDF that
    happens to carry a parameter, not an HTML page whose pagination Screaming
    Frog collapsed; the file type is the fact an analyst acts on. Only the
    path is judged, lowercased, so `REPORT.PDF` and `deck.pptx#slide=3` land
    where their lowercase, fragment-free spellings do.
    """
    if any(marker in url for marker in _MALFORMED_MARKERS):
        return EngineGapReason.MALFORMED_MARKUP
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) >= _TAIL_SEGMENTS and "/".join(segments[-_TAIL_SEGMENTS:]) in loops:
        return EngineGapReason.REPEATED_SUFFIX_TRAP
    path = parts.path.lower()
    if path.endswith(_PDF_SUFFIXES):
        return EngineGapReason.PDF_FILE
    if path.endswith(_PRESENTATION_SUFFIXES):
        return EngineGapReason.PRESENTATION_FILE
    if path.endswith(_SPREADSHEET_SUFFIXES):
        return EngineGapReason.SPREADSHEET_FILE
    if path.endswith(_OTHER_FILE_SUFFIXES):
        return EngineGapReason.OTHER_FILE
    if parts.query:
        return EngineGapReason.QUERY_VARIANT
    return EngineGapReason.SITEMAP_ORPHAN


def reconcile(
    base_url: str,
    engine_urls: tuple[str, ...],
    frog_rows: tuple[ScreamingFrogRow, ...],
    source_format: ExportFormat = ExportFormat.INTERNAL_HTML,
) -> ReconciliationReport:
    """Compare a crawl result against a Screaming Frog export or a URL list.

    Args:
        base_url: The crawl root. Its host decides what counts as in scope.
        engine_urls: Every URL in the crawl result.
        frog_rows: Rows from `load_screaming_frog_csv`.
        source_format: What the rows came from. For a bare list every URL the
            crawl lacks is `UNKNOWN`: the file has no status to judge it on,
            and a rule that still called it a missed page would be inventing
            evidence.

    Returns:
        The full reconciliation, every disagreement carrying exactly one reason
        so the buckets sum to the totals.
    """
    base_host = site_host(urlsplit(base_url).netloc)

    frog_by_key = {normalise(row.address): row for row in frog_rows}
    engine_by_key = {normalise(url): url for url in engine_urls}

    frog_only_keys = frog_by_key.keys() - engine_by_key.keys()
    engine_only_keys = engine_by_key.keys() - frog_by_key.keys()

    bare = source_format is ExportFormat.BARE_URL_LIST
    frog_only = tuple(
        UrlGap(
            url=frog_by_key[key].address,
            reason=(
                FrogGapReason.UNKNOWN if bare else _frog_reason(frog_by_key[key], base_host)
            ).value,
            defaulter_category=_defaulter_category(frog_by_key[key].address) if bare else None,
        )
        for key in sorted(frog_only_keys)
    )

    loops = _repeated_tails([engine_by_key[key] for key in engine_only_keys])
    engine_only = tuple(
        UrlGap(url=engine_by_key[key], reason=_engine_reason(engine_by_key[key], loops).value)
        for key in sorted(engine_only_keys)
    )

    # Sorted so the list is stable between two runs over the same pair of
    # inputs; a set's iteration order is not, and an export that reorders itself
    # for no reason cannot be diffed against last week's.
    shared_keys = sorted(frog_by_key.keys() & engine_by_key.keys())

    report = ReconciliationReport(
        base_url=base_url,
        frog_rows=len(frog_rows),
        frog_live=sum(1 for row in frog_rows if row.status_code == 200),
        engine_urls=len(engine_by_key),
        in_both=len(shared_keys),
        in_both_urls=tuple(engine_by_key[key] for key in shared_keys),
        frog_only=frog_only,
        engine_only=engine_only,
        frog_reasons=dict(Counter(gap.reason for gap in frog_only)),
        engine_reasons=dict(Counter(gap.reason for gap in engine_only)),
        source_format=source_format,
    )
    _logger.info(
        "reconciled",
        extra={
            "base_url": base_url,
            "source_format": source_format.value,
            "in_both": report.in_both,
            "missed": len(report.missed_pages),
            "orphans": len(report.orphans),
        },
    )
    return report


class MissedPageStatus(StrEnum):
    """What a live check found at a URL the export called a missed page."""

    LIVE = "LIVE"
    """Still a page, and still absent from the crawl. A genuine miss."""

    REDIRECTED = "REDIRECTED"
    """Moved since the export was taken. Not a page."""

    GONE = "GONE"
    """4xx or 5xx now. Not a page."""

    UNREACHABLE = "UNREACHABLE"
    """The check itself failed. Unknown, and must not be counted either way."""


class MissedPageCheck(StrictModel):
    """One verified URL from the `MISSED_PAGE` bucket.

    Attributes:
        url: The address as Screaming Frog reported it.
        status: What the live check found.
        http_status: The code returned, or 0 if the check failed.
        destination: Where a redirect points, empty otherwise.
        destination_held: Whether the crawl already holds that destination. When
            true the "miss" is the same page under its old address.
    """

    url: str = Field(min_length=1)
    status: str = Field(min_length=1)
    http_status: int = Field(default=0, ge=0)
    destination: str = ""
    destination_held: bool = False


def verify_missed_pages(
    report: ReconciliationReport,
    engine_urls: tuple[str, ...],
    probe: Callable[[str], tuple[int, str]],
) -> tuple[MissedPageCheck, ...]:
    """Check the `MISSED_PAGE` bucket against the live site.

    Why this is not optional in practice
    ------------------------------------
    The bucket is the only reason in the report that accuses this engine of a
    defect, and it is derived from two snapshots taken at different times. A site
    that reorganises between them manufactures misses out of nothing.

    Measured on highradius.com, that is most of the bucket. A 60-URL random
    sample of its 892 came back **50 redirects and 10 live pages**, and 38 of the
    redirects pointed at URLs the crawl already held: the site had moved
    `/value-creation/` under `/resources/value-creation/` after the export was
    captured. Acting on the unverified number would have meant building crawler
    reach for roughly 750 pages that no longer exist.

    Screaming Frog is not at fault and neither is the reconciliation. Both are
    correct about the moment they describe; only the live site knows which
    moment is now.

    The probe is injected rather than made here, because this module must not
    open sockets — outbound HTTP belongs behind `BaseAPIClient`. The caller
    supplies something that performs one request **without following
    redirects**: following them would report the destination's 200 and reproduce
    the exact confusion this exists to resolve.

    Args:
        report: A reconciliation whose `missed_pages` should be checked.
        engine_urls: Every URL in the crawl, to recognise a redirect that lands
            somewhere already held.
        probe: Given a URL, returns `(status_code, location_header)`. Should
            return `(0, "")` when the request fails rather than raising.

    Returns:
        One check per URL in the bucket, in the same order.
    """
    held = {normalise(url) for url in engine_urls}
    checks: list[MissedPageCheck] = []

    for url in report.missed_pages:
        code, location = probe(url)
        if code == 0:
            status = MissedPageStatus.UNREACHABLE
        elif 300 <= code < 400:
            status = MissedPageStatus.REDIRECTED
        elif code >= 400:
            status = MissedPageStatus.GONE
        else:
            status = MissedPageStatus.LIVE
        checks.append(
            MissedPageCheck(
                url=url,
                status=status.value,
                http_status=code,
                destination=location,
                destination_held=bool(location) and normalise(location) in held,
            )
        )

    surviving = sum(1 for check in checks if check.status == MissedPageStatus.LIVE)
    _logger.info(
        "missed_pages_verified",
        extra={"checked": len(checks), "still_live": surviving},
    )
    return tuple(checks)


def _as_count(value: object) -> int:
    """Read a Search Console metric out of a loosely-typed sidecar row.

    Distinct from `_as_int`: that one reads a spreadsheet cell (`str | None`).
    This reads a value already unpacked from JSON or built in-process, so it
    may already be an `int` — and mypy strict cannot narrow `object` to `int`
    on its own, so the cast happens through `str` on any other input.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def revalidate_defaulters(
    saved: Mapping[str, object], unmatched_rows: Sequence[Mapping[str, object]]
) -> Mapping[str, object] | None:
    """Re-check bare-list `UNKNOWN` rows against a newly attached GSC export.

    Why this exists
    ----------------
    A defaulter category is a pattern match on a URL's shape, made without
    fetching it — this module opens no sockets, by the same rule that keeps
    `verify_missed_pages`'s probe injected rather than built in. Search
    Console is not a live fetch either, but it is independent evidence: a URL
    Google shows impressions or clicks for in the last 16 months was live and
    was requested, whatever its path looks like. That is strong enough to flag
    a pattern match as worth a second look without claiming to have re-crawled
    anything.

    The lookup this reuses (`unresolved_gsc` rows reasoned `not_crawled`) is
    already exactly the right shape: an address Search Console reported that
    this engine's own crawl never reached. A bare-list defaulter row is the
    same fact from the other direction — a URL a list held that this crawl
    never reached — so the two sets are answering the same question and the
    join needs no new machinery.

    Args:
        saved: A job's saved reconciliation sidecar, as `state_store` returns
            it — the same mapping `write_reconciliation` wrote.
        unmatched_rows: The Search Console rows this crawl never resolved to a
            page, in the shape the performance sidecar already stores them
            (`url`, `clicks`, `impressions`, `reason`). Only rows reasoned
            `"not_crawled"` are eligible: the other reasons (`off_site`,
            `ambiguous`, `unparseable`, `other_subdomain`) do not mean "on this
            site but absent from the crawl", which is the one fact a bare-list
            defaulter row needs corroborated.

    Returns:
        An updated copy of `saved` with `DefaulterValidation` attached to
        every matched `frog_only` row, or `None` when there is nothing to
        write — no saved reconciliation, no bare-list `UNKNOWN` rows in it, or
        none of them matched an eligible Search Console row. `None` is a
        no-op instruction to the caller, never a signal to raise.
    """
    frog_only = saved.get("frog_only")
    if not isinstance(frog_only, list) or not frog_only:
        return None

    lookup = {
        normalise(str(row.get("url", ""))): row
        for row in unmatched_rows
        if row.get("reason") == "not_crawled"
    }
    if not lookup:
        return None

    checked_at = datetime.now(UTC).isoformat()
    updated_rows: list[object] = []
    updated_count = 0
    for raw in frog_only:
        if not isinstance(raw, Mapping):
            updated_rows.append(raw)
            continue
        gap = UrlGap.model_validate(raw)
        eligible = gap.reason == FrogGapReason.UNKNOWN.value
        match = lookup.get(normalise(gap.url)) if eligible else None
        if match is None:
            updated_rows.append(dict(raw))
            continue
        impressions = _as_count(match.get("impressions"))
        clicks = _as_count(match.get("clicks"))
        gap = gap.model_copy(
            update={
                "validation": DefaulterValidation(
                    checked_at=checked_at,
                    gsc_impressions=impressions,
                    gsc_clicks=clicks,
                    flagged_real=impressions > 0 or clicks > 0,
                )
            }
        )
        updated_rows.append(gap.model_dump(mode="json"))
        updated_count += 1

    if not updated_count:
        return None

    result = dict(saved)
    result["frog_only"] = updated_rows
    _logger.info(
        "defaulters_revalidated",
        extra={"eligible": len(lookup), "updated": updated_count},
    )
    return result
