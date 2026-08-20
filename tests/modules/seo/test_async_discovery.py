"""Tests for the concurrent discovery path.

The central claim under test is **behavioural equivalence**: the async path must
produce the same graph as the serial one. If concurrency changes what is found,
it is not an optimisation, it is a different crawler.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import (
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    CrawlStalledError,
    _gather_bounded,
    adiscover_site,
)
from src.modules.seo.page_classifier.discovery import (
    DiscoveryReport,
    SiteGraph,
    discover_site,
)
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

PUBLIC_IP = "93.184.216.34"
ROBOTS = "User-agent: *\nDisallow:\n"

SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/services/</loc></url>
  <url><loc>https://e.com/orphaned-campaign/</loc></url>
</urlset>"""

SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://e.com/blog-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://e.com/product-sitemap.xml</loc></sitemap>
</sitemapindex>"""

BLOG_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/blog/post-a/</loc></url>
</urlset>"""

PRODUCT_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/shop/widget/</loc></url>
</urlset>"""

HOME_HTML = """<html><body>
  <a href="/services/">Services</a>
  <a href="/code-of-ethics/">Code of Ethics</a>
</body></html>"""

SERVICES_HTML = '<html><body><a href="/services/cloud/">Cloud</a></body></html>'
LEAF_HTML = "<html><body><p>Leaf.</p></body></html>"

WP_PAGES = """[
  {"id": 1, "link": "https://e.com/services/", "parent": 0},
  {"id": 2, "link": "https://e.com/services/cloud/", "parent": 1}
]"""


def html(body: str) -> httpx.Response:
    """An HTML 200."""
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def xml(body: str) -> httpx.Response:
    """An XML 200."""
    return httpx.Response(200, text=body, headers={"content-type": "application/xml"})


SITE = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/sitemap.xml": xml(SITEMAP),
    "/": html(HOME_HTML),
    "/services/": html(SERVICES_HTML),
    "/services/cloud/": html(LEAF_HTML),
    "/code-of-ethics/": html(LEAF_HTML),
    "/orphaned-campaign/": html(LEAF_HTML),
    "/wp-json/wp/v2/pages": httpx.Response(
        200, text=WP_PAGES, headers={"content-type": "application/json"}
    ),
}

CHAIN_LENGTH = 20
"""Longer than the depth ceiling that used to be the default (5).

