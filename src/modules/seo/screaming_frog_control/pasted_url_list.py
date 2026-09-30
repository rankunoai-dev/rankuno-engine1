"""Read a block of text an operator pasted into the URLs a list crawl will fetch.

The sibling of `url_list.py`'s crawl-sourced path, and deliberately *only* the
front of it. Everything after "these are the URLs" — dedupe, scheme filter,
registrable-domain filter, per-host SSRF validation, the ceiling, the render
and the digest — is `build_url_list`'s, unchanged. This module owns one
question: **which lines of that text are web addresses, and which are not.**

Why a separate module and not a parameter
-----------------------------------------
`url_list.py` receives URLs a crawl already produced: strings this engine
itself built and normalised. A paste is human input from a spreadsheet, and
the failure modes are entirely different — a header row, a quoted cell, a
tab-separated fragment, a missing scheme. Mixing the two would put
spreadsheet heuristics inside the module whose whole job is to be the boring,
auditable filter between a crawl and an external binary.

What is accepted, and how loudly
--------------------------------
Three tiers, because "silently fixed", "fixed and said so" and "refused" are
three different promises to an operator approving a count:

* **Silent.** Leading and trailing whitespace, blank lines anywhere, a UTF-8
  BOM, any line ending, and surrounding quotes. None of these change which
  page gets crawled, so reporting them would be noise in the one place an
  operator has to read carefully.
* **Counted and reported.** A spreadsheet row (the first cell that is a web
  address is used, the rest of the row discarded) and a missing scheme
  (`https://` is assumed). Both change what is fetched, so both are numbers
  the preview shows before anyone approves anything.
* **Refused, per line.** Anything with no readable host, and any non-web
  scheme — `mailto:`, `tel:`, `javascript:`. Refused individually and
  counted, never a reason to reject the whole paste: a 400-line paste with
  one stray heading in the middle is an ordinary paste, and refusing it
  outright would send the operator back to a spreadsheet to hunt for a line
  this code already found. The *whole* paste is refused only when nothing at
  all could be read from it, which `EmptyUrlListError` already says.

A missing scheme becomes `https://`, never `http://`. The assumption is
visible in `PasteCounts.scheme_added` and in the sample the approval shows,
so an operator auditing an http-only site can see it was made and fix the
paste. Guessing `http://` instead would silently downgrade every request on a
site that has TLS, which is the worse error of the two.
"""

from __future__ import annotations

import re

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import registrable_domain, safe_split, site_host

__all__ = [
    "MALFORMED_EXAMPLES",
    "MAX_PASTE_CHARS",
    "ParsedPaste",
    "PasteCounts",
    "PastedDomain",
    "PastedUrlPlan",
    "parse_pasted_urls",
    "plan_pasted_urls",
]

_logger = get_logger(__name__)

MAX_PASTE_CHARS = 2_000_000
"""Hard ceiling on the size of one pasted block, in characters.

Not the operator-facing limit — that is `SCREAMING_FROG_URL_LIST_MAX_URLS`,
enforced by `UrlListTooLargeError` with an explanation. This is the cruder
guard that has to come first, because the URL ceiling can only be applied
after the text has been parsed, and parsing is what an unbounded body would
make expensive. 10,000 URLs at 200 characters each is 2 MB, so a paste that
could legitimately be dispatched always fits with room to spare."""

MALFORMED_EXAMPLES = 5
"""How many unreadable lines are quoted back, with their line numbers.

A bare count ("12 lines could not be read") tells an operator there is a
problem and nothing about where. Five examples with line numbers is enough to
recognise the shape of the mistake — a stray heading, a column of page titles
— without turning a summary into a log file."""

_HEADER_WORDS = frozenset(
    {"address", "addresses", "domain", "domains", "href", "link", "links", "uri", "url", "urls"}
)
"""First-line cell values treated as a spreadsheet header rather than an error.

Exact matches only, lower-cased. None of these is a readable address, so
without this they would be counted as malformed and an operator who pasted a
column *including* its heading would be told their list has an error in it.
Only the first non-blank line is tested: a row reading `url` halfway down a
list really is a mistake, and calling it a header would hide it."""

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
"""Does this line already declare a scheme? Asked before `https://` is
prepended, so `mailto:someone@example.com` is refused as a non-web scheme
rather than mangled into `https://mailto:someone@example.com` — which would
parse, pass every later filter as a path, and be dispatched."""

_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?\.)+(?:[A-Za-z]{2,63}|[0-9]{1,3})$"
)
"""What a schemeless line's first segment must look like to be a host.

At least one dot and a plausible final label. This is the test that keeps
`Page Title`, `404`, and a column of numbers out of the list: they become
`https://Page Title` otherwise, and a URL that only fails later is a URL the
operator was told nothing about. The numeric alternative admits an IPv4
literal, which is a real if rare paste; it is not endorsed here, merely read —
`UrlSafetyPolicy` is what decides whether an address may be fetched."""

