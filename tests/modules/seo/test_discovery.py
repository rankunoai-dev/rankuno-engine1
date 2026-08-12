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


class TestDomBudgetReserve:
    """ADR 0007: a large sitemap must not starve out sitemap-omitted pages.

    Reproduces the live-crawl condition from build-log 0007 §4.1 — a sitemap
    bigger than the node budget — which mocks never hit because fixture sites
    are smaller than any sane ceiling.
    """

    # 12 sitemap URLs, none of which is /code-of-ethics/.
    BIG_SITEMAP = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>https://e.com/sm-{i}/</loc></url>" for i in range(12))
        + "</urlset>"
    )

    HOME = (
        '<html><body><a href="/code-of-ethics/">Ethics</a>'
        '<a href="/human-rights-policy/">Rights</a></body></html>'
    )

    def routes(self) -> dict[str, httpx.Response]:
        table = {
            "/robots.txt": httpx.Response(200, text=ROBOTS),
            "/sitemap.xml": xml(self.BIG_SITEMAP),
            "/": html(self.HOME),
            "/code-of-ethics/": html(LEAF_HTML),
            "/human-rights-policy/": html(LEAF_HTML),
        }
        for i in range(12):
            table[f"/sm-{i}/"] = html(LEAF_HTML)
        return table

    def test_without_a_reserve_the_dom_path_is_starved(self, settings):
        """The pre-fix behaviour, pinned so the regression is unmistakable."""
        _, report = discover_site(
            site_fetcher(self.routes(), settings),
            "https://e.com",
            max_pages=10,
            dom_reserve_fraction=0.0,
        )
        assert report.dom_only == 0, "sitemap consumed the entire budget"

    def test_a_reserve_lets_sitemap_omitted_pages_through(self, settings):
        """The pages an audit actually wants are the ones no sitemap lists."""
        graph, report = discover_site(
            site_fetcher(self.routes(), settings),
            "https://e.com",
            max_pages=10,
            dom_reserve_fraction=0.3,
        )
        found = {node.normalized for node in graph.nodes}
        assert report.dom_only > 0
        assert "https://e.com/code-of-ethics/" in found

    def test_the_reserve_is_reported(self, settings):
        _, report = discover_site(
            site_fetcher(self.routes(), settings),
            "https://e.com",
            max_pages=10,
            dom_reserve_fraction=0.3,
        )
        assert report.dom_reserve == 3
        assert report.dom_reserve_used > 0

    def test_the_hard_ceiling_is_still_absolute(self, settings):
        """The reserve redistributes the budget; it must not enlarge it."""
        graph, _ = discover_site(
            site_fetcher(self.routes(), settings),
            "https://e.com",
            max_pages=10,
            dom_reserve_fraction=0.3,
        )
        assert len(graph) <= 10

    def test_reserve_is_clamped_for_tiny_budgets(self, settings):
        """A 1-page budget must still discover something."""
        graph = SiteGraph("https://e.com", max_pages=1, dom_reserve_fraction=0.9)
        assert graph.pre_crawl_budget >= 1
        assert graph.add("https://e.com/a/", sitemap=True) is not None

    def test_reserve_fraction_is_bounded(self):
        """A fraction above 0.9 would leave the non-DOM paths nothing."""
        graph = SiteGraph("https://e.com", max_pages=100, dom_reserve_fraction=5.0)
        assert graph.dom_reserve <= 90
        assert graph.pre_crawl_budget >= 10


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


class TestBlockedSite:
    """A site that refuses every request must be distinguishable from a small one.

    Observed live: macys.com returned 403 to robots.txt, the sitemap and the
    homepage, and the crawl reported one page classified `HOMEPAGE` at 0.97
    confidence — because the crawl root is seeded as a graph node before the
    first request, and Layer 0 classifies `/` from the URL string alone.
    """

    @staticmethod
    def _forbidden() -> dict[str, httpx.Response]:
        """Every path 403s, as a bot-protected CDN does."""
        return {}

    def test_refusals_are_counted(self, settings):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="<html>Access Denied</html>")

        fetcher = HttpFetcher(
            settings=settings,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(handler),
        )
        _, report = discover_site(fetcher, "https://e.com", max_pages=20)

        assert report.fetch_failures > 0, "a 403 must not vanish into a debug log"
        assert report.pages_fetched == 0
        assert report.sitemaps_fetched == 0

    def test_a_fully_blocked_crawl_reports_retrieving_nothing(self, settings):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="denied")

        fetcher = HttpFetcher(
            settings=settings,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(handler),
        )
        _, report = discover_site(fetcher, "https://e.com", max_pages=20)

        assert report.retrieved_nothing is True
        assert report.total_urls == 1, "only the seed node, which was never fetched"

    def test_a_working_crawl_does_not_report_retrieving_nothing(self, settings):
        _, report = discover_site(site_fetcher(FULL_SITE, settings), "https://e.com")
        assert report.retrieved_nothing is False

    def test_a_sitemap_only_crawl_counts_as_retrieval(self, settings):
        """`crawl_dom=False` fetches no page but is a legitimate, complete run."""
        _, report = discover_site(
            site_fetcher(FULL_SITE, settings), "https://e.com", crawl_dom=False
        )
        assert report.pages_fetched == 0
        assert report.sitemaps_fetched > 0
        assert report.retrieved_nothing is False, "a sitemap is real retrieved data"

    def test_a_non_html_200_is_not_counted_as_a_refusal(self, settings):
        """The server answered; the payload just is not a page.

        Counting it would inflate the refusal count with PDFs and feeds and make
        a genuinely blocked crawl harder to recognise, not easier.
        """
        routes = {
            "/robots.txt": httpx.Response(200, text=ROBOTS),
            "/": httpx.Response(200, text="%PDF-1.4", headers={"content-type": "application/pdf"}),
        }
        _, report = discover_site(site_fetcher(routes, settings), "https://e.com", max_pages=10)
        assert report.fetch_failures == 0


