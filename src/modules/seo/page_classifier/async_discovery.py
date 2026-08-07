"""Concurrent discovery — the path that makes the throughput target reachable.

The synchronous `discovery.discover_site` fetches one page at a time. At even
100ms per request that is 33 minutes for 20,000 pages, against a target of 15–30
seconds. Concurrency is not an optimisation here; it is the difference between
the specification being met and being unreachable.

Shape
-----
Breadth-first **by level**, with each level's pages fetched concurrently:

    depth 0:  [root]                          → 1 request
    depth 1:  [all links from root]           → N requests, concurrent
    depth 2:  [all links from depth 1]        → M requests, concurrent

Level-synchronous rather than a free-running worker pool, for two reasons that
matter more than the small amount of idle time at each barrier:

* **Truncation stays meaningful.** When the node ceiling is hit, what has been
  captured is every page down to depth *k* — a complete shallow crawl. A free
  pool would capture an arbitrary slice, which is far less useful to an auditor.
* **Depth is correct by construction.** A page's recorded depth is the level it
  was fetched at, with no need to reconcile racing discoveries of the same URL.

Politeness is *not* enforced here. `HttpFetcher` already applies a per-host
token bucket honouring `Crawl-delay`, so raising `concurrency` cannot make the
crawler rude to a single host — it makes it wait. The semaphore below bounds
local resource use (sockets, memory), not remote impact.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from src.core.logger import get_logger
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.discovery import (
    DEFAULT_DOM_RESERVE_FRACTION,
    DEFAULT_MAX_PAGES,
    SHOPIFY_ENDPOINTS,
    WORDPRESS_ENDPOINTS,
    DiscoveryReport,
    SiteGraph,
)
from src.modules.seo.page_classifier.discovery_parsers import (
    extract_page_links,
    parse_shopify_records,
    parse_sitemap,
    parse_wordpress_records,
)
from src.modules.seo.page_classifier.url_rules import is_faceted_filter, normalize_url
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

__all__ = [
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "adiscover_site",
]

_logger = get_logger("modules.seo.async_discovery")

DEFAULT_CONCURRENCY = 10
"""Simultaneous in-flight requests. Conservative on purpose: most crawls target
one host, and the per-host bucket will serialise them anyway."""

MAX_CONCURRENCY = 200
"""Hard ceiling. Beyond this the bottleneck is file descriptors and memory, not
the network, and a 512 MB worker starts to matter."""

ResultT = TypeVar("ResultT")


async def _gather_bounded(
    factories: Sequence[Callable[[], Awaitable[ResultT]]], concurrency: int
) -> list[ResultT | None]:
    """Await every factory with at most `concurrency` in flight.

    A failing task resolves to `None` rather than cancelling its siblings: one
    unreachable page must not abandon the other 19,999.
    """
    if not factories:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(factory: Callable[[], Awaitable[ResultT]]) -> ResultT | None:
        async with semaphore:
            try:
                return await factory()
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop a crawl
                _logger.debug("async_task_failed", extra={"error": str(exc)})
                return None

    return list(await asyncio.gather(*(run(factory) for factory in factories)))


async def _abody(fetcher: HttpFetcher, url: str) -> str | None:
    """Fetch a URL, returning `None` for any failure or non-2xx."""
    try:
        result = await fetcher.afetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("async_fetch_failed", extra={"url": url, "error": str(exc)})
        return None
    return result.body if result.ok else None


async def _ahtml(fetcher: HttpFetcher, url: str) -> tuple[str, str] | None:
    """Fetch a URL, returning `(url, html)` only when the response is HTML."""
    try:
        result = await fetcher.afetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("async_fetch_failed", extra={"url": url, "error": str(exc)})
        return None
    if not (result.ok and result.is_html):
        return None
    return url, result.body


async def adiscover_site(
    fetcher: HttpFetcher,
    base_url: str,
    *,
    site_profile: SiteProfile | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = 5,
    crawl_dom: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    dom_reserve_fraction: float = DEFAULT_DOM_RESERVE_FRACTION,
) -> tuple[SiteGraph, DiscoveryReport]:
    """Run all three discovery paths concurrently and merge them.

    Behaviourally identical to `discovery.discover_site`; only the fetching is
    concurrent. The same `SiteGraph` is produced, so downstream classification
    cannot tell which path built it.

    Args:
        fetcher: Safety-wired fetcher. SSRF validation, robots compliance and
            per-host throttling are inherited from it and are **not** relaxed by
            concurrency.
        base_url: Site root.
        site_profile: Platform hints. Path C is skipped for an unrecognised
            platform rather than guessed at.
        max_pages: Node ceiling.
        max_depth: Link depth for the DOM crawl.
        crawl_dom: Run Path B.
        concurrency: Maximum simultaneous requests, clamped to `MAX_CONCURRENCY`.
        dom_reserve_fraction: Share of `max_pages` only the DOM crawl may fill,
            so a large sitemap cannot starve out sitemap-omitted pages.

    Returns:
        The merged graph and its report.
    """
    bounded = min(max(1, concurrency), MAX_CONCURRENCY)
    graph = SiteGraph(base_url, max_pages=max_pages, dom_reserve_fraction=dom_reserve_fraction)

    sitemaps_fetched = await _asitemaps(fetcher, base_url, graph, bounded)
    await _acms(fetcher, base_url, graph, site_profile)
    pages_fetched = await _acrawl(fetcher, base_url, graph, max_depth, bounded) if crawl_dom else 0

    report = graph.report().model_copy(
        update={"sitemaps_fetched": sitemaps_fetched, "pages_fetched": pages_fetched}
    )
    _logger.info("async_discovery_complete", extra={**report.model_dump(), "concurrency": bounded})
    return graph, report


async def _asitemaps(
    fetcher: HttpFetcher, base_url: str, graph: SiteGraph, concurrency: int
) -> int:
    """Path A — walk the index, then fetch every child sitemap concurrently.

    Large sites publish dozens of grouped sitemaps; HighRadius has nine. Serial
    fetching of those alone costs seconds before a single page is retrieved.
    """
    root = base_url.rstrip("/")
    parsed = 0
    visited: set[str] = set()
    pending = [f"{root}/sitemap_index.xml", f"{root}/sitemap.xml"]

    while pending:
        batch = [url for url in pending if url not in visited]
        visited.update(batch)
        if not batch:
            break

        bodies = await _gather_bounded(
            [_factory(_abody, fetcher, url) for url in batch], concurrency
        )

        next_round: list[str] = []
        for url, body in zip(batch, bodies, strict=True):
            if body is None:
                continue
            document = parse_sitemap(body, source_name=url.rsplit("/", 1)[-1])
            if document.kind.name == "UNKNOWN":
                continue
            parsed += 1

            if document.is_index:
                next_round.extend(loc for loc in document.locations if loc not in visited)
            else:
                for location in document.locations:
                    graph.add(location, sitemap=True, sitemap_source=document.source_name)

        pending = next_round

    return parsed


async def _acms(
    fetcher: HttpFetcher, base_url: str, graph: SiteGraph, site_profile: SiteProfile | None
) -> None:
    """Path C — read the CMS database. Skipped for an unrecognised platform."""
    if site_profile is None or site_profile.cms_family is CmsFamily.UNKNOWN:
        return

    root = base_url.rstrip("/")

    if site_profile.cms_family is CmsFamily.WORDPRESS:
        for path, record_type in WORDPRESS_ENDPOINTS:
            body = await _abody(fetcher, f"{root}{path}")
            if body is None:
                continue
            for url, record in parse_wordpress_records(body, record_type).items():
                graph.add(url, cms_api=True, cms_record=record)

    elif site_profile.cms_family is CmsFamily.SHOPIFY:
        for path, collection in SHOPIFY_ENDPOINTS:
            body = await _abody(fetcher, f"{root}{path}")
            if body is None:
                continue
            for url, record in parse_shopify_records(body, root, collection=collection).items():
                graph.add(url, cms_api=True, cms_record=record)


async def _acrawl(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    max_depth: int,
    concurrency: int,
) -> int:
    """Path B — breadth-first traversal, one level at a time, fetched in parallel."""
    graph.add(base_url, dom_link=True, depth=0)
    seen: set[str] = {normalize_url(base_url)}
    level = [base_url]
    fetched = 0

    for depth in range(max_depth + 1):
        # Capacity deliberately does NOT stop the crawl. `graph.add` already
        # refuses *new* nodes when full, so the frontier stops growing on its
        # own. Breaking here instead meant that whenever the sitemap alone
        # filled the budget, the DOM crawl fetched nothing at all — no HTML, no
        # link graph, no in-degree, and Signals 1, 4 and 5 silently starved.
        if not level:
            break

        crawlable = [url for url in level if not is_faceted_filter(url)]
        results = await _gather_bounded(
            [_factory(_ahtml, fetcher, url) for url in crawlable], concurrency
        )

        next_level: list[str] = []
        for item in results:
            if item is None:
                continue
            url, html = item
            fetched += 1
            graph.store_html(url, html)

            links = extract_page_links(html, url)
            for target in graph.record_links(url, links, depth):
                key = normalize_url(target)
                if key not in seen:
                    seen.add(key)
                    next_level.append(target)

        _logger.debug(
            "crawl_level_complete",
            extra={"depth": depth, "fetched": len(crawlable), "queued": len(next_level)},
        )
        level = next_level

    return fetched


def _factory(
    coro: Callable[[HttpFetcher, str], Awaitable[ResultT]], fetcher: HttpFetcher, url: str
) -> Callable[[], Awaitable[ResultT]]:
    """Bind a coroutine function to its arguments without invoking it.

    `_gather_bounded` needs un-started awaitables so the semaphore governs when
    each request begins. Passing coroutine objects directly would start them all
    at creation and defeat the bound.
    """
    return lambda: coro(fetcher, url)
