"""What the crawl records about canonicals, links and breadcrumbs (ADR 0038).

Each fact is read from data the fetch already had, in the same pass that reads
the value it accompanies. These tests drive the graph's record methods directly,
so they pin the stored values the export derives from, without any network.
"""

from __future__ import annotations

from src.integrations.http_fetcher import FetchResult
from src.modules.seo.page_classifier.discovery import SiteGraph
from src.modules.seo.page_classifier.signal_parsers import extract_canonical_declarations

BASE = "https://e.com/"
PAGE = "https://e.com/a/"
CANON = '<link rel="canonical" href="https://e.com/a/">'
OTHER = '<link rel="canonical" href="https://e.com/elsewhere/">'


def _result(body: str, *, content_type: str = "text/html", url: str = PAGE) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type=content_type,
        body=body,
        elapsed_ms=1,
    )


def _graph_with(url: str = PAGE) -> SiteGraph:
    graph = SiteGraph(BASE)
    graph.add(url, dom_link=True)
    return graph


def _node(graph: SiteGraph, url: str = PAGE):  # noqa: ANN202 - a DiscoveredNode
    return {node.normalized: node for node in graph.nodes}[url]


class TestDeclarationsAreCountedInTheSameScanAsTheValue:
    def test_one_declaration_is_declared_and_counted_once(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(f"<html><head>{CANON}</head></html>"))
        node = _node(graph)
        assert node.canonical_declared is True
        assert node.canonical_link_count == 1
        assert node.canonical_url == PAGE

    def test_two_declarations_are_counted_and_the_first_is_the_value(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(f"<head>{OTHER}{CANON}</head>"))
        node = _node(graph)
        assert node.canonical_link_count == 2
        assert node.canonical_url == "https://e.com/elsewhere/", "the value is still the first tag"

    def test_an_undeclared_page_is_recorded_as_undeclared_not_as_self(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result("<html><head></head><body>no canonical</body></html>"))
        node = _node(graph)
        assert node.canonical_declared is False
        assert node.canonical_link_count == 0
        assert node.canonical_url == ""

    def test_an_empty_html_body_is_read_and_declares_nothing(self):
        """Fetched, and the server answered with a page: a measured zero, not unknown."""
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(""))
        node = _node(graph)
        assert node.canonical_declared is False
        assert node.canonical_link_count == 0

    def test_a_non_html_answer_leaves_every_link_fact_unrecorded(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result("%PDF-1.4", content_type="application/pdf"))
        node = _node(graph)
        assert node.canonical_declared is None
        assert node.canonical_link_count is None
        assert node.body_link_count is None

    def test_a_declaration_with_an_empty_href_is_not_a_declaration(self):
        assert extract_canonical_declarations('<link rel="canonical" href="">', PAGE) == ()

    def test_an_over_long_declaration_is_counted_but_not_declared(self):
        """Counted, because the tag is there; not declared, because nothing usable names the page.

        The profile cannot hold an empty canonical, so the declared flag is what stops it
        being read as a self-declaration.
        """
        long_href = "https://e.com/" + "a" * 2100
        declared = extract_canonical_declarations(
            f'<link rel="canonical" href="{long_href}">', PAGE
        )
        assert declared == ("",)
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(f'<head><link rel="canonical" href="{long_href}"></head>'))
        node = _node(graph)
        assert node.canonical_link_count == 1
        assert node.canonical_declared is False
        assert node.canonical_url == ""


class TestTheBreadcrumbParentIsStoredWhenTheBodyIsRead:
    CRUMBS = (
        '<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"},'
        '{"@type":"ListItem","position":2,"name":"Post","item":"https://e.com/a/"}]}'
        "</script>"
    )

    def test_a_read_page_with_a_parent_stores_that_parent(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(f"<html><head>{self.CRUMBS}</head></html>"))
        graph.store_html(PAGE, f"<html><head>{self.CRUMBS}</head></html>")
        assert _node(graph).breadcrumb_parent_url == "https://e.com/"

    def test_a_read_page_with_no_breadcrumb_stores_the_empty_string(self):
        """`""` is "read, none", which the report must tell apart from `None`, "not read"."""
        graph = _graph_with()
        graph.record_fetch(PAGE, _result("<html><body>x</body></html>"))
        graph.store_html(PAGE, "<html><body>x</body></html>")
        assert _node(graph).breadcrumb_parent_url == ""

    def test_an_empty_html_body_is_read_and_stores_the_empty_string(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result(""))
        graph.store_html(PAGE, "")
        assert _node(graph).breadcrumb_parent_url == ""

    def test_a_page_whose_body_was_never_stored_keeps_none(self):
        graph = _graph_with()
        graph.record_fetch(PAGE, _result("%PDF", content_type="application/pdf"))
        assert _node(graph).breadcrumb_parent_url is None


class TestTheStoredParentIsCountedInTheBudget:
    def test_a_released_page_pays_for_its_parent_url(self):
        graph = SiteGraph(BASE, release_bodies=True)
        graph.add(PAGE, dom_link=True)
        crumbs = (
            '<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":['
            '{"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"},'
            '{"@type":"ListItem","position":2,"name":"Post"}]}</script>'
        )
        graph.record_fetch(PAGE, _result(crumbs))
        before = graph.retained_page_bytes(PAGE)
        graph.store_html(PAGE, crumbs)
        assert _node(graph).breadcrumb_parent_url == "https://e.com/"
        assert graph.retained_page_bytes(PAGE) > before
