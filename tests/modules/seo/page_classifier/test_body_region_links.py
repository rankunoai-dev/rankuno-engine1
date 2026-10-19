"""The body-region link reading (ADR 0038): which links sit in the content.

Three things are pinned here. The flat link list is unchanged, because the
discovery graph and every existing count are built from it. The region rule
(first `<main>`, else first `<article>`, else the whole document) selects the
right links. And a target's `unique_content_inlinks` counts distinct source
pages, so a page that links twice still contributes once.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier import discovery as discovery_module
from src.modules.seo.page_classifier.discovery import SiteGraph
from src.modules.seo.page_classifier.discovery_parsers import (
    LinkReading,
    extract_page_links,
    read_page_links,
)

BASE = "https://e.com/"

SITE_CHROME = (
    '<header><a href="/home-link/">Home</a></header><nav><a href="/nav-link/">Nav</a></nav>'
)
CONTENT = '<a href="/content-a/">A</a> <a href="/content-b/">B</a>'
FOOTER = '<footer><a href="/footer-link/">Footer</a></footer>'
PAGE_WITH_MAIN = f"<html><body>{SITE_CHROME}<main>{CONTENT}</main>{FOOTER}</body></html>"


def _abs(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://e.com{path}" for path in paths)


class TestTheFlatListIsUnchanged:
    """`extract_page_links` is defined as the region reading's `links`, so it cannot drift."""

    DOCUMENTS = (
        PAGE_WITH_MAIN,
        '<a href="/x/">x</a><a href="/x/">again</a><a href="/y/#frag">y</a>',
        '<article><a href="/a1/">a</a></article><a href="/outside/">o</a>',
        "",
        '<main><a href="/unclosed/">u</a>',
        '<base href="/base/"><a href="rel/">r</a>',
    )

    def test_the_flat_list_equals_extract_page_links_for_every_document(self):
        for html in self.DOCUMENTS:
            assert read_page_links(html, BASE).links == extract_page_links(html, BASE), html

    def test_the_body_subset_is_always_a_subset_of_the_links_without_repeats(self):
        for html in self.DOCUMENTS:
            reading = read_page_links(html, BASE)
            assert set(reading.body_links) <= set(reading.links), html
            assert len(reading.body_links) == len(set(reading.body_links)), html


class TestTheMainRegionCountsContentOnly:
    def test_header_nav_and_footer_links_are_outside_the_body(self):
        reading = read_page_links(PAGE_WITH_MAIN, BASE)
        assert reading.body_links == _abs("/content-a/", "/content-b/")
        chrome = _abs("/home-link/", "/nav-link/", "/footer-link/")
        assert set(chrome).issubset(reading.links), "chrome links are still in the flat list"

    def test_a_link_in_both_header_and_main_is_a_body_link_once(self):
        html = '<header><a href="/shared/">top</a></header><main><a href="/shared/">in</a></main>'
        reading = read_page_links(html, BASE)
        assert reading.links == _abs("/shared/")
        assert reading.body_links == _abs("/shared/")

    def test_only_the_first_main_element_is_the_region(self):
        html = '<main><a href="/first/">1</a></main><main><a href="/second/">2</a></main>'
        reading = read_page_links(html, BASE)
        assert reading.links == _abs("/first/", "/second/")
        assert reading.body_links == _abs("/first/")

    def test_an_unclosed_main_runs_to_the_last_link(self):
        reading = read_page_links('<main><a href="/a/">a</a><a href="/b/">b</a>', BASE)
        assert reading.body_links == _abs("/a/", "/b/")


