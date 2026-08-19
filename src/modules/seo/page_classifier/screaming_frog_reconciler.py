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
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import (
    NON_PAGE_SUFFIXES,
    is_spider_trap,
    site_host,
)

__all__ = [
    "MIN_TAIL_REPEATS",
    "EngineGapReason",
    "FrogGapReason",
    "ReconciliationReport",
    "ScreamingFrogRow",
    "UrlGap",
    "load_screaming_frog_csv",
    "normalise",
    "reconcile",
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


class UrlGap(StrictModel):
    """One URL that appears on a single side, and why.

    Attributes:
        url: The address as its own tool reported it, *not* normalised — an
            analyst pastes this into a browser.
        reason: The single rule that explains it.
    """

    url: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ReconciliationReport(StrictModel):
    """What the two crawlers agree and disagree about.

    Attributes:
        base_url: The crawl root both sides are measured against.
        frog_rows: Rows read from the export.
        frog_live: Rows with a 200 status.
        engine_urls: Distinct URLs in the crawl result.
        in_both: URLs present on both sides after normalisation.
        frog_only: URLs Screaming Frog holds alone, each with a reason.
        engine_only: URLs this engine holds alone, each with a reason.
        frog_reasons: Counts per `FrogGapReason`, summing to `len(frog_only)`.
        engine_reasons: Counts per `EngineGapReason`, summing to
            `len(engine_only)`.
    """

    base_url: str = Field(min_length=1)
    frog_rows: int = Field(default=0, ge=0)
    frog_live: int = Field(default=0, ge=0)
    engine_urls: int = Field(default=0, ge=0)
    in_both: int = Field(default=0, ge=0)
    frog_only: tuple[UrlGap, ...] = ()
    engine_only: tuple[UrlGap, ...] = ()
    frog_reasons: dict[str, int] = Field(default_factory=dict)
    engine_reasons: dict[str, int] = Field(default_factory=dict)

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
    rows: list[ScreamingFrogRow] = []
    for record in reader:
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
    either.
    """
    if any(marker in url for marker in _MALFORMED_MARKERS):
        return EngineGapReason.MALFORMED_MARKUP
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) >= _TAIL_SEGMENTS and "/".join(segments[-_TAIL_SEGMENTS:]) in loops:
        return EngineGapReason.REPEATED_SUFFIX_TRAP
    if parts.query:
        return EngineGapReason.QUERY_VARIANT
    return EngineGapReason.SITEMAP_ORPHAN


def reconcile(
    base_url: str,
    engine_urls: tuple[str, ...],
    frog_rows: tuple[ScreamingFrogRow, ...],
) -> ReconciliationReport:
    """Compare a crawl result against a Screaming Frog export.

    Args:
        base_url: The crawl root. Its host decides what counts as in scope.
        engine_urls: Every URL in the crawl result.
        frog_rows: Rows from `load_screaming_frog_csv`.

    Returns:
        The full reconciliation, every disagreement carrying exactly one reason
        so the buckets sum to the totals.
    """
    base_host = site_host(urlsplit(base_url).netloc)

    frog_by_key = {normalise(row.address): row for row in frog_rows}
    engine_by_key = {normalise(url): url for url in engine_urls}

    frog_only_keys = frog_by_key.keys() - engine_by_key.keys()
    engine_only_keys = engine_by_key.keys() - frog_by_key.keys()

    frog_only = tuple(
        UrlGap(
            url=frog_by_key[key].address,
            reason=_frog_reason(frog_by_key[key], base_host).value,
        )
        for key in sorted(frog_only_keys)
    )

    loops = _repeated_tails([engine_by_key[key] for key in engine_only_keys])
    engine_only = tuple(
        UrlGap(url=engine_by_key[key], reason=_engine_reason(engine_by_key[key], loops).value)
        for key in sorted(engine_only_keys)
    )

    report = ReconciliationReport(
        base_url=base_url,
        frog_rows=len(frog_rows),
        frog_live=sum(1 for row in frog_rows if row.status_code == 200),
        engine_urls=len(engine_by_key),
        in_both=len(frog_by_key.keys() & engine_by_key.keys()),
        frog_only=frog_only,
        engine_only=engine_only,
        frog_reasons=dict(Counter(gap.reason for gap in frog_only)),
        engine_reasons=dict(Counter(gap.reason for gap in engine_only)),
    )
    _logger.info(
        "reconciled",
        extra={
            "base_url": base_url,
            "in_both": report.in_both,
            "missed": len(report.missed_pages),
            "orphans": len(report.orphans),
        },
    )
    return report