A chain, not a tree: each hop is reachable only through the one above it, so the
number of pages fetched states exactly how far traversal got.
"""

DEEP_CHAIN: dict[str, httpx.Response] = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/": html('<html><body><a href="/c0/">Down</a></body></html>'),
}
for _hop in range(CHAIN_LENGTH):
    _next = f'<a href="/c{_hop + 1}/">Down</a>' if _hop + 1 < CHAIN_LENGTH else "end"
    DEEP_CHAIN[f"/c{_hop}/"] = html(f"<html><body>{_next}</body></html>")

NESTED_SITEMAPS = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/sitemap_index.xml": xml(SITEMAP_INDEX),
    "/blog-sitemap.xml": xml(BLOG_SITEMAP),
    "/product-sitemap.xml": xml(PRODUCT_SITEMAP),
    "/": html("<html><body>root</body></html>"),
}


def build_fetcher(settings, routes: dict[str, httpx.Response] | None = None) -> HttpFetcher:
    """Build a fetcher with both transports wired to the same route table.

    A **fresh** `Response` is built per request. Returning a shared instance
    exhausts its stream after the first read, and the async client additionally
    asserts on the stream type — so a reused response fails in a way that looks
    like a transport bug rather than a fixture bug.
    """
    table = routes if routes is not None else SITE

    def handler(request: httpx.Request) -> httpx.Response:
        template = table.get(request.url.path)
        if template is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(
            template.status_code,
            content=template.content,
            headers={"content-type": template.headers.get("content-type", "text/plain")},
        )

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
    )


def run_async(
    settings,
    routes: dict[str, httpx.Response] | None = None,
    **kwargs: Any,
) -> tuple[SiteGraph, DiscoveryReport]:
    """Run the async discovery path to completion."""

    async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
        fetcher = build_fetcher(settings, routes)
        async with fetcher:
            return await adiscover_site(fetcher, "https://e.com", **kwargs)

    return asyncio.run(scenario())


class TestEquivalenceWithSerialPath:
    """Concurrency must change the speed, not the result."""

    def test_finds_the_same_urls(self, settings):
        _, serial = discover_site(build_fetcher(settings), "https://e.com")
        _, concurrent = run_async(settings)
        assert concurrent.total_urls == serial.total_urls

    def test_attributes_the_same_paths(self, settings):
        _, serial = discover_site(build_fetcher(settings), "https://e.com")
        _, concurrent = run_async(settings)
        assert concurrent.from_sitemap == serial.from_sitemap
        assert concurrent.from_dom == serial.from_dom
        assert concurrent.dom_only == serial.dom_only
        assert concurrent.sitemap_only == serial.sitemap_only

    def test_builds_the_same_graph_nodes(self, settings):
        serial_graph, _ = discover_site(build_fetcher(settings), "https://e.com")
        concurrent_graph, _ = run_async(settings)
        assert {node.normalized for node in concurrent_graph.nodes} == {
            node.normalized for node in serial_graph.nodes
        }

    def test_produces_equivalent_page_evidence(self, settings):
        serial_graph, _ = discover_site(build_fetcher(settings), "https://e.com")
        concurrent_graph, _ = run_async(settings)
        assert len(concurrent_graph.to_page_evidence()) == len(serial_graph.to_page_evidence())

    def test_records_the_same_orphans(self, settings):
        _, serial = discover_site(build_fetcher(settings), "https://e.com")
        _, concurrent = run_async(settings)
        assert concurrent.orphans == serial.orphans


class TestConcurrentBehaviour:
    def test_finds_pages_the_sitemap_omits(self, settings):
        graph, report = run_async(settings)
        paths = {node.normalized for node in graph.nodes}
        assert "https://e.com/code-of-ethics/" in paths
        assert report.dom_only >= 1

    def test_fetches_nested_sitemaps(self, settings):
        _, report = run_async(settings, NESTED_SITEMAPS)
        assert report.sitemaps_fetched == 3, "index plus two children"
        assert report.from_sitemap == 2

    def test_cms_path_runs_for_a_recognised_platform(self, settings):
        _, report = run_async(settings, site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS))
        assert report.from_cms >= 2

    def test_retains_html_for_dom_signals(self, settings):
        """The bug class from cycle 0004: URLs found but bodies never captured."""
        graph, _ = run_async(settings)
        evidence = {item.normalized_path: item for item in graph.to_page_evidence()}
        assert evidence["https://e.com/services/"].html is not None

    def test_respects_the_depth_ceiling(self, settings):
        _, report = run_async(settings, max_depth=0)
        assert report.pages_fetched == 1


class TestUnlimitedDepth:
    """`max_depth=None` traverses until the frontier is exhausted.

    The previous default of 5 was a silent truncation: a site deeper than five
    hops lost everything below, while the page budget it would have used sat
    unspent. `max_pages` is the real bound.
    """

    def test_async_follows_the_whole_chain(self, settings):
        graph, report = run_async(settings, DEEP_CHAIN)
        paths = {node.normalized for node in graph.nodes}
        assert f"https://e.com/c{CHAIN_LENGTH - 1}/" in paths
        assert report.pages_fetched == CHAIN_LENGTH + 1, "every hop, plus the root"

    def test_serial_follows_the_whole_chain(self, settings):
        _, report = discover_site(build_fetcher(settings, DEEP_CHAIN), "https://e.com")
        assert report.pages_fetched == CHAIN_LENGTH + 1

    def test_unlimited_is_the_default(self, settings):
        """Neither path needs `max_depth` passed to reach the bottom."""
        _, serial = discover_site(build_fetcher(settings, DEEP_CHAIN), "https://e.com")
        _, concurrent = run_async(settings, DEEP_CHAIN)
        assert serial.pages_fetched == concurrent.pages_fetched == CHAIN_LENGTH + 1

    def test_an_explicit_ceiling_still_truncates(self, settings):
        """Opting back in must work, or the ceiling is not a ceiling."""
        _, report = run_async(settings, DEEP_CHAIN, max_depth=3)
        assert report.pages_fetched == 4, "root plus three hops"

    def test_both_paths_truncate_identically(self, settings):
        """Depth arithmetic differs between the loops; the result must not."""
        _, serial = discover_site(build_fetcher(settings, DEEP_CHAIN), "https://e.com", max_depth=3)
        _, concurrent = run_async(settings, DEEP_CHAIN, max_depth=3)
        assert serial.pages_fetched == concurrent.pages_fetched == 4

    def test_the_page_budget_still_bounds_an_unlimited_crawl(self, settings):
        """Unlimited depth is not unlimited work.

        The graph refuses new nodes at `max_pages`, so the frontier drains. If
        this ever regressed, an unlimited crawl of a cyclic site would not
        terminate.
        """
        graph, report = run_async(settings, DEEP_CHAIN, max_pages=6)
        assert report.truncated is True
        assert len(list(graph.nodes)) == 6

    def test_reports_truncation(self, settings):
        _, report = run_async(settings, max_pages=2)
        assert report.truncated is True
        assert report.total_urls == 2

    def test_a_full_graph_still_fetches_pages(self, settings):
        """Regression, found by the first live crawl of highradius.com.

        The sitemap alone filled the node budget, so `at_capacity()` was already
        true when the DOM crawl began and it broke out immediately: 40 URLs
        discovered, **zero pages fetched**. No HTML, no link graph, no in-degree,
        and Signals 1, 4 and 5 silently starved.

        Capacity must stop *discovering* new nodes, not stop *fetching* known
        ones. Mocks never caught this because the fixture site is smaller than
        any sane ceiling.
        """
        graph, report = run_async(settings, max_pages=2)
        assert report.truncated is True
        assert report.pages_fetched > 0, "a full graph must still fetch what it knows about"
        assert any(item.html for item in graph.to_page_evidence())

    def test_dom_crawl_can_be_disabled(self, settings):
        _, report = run_async(settings, crawl_dom=False)
        assert report.pages_fetched == 0
        assert report.from_sitemap >= 2

    def test_a_failing_page_does_not_abandon_its_siblings(self, settings):
        """One unreachable page must not lose the other 19,999."""
        routes = dict(SITE)
        routes["/services/"] = httpx.Response(500, text="boom")
        _, report = run_async(settings, routes)
        assert report.pages_fetched >= 2

    def test_empty_site_completes_cleanly(self, settings):
        _, report = run_async(settings, {"/robots.txt": httpx.Response(200, text=ROBOTS)})
        assert report.total_urls >= 0


class TestConcurrencyBounds:
    @pytest.mark.parametrize("requested", [1, 5, 50])
    def test_any_valid_concurrency_produces_the_same_result(self, settings, requested):
        """Correctness must not depend on how many requests are in flight."""
        _, report = run_async(settings, concurrency=requested)
        _, baseline = run_async(settings, concurrency=DEFAULT_CONCURRENCY)
        assert report.total_urls == baseline.total_urls

    def test_clamps_an_absurd_concurrency(self, settings):
        """Beyond the ceiling the bottleneck is file descriptors, not network."""
        _, report = run_async(settings, concurrency=MAX_CONCURRENCY * 100)
        assert report.total_urls > 0

    def test_rejects_nothing_but_clamps_zero(self, settings):
        _, report = run_async(settings, concurrency=0)
        assert report.total_urls > 0


class TestSafetyIsNotRelaxed:
    def test_ssrf_guard_still_applies(self, settings):
        """Concurrency must not become a way around URL validation."""
        routes = dict(SITE)
        routes["/"] = html('<html><body><a href="http://169.254.169.254/">meta</a></body></html>')
        graph, _ = run_async(settings, routes)
        assert all("169.254" not in node.url for node in graph.nodes if node.sources.dom_link)

    def test_robots_is_still_enforced(self, settings):
        routes = dict(SITE)
        routes["/robots.txt"] = httpx.Response(200, text="User-agent: *\nDisallow: /services/\n")
        graph, _ = run_async(settings, routes)
        evidence = {item.normalized_path: item for item in graph.to_page_evidence()}
        assert evidence["https://e.com/services/"].html is None, "disallowed page not fetched"

    def test_faceted_urls_are_never_fetched(self, settings):
        routes = dict(SITE)
        routes["/"] = html('<html><body><a href="/shop?color=red">Filter</a></body></html>')
        _, report = run_async(settings, routes)
        assert report.pages_fetched == 1, "only the root; the facet is classified unfetched"


class TestProgressReporting:
    """Progress has to arrive per page, not per level.

    This crawler is level-synchronous, so one level can hold hundreds of pages
    fetched concurrently over tens of seconds. Reporting once per level leaves a
    progress bar frozen and then jumping — observed live on gep.com at 1/400 for
    28 seconds, then 81/400 at completion.
    """

    def test_progress_is_reported_for_every_page(self, settings):
        seen: list[tuple[int, int]] = []
        _, report = run_async(
            settings,
            DEEP_CHAIN,
            on_progress=lambda done, total, _recent: seen.append((done, total)),
        )
        completions = [done for done, _ in seen]
        assert report.pages_fetched == CHAIN_LENGTH + 1
        # One reading per page, not one per level.
        assert max(completions) == CHAIN_LENGTH + 1
        assert len([c for c in completions if c > 0]) >= CHAIN_LENGTH

    def test_completion_counts_never_go_backwards(self, settings):
        """A bar that rewinds reads as a bug even when the crawl is fine."""
        seen: list[int] = []
        run_async(settings, DEEP_CHAIN, on_progress=lambda done, _t, _r: seen.append(done))
        assert seen == sorted(seen)

    def test_recent_urls_are_reported(self, settings):
        recent: list[tuple[str, ...]] = []
        run_async(settings, on_progress=lambda _d, _t, urls: recent.append(urls))
        assert any(len(batch) > 0 for batch in recent)
        assert all(url.startswith("https://e.com") for batch in recent for url in batch)

    def test_the_denominator_is_reported_before_any_page_is_fetched(self, settings):
        """Otherwise the first ten seconds of a large crawl show 0 of 0."""
        seen: list[tuple[int, int]] = []
        run_async(settings, on_progress=lambda done, total, _r: seen.append((done, total)))
        assert seen[0][0] == 0
        assert seen[0][1] > 0, "sitemap discovery establishes the total"

    def test_a_failing_sink_does_not_break_the_crawl(self, settings):
        """Telemetry is not worth losing a twenty-minute crawl over."""

        def explode(_done: int, _total: int, _recent: tuple[str, ...]) -> None:
            raise RuntimeError("sink is down")

        _, report = run_async(settings, DEEP_CHAIN, on_progress=explode)
        assert report.pages_fetched == CHAIN_LENGTH + 1

    def test_no_sink_is_the_default(self, settings):
        _, report = run_async(settings, DEEP_CHAIN)
        assert report.pages_fetched == CHAIN_LENGTH + 1


class TestStallAndPartialResults:
    """A crawl that stops responding must end, not hang — and keep what it found.

    A worker blocked on a socket is a worker that never returns. With 50 of them
    the job hangs forever, holds a concurrency slot, and produces nothing. Ending
    with a partial result an operator can read is strictly better.
    """

    def test_a_stalled_batch_raises_rather_than_hanging(self, settings):
        async def scenario() -> None:
            async def never() -> str:
                await asyncio.sleep(3600)
                return "unreachable"

            with pytest.raises(CrawlStalledError):
                await _gather_bounded([lambda: never()], concurrency=2, stall_timeout_s=0.2)

        asyncio.run(scenario())

    def test_a_slow_but_progressing_batch_is_not_cut_off(self, settings):
        """The detector fires on *no* progress, not on slowness.

        A large crawl of a slow site is healthy and must be allowed to finish.
        """

        async def scenario() -> list[int | None]:
            async def slow(value: int) -> int:
                await asyncio.sleep(0.05)
                return value

            return await _gather_bounded(
                [(lambda v=n: slow(v)) for n in range(10)], concurrency=2, stall_timeout_s=0.3
            )

        assert asyncio.run(scenario()) == list(range(10))

    def test_results_keep_their_input_order(self, settings):
        """The stall path rebuilds the list; order must survive it."""

        async def scenario() -> list[int | None]:
            async def after(delay: float, value: int) -> int:
                await asyncio.sleep(delay)
                return value

            return await _gather_bounded(
                [lambda: after(0.05, 0), lambda: after(0.01, 1), lambda: after(0.03, 2)],
                concurrency=3,
                stall_timeout_s=0.5,
            )

        assert asyncio.run(scenario()) == [0, 1, 2]

    def test_a_stalled_crawl_keeps_the_pages_it_found(self, settings):
        """The whole point: a partial tree, not a lost crawl."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path in ("/robots.txt", "/sitemap.xml"):
                return httpx.Response(
                    200,
                    text=SITEMAP if request.url.path.endswith(".xml") else ROBOTS,
                    headers={"content-type": "application/xml"},
                )
            raise httpx.ReadTimeout("tarpit")

        fetcher = HttpFetcher(
            settings=settings,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(handler),
            async_transport=httpx.MockTransport(handler),
        )

        async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
            async with fetcher:
                return await adiscover_site(fetcher, "https://e.com", max_pages=50)

        _, report = asyncio.run(scenario())
        # The sitemap URLs survived even though every page fetch failed.
        assert report.total_urls >= 2
        assert report.from_sitemap >= 2

    def test_stopped_reason_is_none_on_a_clean_crawl(self, settings):
        """Otherwise every crawl would carry a disclaimer it does not need."""
        _, report = run_async(settings)
        assert report.stopped_reason is None


