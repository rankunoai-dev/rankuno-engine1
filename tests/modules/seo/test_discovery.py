"""Tests for the 3-path merged discovery pipeline.

Runs against `httpx.MockTransport` shaped like a real site: a sitemap that
omits pages, a link graph that reaches them, and a CMS that knows their parents.
That combination is the point of merging three paths, so it is what gets tested.
"""

from __future__ import annotations

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.discovery import (
    DiscoveredNode,
    DiscoverySource,
    SiteGraph,
    discover_site,
)
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

PUBLIC_IP = "93.184.216.34"
ROBOTS = "User-agent: *\nDisallow:\n"

# A sitemap listing two pages. Note what it omits: /code-of-ethics/.
SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/services/</loc></url>
  <url><loc>https://e.com/orphaned-campaign/</loc></url>
</urlset>"""

HOME_HTML = """<html><body>
  <a href="/services/">Services</a>
  <a href="/code-of-ethics/">Code of Ethics</a>
</body></html>"""

SERVICES_HTML = '<html><body><a href="/services/cloud/">Cloud</a></body></html>'
LEAF_HTML = "<html><body><p>Leaf page.</p></body></html>"

WP_PAGES = """[
  {"id": 1, "link": "https://e.com/services/", "parent": 0},
  {"id": 2, "link": "https://e.com/services/cloud/", "parent": 1}
]"""


def site_fetcher(routes: dict[str, httpx.Response], settings) -> HttpFetcher:
    """Build a fetcher answering from a fixed path table."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404, text="not found"))

    def resolver(host: str) -> list[str]:
        return [PUBLIC_IP]

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=resolver),
        transport=httpx.MockTransport(handler),
    )


def html(body: str) -> httpx.Response:
    """An HTML 200."""
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def xml(body: str) -> httpx.Response:
    """An XML 200."""
    return httpx.Response(200, text=body, headers={"content-type": "application/xml"})


def json_body(body: str) -> httpx.Response:
    """A JSON 200."""
    return httpx.Response(200, text=body, headers={"content-type": "application/json"})


FULL_SITE = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/sitemap.xml": xml(SITEMAP),
    "/": html(HOME_HTML),
    "/services/": html(SERVICES_HTML),
    "/services/cloud/": html(LEAF_HTML),
    "/code-of-ethics/": html(LEAF_HTML),
    "/orphaned-campaign/": html(LEAF_HTML),
    # Keyed by path only: MockTransport routing here ignores the query string,
    # while the real endpoint is requested with ?per_page=100.
    "/wp-json/wp/v2/pages": json_body(WP_PAGES),
}