_CELL_SEPARATORS = ("\t", ",", ";")
"""Tried in order on a line that is not itself an address.

Tab first: a paste from a spreadsheet is tab-separated, and a URL containing
a comma (a query string routinely does) would be cut in half by trying the
comma first. Semicolon last, for the European CSV dialect Excel writes when
the locale's decimal separator is a comma."""


class PasteCounts(StrictModel):
    """What reading the text did, so the preview can say so before approval.

    Covers parsing only. Deduplication, the off-domain filter and the SSRF
    check happen afterwards in `build_url_list` and are reported by
    `UrlListCounts`, which has its own reconciliation identity. Two models
    rather than one because they answer different questions — "what did I
    paste" and "what survived the filters" — and because merging them would
    break the identity a test already pins on the second.

    The identity here is `lines - blank_dropped - header_dropped -
    malformed_dropped == accepted`, and a test pins it. `spreadsheet_rows`
    and `scheme_added` are *annotations on accepted lines*, not drops, and
    are deliberately outside that sum.

    Attributes:
        lines: Every line the text held, blank ones included.
        blank_dropped: Lines that were empty or only whitespace.
        header_dropped: A leading spreadsheet header row. At most one.
        malformed_dropped: Lines with no readable web address.
        accepted: Lines that yielded a URL.
        spreadsheet_rows: Accepted lines where the address came from one cell
            of a wider row, the rest of which was discarded.
        scheme_added: Accepted lines that had no scheme and were given
            `https://`.
        malformed_examples: Up to `MALFORMED_EXAMPLES` unreadable lines,
            quoted with their line numbers. Operator-supplied text — a caller
            rendering these must treat them as data, never as markup.
    """

    lines: int = Field(ge=0)
    blank_dropped: int = Field(default=0, ge=0)
    header_dropped: int = Field(default=0, ge=0)
    malformed_dropped: int = Field(default=0, ge=0)
    accepted: int = Field(default=0, ge=0)
    spreadsheet_rows: int = Field(default=0, ge=0)
    scheme_added: int = Field(default=0, ge=0)
    malformed_examples: tuple[str, ...] = ()


class ParsedPaste(StrictModel):
    """The URLs read out of a paste, and the account of how they were read."""

    urls: tuple[str, ...] = ()
    counts: PasteCounts


class PastedDomain(StrictModel):
    """One registrable domain a paste covers, and how much of it.

    Attributes:
        registrable_domain: What the URLs of this group share. The same rule
            `build_url_list` filters on, so choosing a group here and sending
            it as the dispatch's `seed_url` cannot disagree with the list.
        url_count: How many parsed URLs fall in it — a **candidate** count,
            before deduplication and the SSRF check, exactly like
            `UrlListSourceOption.candidate_url_count`. The preview reports
            the truthful post-filter number and is the only number an
            approval ever shows.
        suggested_seed_url: An address in this group to seed the dispatch
            with — its own scheme and host, no path. A list run does not
            spider from the seed; it is what names the site on the job
            record and what the list is filtered against.
    """

    registrable_domain: str = Field(min_length=1, max_length=253)
    url_count: int = Field(ge=1)
    suggested_seed_url: str = Field(min_length=1, max_length=2048)


class PastedUrlPlan(StrictModel):
    """What a paste would produce, offered before anything is generated.

    The paste-mode counterpart of `GET /jobs/{id}/url-list/sources`, and for
    the same reason: a dispatch form must never offer a choice that would
    fail, and it cannot work out on its own which site a block of text is
    about. Nothing is stored and no digest is minted — this is a reading of
    the text, not an approvable artifact. The bytes are still frozen at
    preview time (ADR 0023).

    Attributes:
        counts: The parse account, for the "12 lines could not be read" note.
        domains: Every registrable domain present, largest group first. More
            than one entry is the case the operator has to resolve, because
            only one domain's URLs can be in scope for one crawl.
        suggested_seed_url: The largest group's suggestion, or `""` when
            nothing was readable. A default, never a decision — the operator
            can pick another group or type an address of their own.
        max_urls: The server's list ceiling, so a form never hardcodes it.
        exceeds_ceiling: Whether the largest group alone is already over
            `max_urls`. Surfaced here so the refusal is visible before the
            operator commits, rather than as a 422 after they press Preview.
    """

    counts: PasteCounts
    domains: tuple[PastedDomain, ...] = ()
    suggested_seed_url: str = Field(default="", max_length=2048)
    max_urls: int = Field(ge=1)
    exceeds_ceiling: bool = False


def _unquote(cell: str) -> str:
    """Strip matched surrounding quotes and the CSV doubling inside them.

    A spreadsheet writes `"https://example.com/a,b"` for a cell containing a
    comma, and Excel writes `""` for a literal quote inside one. Both are
    formatting, not part of the address.
    """
    text = cell.strip()
    for quote in ('"', "'"):
        if len(text) >= 2 and text.startswith(quote) and text.endswith(quote):
            text = text[1:-1].replace(quote * 2, quote)
            break
    return text.strip()