class TestCheckpointHookReachesTheCrawl:
    """The wiring, not the checkpointer.

    Both paths silently dropped `on_checkpoint` between `discover_site` and the
    DOM crawl: every unit test of the checkpointer passed while no crawl ever
    invoked it, and `has_checkpoint` was false on a live 400-URL run. A test of
    a component in isolation cannot catch an argument that is never passed.
    """

    def test_the_concurrent_path_invokes_the_sink(self, settings):
        seen: list[int] = []
        run_async(settings, on_checkpoint=lambda graph: seen.append(len(graph)))
        assert seen, "adiscover_site never offered the graph for checkpointing"

    def test_the_serial_path_invokes_the_sink(self, settings):
        seen: list[int] = []
        discover_site(
            build_fetcher(settings),
            "https://e.com",
            on_checkpoint=lambda graph: seen.append(len(graph)),
        )
        assert seen, "discover_site never offered the graph for checkpointing"

    def test_the_sink_is_offered_before_the_dom_crawl(self, settings):
        """A crawl interrupted seconds in must still have saved its sitemap."""
        seen: list[int] = []
        run_async(settings, crawl_dom=False, on_checkpoint=lambda graph: seen.append(len(graph)))
        assert seen, "nothing was offered when the DOM crawl was disabled"

    def test_a_failing_sink_does_not_break_the_crawl(self, settings):
        def explode(_graph: object) -> None:
            raise RuntimeError("disk full")

        _, report = run_async(settings, on_checkpoint=explode)
        assert report.total_urls > 0

    def test_no_sink_is_the_default(self, settings):
        _, report = run_async(settings)
        assert report.total_urls > 0


