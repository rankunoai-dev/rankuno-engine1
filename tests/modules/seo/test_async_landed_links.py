"""The async crawl extracts links when a page lands, and records them after the level.

Before extract-at-fetch, a level's results list carried every body to the level
boundary, and links were extracted there. Extraction now happens in the fetch
task, so the results carry links instead of bodies. Three behaviours that
depended on *where* extraction ran are pinned here, and each held before the
move:

* an extraction error aborts the DOM crawl at that page's input position;
* a redirected page evicted by an earlier sibling's links resolves its relative
  links exactly as the serial path does;
* a level abandoned by the stall detector keeps its completed pages, and records
  none of their links (build-log 0137 §4.2).

Link *order* under shuffled completion is pinned by the golden test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier import async_discovery
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import DiscoveryReport, SiteGraph, discover_site

from tests.modules.seo.golden_site_factory import (
    BASE,
    PUBLIC_IP,
    GoldenFetcher,
    Route,
    build_fetcher,
    golden_settings,
)

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")
SEEDS = pytest.mark.parametrize("seed", [1, 2, 3])


def page(*links: str) -> Route:
    return Route(200, "text/html", "".join(f'<a href="{link}">x</a>' for link in links))


def run_async(
    tmp_path: Path, site: dict[str, Route], seed: int
) -> tuple[SiteGraph, DiscoveryReport]:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=seed)

    async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
        async with fetcher:
            return await adiscover_site(fetcher, BASE)

    return asyncio.run(scenario())


def urls(graph: SiteGraph) -> list[str]:
    return [node.url for node in graph.nodes]


class TestAnExtractionErrorAbortsWhereItAlwaysDid:
    SITE = {
        "/robots.txt": ROBOTS,
        "/": page("/a/", "/b/", "/c/"),
        "/a/": page("/a1/"),
        "/b/": page("/b1/"),
        "/c/": page("/c1/"),
    }

    @SEEDS
    def test_earlier_pages_record_links_and_the_crawl_stops_at_the_failing_one(
        self, tmp_path, monkeypatch, seed
    ):
        real = async_discovery.extract_page_links

        def failing(html: str, base_url: str, **kwargs: object) -> tuple[str, ...]:
            if base_url.endswith("/b/"):
                msg = "boom"
                raise RuntimeError(msg)
            return real(html, base_url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(async_discovery, "extract_page_links", failing)
        graph, report = run_async(tmp_path, self.SITE, seed)

        assert report.stopped_reason == "RuntimeError: boom"
        found = urls(graph)
        assert f"{BASE}/a1/" in found, "a page before the failure in input order"
        assert f"{BASE}/b1/" not in found
        assert f"{BASE}/c1/" not in found, "a page after it, however early it landed"
        unfetched = graph.unfetched_urls()
        assert f"{BASE}/b/" not in unfetched, "the failing page was still fetched"
        assert f"{BASE}/c/" not in unfetched
        # Pre-existing: an aborted DOM crawl never assigns its count.
        assert report.pages_fetched == 0


class TestARedirectEvictedBySiblingResolvesLikeTheSerialPath:
    """`/p0/a/b/c/` redirects to `/landing/x/`, which links `child/` relatively.

    `/hub/` comes earlier in the same level and links enough copies of the
    `a/b/c` tail to confirm a loop, evicting `/p0/a/b/c/`. The serial path
    evicts it before fetching it, so it never learns where the page landed and
    resolves `child/` against the requested URL. The async path must agree, even
    though it fetched the page, and learned its destination, first.
    """

    COPIES = tuple(
        f"/p{i}/{prefix}a/b/c/" for i in range(1, 12) for prefix in ("", "y/", "y/z/", "y/z/w/")
    )
    SITE = {
        "/robots.txt": ROBOTS,
        "/": page("/hub/", "/p0/a/b/c/"),
        "/hub/": page(*COPIES),
        "/p0/a/b/c/": Route(301, "text/html", "", "/landing/x/"),
        "/landing/x/": page("child/"),
    }

    def test_serial_resolves_against_the_requested_url(self, tmp_path):
        graph, _ = discover_site(build_fetcher(golden_settings(tmp_path), self.SITE), BASE)
        assert graph.loop_urls_skipped > 0
        assert f"{BASE}/p0/a/b/c/child/" in urls(graph)
        assert f"{BASE}/landing/x/child/" not in urls(graph)

    @SEEDS
    def test_async_builds_the_same_graph(self, tmp_path, seed):
        serial, _ = discover_site(build_fetcher(golden_settings(tmp_path), self.SITE), BASE)
        concurrent, _ = run_async(tmp_path, self.SITE, seed)
        assert urls(concurrent) == urls(serial)
        assert f"{BASE}/landing/x/child/" not in urls(concurrent)


class TestAnAbandonedLevelKeepsItsPagesAndRecordsNoLinks:
    """Build-log 0137 §4.2, unchanged by moving extraction into the task."""

    def test_a_stalled_level(self, tmp_path, monkeypatch):
        monkeypatch.setattr(async_discovery, "STALL_TIMEOUT_S", 0.3)
        site = {
            "/robots.txt": ROBOTS,
            "/": page("/fast/", "/slow/"),
            "/fast/": page("/fast-child/"),
        }
        never = asyncio.Event()

        def handler(request: httpx.Request) -> httpx.Response:
            route = site.get(request.url.path)
            if route is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(
                route.status,
                content=route.body.encode(),
                headers={"content-type": route.content_type},
            )

        async def ahandler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/slow/":
                await never.wait()
            return handler(request)

        fetcher = GoldenFetcher(
            settings=golden_settings(tmp_path),
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(handler),
            async_transport=httpx.MockTransport(ahandler),
        )

        async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
            async with fetcher:
                return await adiscover_site(fetcher, BASE)

        graph, report = asyncio.run(scenario())

        assert report.stopped_reason is not None
        assert report.abandoned_in_flight == 1
        assert f"{BASE}/fast/" not in graph.unfetched_urls(), "kept, and fetched"
        assert f"{BASE}/slow/" in graph.unfetched_urls()
        assert f"{BASE}/fast-child/" not in urls(graph), "its links were never recorded"


class TestLandedPageLinksFor:
    """Only the two addresses a page could be resolved against are answerable."""

    LANDED = async_discovery._LandedPage(
        url=f"{BASE}/old/",
        document_url=f"{BASE}/new/sub/",
        links=(f"{BASE}/new/sub/child/",),
        links_if_evicted=(f"{BASE}/old/child/",),
    )

    def test_answers_for_where_it_landed_and_where_it_was_requested(self):
        assert self.LANDED.links_for(f"{BASE}/new/sub/") == (f"{BASE}/new/sub/child/",)
        assert self.LANDED.links_for(f"{BASE}/old/") == (f"{BASE}/old/child/",)

    def test_refuses_an_address_it_never_resolved_against(self):
        with pytest.raises(AssertionError):
            self.LANDED.links_for(f"{BASE}/elsewhere/")
