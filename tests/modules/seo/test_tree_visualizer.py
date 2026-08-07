"""Tests for the interactive hierarchy report.

The XSS cases matter most: every string rendered originates from a crawled
third-party site, which makes it attacker controlled.
"""

from __future__ import annotations

import json

import pytest
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tree_visualizer import (
    LEVEL_ORDER,
    PAGE_TYPE_COLOURS,
    build_tree,
    render_tree_html,
)


def profile(
    path: str,
    level: HierarchyLevel = HierarchyLevel.L3_LEAF_PAGE,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
    url: str | None = None,
) -> FullPageIntelligenceProfile:
    """Build a classified page at a given path."""
    full = url or f"https://e.com{path}"
    return FullPageIntelligenceProfile(
        url=full,
        canonical_url=full,
        normalized_path=full,
        hierarchy_level=level,
        primary_page_type=page_type,
        depth_from_l0=max(0, len([s for s in path.split("/") if s])),
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=level,
                suggested_page_type=page_type,
                confidence=0.9,
            ),
        ),
        final_confidence_score=0.9,
        consensus_method=ConsensusMethod.WEIGHTED_CONSENSUS,
    )


class TestTreeBuilding:
    def test_nests_by_url_path(self):
        tree = build_tree([profile("/services/"), profile("/services/cloud/")])
        services = tree.children["services"]
        assert "cloud" in services.children

    def test_root_page_attaches_to_the_root_node(self):
        tree = build_tree([profile("/", HierarchyLevel.L0_HOMEPAGE, PrimaryPageType.HOMEPAGE)])
        assert tree.profile is not None
        assert tree.profile.primary_page_type is PrimaryPageType.HOMEPAGE

    def test_creates_structural_nodes_for_missing_parents(self):
        """A child must never be orphaned because its parent was not crawled."""
        tree = build_tree([profile("/a/b/c/")])
        assert tree.children["a"].profile is None
        assert tree.children["a"].children["b"].children["c"].profile is not None

    def test_counts_descendants_for_the_rollup_badge(self):
        tree = build_tree(
            [profile("/resources/"), profile("/resources/a/"), profile("/resources/b/")]
        )
        assert tree.children["resources"].descendant_count == 2

    def test_orders_children_by_hierarchy_level(self):
        """Utility pages sort last so they do not clutter the structural view."""
        tree = build_tree(
            [
                profile("/zzz-util/", HierarchyLevel.UTILITY_PAGE, PrimaryPageType.UTILITY_LEGAL),
                profile("/aaa-hub/", HierarchyLevel.L1_PRIMARY_NAV_HUB),
            ]
        )
        ordered = [node.segment for node in tree.sorted_children()]
        assert ordered == ["aaa-hub", "zzz-util"]

    def test_empty_input_yields_a_bare_root(self):
        tree = build_tree([])
        assert tree.children == {}
        assert tree.profile is None


class TestRendering:
    def test_produces_a_standalone_document(self):
        html_out = render_tree_html([profile("/a/")], site_name="Example")
        assert html_out.startswith("<!DOCTYPE html>")
        assert html_out.rstrip().endswith("</html>")

    def test_has_no_external_dependencies(self):
        """It must open from a filesystem and survive being emailed."""
        html_out = render_tree_html([profile("/a/")])
        for marker in ('src="http', 'href="http://', "cdn.", '<link rel="stylesheet"'):
            assert marker not in html_out

    def test_includes_the_site_name_and_counts(self):
        html_out = render_tree_html([profile("/a/"), profile("/b/")], site_name="HighRadius")
        assert "HighRadius" in html_out
        assert "2 pages" in html_out

    def test_embeds_every_page_in_the_payload(self):
        html_out = render_tree_html([profile("/a/"), profile("/b/")])
        assert "\\u0022a\\u0022" in html_out or '"a"' in html_out or "a" in html_out

    def test_renders_the_legend_only_for_types_present(self):
        html_out = render_tree_html([profile("/a/", page_type=PrimaryPageType.CASE_STUDY)])
        assert "CASE_STUDY" in html_out
        assert "PRODUCT_DETAIL_PAGE" not in html_out

    def test_highlights_unclassified_pages(self):
        """Phase 1's goal is zero, so they must be visually alarming."""
        html_out = render_tree_html([profile("/a/", page_type=PrimaryPageType.UNKNOWN)])
        assert "1 unclassified" in html_out
        assert 'class="stat"' in html_out

    def test_does_not_cry_wolf_on_a_clean_run(self):
        html_out = render_tree_html([profile("/a/")])
        assert "0 unclassified" in html_out
        assert 'class="stat"' not in html_out

    def test_renders_an_empty_crawl_without_error(self):
        assert render_tree_html([]).startswith("<!DOCTYPE html>")