def _coerce(cell: str) -> tuple[str, bool] | None:
    """Read one cell as a web address.

    Returns:
        The URL and whether a scheme had to be added, or `None` when the cell
        is not a web address at all. `None` covers both "no host here" and
        "a scheme this crawler must never follow", which are the same outcome
        for the operator — the line is not dispatched — and are counted
        together for that reason.
    """
    text = _unquote(cell)
    if not text or any(char.isspace() for char in text):
        # Whitespace inside is the tell for prose: a page title, a note, a
        # sentence. A real URL that contains a space has already been
        # percent-encoded by whatever produced it.
        return None
    if text.startswith("//"):
        # Protocol-relative, as copied out of page source. The host is there;
        # only the scheme is missing, which is exactly the schemeless case.
        text = text[2:]
    if _SCHEME_RE.match(text):
        parts = safe_split(text)
        if parts is None or parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            return None
        return text, False
    host = re.split(r"[/?#]", text, maxsplit=1)[0].rsplit(":", 1)[0]
    if not _HOST_RE.match(host):
        return None
    return f"https://{text}", True


def _read_line(text: str) -> tuple[str, bool, bool] | None:
    """Read one whole line: the URL, whether a scheme was added, whether it was a row.

    The line is tried whole before it is split, so a URL containing a comma
    survives. Only when the whole line is not an address is it treated as a
    spreadsheet row and its cells tried in turn, first address wins.
    """
    whole = _coerce(text)
    if whole is not None:
        return whole[0], whole[1], False
    for separator in _CELL_SEPARATORS:
        if separator not in text:
            continue
        for cell in text.split(separator):
            found = _coerce(cell)
            if found is not None:
                return found[0], found[1], True
    return None


def parse_pasted_urls(text: str) -> ParsedPaste:
    """Read pasted text into URLs, counting every decision made on the way.

    Order is not changed and duplicates are not removed: both belong to
    `build_url_list`, which reports the deduplication in `UrlListCounts` and
    keeps first occurrence. Doing it twice would produce two numbers for one
    fact.

    Args:
        text: Exactly what the operator pasted, newlines and all.

    Returns:
        The URLs in paste order, and the parse account.
    """
    lines = text.lstrip("﻿").splitlines()
    urls: list[str] = []
    examples: list[str] = []
    blank = header = malformed = rows = schemed = 0
    seen_content = False

    for number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            blank += 1
            continue
        if not seen_content and _unquote(stripped).lower() in _HEADER_WORDS:
            seen_content = True
            header += 1
            continue
        seen_content = True
        read = _read_line(stripped)
        if read is None:
            malformed += 1
            if len(examples) < MALFORMED_EXAMPLES:
                examples.append(f"line {number}: {stripped[:80]}")
            continue
        url, added_scheme, from_row = read
        urls.append(url)
        schemed += int(added_scheme)
        rows += int(from_row)

    counts = PasteCounts(
        lines=len(lines),
        blank_dropped=blank,
        header_dropped=header,
        malformed_dropped=malformed,
        accepted=len(urls),
        spreadsheet_rows=rows,
        scheme_added=schemed,
        malformed_examples=tuple(examples),
    )
    _logger.info(
        "sf_paste_parsed",
        extra={
            "lines": counts.lines,
            "accepted": counts.accepted,
            "malformed_dropped": counts.malformed_dropped,
        },
    )
    return ParsedPaste(urls=tuple(urls), counts=counts)


def _group_by_domain(urls: tuple[str, ...]) -> tuple[PastedDomain, ...]:
    """Group parsed URLs by registrable domain, largest group first.

    Ties break alphabetically so the offered order is stable across two
    identical pastes — an operator re-checking a list must not see the
    pre-selected domain move.
    """
    tally: dict[str, int] = {}
    seeds: dict[str, str] = {}
    for url in urls:
        parts = safe_split(url)
        if parts is None or not parts.netloc:
            continue
        domain = registrable_domain(site_host(parts.netloc))
        if not domain:
            continue
        tally[domain] = tally.get(domain, 0) + 1
        seeds.setdefault(domain, f"{parts.scheme.lower()}://{parts.netloc}/")
    ordered = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        PastedDomain(registrable_domain=domain, url_count=count, suggested_seed_url=seeds[domain])
        for domain, count in ordered
    )


def plan_pasted_urls(text: str, *, max_urls: int) -> PastedUrlPlan:
    """Read a paste and report what it would crawl, without generating anything.

    Args:
        text: Exactly what the operator pasted.
        max_urls: The server's ceiling, echoed so a form never hardcodes it.

    Returns:
        The parse account, the domains found, and the suggested seed URL.
    """
    parsed = parse_pasted_urls(text)
    domains = _group_by_domain(parsed.urls)
    largest = domains[0] if domains else None
    return PastedUrlPlan(
        counts=parsed.counts,
        domains=domains,
        suggested_seed_url="" if largest is None else largest.suggested_seed_url,
        max_urls=max_urls,
        exceeds_ceiling=largest is not None and largest.url_count > max_urls,
    )
