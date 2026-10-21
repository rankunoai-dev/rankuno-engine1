"""`depth_from_l0` is the BFS click distance from the homepage, not path depth.

Before this cycle the exported value was `depth_of(normalized_path)`, and
`normalized_path` holds a whole URL, so `https:` and the host were counted as
two path segments: the homepage exported 2 and every page exported its click
distance plus two. The link crawl had already recorded the true distance on each
graph node and then dropped it at the join into classification.

These tests run a real discovery pass over a stub site (no network), join it to
the classifier exactly as `tool.py` does, and read the exported field. They do
not go through `make_page`, which hard-codes the value.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.config import Settings
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.cascading_pipeline import classify_page
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from src.modules.seo.page_classifier.navigation_context import NavigationContextClassifier
from src.modules.seo.page_classifier.report_pdf import pdf_row
from src.modules.seo.page_classifier.schemas import MAX_CRAWL_DEPTH
from src.modules.seo.page_classifier.signal_parsers import PageEvidence
from tests.modules.seo.golden_site_factory import (
    BASE,
    Route,
    build_fetcher,
    golden_settings,
)
from tests.modules.seo.page_classifier.report_profile_factory import make_page

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")


def _page(*links: str) -> Route:
    anchors = "".join(f'<a href="{href}">link</a>' for href in links)
    return Route(
        200,
        "text/html; charset=utf-8",
        f"<!doctype html><html><head></head><body>{anchors}<p>page</p></body></html>",
    )


# Home -> /a/ -> /a/b/ -> /a/b/c/ is three clicks. /about-us/ is one click.
# /unlinked/ appears in the sitemap and no page links to it: it has no click
# distance at all, however short or long its path is.
SITE: dict[str, Route] = {
    "/robots.txt": ROBOTS,
    "/": _page("/a/", "/about-us/"),
    "/a/": _page("/a/b/"),
    "/a/b/": _page("/a/b/c/"),
    "/a/b/c/": _page(),
    "/about-us/": _page(),
    "/unlinked/": _page(),
    "/sitemap.xml": Route(
        200,
        "application/xml",
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE}/unlinked/</loc></url></urlset>",
    ),
}


def _exported(graph: SiteGraph) -> dict[str, int | None]:
    """The `depth_from_l0` the classifier exports, keyed by normalised path."""
    return {ev.normalized_path: classify_page(ev).depth_from_l0 for ev in graph.to_page_evidence()}


def _serial_graph(tmp_path: Path, site: dict[str, Route]) -> SiteGraph:
    settings: Settings = golden_settings(tmp_path)
    return discover_site(build_fetcher(settings, site), BASE)[0]


def test_the_homepage_exports_zero_and_each_click_exports_its_distance(tmp_path: Path) -> None:
    depths = _exported(_serial_graph(tmp_path, SITE))

    assert depths[f"{BASE}/"] == 0
    assert depths[f"{BASE}/a/"] == 1
    assert depths[f"{BASE}/about-us/"] == 1
    assert depths[f"{BASE}/a/b/"] == 2, "a two-click page exports 2, not its path depth plus two"
    assert depths[f"{BASE}/a/b/c/"] == 3


def test_the_async_crawl_exports_the_same_distances(tmp_path: Path) -> None:
    settings = golden_settings(tmp_path)
    fetcher = build_fetcher(settings, SITE, seed=3)

    async def scenario() -> SiteGraph:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE))[0]

    depths = _exported(asyncio.run(scenario()))

    assert depths[f"{BASE}/"] == 0
    assert depths[f"{BASE}/a/b/"] == 2
    assert depths[f"{BASE}/a/b/c/"] == 3


def test_a_page_no_link_reaches_exports_no_distance_rather_than_its_path_depth(
    tmp_path: Path,
) -> None:
    """Path depth of `/unlinked/` is 1, which would be a false click distance."""
    depths = _exported(_serial_graph(tmp_path, SITE))

    assert f"{BASE}/unlinked/" in depths
    assert depths[f"{BASE}/unlinked/"] is None


def test_a_click_distance_beyond_the_schema_ceiling_saturates_at_it() -> None:
    """Link chains are not path-limited, so the BFS can exceed `MAX_CRAWL_DEPTH`."""
    deep = PageEvidence(
        url=f"{BASE}/p/",
        normalized_path=f"{BASE}/p/",
        depth=MAX_CRAWL_DEPTH + 5,
    )

    assert classify_page(deep).depth_from_l0 == MAX_CRAWL_DEPTH


def test_evidence_without_a_recorded_level_exports_none() -> None:
    """Screaming Frog imports and other evidence the crawl never walked."""
    page = PageEvidence(url=f"{BASE}/x/", normalized_path=f"{BASE}/x/")

    assert classify_page(page).depth_from_l0 is None


def test_an_unknown_distance_does_not_break_navigation_enrichment() -> None:
    """Navigation compares depth with `>= 3`; `None` must take the fallback path."""
    page = NavigationContextClassifier().enrich(
        make_page(f"{BASE}/x/", depth_from_l0=None, inbound_internal_links_count=0)
    )

    assert page.depth_from_l0 is None
    assert page.navigation_reachability_tier is not None


def test_an_unknown_distance_is_shown_as_a_dash_in_the_pdf() -> None:
    row = pdf_row(make_page(f"{BASE}/x/", depth_from_l0=None))

    assert "—" in row
    assert "None" not in row
