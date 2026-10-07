"""`SiteGraph._fetched` must say exactly what the stored bodies used to say.

"Fetched" was defined as "has stored HTML". The extract-at-fetch work stops
storing most bodies, so the definition moved to a set of its own first, while
the bodies are all still held. That makes this the moment the two can be
compared directly: every case below asserts the old definition and the new one
agree, on both crawl paths.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from src.modules.seo.page_classifier.relative_loops import MIN_DEPTH_SPREAD, MIN_LOOP_URLS

from tests.modules.seo.golden_site_factory import (
    BASE,
    PUBLIC_IP,
    GoldenFetcher,
    Route,
    build_fetcher,
    build_site,
    golden_settings,
)


def old_unfetched(graph: SiteGraph) -> tuple[str, ...]:
    """The definition `unfetched_urls` used before the set existed."""
    return tuple(node.url for node in graph.nodes if node.normalized not in graph._html)


def assert_definitions_agree(graph: SiteGraph) -> None:
    assert graph.unfetched_urls() == old_unfetched(graph)
    assert graph._fetched == set(graph._html)


def crawl(tmp_path: Path, site: dict[str, Route], *, seed: int | None) -> SiteGraph:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=seed)
    if seed is None:
        return discover_site(fetcher, BASE)[0]

    async def scenario() -> SiteGraph:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE))[0]

    return asyncio.run(scenario())


PATHS = pytest.mark.parametrize("seed", [None, 1, 2], ids=["serial", "async-1", "async-2"])


@PATHS
def test_the_definitions_agree_across_the_golden_site(tmp_path, seed):
    """404, PDF, empty body, redirects and loop eviction, all at once."""
    graph = crawl(tmp_path, build_site(), seed=seed)
    assert graph.loop_urls_skipped > 0, "the fixture must evict fetched nodes"
    assert_definitions_agree(graph)


@PATHS
def test_an_empty_html_body_counts_as_fetched(tmp_path, seed):
    graph = crawl(tmp_path, build_site(), seed=seed)
    assert graph.html_for(f"{BASE}/careers/empty/") == ""
    assert f"{BASE}/careers/empty/" not in graph.unfetched_urls()


@PATHS
def test_errors_and_non_html_answers_stay_unfetched(tmp_path, seed):
    graph = crawl(tmp_path, build_site(), seed=seed)
    unfetched = graph.unfetched_urls()
    assert f"{BASE}/careers/old-role/" in unfetched
    assert f"{BASE}/resources/whitepaper-download/" in unfetched


@pytest.mark.parametrize("use_async", [False, True], ids=["serial", "async"])
def test_a_transport_failure_stays_unfetched(tmp_path, use_async):
    site = build_site()

    def raising(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/about/team/":
            msg = "connection reset"
            raise httpx.ConnectError(msg, request=request)
        template = site.get(request.url.path)
        if template is None:
            return httpx.Response(404, text="not found")
        headers = {"content-type": template.content_type}
        if template.location:
            headers["location"] = template.location
        return httpx.Response(template.status, content=template.body.encode(), headers=headers)

    async def araising(request: httpx.Request) -> httpx.Response:
        return raising(request)

    fetcher = GoldenFetcher(
        settings=golden_settings(tmp_path),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(raising),
        async_transport=httpx.MockTransport(araising),
    )
    if use_async:

        async def scenario() -> SiteGraph:
            async with fetcher:
                return (await adiscover_site(fetcher, BASE))[0]

        graph = asyncio.run(scenario())
    else:
        graph = discover_site(fetcher, BASE)[0]
    assert f"{BASE}/about/team/" in graph.unfetched_urls()
    assert_definitions_agree(graph)


def _loop_urls() -> list[str]:
    """Copies of one three-segment tail, spread over enough parents and depths."""
    prefixes = ["", "y/", "y/z/", "y/z/w/"][:MIN_DEPTH_SPREAD]
    count = MIN_LOOP_URLS // len(prefixes) + 2
    return [f"{BASE}/p{i}/{prefix}a/b/c/" for i in range(count) for prefix in prefixes]


class TestEviction:
    def _evict_a_fetched_member(self) -> tuple[SiteGraph, str]:
        graph = SiteGraph(BASE)
        urls = _loop_urls()
        assert graph.add(urls[0], dom_link=True) is not None
        graph.store_html(urls[0], "<html>first</html>")
        assert urls[0] in graph._fetched, "precondition: the member was fetched"
        for url in urls[1:]:
            graph.add(url, dom_link=True)
        assert graph.loop_urls_skipped > 0, "the tail must be confirmed as a loop"
        return graph, urls[0]

    def test_eviction_clears_the_fetched_mark_with_the_body(self):
        graph, evicted = self._evict_a_fetched_member()
        assert graph.html_for(evicted) is None
        assert evicted not in graph._fetched
        assert_definitions_agree(graph)

    def test_an_evicted_url_offered_again_is_refused_and_stays_unmarked(self):
        graph, evicted = self._evict_a_fetched_member()
        assert graph.add(evicted, dom_link=True) is None
        assert evicted not in graph._fetched
        assert_definitions_agree(graph)
