"""The ADR 0038 facts come out the same from the serial and async crawl paths.

Behavioural equivalence between the two paths is the central claim of
`async_discovery`, and a fact recorded on one path and not the other would
break it silently. This crawls one small stub site both ways, in several
completion orders, and compares every new stored field node by node. It also
pins a few concrete values, so the comparison cannot pass by both paths being
wrong in the same way.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from src.core.config import Settings
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from tests.modules.seo.golden_site_factory import (
    BASE,
    Route,
    build_fetcher,
    golden_settings,
)

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")
CRUMB_A = (
    '<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":['
    '{"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"},'
    '{"@type":"ListItem","position":2,"name":"A","item":"https://e.com/a/"}]}</script>'
)


def _page(head: str, body: str) -> Route:
    html = f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"
    return Route(200, "text/html; charset=utf-8", html)


SITE: dict[str, Route] = {
    "/robots.txt": ROBOTS,
    "/": _page(
        '<link rel="canonical" href="https://e.com/">',
        '<header><a href="/a/">A</a></header>'
        '<main><a href="/b/">b</a><a href="/b/">b again</a><a href="/c/">c</a></main>'
        '<footer><a href="/b/">footer</a></footer>',
    ),
    "/a/": _page(
        CRUMB_A + '<link rel="canonical" href="https://e.com/b/">',
        '<main><a href="/b/">b</a></main><header><a href="/">home</a></header>',
    ),
    "/b/": _page(
        '<link rel="canonical" href="https://e.com/b/">'
        '<link rel="canonical" href="https://e.com/b/">',
        '<header><a href="/a/">a</a></header><p>no main, so the whole body counts</p>',
    ),
    "/c/": _page(
        "",
        '<article><a href="/b/">b</a></article>',
    ),
}


def _crawl(tmp_path: Path, seed: int | None) -> SiteGraph:
    settings: Settings = golden_settings(tmp_path)
    fetcher: HttpFetcher = build_fetcher(settings, SITE, seed=seed)
    if seed is None:
        return discover_site(fetcher, BASE)[0]

    async def scenario() -> SiteGraph:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE))[0]

    return asyncio.run(scenario())


FIELDS = (
    "canonical_declared",
    "canonical_link_count",
    "body_link_count",
    "breadcrumb_parent_url",
    "unique_content_inlinks",
)


def _facts(graph: SiteGraph) -> dict[str, tuple[object, ...]]:
    return {
        node.normalized: tuple(getattr(node, field) for field in FIELDS)
        for node in graph.nodes
    }


@pytest.fixture(scope="module")
def serial_facts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[object, ...]]:
    return _facts(_crawl(tmp_path_factory.mktemp("serial"), seed=None))


class TestSerialAndAsyncAgree:
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_every_node_has_the_same_new_facts_on_both_paths(
        self, tmp_path: Path, serial_facts: dict[str, tuple[object, ...]], seed: int
    ) -> None:
        assert _facts(_crawl(tmp_path, seed=seed)) == serial_facts


@pytest.fixture(scope="module")
def by_path(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, object]]:
    graph = _crawl(tmp_path_factory.mktemp("pinned"), seed=None)
    return {
        node.normalized.removeprefix(BASE): {field: getattr(node, field) for field in FIELDS}
        for node in graph.nodes
    }


class TestConcreteValuesOnTheStubSite:
    """Pinned on the serial path. The values are worked out by hand from the page markup."""

    def test_a_declared_self_canonical_is_declared_once(self, by_path: dict[str, dict[str, object]]) -> None:
        assert by_path["/"]["canonical_declared"] is True
        assert by_path["/"]["canonical_link_count"] == 1

    def test_two_canonical_tags_are_counted_as_two(self, by_path: dict[str, dict[str, object]]) -> None:
        assert by_path["/b/"]["canonical_link_count"] == 2

    def test_a_page_with_no_canonical_is_undeclared_with_a_zero_count(
        self, by_path: dict[str, dict[str, object]]
    ) -> None:
        assert by_path["/c/"]["canonical_declared"] is False
        assert by_path["/c/"]["canonical_link_count"] == 0

    def test_the_body_region_excludes_the_header_and_footer(self, by_path: dict[str, dict[str, object]]) -> None:
        # The homepage's <main> holds /b/ (twice, so once) and /c/. The header /a/
        # and the footer /b/ are outside it.
        assert by_path["/"]["body_link_count"] == 2

    def test_a_page_without_main_counts_its_whole_body(self, by_path: dict[str, dict[str, object]]) -> None:
        # /b/ has no <main> or <article>, so its header link to /a/ counts.
        assert by_path["/b/"]["body_link_count"] == 1

    def test_unique_content_inlinks_counts_distinct_content_sources(
        self, by_path: dict[str, dict[str, object]]
    ) -> None:
        # /b/ is linked from the content of /, /a/ and /c/ (article), each once.
        assert by_path["/b/"]["unique_content_inlinks"] == 3

    def test_the_breadcrumb_parent_is_the_homepage_for_a(self, by_path: dict[str, dict[str, object]]) -> None:
        assert by_path["/a/"]["breadcrumb_parent_url"] == "https://e.com/"

    def test_a_page_read_with_no_breadcrumb_stores_the_empty_string(
        self, by_path: dict[str, dict[str, object]]
    ) -> None:
        assert by_path["/c/"]["breadcrumb_parent_url"] == ""
