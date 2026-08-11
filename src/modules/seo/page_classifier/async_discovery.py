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
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import TypeVar

from src.core.logger import get_logger
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.discovery import (
    DEFAULT_DOM_RESERVE_FRACTION,
    DEFAULT_MAX_PAGES,
    MAX_CMS_PAGES,
    SHOPIFY_ENDPOINTS,
    WORDPRESS_ENDPOINTS,
    CheckpointSink,
    DiscoveryReport,
    ProgressSink,
    SiteGraph,
    _checkpoint,
    _notify,
    is_refusal,
)
from src.modules.seo.page_classifier.discovery_parsers import (
    extract_page_links,
    parse_link_header,
    parse_shopify_records,
    parse_sitemap,
    parse_wordpress_records,
    with_page_param,
    wordpress_total_pages,
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

REQUEST_DEADLINE_S = 20.0
"""Total wall-clock a single page fetch may take.

httpx has no equivalent setting. Its read timeout measures the gap between
bytes, so a server sending one byte every few seconds resets it forever — the
request never times out and the worker never comes back. This bounds the whole
request, which is the only thing that defeats that.
"""

STALL_TIMEOUT_S = 30.0
"""How long a crawl may make no progress at all before it is abandoned.

The last line of defence, above the per-request deadline. If every in-flight
request is stuck, the crawl stops and returns what it has rather than hanging —
a partial result an operator can read beats a job that never finishes.
"""


class CrawlStalledError(RuntimeError):
    """No request completed within the stall window.

    Not a failure of the crawl so much as its end: the caller keeps what was
    already discovered and records why it stopped.
    """

    def __init__(self, in_flight: int, window_s: float) -> None:
        """Describe the stall in terms an operator can act on."""
        super().__init__(
            f"no page completed in {window_s:g}s with {in_flight} requests in flight — "
            f"the target stopped responding"
        )
        self.in_flight = in_flight


async def _gather_bounded(
    factories: Sequence[Callable[[], Awaitable[ResultT]]],
    concurrency: int,
    stall_timeout_s: float | None = None,
) -> list[ResultT | None]:
    """Await every factory with at most `concurrency` in flight.

    A failing task resolves to `None` rather than cancelling its siblings: one
    unreachable page must not abandon the other 19,999.

    Args:
        factories: Un-started awaitables.
        concurrency: Maximum in flight.
        stall_timeout_s: Abandon the batch if **nothing at all** completes within
            this window. Not a per-request timeout — a slow batch that keeps
            finishing pages is healthy and must not be cut off. This fires only
            when every in-flight request is stuck, which is what a tarpit or a
            dead socket looks like from here.

    Returns:
        Results in input order, `None` for anything that failed or was
        abandoned.

    Raises:
        CrawlStalledError: If nothing completes within `stall_timeout_s`.
    """
    if not factories:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(factory: Callable[[], Awaitable[ResultT]]) -> ResultT | None:
        async with semaphore:
            try:
                return await factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop a crawl
                _logger.debug("async_task_failed", extra={"error": str(exc)})
                return None

    tasks = [asyncio.create_task(run(factory)) for factory in factories]
    if stall_timeout_s is None:
        return list(await asyncio.gather(*tasks))

    positions = {task: index for index, task in enumerate(tasks)}
    results: list[ResultT | None] = [None] * len(tasks)
    pending = set(tasks)

    while pending:
        done, pending = await asyncio.wait(
            pending, timeout=stall_timeout_s, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            # Nothing finished in the whole window, so every worker is stuck.
            # Cancelled rather than awaited: the point of the detector is that
            # these will not return.
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise CrawlStalledError(len(pending), stall_timeout_s)

        for task in done:
            results[positions[task]] = task.result()

    return results


async def _abody(graph: SiteGraph, fetcher: HttpFetcher, url: str) -> str | None:
    """Fetch a URL, returning `None` for any failure or non-2xx.

    Refusals are counted on the graph, matching the serial path. Behavioural
    equivalence is the central claim of this module, and a report that differed
    between the two paths would break it.
    """
    try:
        result = await asyncio.wait_for(fetcher.afetch(url), timeout=REQUEST_DEADLINE_S)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("async_fetch_failed", extra={"url": url, "error": str(exc)})
        graph.fetch_failures += 1
        return None
    if not result.ok:
        if is_refusal(result.status_code):
            graph.fetch_failures += 1
        return None
    return result.body


async def _ahtml(graph: SiteGraph, fetcher: HttpFetcher, url: str) -> tuple[str, str] | None:
    """Fetch a URL, returning `(url, html)` only when the response is HTML.

    A non-HTML 200 is not a failure: the server answered, the payload simply is
    not a page.
    """
    try:
        # Bounded here rather than by httpx: its read timeout measures the gap
        # between bytes, so a server dribbling data resets it forever and the
        # worker never returns.
        result = await asyncio.wait_for(fetcher.afetch(url), timeout=REQUEST_DEADLINE_S)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("async_fetch_failed", extra={"url": url, "error": str(exc)})
        graph.fetch_failures += 1
        return None
    if not result.ok:
        if is_refusal(result.status_code):
            graph.fetch_failures += 1
        return None
    if not result.is_html:
        return None
    return url, result.body


async def adiscover_site(
    fetcher: HttpFetcher,
    base_url: str,
    *,
    site_profile: SiteProfile | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int | None = None,
    crawl_dom: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    dom_reserve_fraction: float = DEFAULT_DOM_RESERVE_FRACTION,
    on_progress: ProgressSink | None = None,
    on_checkpoint: CheckpointSink | None = None,
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
        max_depth: Link depth ceiling for the DOM crawl. `None` traverses until
            the link frontier is exhausted or `max_pages` is reached.
        crawl_dom: Run Path B.
        concurrency: Maximum simultaneous requests, clamped to `MAX_CONCURRENCY`.
        dom_reserve_fraction: Share of `max_pages` only the DOM crawl may fill,
            so a large sitemap cannot starve out sitemap-omitted pages.
        on_progress: Optional observability hook, called as pages are fetched.
        on_checkpoint: Optional durability hook, offered the graph so partial
            work survives an interruption. Implementations must throttle.

    Returns:
        The merged graph and its report.
    """
    bounded = min(max(1, concurrency), MAX_CONCURRENCY)
    graph = SiteGraph(base_url, max_pages=max_pages, dom_reserve_fraction=dom_reserve_fraction)

    sitemaps_fetched = await _asitemaps(fetcher, base_url, graph, bounded, on_progress)
    await _acms(fetcher, base_url, graph, site_profile)
    # Reported once before the DOM crawl: sitemap and CMS discovery establish the
    # denominator, so without this the first progress reading is 0 of 0.
    _notify(on_progress, graph, 0, [])
    # The sitemap alone is often most of what a crawl will ever know. Saving it
    # before the DOM crawl starts means an interruption seconds in still leaves
    # something worth rendering.
    _checkpoint(on_checkpoint, graph)

    pages_fetched = 0
    if crawl_dom:
        try:
            pages_fetched = await _acrawl(
                fetcher, base_url, graph, max_depth, bounded, on_progress, on_checkpoint
            )
        except Exception as exc:  # noqa: BLE001 - a partial graph beats no graph
            # Everything discovered before the failure is real data an operator
            # can act on. Losing a 500-URL crawl because page 501 broke the
            # event loop would throw away the work and tell them nothing.
            _logger.exception("dom_crawl_aborted", extra={"url": base_url})
            graph.stopped_reason = f"{type(exc).__name__}: {exc}"

    report = graph.report().model_copy(
        update={"sitemaps_fetched": sitemaps_fetched, "pages_fetched": pages_fetched}
    )
    _logger.info("async_discovery_complete", extra={**report.model_dump(), "concurrency": bounded})
    return graph, report


async def _asitemaps(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    concurrency: int,
    on_progress: ProgressSink | None = None,
    on_checkpoint: CheckpointSink | None = None,
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
            [_factory(_abody, graph, fetcher, url) for url in batch], concurrency
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

        # Sitemap discovery can run for ten seconds before the DOM crawl starts.
        # Without this the client shows 0 of 0 for that whole window.
        _notify(on_progress, graph, 0, [])
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
            async for body in _apaginate(fetcher, f"{root}{path}", graph):
                for url, record in parse_wordpress_records(body, record_type).items():
                    graph.add(url, cms_api=True, cms_record=record)

    elif site_profile.cms_family is CmsFamily.SHOPIFY:
        for path, collection in SHOPIFY_ENDPOINTS:
            async for body in _apaginate(fetcher, f"{root}{path}", graph):
                records = parse_shopify_records(body, root, collection=collection)
                for url, record in records.items():
                    graph.add(url, cms_api=True, cms_record=record)


async def _apaginate(fetcher: HttpFetcher, endpoint: str, graph: SiteGraph) -> AsyncIterator[str]:
    """Yield every page of a CMS collection.

    The async twin of `discovery._paginate`, with identical termination rules —
    `Link: rel="next"`, then `X-WP-TotalPages`, then an empty or repeated page.
    Pages are fetched sequentially rather than concurrently because each one's
    cursor is only knowable from the previous response.

    Args:
        fetcher: Safety-wired fetcher.
        endpoint: First-page URL.
        graph: Receives the refusal count, so a blocked CMS endpoint is visible
            in the report rather than only in debug logs.

    Yields:
        Response bodies, in page order.
    """
    url: str | None = endpoint
    declared_pages: int | None = None
    seen_bodies: set[int] = set()

    for page in range(1, MAX_CMS_PAGES + 1):
        if url is None:
            return
        try:
            result = await fetcher.afetch(url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop discovery
            _logger.debug("cms_page_failed", extra={"url": url, "error": str(exc)})
            graph.fetch_failures += 1
            return
        if not result.ok:
            if is_refusal(result.status_code):
                graph.fetch_failures += 1
            return
        if not result.body.strip():
            return

        fingerprint = hash(result.body)
        if fingerprint in seen_bodies:
            _logger.debug("cms_pagination_not_advancing", extra={"endpoint": endpoint})
            return
        seen_bodies.add(fingerprint)

        yield result.body

        if declared_pages is None:
            declared_pages = wordpress_total_pages(result.headers)
        if declared_pages is not None and page >= declared_pages:
            return

        next_link = parse_link_header(result.headers.get("link", "")).get("next")
        url = next_link or with_page_param(endpoint, page + 1)

    _logger.info("cms_pagination_ceiling_reached", extra={"endpoint": endpoint})


async def _acrawl(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    max_depth: int | None,
    concurrency: int,
    on_progress: ProgressSink | None = None,
    on_checkpoint: CheckpointSink | None = None,
) -> int:
    """Path B — breadth-first traversal, one level at a time, fetched in parallel.

    Driven by whether a level is non-empty rather than by a fixed range, so
    `max_depth=None` runs until the frontier is exhausted. That is bounded by
    `max_pages`: `graph.record_links` drops targets the graph refused, so once
    the budget is spent no new URLs can enter the next level.
    """
    graph.add(base_url, dom_link=True, depth=0)
    seen: set[str] = {normalize_url(base_url)}
    level = [base_url]
    fetched = 0
    depth = 0
    recent: list[str] = []

    # Capacity deliberately does NOT stop the crawl. `graph.add` already
    # refuses *new* nodes when full, so the frontier stops growing on its
    # own. Breaking on capacity instead meant that whenever the sitemap alone
    # filled the budget, the DOM crawl fetched nothing at all — no HTML, no
    # link graph, no in-degree, and Signals 1, 4 and 5 silently starved.
    while level and (max_depth is None or depth <= max_depth):
        crawlable = [url for url in level if not is_faceted_filter(url)]

        def note(url: str) -> None:
            """Report one completed page, from inside the level.

            Per page, not per level. This crawler is level-synchronous, and a
            single level can hold hundreds of pages taking tens of seconds — so
            notifying once per level leaves a progress bar frozen and then
            jumping. Observed live on gep.com: 1/400 for 28 seconds, then 81/400.

            Cheap because the sink throttles its own writes; asyncio is
            single-threaded, so the counter needs no lock.
            """
            nonlocal fetched
            fetched += 1
            recent.append(url)
            _notify(on_progress, graph, fetched, recent)
            _checkpoint(on_checkpoint, graph)

        try:
            results = await _gather_bounded(
                [_factory(_ahtml, graph, fetcher, url, note) for url in crawlable],
                concurrency,
                stall_timeout_s=STALL_TIMEOUT_S,
            )
        except CrawlStalledError as exc:
            # Ends the crawl, it does not fail it. Everything discovered so far
            # is real and worth returning; the report records why it stopped so
            # the partial view is never mistaken for a complete one.
            _logger.warning("crawl_stalled", extra={"url": base_url, "error": str(exc)})
            graph.stopped_reason = str(exc)
            break

        next_level: list[str] = []
        for item in results:
            if item is None:
                continue
            url, html = item
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
        depth += 1

    return fetched


def _factory(
    coro: Callable[..., Awaitable[ResultT]],
    graph: SiteGraph,
    fetcher: HttpFetcher,
    url: str,
    on_page: Callable[[str], None] | None = None,
) -> Callable[[], Awaitable[ResultT]]:
    """Bind a coroutine function to its arguments without invoking it.

    `_gather_bounded` needs un-started awaitables so the semaphore governs when
    each request begins. Passing coroutine objects directly would start them all
    at creation and defeat the bound.
    """
    if on_page is None:
        return lambda: coro(graph, fetcher, url)
    return lambda: _with_notify(coro(graph, fetcher, url), url, on_page)


async def _with_notify(
    awaitable: Awaitable[ResultT], url: str, on_page: Callable[[str], None]
) -> ResultT:
    """Await a fetch and report it the moment it lands, not when its level ends."""
    result = await awaitable
    if result is not None:
        on_page(url)
    return result
