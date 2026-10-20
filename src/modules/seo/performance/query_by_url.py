"""Attach each crawled URL's top search queries from a query-by-page fetch.

The join uses `UrlResolutionIndex`, the same matcher the performance report uses,
so a query row and a performance row for one page always land on the same
crawled URL. A second matcher here would be free to disagree with the first, and
the two reports would then show one page's traffic under two different URLs.

Two GSC addresses can name one crawled page (an `http` and an `https` form, or a
trailing-slash variant). Their rows for the same query are summed before ranking,
because listing one query twice for one page would waste one of the five places.
Position is averaged weighted by impressions, the usual way to combine averages of
this kind.

Pure: no I/O and no settings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from src.integrations.gsc_schemas import GscPageQueries, GscQueryRow
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.performance.url_identity import UrlResolutionIndex

__all__ = ["TOP_QUERIES_PER_URL", "rank_queries", "top_queries_by_crawl_url"]

TOP_QUERIES_PER_URL: Final[int] = 5
"""How many queries one URL shows. Five is what fits a spreadsheet cell and a PDF row."""


def _combine(rows: Sequence[GscQueryRow], page: str, query: str) -> GscQueryRow:
    """One row for a (page, query) pair that GSC split across several addresses."""
    clicks = sum(row.clicks for row in rows)
    impressions = sum(row.impressions for row in rows)
    if impressions:
        position = sum(row.avg_position * row.impressions for row in rows) / impressions
    else:
        position = sum(row.avg_position for row in rows) / len(rows)
    return GscQueryRow(
        page=page,
        query=query,
        clicks=clicks,
        impressions=impressions,
        avg_position=position,
    )


def rank_queries(rows: Iterable[GscQueryRow]) -> tuple[GscQueryRow, ...]:
    """The top queries for one URL, most valuable first.

    Ordered by clicks, then impressions, both descending, then the query text
    ascending, so two queries with the same counts always come out in the same
    order. Without the last key, a re-export could reshuffle a tie.

    Args:
        rows: Every query row for one URL.

    Returns:
        At most `TOP_QUERIES_PER_URL` rows.
    """
    ranked = sorted(rows, key=lambda row: (-row.clicks, -row.impressions, row.query))
    return tuple(ranked[:TOP_QUERIES_PER_URL])


def top_queries_by_crawl_url(
    pages: Iterable[FullPageIntelligenceProfile],
    queries: GscPageQueries | None,
) -> Mapping[str, tuple[GscQueryRow, ...]]:
    """Each crawled URL's top queries, keyed by the crawled URL.

    A GSC row whose address matches no crawled page, or matches several, is left
    out rather than attached to a guess. The matcher already refuses to guess, and
    a wrong attribution would put one page's queries under another's name.

    Args:
        pages: The crawled pages, as the result holds them.
        queries: The query-by-page fetch, or `None` when none was taken.

    Returns:
        A mapping from crawled URL to its ranked queries. URLs with no matched
        query are absent, not mapped to an empty tuple.
    """
    if queries is None:
        return {}
    index = UrlResolutionIndex(pages)
    grouped: dict[str, dict[str, list[GscQueryRow]]] = defaultdict(lambda: defaultdict(list))
    for row in queries.rows:
        crawl_url = index.resolve_url(row.page)
        if crawl_url is not None:
            grouped[crawl_url][row.query].append(row)
    return {
        url: rank_queries(_combine(rows, url, query) for query, rows in by_query.items())
        for url, by_query in grouped.items()
    }
