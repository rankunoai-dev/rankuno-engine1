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