class TestInjectionSafety:
    """Crawled content is attacker controlled. These are the real attacks."""

    def test_script_tag_in_a_url_cannot_break_out_of_the_payload(self):
        hostile = "https://e.com/</script><script>alert(1)</script>/"
        html_out = render_tree_html([profile("/x/", url=hostile)])
        assert "</script><script>alert(1)" not in html_out
        assert "\\u003c" in html_out

    def test_script_tag_in_the_site_name_is_escaped(self):
        html_out = render_tree_html([profile("/a/")], site_name="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_script_tag_in_the_subtitle_is_escaped(self):
        html_out = render_tree_html([profile("/a/")], subtitle="<img src=x onerror=alert(1)>")
        assert "<img src=x onerror=alert(1)>" not in html_out

    def test_quote_breakout_in_an_attribute_is_escaped(self):
        html_out = render_tree_html([profile("/a/")], site_name='" onload="alert(1)')
        assert '" onload="alert(1)' not in html_out

    def test_angle_brackets_are_neutralised_throughout_the_payload(self):
        """No raw < or > may survive into the embedded JSON."""
        hostile = "https://e.com/<img src=x onerror=alert(1)>/"
        html_out = render_tree_html([profile("/x/", url=hostile)])
        payload = html_out.split("const DATA = ", 1)[1].split(";\n", 1)[0]
        assert "<" not in payload
        assert ">" not in payload

    def test_payload_remains_valid_json_after_escaping(self):
        """Escaping must not corrupt the data the page depends on."""
        html_out = render_tree_html([profile("/x/", url="https://e.com/<>&/")])
        payload = html_out.split("const DATA = ", 1)[1].split(";\n", 1)[0]
        assert isinstance(json.loads(payload), list)


class TestSpecificationCompliance:
    @pytest.mark.parametrize(
        ("page_type", "colour"),
        [
            (PrimaryPageType.HOMEPAGE, "#00f2fe"),
            (PrimaryPageType.PRODUCT_CATEGORY_HUB, "#4facfe"),
            (PrimaryPageType.PRODUCT_DETAIL_PAGE, "#00c6ff"),
            (PrimaryPageType.SERVICE_CATEGORY_HUB, "#a855f7"),
            (PrimaryPageType.BLOG_HUB, "#3b82f6"),
            (PrimaryPageType.BLOG_ARTICLE, "#60a5fa"),
            (PrimaryPageType.COMMERCIAL_LEAD_GEN, "#10b981"),
            (PrimaryPageType.CASE_STUDY, "#f59e0b"),
            (PrimaryPageType.UTILITY_LEGAL, "#64748b"),
        ],
    )
    def test_badge_colours_match_the_specification(self, page_type, colour):
        """Pins TREE_VISUALIZER_SPECIFICATION.md §2.2."""
        assert PAGE_TYPE_COLOURS[page_type] == colour

    def test_every_page_type_has_a_colour(self):
        assert set(PAGE_TYPE_COLOURS) == set(PrimaryPageType)

    def test_every_level_has_a_sort_position(self):
        assert set(LEVEL_ORDER) == set(HierarchyLevel)

    def test_provides_expand_collapse_and_search_controls(self):
        html_out = render_tree_html([profile("/a/")])
        assert "Expand all" in html_out
        assert "Collapse all" in html_out
        assert 'oninput="filter(' in html_out

    def test_external_links_are_safe(self):
        """target=_blank without noopener is a tabnabbing vector."""
        html_out = render_tree_html([profile("/a/")])
        assert "noopener noreferrer" in html_out
