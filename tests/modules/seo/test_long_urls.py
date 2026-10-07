"""URL length on the crawl path: what is dropped, what is fetched, what is exported.

Two limits apply and they are deliberately different:

* `MAX_FETCH_URL_LENGTH` (8,192, `core.url_safety`) — a link longer than this is
  never collected, and the fetcher never requests one. It bounds memory: a long
  same-site `<base href>` under thousands of `href="?n"` used to turn a 104 KB
  body into 20 MB of link strings (P4 security review, R1).
* `contracts.audit.MAX_URL_LENGTH` (2,048) — what the audit workbook accepts. A
  crawled page between the two is fetched and classified as it always was, and
  makes the workbook export refuse, exactly as it did before extract-at-fetch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from src.core.url_safety import MAX_FETCH_URL_LENGTH
from src.modules.seo.contracts.audit import MAX_URL_LENGTH
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.audit_export import AuditExportError, to_audit_dataset
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from src.modules.seo.page_classifier.discovery_parsers import extract_page_links
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool

from tests.modules.seo.golden_site_factory import BASE, Route, build_fetcher, golden_settings

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")
LONG_BASE = f"{BASE}/" + "b" * MAX_FETCH_URL_LENGTH + "/"
"""A same-site base longer than the ceiling: every relative link under it is too."""


def base_page(count: int) -> str:
    anchors = "".join(f'<a href="?{i}">{i}</a>' for i in range(count))
    return f'<html><head><base href="{LONG_BASE}"></head><body>{anchors}</body></html>'


def crawl(tmp_path: Path, site: dict[str, Route], *, use_async: bool) -> SiteGraph:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=1 if use_async else None)
    if not use_async:
        return discover_site(fetcher, BASE)[0]

    async def scenario() -> SiteGraph:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE))[0]

    return asyncio.run(scenario())


class TestOverLongLinksAreNeverCollected:
    def test_extraction_drops_them(self):
        assert extract_page_links(base_page(200), f"{BASE}/") == ()

    def test_a_link_at_the_ceiling_is_kept(self):
        at_limit = f"{BASE}/" + "k" * (MAX_FETCH_URL_LENGTH - len(BASE) - 1)
        assert len(at_limit) == MAX_FETCH_URL_LENGTH
        html = f'<a href="{at_limit}">a</a><a href="{at_limit}x">b</a>'
        assert extract_page_links(html, f"{BASE}/") == (at_limit,)

    @pytest.mark.parametrize("use_async", [False, True], ids=["serial", "async"])
    def test_they_never_become_graph_nodes(self, tmp_path, use_async):
        site = {"/robots.txt": ROBOTS, "/": Route(200, "text/html", base_page(5_000))}
        graph = crawl(tmp_path, site, use_async=use_async)
        assert [node.url for node in graph.nodes] == [BASE]
        (home,) = graph.nodes
        assert home.outbound_links == 0


class TestAuditContractForUrlsBetweenTheTwoLimits:
    """2,049-8,192 characters: crawled as before; the workbook refuses as before."""

    LONG_PATH = "/" + "l" * (MAX_URL_LENGTH + 500) + "/"

    def site(self) -> dict[str, Route]:
        return {
            "/robots.txt": ROBOTS,
            "/": Route(200, "text/html", f'<a href="{self.LONG_PATH}">long</a>'),
            self.LONG_PATH: Route(200, "text/html", "<title>Long</title><p>x</p>"),
        }

    @pytest.mark.parametrize("use_async", [False, True], ids=["serial", "async"])
    def test_the_page_is_discovered_and_fetched(self, tmp_path, use_async):
        graph = crawl(tmp_path, self.site(), use_async=use_async)
        assert f"{BASE}{self.LONG_PATH}" in [node.url for node in graph.nodes]
        assert f"{BASE}{self.LONG_PATH}" not in graph.unfetched_urls()

    def test_the_workbook_export_refuses_the_crawl(self, tmp_path):
        tool = PageClassificationTool(fetcher=build_fetcher(golden_settings(tmp_path), self.site()))
        result = tool.run(PageClassificationInput(base_url=BASE))
        assert result.data is not None
        with pytest.raises(AuditExportError):
            to_audit_dataset(result.data.pages, produced_at=None)
