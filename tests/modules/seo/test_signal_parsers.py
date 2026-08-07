"""Tests for the five structural consensus signal parsers.

No network and no fixtures on disk: every parser is a pure function over text,
which is exactly what makes them testable at this density.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.schemas import (
    HierarchyLevel,
    PrimaryPageType,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import (
    CmsRecord,
    NavLink,
    PageEvidence,
    collect_structural_signals,
    extract_nav_links,
    parse_aria_nav_signal,
    parse_cms_endpoint_signal,
    parse_jsonld_signal,
    parse_link_indegree_signal,
    parse_sitemap_signal,
)


def evidence(**overrides: object) -> PageEvidence:
    """Build page evidence with sensible defaults."""
    defaults: dict[str, object] = {
        "url": "https://e.com/software/order-to-cash/",
        "normalized_path": "/software/order-to-cash/",
    }
    return PageEvidence(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestNavExtraction:
    def test_extracts_links_from_a_nav_landmark(self):
        html = '<nav><ul><li><a href="/services/">Services</a></li></ul></nav>'
        links = extract_nav_links(html)
        assert len(links) == 1
        assert links[0].href == "/services/"
        assert links[0].text == "Services"
        assert links[0].nav_depth == 0

    def test_nested_dropdown_increases_depth(self):
        html = """
        <nav><ul>
          <li><a href="/services/">Services</a>
            <ul><li><a href="/services/cloud/">Cloud</a></li></ul>
          </li>
        </ul></nav>
        """
        by_href = {link.href: link.nav_depth for link in extract_nav_links(html)}
        assert by_href["/services/"] == 0
        assert by_href["/services/cloud/"] == 1

    def test_reads_hidden_hamburger_menus(self):
        """The headline case: CSS visibility is irrelevant to a DOM parser."""
        html = (
            '<nav class="mobile-menu" style="display:none">'
            '<ul><li><a href="/products/">Products</a></li></ul></nav>'
        )
        assert len(extract_nav_links(html)) == 1

    def test_honours_role_navigation_without_a_nav_tag(self):
        html = '<div role="navigation"><ul><li><a href="/about/">About</a></li></ul></div>'
        assert len(extract_nav_links(html)) == 1

    def test_ignores_links_outside_navigation(self):
        html = '<nav><a href="/in/">in</a></nav><main><a href="/out/">out</a></main>'
        assert [link.href for link in extract_nav_links(html)] == ["/in/"]

    @pytest.mark.parametrize("href", ["#top", "javascript:void(0)", "mailto:a@b.com", "tel:123"])
    def test_skips_non_navigational_hrefs(self, href):
        assert extract_nav_links(f'<nav><a href="{href}">x</a></nav>') == ()

    def test_malformed_markup_does_not_raise(self):
        """A broken page must not abort a 20,000-page crawl."""
        assert isinstance(extract_nav_links("<nav><ul><li><a href=/x>unclosed"), tuple)

    def test_no_navigation_yields_nothing(self):
        assert extract_nav_links("<main><a href='/x/'>x</a></main>") == ()


class TestAriaNavSignal:
    def test_top_level_nav_item_is_a_primary_hub(self):
        signal = parse_aria_nav_signal(
            evidence(
                normalized_path="/services/",
                nav_links=(NavLink(href="/services/", nav_depth=0),),
            )
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L1_PRIMARY_NAV_HUB
        assert signal.source is SignalSource.ARIA_NAV_TREE

    def test_dropdown_item_is_a_sub_hub(self):
        signal = parse_aria_nav_signal(
            evidence(
                normalized_path="/services/cloud/",
                nav_links=(NavLink(href="/services/cloud/", nav_depth=1),),
            )
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L2_SUB_NAV_HUB

    def test_absolute_and_relative_hrefs_match_the_same_page(self):
        signal = parse_aria_nav_signal(
            evidence(
                normalized_path="/services/",
                nav_links=(NavLink(href="https://e.com/services/", nav_depth=0),),
            )
        )
        assert signal is not None

    def test_page_absent_from_navigation_yields_no_opinion(self):
        signal = parse_aria_nav_signal(
            evidence(normalized_path="/blog/post/", nav_links=(NavLink(href="/services/"),))
        )
        assert signal is None

    def test_no_nav_tree_yields_no_opinion(self):
        assert parse_aria_nav_signal(evidence()) is None


class TestCmsEndpointSignal:
    def test_resolves_a_flat_url_via_parent_id(self):
        """The signal that exists specifically for `site.com/capsules`.

        The URL has no path depth to read, but the CMS states a parent, so the
        page is placed beneath it. Childless means leaf, which is why this is
        L3 rather than a hub.
        """
        signal = parse_cms_endpoint_signal(
            evidence(
                normalized_path="/capsules/",
                cms_record=CmsRecord(record_type="page", parent_id=12, parent_url="/products/"),
            )
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L3_LEAF_PAGE
        assert signal.confidence >= 0.9, "a resolved parent is stated, not inferred"

    def test_flat_url_with_children_is_a_sub_hub(self):
        """Same flat URL shape, but it parents other records, so it is a hub."""
        signal = parse_cms_endpoint_signal(
            evidence(
                normalized_path="/capsules/",
                cms_record=CmsRecord(
                    record_type="page", parent_id=12, parent_url="/products/", has_children=True
                ),
            )
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L2_SUB_NAV_HUB

    def test_root_page_with_children_is_a_primary_hub(self):
        signal = parse_cms_endpoint_signal(
            evidence(cms_record=CmsRecord(record_type="page", has_children=True))
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L1_PRIMARY_NAV_HUB

    def test_shopify_product_is_a_leaf(self):
        signal = parse_cms_endpoint_signal(evidence(cms_record=CmsRecord(record_type="product")))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.PRODUCT_DETAIL_PAGE

    def test_shopify_collection_at_root_is_a_primary_hub(self):
        signal = parse_cms_endpoint_signal(
            evidence(cms_record=CmsRecord(record_type="collection", parent_id=None))
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L1_PRIMARY_NAV_HUB

    def test_wordpress_post_is_a_blog_article(self):
        signal = parse_cms_endpoint_signal(evidence(cms_record=CmsRecord(record_type="post")))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.BLOG_ARTICLE

    def test_page_with_children_is_a_hub(self):
        signal = parse_cms_endpoint_signal(
            evidence(cms_record=CmsRecord(record_type="page", has_children=True))
        )
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.SERVICE_CATEGORY_HUB

    def test_no_record_yields_no_opinion(self):
        assert parse_cms_endpoint_signal(evidence()) is None

    def test_is_the_highest_confidence_structural_signal(self):
        """It reads the database; every other signal infers from presentation."""
        cms = parse_cms_endpoint_signal(evidence(cms_record=CmsRecord(record_type="product")))
        sitemap = parse_sitemap_signal(evidence(sitemap_source="product-sitemap.xml"))
        assert cms is not None and sitemap is not None
        assert cms.confidence > sitemap.confidence


class TestSitemapSignal:
    @pytest.mark.parametrize(
        ("filename", "expected_type"),
        [
            ("product-sitemap.xml", PrimaryPageType.PRODUCT_DETAIL_PAGE),
            ("collection-sitemap.xml", PrimaryPageType.PRODUCT_CATEGORY_HUB),
            ("blog-pages-sitemap.xml", PrimaryPageType.BLOG_ARTICLE),
            ("post-sitemap.xml", PrimaryPageType.BLOG_ARTICLE),
            ("case-studies-sitemap.xml", PrimaryPageType.CASE_STUDY),
            ("resource-pages-sitemap.xml", PrimaryPageType.BLOG_ARTICLE),
        ],
    )
    def test_maps_grouped_sitemaps_to_types(self, filename, expected_type):
        signal = parse_sitemap_signal(evidence(sitemap_source=filename))
        assert signal is not None
        assert signal.suggested_page_type is expected_type

    def test_highradius_sitemap_names_are_recognised(self):
        """Real filenames from docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md §2."""
        for name in ("software-pages-o2c-sitemap.xml", "blog-pages-sitemap.xml"):
            assert parse_sitemap_signal(evidence(sitemap_source=name)) is not None

    def test_ungrouped_sitemap_yields_no_opinion(self):
        assert parse_sitemap_signal(evidence(sitemap_source="sitemap1.xml")) is None

    def test_no_sitemap_yields_no_opinion(self):
        assert parse_sitemap_signal(evidence()) is None


class TestJsonLdSignal:
    def test_extracts_a_top_level_type(self):
        html = '<script type="application/ld+json">{"@type": "Product"}</script>'
        signal = parse_jsonld_signal(evidence(html=html))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.PRODUCT_DETAIL_PAGE

    def test_walks_nested_graph_structures(self):
        """Real sites bury the interesting type inside @graph."""
        html = """<script type="application/ld+json">
        {"@context": "https://schema.org", "@graph": [
          {"@type": "WebSite"}, {"@type": "BlogPosting", "headline": "x"}
        ]}</script>"""
        signal = parse_jsonld_signal(evidence(html=html))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.BLOG_ARTICLE

    def test_handles_a_type_array(self):
        html = '<script type="application/ld+json">{"@type": ["Thing", "Service"]}</script>'
        signal = parse_jsonld_signal(evidence(html=html))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.SERVICE_DETAIL_PAGE

    def test_recognises_software_application(self):
        html = '<script type="application/ld+json">{"@type": "SoftwareApplication"}</script>'
        signal = parse_jsonld_signal(evidence(html=html))
        assert signal is not None
        assert signal.suggested_page_type is PrimaryPageType.TOOL_APPLICATION

    def test_malformed_json_is_skipped_not_raised(self):
        html = '<script type="application/ld+json">{broken,</script>'
        assert parse_jsonld_signal(evidence(html=html)) is None

    def test_skips_a_broken_block_and_reads_the_next(self):
        html = (
            '<script type="application/ld+json">{oops</script>'
            '<script type="application/ld+json">{"@type": "Product"}</script>'
        )
        assert parse_jsonld_signal(evidence(html=html)) is not None

    def test_uninformative_types_yield_no_opinion(self):
        html = '<script type="application/ld+json">{"@type": "WebPage"}</script>'
        assert parse_jsonld_signal(evidence(html=html)) is None

    def test_no_html_yields_no_opinion(self):
        assert parse_jsonld_signal(evidence()) is None


class TestLinkInDegreeSignal:
    def test_site_wide_link_count_indicates_a_primary_hub(self):
        signal = parse_link_indegree_signal(
            evidence(inbound_internal_links=1500, total_pages_in_crawl=2000)
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L1_PRIMARY_NAV_HUB

    def test_threshold_scales_down_for_small_sites(self):
        """1,000 inbound links is impossible on a 200-page site."""
        signal = parse_link_indegree_signal(
            evidence(inbound_internal_links=150, total_pages_in_crawl=200)
        )
        assert signal is not None
        assert signal.suggested_level is HierarchyLevel.L1_PRIMARY_NAV_HUB

    def test_ordinary_link_count_yields_no_opinion(self):
        assert (
            parse_link_indegree_signal(
                evidence(inbound_internal_links=12, total_pages_in_crawl=2000)
            )
            is None
        )

    def test_near_orphan_is_reported_weakly(self):
        signal = parse_link_indegree_signal(
            evidence(inbound_internal_links=1, total_pages_in_crawl=500)
        )
        assert signal is not None
        assert signal.confidence < 0.5
        assert "orphan" in signal.notes

    def test_zero_inbound_yields_no_opinion(self):
        assert parse_link_indegree_signal(evidence(inbound_internal_links=0)) is None


class TestCollectStructuralSignals:
    def test_returns_only_signals_that_had_an_opinion(self):
        signals = collect_structural_signals(
            evidence(
                cms_record=CmsRecord(record_type="product"),
                sitemap_source="product-sitemap.xml",
            )
        )
        sources = {s.source for s in signals}
        assert sources == {SignalSource.CMS_API_ENDPOINT, SignalSource.SITEMAP_INDEX}

    def test_no_evidence_yields_no_signals(self):
        assert collect_structural_signals(evidence()) == ()

    def test_never_returns_the_llm_source(self):
        """Layer 3 is an escalation, not a structural parser."""
        signals = collect_structural_signals(evidence(cms_record=CmsRecord(record_type="product")))
        assert all(s.source is not SignalSource.LLM_ZERO_SHOT for s in signals)
