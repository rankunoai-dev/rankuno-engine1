"""What the crawl reads from a body at fetch time equals what the body yields later.

P3 of extract-at-fetch. Breadcrumb section labels and schema.org types are read
in `SiteGraph.store_html` instead of after the crawl. Bodies are still retained
in this phase, which is what makes the comparison possible: every assertion
here derives the value from the retained body the way the post-crawl code used
to, and requires the stored value to match it exactly.

The strongest check is the last class: the whole tool, run with every body
stripped from the evidence, must still reproduce the golden snapshot. That is
the classification half of P4's claim, proven before any body is released.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from src.modules.seo.page_classifier import signal_parsers
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.breadcrumb_parser import extract_breadcrumb
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from src.modules.seo.page_classifier.signal_parsers import (
    PageEvidence,
    extract_schema_types,
    parse_jsonld_signal,
)

from tests.modules.seo.golden_site_factory import (
    BASE,
    Route,
    build_fetcher,
    build_site,
    golden_settings,
)
from tests.modules.seo.test_fetched_set import _loop_urls
from tests.modules.seo.test_golden_extract_at_fetch import (
    assert_identical,
    canonical,
    run_tool,
)
from tests.modules.seo.test_golden_extract_at_fetch import (
    snapshot as snapshot,  # the pytest fixture, re-exported for this module
)

PATHS = pytest.mark.parametrize("seed", [None, 1, 2], ids=["serial", "async-1", "async-2"])


def crawl(tmp_path: Path, site: dict[str, Route], *, seed: int | None) -> SiteGraph:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=seed)
    if seed is None:
        return discover_site(fetcher, BASE)[0]

    async def scenario() -> SiteGraph:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE))[0]

    return asyncio.run(scenario())


def body_labels(graph: SiteGraph, html: str | None, node_url: str) -> tuple[str, ...]:
    """The reading `to_page_evidence` made before P3, verbatim."""
    trail = extract_breadcrumb(html, node_url) if html else None
    return trail.section_labels(graph.base_url, node_url) if trail else ()


def body_types(html: str | None) -> tuple[str, ...]:
    """Every declared type Signal 4 would walk, filtered to those it recognises."""
    if not html:
        return ()
    walked = signal_parsers._iter_declared_types(html)
    return tuple(name for name in walked if signal_parsers._recognised(name) is not None)


def assert_stored_matches_bodies(graph: SiteGraph) -> None:
    for node in graph.nodes:
        html = graph.html_for(node.url)
        assert graph._breadcrumbs.get(node.normalized, ()) == body_labels(graph, html, node.url)
        assert graph._jsonld_types.get(node.normalized, ()) == body_types(html), node.url
    # Nothing is held for a node the graph no longer has, or never fetched.
    assert set(graph._breadcrumbs) <= graph._fetched
    assert set(graph._jsonld_types) <= graph._fetched
    assert all(graph._breadcrumbs.values()) and all(graph._jsonld_types.values())


class TestStoredEqualsTheBody:
    @PATHS
    def test_across_the_golden_site(self, tmp_path, seed):
        graph = crawl(tmp_path, build_site(), seed=seed)
        assert graph._breadcrumbs, "the fixture publishes breadcrumbs"
        assert graph._jsonld_types, "the fixture declares schema types"
        assert_stored_matches_bodies(graph)

    @PATHS
    def test_signal_4_reads_the_same_with_or_without_the_body(self, tmp_path, seed):
        graph = crawl(tmp_path, build_site(), seed=seed)
        evidence = graph.to_page_evidence()
        assert any(parse_jsonld_signal(item) for item in evidence)
        for item in evidence:
            stripped = item.model_copy(update={"html": None})
            assert parse_jsonld_signal(stripped) == parse_jsonld_signal(item), item.url

    @pytest.mark.parametrize("seed", [None, 1], ids=["serial", "async"])
    def test_a_redirected_page_resolves_its_trail_against_its_own_url(self, tmp_path, seed):
        """`../` from `/moved/` is the root (dropped); from `/deep/landing/` it is not."""
        trail = (
            '<nav aria-label="breadcrumb"><ol><li><a href="../">Parent</a></li>'
            '<li><a href="./">Here</a></li></ol></nav>'
        )
        site = {
            "/robots.txt": Route(200, "text/plain", "User-agent: *\nDisallow:\n"),
            "/": Route(200, "text/html", '<a href="/moved/">m</a>'),
            "/moved/": Route(301, "text/html", "", "/deep/landing/"),
            "/deep/landing/": Route(200, "text/html", trail),
        }
        graph = crawl(tmp_path, site, seed=seed)
        assert graph.landed_url(f"{BASE}/moved/") == f"{BASE}/deep/landing/"
        assert f"{BASE}/moved/" not in graph._breadcrumbs
        assert_stored_matches_bodies(graph)


class TestSchemaTypes:
    TWO_TYPES = (
        '<script type="application/ld+json">{"@type": "BreadcrumbList", "itemListElement":'
        ' [{"@type": "ListItem"}]}</script>'
        '<script type="application/ld+json">{"@graph": [{"@type": "Article"},'
        ' {"@type": ["Thing", "Product"]}]}</script>'
        '<script type="application/ld+json">{"@type": "Product",</script>'
        '<script type="application/ld+json">{"@type": "https://schema.org/FAQPage"}</script>'
    )

    def test_keeps_recognised_types_verbatim_in_document_order(self):
        assert extract_schema_types(self.TWO_TYPES) == (
            "Article",
            "Product",
            "https://schema.org/FAQPage",
        )

    def test_the_first_recognised_type_still_wins_without_the_body(self):
        with_body = PageEvidence(url=f"{BASE}/x/", normalized_path="/x/", html=self.TWO_TYPES)
        without = PageEvidence(
            url=f"{BASE}/x/",
            normalized_path="/x/",
            jsonld_types=extract_schema_types(self.TWO_TYPES),
        )
        assert parse_jsonld_signal(with_body) == parse_jsonld_signal(without)
        signal = parse_jsonld_signal(without)
        assert signal is not None
        assert signal.notes == "schema.org @type 'Article'"

    def test_a_block_too_deep_to_parse_is_skipped_not_raised(self):
        deep = "[" * 100_000 + "]" * 100_000
        html = (
            f'<script type="application/ld+json">{deep}</script>'
            '<script type="application/ld+json">{"@type": "Product"}</script>'
        )
        assert extract_schema_types(html) == ("Product",)

    def test_html_still_wins_when_present(self):
        """A corpus row carries HTML only; stored types must not override it."""
        evidence = PageEvidence(
            url=f"{BASE}/x/",
            normalized_path="/x/",
            html='<script type="application/ld+json">{"@type": "Product"}</script>',
            jsonld_types=("Article",),
        )
        signal = parse_jsonld_signal(evidence)
        assert signal is not None
        assert signal.notes == "schema.org @type 'Product'"


class TestSideTablesFollowTheNode:
    PAGE = (
        '<script type="application/ld+json">{"@type": "Product"}</script>'
        '<nav aria-label="breadcrumb"><ol><li><a href="/shop/">Shop</a></li></ol></nav>'
    )

    def test_eviction_drops_every_side_table_entry(self):
        graph = SiteGraph(BASE)
        urls = _loop_urls()
        graph.add(urls[0], dom_link=True)
        graph.store_html(urls[0], self.PAGE)
        assert urls[0] in graph._breadcrumbs, "precondition"
        assert urls[0] in graph._jsonld_types, "precondition"
        for url in urls[1:]:
            graph.add(url, dom_link=True)
        assert graph.loop_urls_skipped > 0
        assert urls[0] not in graph._breadcrumbs
        assert urls[0] not in graph._jsonld_types

    def test_store_keeps_document_order_through_to_the_signal(self):
        """The golden site declares one recognised type per page, so it cannot see order."""
        graph = SiteGraph(BASE)
        graph.add(f"{BASE}/x/", dom_link=True)
        graph.store_html(f"{BASE}/x/", TestSchemaTypes.TWO_TYPES)
        assert graph._jsonld_types[f"{BASE}/x/"] == body_types(TestSchemaTypes.TWO_TYPES)
        (evidence,) = (item for item in graph.to_page_evidence() if item.url == f"{BASE}/x/")
        signal = parse_jsonld_signal(evidence.model_copy(update={"html": None}))
        assert signal is not None
        assert signal.notes == "schema.org @type 'Article'"

    def test_an_empty_body_stores_nothing(self):
        graph = SiteGraph(BASE)
        graph.add(f"{BASE}/empty/", dom_link=True)
        graph.store_html(f"{BASE}/empty/", self.PAGE)
        graph.store_html(f"{BASE}/empty/", "")
        assert graph._breadcrumbs == {}
        assert graph._jsonld_types == {}

    def test_a_url_with_no_node_stores_nothing(self):
        graph = SiteGraph(BASE)
        graph.store_html(f"{BASE}/never-added/", self.PAGE)
        assert graph._breadcrumbs == {}
        assert graph._jsonld_types == {}


class TestClassificationWithoutBodies:
    """The tool reproduces the golden snapshot when no evidence carries a body."""

    @pytest.mark.parametrize("seed", [None, 1], ids=["serial", "async"])
    def test_matches_the_snapshot(self, tmp_path, monkeypatch, snapshot, seed):
        real = SiteGraph.to_page_evidence

        def stripped(self: SiteGraph, total_pages: int | None = None) -> tuple[Any, ...]:
            return tuple(item.model_copy(update={"html": None}) for item in real(self, total_pages))

        monkeypatch.setattr(SiteGraph, "to_page_evidence", stripped)
        output = run_tool(golden_settings(tmp_path), build_site(), seed=seed)
        assert_identical(
            {"tool": json.loads(canonical(output))},
            {"tool": snapshot["tool"]},
            "body-free classification",
        )