# A WordPress index pointing at both a page sitemap and an attachment sitemap.
# The attachment sitemap is what put every uploaded image into the graph.
MEDIA_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://e.com/page-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://e.com/attachment-sitemap.xml</loc></sitemap>
</sitemapindex>"""

PAGE_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/services/</loc></url>
  <url><loc>https://e.com/v1.0/details</loc></url>
</urlset>"""

ATTACHMENT_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/uploads/hero.jpg</loc></url>
  <url><loc>https://e.com/uploads/logo.png</loc></url>
  <url><loc>https://e.com/uploads/brochure.webp</loc></url>
</urlset>"""

MEDIA_SITE = {
    "/robots.txt": httpx.Response(200, text=ROBOTS),
    "/sitemap.xml": xml(MEDIA_INDEX),
    "/page-sitemap.xml": xml(PAGE_SITEMAP),
    "/attachment-sitemap.xml": xml(ATTACHMENT_SITEMAP),
    "/": html("<html><body><a href='/services/'>S</a></body></html>"),
    "/services/": html(LEAF_HTML),
    "/v1.0/details": html(LEAF_HTML),
}


class TestNonPageFiltering:
    """Media must not enter the graph, whichever path found it.

    `extract_page_links` screened DOM links from the start; the sitemap and CMS
    paths did not, so a WordPress `attachment-sitemap.xml` produced one graph
    node per uploaded image — fetched, then classified UNKNOWN at 0.0.
    """

    def test_the_graph_refuses_media_from_any_path(self):
        graph = SiteGraph("https://e.com")
        assert graph.add("https://e.com/uploads/hero.jpg", sitemap=True) is None
        assert graph.add("https://e.com/logo.png", cms_api=True) is None
        assert graph.add("https://e.com/a.js", dom_link=True) is None
        assert len(graph) == 0
        assert graph.media_skipped == 3

    def test_refusing_media_is_not_recorded_as_truncation(self):
        """Truncation means the ceiling stopped the crawl. This is not that."""
        graph = SiteGraph("https://e.com")
        graph.add("https://e.com/hero.jpg", sitemap=True)
        assert graph.truncated is False

    def test_the_crawl_root_is_exempt(self):
        """An operator who types a media URL gets a report, not an empty graph."""
        graph = SiteGraph("https://e.com/hero.jpg")
        assert graph.add("https://e.com/hero.jpg", dom_link=True) is not None

    def test_pages_with_dotted_paths_still_enter(self):
        graph = SiteGraph("https://e.com")
        assert graph.add("https://e.com/v1.0/details", sitemap=True) is not None

    def test_media_sitemap_entries_are_dropped_end_to_end(self, settings):
        graph, report = discover_site(
            site_fetcher(MEDIA_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.UNKNOWN),
            max_pages=50,
        )
        urls = {node.url for node in graph.nodes}
        assert report.media_skipped == 3
        assert not any(url.endswith((".jpg", ".png", ".webp")) for url in urls)

    def test_a_sitemap_index_is_still_traversed(self, settings):
        """The regression the obvious fix causes.

        Filtering `<loc>` values inside the sitemap parser hits both document
        kinds, and an index's entries are child sitemaps ending in `.xml` — a
        suffix on the non-page list. Applied there, this filter would discard
        every child sitemap and WordPress discovery would return nothing.
        """
        _, report = discover_site(
            site_fetcher(MEDIA_SITE, settings),
            "https://e.com",
            site_profile=SiteProfile(cms_family=CmsFamily.UNKNOWN),
            max_pages=50,
        )
        # index + two children
        assert report.sitemaps_fetched == 3
        assert report.from_sitemap == 2
