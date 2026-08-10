"""Tests for multi-page CMS collection retrieval.

Reading page one and stopping capped the live Allbirds crawl at 35 records for a
far larger catalogue, and CMS coverage turned out to be the dominant driver of
classification confidence (build-log 0010 §4). These tests cover both the
termination signals and the ways a remote server can fail to provide one.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import (
    MAX_CMS_PAGES,
    DiscoveryReport,
    SiteGraph,
    discover_site,
)
from src.modules.seo.page_classifier.discovery_parsers import (
    extract_page_links,
    parse_link_header,
    with_page_param,
    wordpress_total_pages,
)
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

PUBLIC_IP = "93.184.216.34"
ROBOTS = "User-agent: *\nDisallow:\n"
HOME = "<html><body><p>root</p></body></html>"


def wp_page(start: int, count: int) -> str:
    """A WordPress REST page holding `count` records numbered from `start`."""
    return json.dumps(
        [
            {"id": i, "link": f"https://e.com/wp-{i}/", "parent": 0}
            for i in range(start, start + count)
        ]
    )


def shopify_page(start: int, count: int) -> str:
    """A Shopify products page holding `count` handles numbered from `start`."""
    return json.dumps({"products": [{"handle": f"sku-{i}"} for i in range(start, start + count)]})


def routed_fetcher(handler, settings) -> HttpFetcher:
    """A fetcher wired to a request handler on both transports."""
    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
    )


def base_routes(request: httpx.Request) -> httpx.Response | None:
    """Answer the non-CMS paths every crawl touches. `None` if unhandled."""
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS)
    if request.url.path == "/":
        return httpx.Response(200, text=HOME, headers={"content-type": "text/html"})
    return None


class TestLinkHeaderParsing:
    def test_extracts_next(self):
        header = '<https://e.com/products.json?page_info=abc>; rel="next"'
        assert parse_link_header(header)["next"] == "https://e.com/products.json?page_info=abc"

    def test_extracts_several_relations(self):
        header = '<https://e.com/a>; rel="previous", <https://e.com/b>; rel="next"'
        links = parse_link_header(header)
        assert links["previous"] == "https://e.com/a"
        assert links["next"] == "https://e.com/b"

    def test_tolerates_unquoted_rel(self):
        assert parse_link_header("<https://e.com/b>; rel=next")["next"] == "https://e.com/b"

    @pytest.mark.parametrize("header", ["", "garbage", "https://e.com/b; rel=next", "<unclosed"])
    def test_malformed_headers_yield_nothing(self, header):
        assert parse_link_header(header) == {}

    def test_ignores_links_without_a_rel(self):
        assert parse_link_header("<https://e.com/b>") == {}


class TestPageParam:
    def test_appends_when_absent(self):
        assert with_page_param("https://e.com/x.json", 3).endswith("page=3")

    def test_replaces_rather_than_duplicating(self):
        """`?page=1&page=2` would let the server choose which one wins."""
        result = with_page_param("https://e.com/x.json?page=1", 2)
        assert result.count("page=") == 1
        assert result.endswith("page=2")

    def test_preserves_other_parameters(self):
        result = with_page_param("https://e.com/x.json?limit=250", 2)
        assert "limit=250" in result
        assert "page=2" in result


class TestWordPressTotalPages:
    def test_reads_the_header(self):
        assert wordpress_total_pages({"x-wp-totalpages": "7"}) == 7

    @pytest.mark.parametrize("value", ["", "  ", "many", "0", "-3"])
    def test_absent_or_nonsense_yields_none(self, value):
        assert wordpress_total_pages({"x-wp-totalpages": value}) is None

    def test_missing_header_yields_none(self):
        assert wordpress_total_pages({}) is None


class TestWordPressPagination:
    def handler(self, total_pages: int = 3, per_page: int = 2):
        """A WordPress API declaring its page count in the header."""

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if not request.url.path.startswith("/wp-json/wp/v2/pages"):
                return httpx.Response(404, text="not found")

            page = int(dict(request.url.params).get("page", "1"))
            if page > total_pages:
                return httpx.Response(400, text="rest_post_invalid_page_number")
            return httpx.Response(
                200,
                text=wp_page((page - 1) * per_page, per_page),
                headers={
                    "content-type": "application/json",
                    "x-wp-totalpages": str(total_pages),
                },
            )

        return respond

    def test_reads_every_declared_page(self, settings):
        _, report = discover_site(
            routed_fetcher(self.handler(total_pages=3), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
            crawl_dom=False,
        )
        assert report.from_cms == 6, "3 pages x 2 records"

    def test_stops_at_the_declared_total_without_probing_past_it(self, settings):
        """WordPress errors past the end; the header lets us avoid asking."""
        requested: list[int] = []

        inner = self.handler(total_pages=2)

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/wp-json"):
                requested.append(int(dict(request.url.params).get("page", "1")))
            return inner(request)

        discover_site(
            routed_fetcher(respond, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
            crawl_dom=False,
        )
        assert max(requested) == 2, "must not request a page it was told does not exist"

    def test_a_single_page_collection_fetches_once(self, settings):
        _, report = discover_site(
            routed_fetcher(self.handler(total_pages=1), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
            crawl_dom=False,
        )
        assert report.from_cms == 2


class TestShopifyPagination:
    def cursor_handler(self, pages: int = 3, per_page: int = 2):
        """A Shopify API using `Link: rel="next"` cursor pagination."""

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")

            cursor = int(dict(request.url.params).get("page_info", "1"))
            headers = {"content-type": "application/json"}
            if cursor < pages:
                headers["link"] = (
                    f'<https://e.com/products.json?page_info={cursor + 1}>; rel="next"'
                )
            return httpx.Response(
                200, text=shopify_page((cursor - 1) * per_page, per_page), headers=headers
            )

        return respond

    def page_param_handler(self, pages: int = 3, per_page: int = 2):
        """A Shopify API using the older `?page=N` scheme with no Link header."""

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")

            page = int(dict(request.url.params).get("page", "1"))
            body = shopify_page((page - 1) * per_page, per_page) if page <= pages else "{}"
            return httpx.Response(200, text=body, headers={"content-type": "application/json"})

        return respond

    def test_follows_the_link_header_cursor(self, settings):
        _, report = discover_site(
            routed_fetcher(self.cursor_handler(pages=3), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert report.from_cms == 6, "3 cursor pages x 2 products"

    def test_stops_when_the_cursor_runs_out(self, settings):
        _, report = discover_site(
            routed_fetcher(self.cursor_handler(pages=1), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert report.from_cms == 2

    def test_falls_back_to_the_page_parameter(self, settings):
        """Older storefronts paginate with ?page=N and send no Link header."""
        _, report = discover_site(
            routed_fetcher(self.page_param_handler(pages=3), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert report.from_cms == 6


class TestTerminationSafety:
    def test_a_server_that_ignores_pagination_does_not_loop(self, settings):
        """The dangerous case: identical responses forever.

        Without a repeat check this would run to MAX_CMS_PAGES, making 40
        pointless requests against a client's server and collecting duplicates.
        """
        calls: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")
            calls.append(str(request.url))
            return httpx.Response(
                200, text=shopify_page(0, 2), headers={"content-type": "application/json"}
            )

        _, report = discover_site(
            routed_fetcher(respond, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert len(calls) == 2, "one real page, one repeat detected, then stop"
        assert report.from_cms == 2

    def test_an_empty_page_terminates(self, settings):
        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")
            page = int(dict(request.url.params).get("page", "1"))
            body = shopify_page(0, 2) if page == 1 else ""
            return httpx.Response(200, text=body, headers={"content-type": "application/json"})

        _, report = discover_site(
            routed_fetcher(respond, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert report.from_cms == 2

    def test_an_error_mid_collection_keeps_earlier_pages(self, settings):
        """A 500 on page 3 must not discard pages 1 and 2."""

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")
            page = int(dict(request.url.params).get("page", "1"))
            if page >= 3:
                return httpx.Response(500, text="boom")
            return httpx.Response(
                200,
                text=shopify_page((page - 1) * 2, 2),
                headers={"content-type": "application/json"},
            )

        _, report = discover_site(
            routed_fetcher(respond, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert report.from_cms == 4

    def test_the_page_ceiling_is_bounded(self, settings):
        """An endless but always-changing collection must still terminate."""
        calls: list[int] = []

        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if request.url.path != "/products.json":
                return httpx.Response(404, text="not found")
            page = int(dict(request.url.params).get("page", "1"))
            calls.append(page)
            return httpx.Response(
                200,
                text=shopify_page(page * 100, 1),
                headers={"content-type": "application/json"},
            )

        discover_site(
            routed_fetcher(respond, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.SHOPIFY),
            crawl_dom=False,
        )
        assert len(calls) <= MAX_CMS_PAGES


class TestAsyncParity:
    """The async path must paginate identically, or the two crawls diverge."""

    def handler(self, pages: int = 3, per_page: int = 2):
        def respond(request: httpx.Request) -> httpx.Response:
            fallback = base_routes(request)
            if fallback is not None:
                return fallback
            if not request.url.path.startswith("/wp-json/wp/v2/pages"):
                return httpx.Response(404, text="not found")
            page = int(dict(request.url.params).get("page", "1"))
            if page > pages:
                return httpx.Response(400, text="invalid page")
            return httpx.Response(
                200,
                text=wp_page((page - 1) * per_page, per_page),
                headers={"content-type": "application/json", "x-wp-totalpages": str(pages)},
            )

        return respond

    def test_async_reads_every_page(self, settings):
        async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
            fetcher = routed_fetcher(self.handler(pages=3), settings)
            async with fetcher:
                return await adiscover_site(
                    fetcher,
                    "https://e.com",
                    site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
                    crawl_dom=False,
                )

        _, report = asyncio.run(scenario())
        assert report.from_cms == 6

    def test_both_paths_agree(self, settings):
        _, serial = discover_site(
            routed_fetcher(self.handler(pages=3), settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
            crawl_dom=False,
        )

        async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
            fetcher = routed_fetcher(self.handler(pages=3), settings)
            async with fetcher:
                return await adiscover_site(
                    fetcher,
                    "https://e.com",
                    site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
                    crawl_dom=False,
                )

        _, concurrent = asyncio.run(scenario())
        assert concurrent.from_cms == serial.from_cms


class TestNonPageExtensions:
    def test_markdown_files_are_not_crawled(self):
        """Observed live: allbirds.com/agents.md entered the graph as a page."""
        html = '<a href="/agents.md">agents</a><a href="/real-page/">page</a>'
        links = extract_page_links(html, "https://e.com/")
        assert links == ("https://e.com/real-page/",)

    @pytest.mark.parametrize("path", ["/notes.md", "/README.markdown", "/DOC.MD"])
    def test_markdown_variants_are_filtered(self, path):
        assert extract_page_links(f'<a href="{path}">x</a>', "https://e.com/") == ()

    def test_llms_txt_is_deliberately_still_crawlable(self):
        """Phase 7's answer-readiness audit reads llms.txt; do not filter .txt."""
        links = extract_page_links('<a href="/llms.txt">manifest</a>', "https://e.com/")
        assert links == ("https://e.com/llms.txt",)
