"""The tool hands the homepage body to `homepage_sink`, once, on both crawl paths.

The server persists that body (`store.write_homepage`) so a later fix to the
header-menu parser can be applied without re-crawling. Nothing tested that the
tool calls the sink at all, and the extract-at-fetch work changes exactly which
bodies a crawl still holds when it ends — so the contract is pinned first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool

from tests.modules.seo.golden_site_factory import BASE, Route, build_fetcher, golden_settings

HOME = (
    "<html><head><title>Home</title></head><body><header><nav><ul>"
    '<li><a href="/services/">Services</a></li><li><a href="/about/">About</a></li>'
    "</ul></nav></header><h1>Welcome</h1></body></html>"
)
LEAF = "<html><body><p>Leaf.</p></body></html>"
ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")


def _site(homepage: Route | None) -> dict[str, Route]:
    site = {
        "/robots.txt": ROBOTS,
        "/home/": Route(200, "text/html", HOME),
        "/services/": Route(200, "text/html", LEAF),
        "/about/": Route(200, "text/html", LEAF),
    }
    if homepage is not None:
        site["/"] = homepage
    return site


def _run(
    tmp_path: Path, site: dict[str, Route], *, use_async: bool, sink: object
) -> PageClassificationTool:
    tool = PageClassificationTool(
        fetcher=build_fetcher(golden_settings(tmp_path), site, seed=1 if use_async else None),
        homepage_sink=sink,  # type: ignore[arg-type]
    )
    tool.run(PageClassificationInput(base_url=BASE, use_async_crawl=use_async))
    return tool


@pytest.mark.parametrize("use_async", [True, False], ids=["async", "serial"])
class TestHomepageSink:
    def test_receives_the_redirected_homepage_body_exactly_once(self, tmp_path, use_async):
        """`/` redirects; the body is the landed page's, stored under the requested key."""
        received: list[str] = []
        site = _site(Route(301, "text/html", "", "/home/"))
        _run(tmp_path, site, use_async=use_async, sink=received.append)
        assert received == [HOME]

    def test_receives_a_directly_served_homepage(self, tmp_path, use_async):
        received: list[str] = []
        _run(
            tmp_path,
            _site(Route(200, "text/html", HOME)),
            use_async=use_async,
            sink=received.append,
        )
        assert received == [HOME]

    @pytest.mark.parametrize(
        "homepage",
        [None, Route(200, "application/pdf", "%PDF-1.4")],
        ids=["not-found", "not-html"],
    )
    def test_is_not_called_when_the_homepage_was_never_fetched(self, tmp_path, use_async, homepage):
        received: list[str] = []
        _run(tmp_path, _site(homepage), use_async=use_async, sink=received.append)
        assert received == []

    def test_a_failing_sink_does_not_fail_the_job(self, tmp_path, use_async):
        def explode(_html: str) -> None:
            msg = "disk full"
            raise OSError(msg)

        site = _site(Route(301, "text/html", "", "/home/"))
        tool = PageClassificationTool(
            fetcher=build_fetcher(golden_settings(tmp_path), site, seed=None),
            homepage_sink=explode,
        )
        result = tool.run(PageClassificationInput(base_url=BASE, use_async_crawl=use_async))
        assert result.ok, result.error
        assert result.data is not None
        assert result.data.nav_coverage.nav_entries == 2
