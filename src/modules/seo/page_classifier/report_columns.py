"""Derived cells for the columns appended to the "All URLs" workbook sheet.

`reports.py` already carries twelve columns. These nine answer the questions an
analyst asks next: how a URL was found, whether the sitemap listed it, how many
pages link to it, whether nothing links to it, what Search Console's CTR is as a
decimal, where the fetch landed, and whether the page may be indexed.

Every value is derived at export time from fields the profile already stores.
Nothing here is persisted, requested, or fetched, so the export can never
disagree with a crawl by re-reading the site, and no field is added to
`FullPageIntelligenceProfile`.

The rules are deliberately narrow. Each one answers with a labelled fact or
leaves the cell blank; none guesses. In particular a zero is never written where
the crawl did not measure one, because a count of zero and an unknown count look
the same in a spreadsheet and mean opposite things to the client.

Orphan here is **not** the navigation pass's `ORPHANED` status. That status comes
from the navigation classifier and reads the tree. This column is a plain count
from the discovery graph: the URL was listed by a sitemap, no crawled link
reached it, no CMS record names it, and no page links to it. The two can
disagree, and the workbook must not present one as the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .fetch_status import (
    LABEL_NO_RESPONSE,
    LABEL_NOT_FETCHED,
    LABEL_NOT_RECORDED,
    http_status_label,
)

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile

__all__ = [
    "CTR_DECIMAL_FORMAT",
    "CTR_DECIMAL_HEADER",
    "TRAILING_HEADERS",
    "trailing_cells",
]

CTR_DECIMAL_HEADER = "GSC CTR (decimal)"
CTR_DECIMAL_FORMAT = "0.000"
"""Shown as 0.023, not 2.3. The existing "GSC CTR %" column is left as it is."""

TRAILING_HEADERS: tuple[str, ...] = (
    "Found Via",
    "In Sitemap",
    "Unique Inlinks",
    "Unique Outlinks",
    "Orphan",
    CTR_DECIMAL_HEADER,
    "Final URL",
    "Indexability",
    "Indexability Reason",
)
"""Appended after the twelve legacy columns, in this order. Order is part of the contract."""

_YES = "Yes"
_NO = "No"
_FOUND_VIA_CRAWL_LINK = "Crawl link"
_FOUND_VIA_CMS = "CMS"
_FOUND_VIA_SITEMAP = "Sitemap"


def _has_discovery_flags(page: FullPageIntelligenceProfile) -> bool:
    """Whether any discovery path is recorded for this page.

    Every URL a crawl discovers is added to the graph by at least one path, so
    a profile with all three flags false was not produced by discovery that
    recorded its sources. It is a result from before the flags were stored, and
    the cells that depend on them say so rather than reporting "No".
    """
    sources = page.discovery_sources
    return sources.sitemap or sources.dom_link or sources.cms_api


def _is_legacy(page: FullPageIntelligenceProfile) -> bool:
    """Whether the result predates the fetch-outcome capture.

    `fetch_outcome` is set on every page a crawl that ran has seen, including
    `not_fetched`, so `None` means the crawl never recorded the fetch at all.
    """
    return page.fetch_outcome is None


def found_via(page: FullPageIntelligenceProfile) -> str:
    """How the crawl first reached this URL, by a fixed precedence.

    A URL can be found by several paths. The precedence is: a followed link
    ("Crawl link") wins over a CMS record ("CMS"), which wins over a sitemap
    entry ("Sitemap"). The reason is that a link is the strongest evidence the
    site itself uses the page; a sitemap entry alone is the site asserting it
    exists. Every overlap is still visible in the "In Sitemap" column, so the
    precedence hides nothing.

    Returns:
        One of the three labels above, or "Not recorded (older crawl)" when no
        discovery path was recorded.
    """
    if not _has_discovery_flags(page):
        return LABEL_NOT_RECORDED
    sources = page.discovery_sources
    if sources.dom_link:
        return _FOUND_VIA_CRAWL_LINK
    if sources.cms_api:
        return _FOUND_VIA_CMS
    return _FOUND_VIA_SITEMAP


def in_sitemap(page: FullPageIntelligenceProfile) -> str:
    """Yes when a sitemap listed the URL, otherwise No."""
    if not _has_discovery_flags(page):
        return LABEL_NOT_RECORDED
    return _YES if page.discovery_sources.sitemap else _NO


def unique_inlinks(page: FullPageIntelligenceProfile) -> int | str:
    """Distinct internal pages linking to this URL.

    The count is already de-duplicated per linking page at discovery, so this
    is the number of pages that link here, not the number of link elements. A
    page the crawl never fetched keeps its real count: links *to* it were read
    from other pages, so the number is known even though its own body was not.
    """
    if _is_legacy(page):
        return LABEL_NOT_RECORDED
    return page.inbound_internal_links_count


def unique_outlinks(page: FullPageIntelligenceProfile) -> int | str | None:
    """Distinct internal links this page emits, or blank where that is unknown.

    A page with no response, or never requested, has no body to read, so its
    outbound count is unknown rather than zero. It is blank, not `0`, because a
    zero there would tell the client the page links to nothing.
    """
    if _is_legacy(page):
        return LABEL_NOT_RECORDED
    if http_status_label(page) in (LABEL_NOT_FETCHED, LABEL_NO_RESPONSE):
        return None
    return page.outbound_internal_links_count


def orphan(page: FullPageIntelligenceProfile) -> str:
    """Yes when the sitemap is the only path that knows this URL.

    The rule is: listed by a sitemap, not reached by a crawled link, not in the
    CMS, and with no inbound internal link. Every clause matters. A sitemap
    entry that a link does reach is not an orphan, and neither is a page the
    CMS knows about even if no link reaches it, because the CMS is a second
    source of truth that the crawl did not try to link from.

    Returns:
        "Yes", "No", or "Not recorded (older crawl)" when no discovery path was
        recorded.
    """
    if not _has_discovery_flags(page):
        return LABEL_NOT_RECORDED
    sources = page.discovery_sources
    is_orphan = (
        sources.sitemap
        and not sources.dom_link
        and not sources.cms_api
        and page.inbound_internal_links_count == 0
    )
    return _YES if is_orphan else _NO


def gsc_ctr_decimal(page: FullPageIntelligenceProfile) -> float | None:
    """Clicks divided by impressions, as a decimal, or blank with no denominator.

    Blank when Search Console was not joined (`gsc_impressions` is `None`) and
    when the URL drew no impressions. A CTR is undefined at zero impressions,
    and a `0.000` there would claim a measured zero click rate.
    """
    impressions = page.gsc_impressions
    if not impressions:
        return None
    return (page.gsc_clicks or 0) / impressions


def final_url(page: FullPageIntelligenceProfile) -> str | None:
    """Where the fetch landed after redirects; blank when no fetch happened."""
    if _is_legacy(page):
        return LABEL_NOT_RECORDED
    if http_status_label(page) == LABEL_NOT_FETCHED:
        return None
    return page.final_url or None


def indexability(page: FullPageIntelligenceProfile) -> str:
    """The page's own indexability verdict, as stored (not re-judged here)."""
    if _is_legacy(page):
        return LABEL_NOT_RECORDED
    return page.indexability.value


def indexability_reason(page: FullPageIntelligenceProfile) -> str | None:
    """The one-line reason stored with the verdict, blank when none was stored."""
    if _is_legacy(page):
        return LABEL_NOT_RECORDED
    return page.indexability_reason or None


def trailing_cells(page: FullPageIntelligenceProfile) -> list[str | int | float | None]:
    """The nine appended cell values for one page, in `TRAILING_HEADERS` order.

    Returns:
        Values ready for openpyxl. `None` is an empty cell, not the text "None".
    """
    return [
        found_via(page),
        in_sitemap(page),
        unique_inlinks(page),
        unique_outlinks(page),
        orphan(page),
        gsc_ctr_decimal(page),
        final_url(page),
        indexability(page),
        indexability_reason(page),
    ]
