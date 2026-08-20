"""Tests for the record-only redirect and canonical capture.

The property that matters most is what these fields *do not* do: recording a
redirect must leave the graph exactly as it was. Every count the engine reports
hangs off the node keys, and re-pointing a node at its destination would move
all of them in the same change that was supposed to add metadata.
"""

from __future__ import annotations

import pytest
from src.integrations.http_fetcher import FetchResult
from src.modules.seo.page_classifier.discovery import SiteGraph
from src.modules.seo.page_classifier.signal_parsers import extract_canonical_url

BASE = "https://e.com/"
PAGE = "https://e.com/a/b"


def fetched(
    requested: str = PAGE,
    final: str = PAGE,
    chain: tuple[str, ...] = (),
    body: str = "<html></html>",
) -> FetchResult:
    return FetchResult(
        requested_url=requested,
        final_url=final,
        status_code=200,
        content_type="text/html",
        body=body,
        elapsed_ms=1,
        redirect_chain=chain,
    )


class TestCanonicalExtraction:
    """A declaration by the site, read whatever shape it arrives in."""

    @pytest.mark.parametrize(
        "tag",
        [
            '<link rel="canonical" href="https://e.com/x">',
            '<link href="https://e.com/x" rel="canonical">',
            "<link rel='canonical' href='https://e.com/x'>",
            "<link rel=canonical href=https://e.com/x>",
            '<link rel="canonical alternate" href="https://e.com/x">',
            '<LINK REL="CANONICAL" HREF="https://e.com/x">',
        ],
    )
    def test_every_shape_a_site_writes_it_in(self, tag):
        """Attribute order is not fixed and `rel` may carry several tokens.

        A single pattern expecting one order returns nothing for the other, and
        does it silently.
        """
        assert extract_canonical_url(tag, PAGE) == "https://e.com/x"

    def test_a_relative_href_resolves_against_the_page(self):
        assert (
            extract_canonical_url('<link rel="canonical" href="../x">', PAGE) == "https://e.com/x"
        )

    def test_a_page_declaring_none_returns_empty(self):
        """A fact about the page, not a failure. Many sites carry no tag."""
        assert extract_canonical_url('<link rel="stylesheet" href="/a.css">', PAGE) == ""

    def test_a_canonical_built_from_broken_markup_is_refused(self):
        """A site that emits `<a href=` into an address emits it here too.

        Screened with the rule discovered URLs already face, rather than a
        second standard.
        """
        tag = '<link rel="canonical" href="/x/<a href=">'
        assert extract_canonical_url(tag, PAGE) == ""

    def test_only_the_head_is_scanned(self):
        """Bounded so this stays off the critical path at ten thousand pages."""
        buried = "x" * 300_000 + '<link rel="canonical" href="https://e.com/x">'
        assert extract_canonical_url(buried, PAGE) == ""


class TestRecordOnly:
    """The graph must come out of this unchanged."""

    def _graph(self) -> SiteGraph:
        graph = SiteGraph(base_url=BASE, max_pages=100)
        graph.add(PAGE, dom_link=True)
        return graph

    def test_a_redirect_does_not_move_the_node(self):
        """The whole safety argument for shipping this without a re-crawl.

        Re-pointing would merge the node with whatever sits at the destination,
        and inbound links, orphan status and the page total would all move.
        """
        graph = self._graph()
        before = {node.url for node in graph._nodes.values()}

        graph.record_fetch(PAGE, fetched(final="https://e.com/moved", chain=(PAGE,)))

        assert {node.url for node in graph._nodes.values()} == before
        assert graph.report().total_urls == 1

    def test_the_destination_is_kept_beside_the_node(self):
        graph = self._graph()
        graph.record_fetch(PAGE, fetched(final="https://e.com/moved", chain=(PAGE,)))
        (node,) = graph._nodes.values()
        assert node.final_url == "https://e.com/moved"
        assert node.redirect_chain == (PAGE,)

    def test_the_canonical_is_read_from_the_body(self):
        graph = self._graph()
        body = '<html><head><link rel="canonical" href="/c"></head></html>'
        graph.record_fetch(PAGE, fetched(body=body))
        (node,) = graph._nodes.values()
        assert node.canonical_url == "https://e.com/c"

    def test_a_canonical_resolves_against_the_final_url_not_the_requested_one(self):
        """After a redirect, a relative canonical is relative to where we landed."""
        graph = self._graph()
        graph.record_fetch(
            PAGE,
            fetched(final="https://e.com/deep/moved", body='<link rel="canonical" href="x">'),
        )
        (node,) = graph._nodes.values()
        assert node.canonical_url == "https://e.com/deep/x"

    def test_recording_an_unknown_url_is_ignored(self):
        """A URL refused by a filter is fetched by nobody, but be safe anyway."""
        graph = self._graph()
        graph.record_fetch("https://e.com/never-added", fetched())
        assert graph.report().total_urls == 1

    def test_the_fields_reach_page_evidence(self):
        graph = self._graph()
        body = '<link rel="canonical" href="https://e.com/c">'
        graph.store_html(PAGE, body)
        graph.record_fetch(PAGE, fetched(final="https://e.com/f", chain=(PAGE,), body=body))
        (evidence,) = graph.to_page_evidence()
        assert evidence.canonical_url == "https://e.com/c"
        assert evidence.final_url == "https://e.com/f"
        assert evidence.redirect_chain == (PAGE,)