# Same shape as `RESUME_SITE` in the serial suite: a root linking to both
# leaves, so a crawl that starts at the root necessarily reaches everything.
RESUME_SITE_ASYNC = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/": html('<html><body><a href="/a/">A</a><a href="/b/">B</a></body></html>'),
    "/a/": html("<html><body>leaf</body></html>"),
    "/b/": html("<html><body>leaf</body></html>"),
}


class TestExcludeUrlsMatchesTheSerialPath:
    """A resume must not depend on `use_async_crawl`.

    The two paths are documented as behaviourally indistinguishable. An
    exclusion honoured by only one of them would make a resumed crawl restart
    from the homepage on whichever path the operator happened to be using — and
    the async path is the default.
    """

    def test_a_plain_crawl_fetches_everything(self, settings):
        _, report = run_async(settings, RESUME_SITE_ASYNC)
        assert report.pages_fetched == 3

    def test_an_excluded_url_is_never_fetched(self, settings):
        _, report = run_async(settings, RESUME_SITE_ASYNC, exclude_urls=("https://e.com/a/",))
        assert report.pages_fetched == 2

    def test_excluding_the_root_stops_the_crawl_restarting_there(self, settings):
        _, report = run_async(
            settings,
            RESUME_SITE_ASYNC,
            seed_urls=("https://e.com/b/",),
            exclude_urls=("https://e.com/", "https://e.com/a/"),
        )
        assert report.pages_fetched == 1

    def test_the_match_is_normalised_not_literal(self, settings):
        _, report = run_async(settings, RESUME_SITE_ASYNC, exclude_urls=("https://e.com/a",))
        assert report.pages_fetched == 2