class TestSiteGraph:
    def test_merges_sources_for_the_same_url(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/a/", sitemap=True)
        node = graph.add("https://e.com/a/", dom_link=True)
        assert node is not None
        assert node.sources.sitemap is True
        assert node.sources.dom_link is True
        assert node.sources.count == 2
        assert len(graph) == 1

    def test_deduplicates_by_normalised_url(self):
        """Tracking params and trailing slashes must not fork a node."""
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/a")
        graph.add("https://e.com/a/?utm_source=x")
        assert len(graph) == 1

    def test_enforces_the_node_ceiling(self):
        graph = SiteGraph("https://e.com", max_pages=2)
        assert graph.add("https://e.com/1/") is not None
        assert graph.add("https://e.com/2/") is not None
        assert graph.add("https://e.com/3/") is None
        assert graph.truncated is True

    def test_existing_nodes_stay_updatable_at_capacity(self):
        """A full graph must still record new evidence about URLs it holds."""
        graph = SiteGraph("https://e.com", max_pages=1)
        graph.add("https://e.com/a/", sitemap=True)
        node = graph.add("https://e.com/a/", cms_api=True)
        assert node is not None
        assert node.sources.cms_api is True

    def test_records_link_counts_in_both_directions(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/", dom_link=True, depth=0)
        graph.record_links("https://e.com/", ("https://e.com/a/", "https://e.com/b/"), 0)
        nodes = {node.normalized: node for node in graph.nodes}
        assert nodes["https://e.com/"].outbound_links == 2
        assert nodes["https://e.com/a/"].inbound_links == 1

    def test_returns_targets_already_known_from_another_path(self):
        """Regression: returning only graph-new URLs skipped every sitemap page.

        A URL the sitemap already surfaced still has to be *fetched* by the DOM
        crawl. Filtering it out here produced a report full of discovered URLs
        and almost no captured HTML — invisible unless you checked the bodies.
        """
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/a/", sitemap=True)
        graph.add("https://e.com/", dom_link=True)

        recorded = graph.record_links("https://e.com/", ("https://e.com/a/",), 0)
        assert recorded == ["https://e.com/a/"], "already-known URLs must still be crawlable"

    def test_counts_every_inbound_link_including_repeats(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/", dom_link=True)
        graph.record_links("https://e.com/", ("https://e.com/a/",), 0)
        graph.record_links("https://e.com/b/", ("https://e.com/a/",), 0)
        nodes = {node.normalized: node for node in graph.nodes}
        assert nodes["https://e.com/a/"].inbound_links == 2

    def test_keeps_the_shallowest_depth(self):
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/a/", depth=3)
        node = graph.add("https://e.com/a/", depth=1)
        assert node is not None
        assert node.depth == 1

    def test_orphan_detection(self):
        node = DiscoveredNode(url="https://e.com/x/", normalized="https://e.com/x/")
        assert node.is_orphan is True
        assert node.model_copy(update={"inbound_links": 1}).is_orphan is False


class TestMergedDiscovery:
    def test_finds_pages_the_sitemap_omits(self, settings):
        """The HighRadius finding: /code-of-ethics/ is in no sitemap."""
        graph, report = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        by_url = {node.normalized: node for node in graph.nodes}

        ethics = by_url["https://e.com/code-of-ethics/"]
        assert ethics.sources.dom_link is True
        assert ethics.sources.sitemap is False
        assert report.dom_only >= 1

    def test_finds_pages_the_link_graph_omits(self, settings):
        """The reverse gap: an orphaned campaign page nothing links to."""
        graph, report = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        by_url = {node.normalized: node for node in graph.nodes}

        campaign = by_url["https://e.com/orphaned-campaign/"]
        assert campaign.sources.sitemap is True
        assert campaign.is_orphan is True
        assert report.sitemap_only >= 1

    def test_reports_contributions_per_path(self, settings):
        _, report = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        assert report.from_sitemap >= 2
        assert report.from_dom >= 2
        assert report.total_urls >= 4
        assert report.sitemaps_fetched == 1

    def test_cms_path_runs_only_for_a_recognised_platform(self, settings):
        """Probing endpoints that are not there looks like scanning."""
        _, without = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        assert without.from_cms == 0

        _, with_wp = discover_site(
            site_fetcher(FULL_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
        )
        assert with_wp.from_cms >= 2

    def test_cms_records_reach_the_graph(self, settings):
        graph, _ = discover_site(
            site_fetcher(FULL_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
        )
        by_url = {node.normalized: node for node in graph.nodes}
        cloud = by_url["https://e.com/services/cloud/"]
        assert cloud.cms_record is not None
        assert cloud.cms_record.parent_url == "https://e.com/services/"

    def test_dom_crawl_can_be_disabled(self, settings):
        _, report = discover_site(
            site_fetcher(FULL_SITE, settings), "https://e.com", crawl_dom=False
        )
        assert report.pages_fetched == 0
        assert report.from_sitemap >= 2

    def test_respects_the_depth_ceiling(self, settings):
        _, shallow = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com", max_depth=0)
        assert shallow.pages_fetched == 1

    def test_reports_truncation_rather_than_hiding_it(self, settings):
        _, report = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com", max_pages=2)
        assert report.truncated is True
        assert report.total_urls == 2

    def test_a_full_graph_still_fetches_pages(self, settings):
        """Regression, found by the first live crawl of highradius.com.

        Capacity must stop *discovering* new nodes, not stop *fetching* known
        ones. When the sitemap alone filled the budget, the DOM crawl fetched
        nothing: 40 URLs discovered, zero pages retrieved.
        """
        graph, report = discover_site(
            site_fetcher(FULL_SITE, settings), "https://e.com", max_pages=2
        )
        assert report.pages_fetched > 0, "a full graph must still fetch what it knows about"
        assert any(item.html for item in graph.to_page_evidence())

    def test_survives_a_site_with_nothing_at_all(self, settings):
        fetcher = site_fetcher({"/robots.txt": httpx.Response(200, text=ROBOTS)}, settings)
        graph, report = discover_site(fetcher, "https://e.com")
        assert report.total_urls >= 0
        assert isinstance(graph, SiteGraph)

    def test_a_broken_sitemap_does_not_stop_discovery(self, settings):
        routes = dict(FULL_SITE)
        routes["/sitemap.xml"] = xml("<urlset><unclosed>")
        _, report = discover_site(site_fetcher(routes, settings), "https://e.com")
        assert report.from_dom >= 2, "the DOM crawl must still run"


class TestPageEvidenceProduction:
    def test_produces_evidence_the_signal_parsers_can_consume(self, settings):
        """The join between discovery and classification — this module's purpose."""
        graph, _ = discover_site(
            site_fetcher(FULL_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
        )
        evidence = graph.to_page_evidence()
        assert len(evidence) == len(graph)

        by_url = {item.normalized_path: item for item in evidence}
        cloud = by_url["https://e.com/services/cloud/"]
        assert cloud.cms_record is not None
        assert cloud.total_pages_in_crawl == len(graph)

    def test_carries_sitemap_source_through_for_signal_three(self, settings):
        graph, _ = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        evidence = {item.normalized_path: item for item in graph.to_page_evidence()}
        assert evidence["https://e.com/services/"].sitemap_source == "sitemap.xml"

    def test_carries_link_counts_through_for_signal_five(self, settings):
        graph, _ = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        evidence = {item.normalized_path: item for item in graph.to_page_evidence()}
        assert evidence["https://e.com/services/"].inbound_internal_links >= 1

    def test_retains_html_for_dom_based_signals(self, settings):
        graph, _ = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        evidence = {item.normalized_path: item for item in graph.to_page_evidence()}
        assert evidence["https://e.com/services/"].html is not None

    def test_crawl_size_can_be_overridden_for_in_degree_scaling(self, settings):
        graph, _ = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        evidence = graph.to_page_evidence(total_pages=50_000)
        assert all(item.total_pages_in_crawl == 50_000 for item in evidence)


class TestEndToEnd:
    def test_discovery_output_classifies_without_further_wiring(self, settings):
        """Proves the contract actually joins: discovery → parsers → profile."""
        from src.modules.seo.page_classifier.cascading_pipeline import classify_page

        graph, _ = discover_site(
            site_fetcher(FULL_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.WORDPRESS),
        )
        profiles = [classify_page(item) for item in graph.to_page_evidence()]

        assert len(profiles) == len(graph)
        assert all(profile.signals_evaluated for profile in profiles), "every page auditable"

    def test_sources_model_counts_agreement(self):
        assert DiscoverySource(sitemap=True, dom_link=True, cms_api=True).count == 3
        assert DiscoverySource().count == 0


@pytest.mark.parametrize("base", ["https://e.com", "https://e.com/"])
def test_trailing_slash_on_base_url_is_tolerated(base, settings):
    _, report = discover_site(site_fetcher(FULL_SITE, settings), base)
    assert report.total_urls >= 4