class TestArticleAndWholeBodyFallbacks:
    def test_without_main_the_first_article_is_the_region(self):
        html = (
            '<header><a href="/top/">top</a></header>'
            '<article><a href="/story/">story</a></article>'
            '<footer><a href="/foot/">foot</a></footer>'
        )
        assert read_page_links(html, BASE).body_links == _abs("/story/")

    def test_main_wins_over_an_article_that_comes_first(self):
        html = '<article><a href="/article/">a</a></article><main><a href="/main/">m</a></main>'
        assert read_page_links(html, BASE).body_links == _abs("/main/")

    def test_a_page_with_neither_tag_counts_links_from_the_whole_body(self):
        """The inflation the column note warns about: header and footer links count here."""
        html = (
            '<header><a href="/top/">top</a></header>'
            '<div><a href="/content/">c</a></div>'
            '<footer><a href="/foot/">foot</a></footer>'
        )
        reading = read_page_links(html, BASE)
        assert reading.body_links == reading.links == _abs("/top/", "/content/", "/foot/")

    def test_a_document_with_no_links_has_an_empty_body(self):
        assert read_page_links("<main><p>no links</p></main>", BASE) == LinkReading((), ())


class TestCapReadingKeepsTheBodySubsetInStep:
    def test_a_body_link_beyond_the_cap_is_dropped_with_its_outbound_link(self, monkeypatch):
        monkeypatch.setattr(discovery_module, "MAX_LINKS_PER_PAGE", 2)
        graph = SiteGraph("https://e.com")
        reading = LinkReading(_abs("/one/", "/two/", "/three/"), _abs("/two/", "/three/"))
        capped = graph.cap_reading(BASE, reading, count=False)
        assert capped.links == _abs("/one/", "/two/")
        assert capped.body_links == _abs("/two/")

    def test_an_uncapped_reading_is_returned_unchanged(self):
        graph = SiteGraph("https://e.com")
        reading = LinkReading(_abs("/one/"), _abs("/one/"))
        assert graph.cap_reading(BASE, reading) is reading


class TestUniqueContentInlinksCountsDistinctSources:
    @staticmethod
    def _link(graph: SiteGraph, source: str, html: str) -> None:
        reading = read_page_links(html, source)
        graph.record_links(source, reading.links, 0, reading.body_links)

    @staticmethod
    def _node(graph: SiteGraph, path: str):  # noqa: ANN205 - a DiscoveredNode, typed by the graph
        return {node.normalized: node for node in graph.nodes}[f"https://e.com{path}"]

    def test_a_page_linking_twice_in_content_counts_once(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/", dom_link=True)
        graph.add("https://e.com/target/", dom_link=True)
        twice = '<main><a href="/target/">one</a><a href="/target/">two</a></main>'
        self._link(graph, "https://e.com/", twice)
        target = self._node(graph, "/target/")
        assert target.unique_content_inlinks == 1
        assert target.inbound_links == 1

    def test_distinct_content_sources_add_up_and_header_links_do_not(self):
        graph = SiteGraph("https://e.com")
        for path in ("/", "/a/", "/b/", "/c/", "/target/"):
            graph.add(f"https://e.com{path}", dom_link=True)
        in_main = '<main><a href="/target/">t</a></main>'
        self._link(graph, "https://e.com/", in_main)
        self._link(graph, "https://e.com/a/", in_main)
        # A `<main>` with no links: the region exists, so the header link is outside it.
        self._link(
            graph,
            "https://e.com/b/",
            '<header><a href="/target/">t</a></header><main>no links here</main>',
        )
        self._link(graph, "https://e.com/c/", '<article><a href="/target/">t</a></article>')
        target = self._node(graph, "/target/")
        assert target.inbound_links == 4, "the sitewide count still sees every link"
        assert target.unique_content_inlinks == 3, "the header-only link is excluded"

    def test_a_page_records_its_body_link_count_and_a_fresh_node_starts_at_zero(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/", dom_link=True)
        fresh = graph.add("https://e.com/new/", dom_link=True)
        assert fresh is not None
        assert fresh.unique_content_inlinks == 0
        self._link(
            graph,
            "https://e.com/",
            '<header><a href="/h/">h</a></header><main><a href="/m/">m</a></main>',
        )
        home = self._node(graph, "/")
        assert home.body_link_count == 1
        assert home.outbound_links == 2

    @pytest.mark.parametrize("path", ["/", "/a/"])
    def test_an_unfetched_node_has_no_body_link_count(self, path: str):
        graph = SiteGraph("https://e.com")
        graph.add(f"https://e.com{path}", dom_link=True)
        assert self._node(graph, path).body_link_count is None
