"""Tests for header navigation extraction.

The parse has to survive real menu markup, which is messier than the examples:
duplicated desktop/mobile menus, unlinked section headings, fragment links, and
several `<nav>` elements per page of which only one is the header.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.nav_tree_parser import (
    MAX_NAV_DEPTH,
    NavigationTree,
    parse_navigation,
)

BASE = "https://e.com/"

MEGA_MENU = """
<header>
  <nav>
    <ul>
      <li><a href="/gqi/">GEP Quantum Intelligence</a>
        <ul>
          <li><a href="/gqi/solutions/">Solutions</a>
            <ul>
              <li><a href="/gqi/solutions/intake/">Intake &amp; Orchestration</a></li>
              <li><a href="/gqi/solutions/sourcing/">Sourcing Management</a></li>
            </ul>
          </li>
          <li><a href="/gqi/platform/">Platform</a>
            <ul>
              <li><a href="/gqi/platform/ai-native/">AI-Native Architecture</a></li>
            </ul>
          </li>
        </ul>
      </li>
      <li><a href="/company/">Company</a>
        <ul>
          <li><a href="/company/about/">About</a>
            <ul>
              <li><a href="/company/about/leadership/">Leadership</a></li>
            </ul>
          </li>
        </ul>
      </li>
      <li><a href="/contact/">Contact Us</a></li>
    </ul>
  </nav>
</header>
"""


def labels(tree: NavigationTree) -> list[str]:
    return [root.label for root in tree.roots]


class TestStructureExtraction:
    def test_top_tabs_become_roots(self):
        tree = parse_navigation(MEGA_MENU, BASE)
        assert labels(tree) == ["GEP Quantum Intelligence", "Company", "Contact Us"]

    def test_mega_menu_headings_become_children(self):
        tree = parse_navigation(MEGA_MENU, BASE)
        gqi = tree.roots[0]
        assert [child.label for child in gqi.children] == ["Solutions", "Platform"]

    def test_dropdown_items_become_grandchildren(self):
        tree = parse_navigation(MEGA_MENU, BASE)
        solutions = tree.roots[0].children[0]
        assert [child.label for child in solutions.children] == [
            "Intake & Orchestration",
            "Sourcing Management",
        ]

    def test_urls_are_absolute(self):
        tree = parse_navigation(MEGA_MENU, BASE)
        assert tree.roots[0].url == "https://e.com/gqi/"

    def test_entities_in_labels_are_decoded(self):
        """`Intake &amp; Orchestration` must not reach a UI as raw markup."""
        tree = parse_navigation(MEGA_MENU, BASE)
        item = tree.roots[0].children[0].children[0]
        assert item.label == "Intake & Orchestration"

    def test_the_source_records_how_it_was_found(self):
        tree = parse_navigation(MEGA_MENU, BASE)
        assert tree.source.strategy == "dom"
        assert tree.source.link_count == 10

    def test_linked_nodes_returns_every_destination(self):
        assert len(parse_navigation(MEGA_MENU, BASE).linked_nodes()) == 10


class TestFooterExclusion:
    """gep.com publishes seven `<nav>` elements; most are not the header menu."""

    def test_footer_navigation_is_ignored(self):
        html = (
            MEGA_MENU
            + """
        <footer>
          <nav><ul>
            <li><a href="/privacy/">Privacy Policy</a></li>
            <li><a href="/terms/">Terms</a></li>
          </ul></nav>
        </footer>
        """
        )
        assert "Privacy Policy" not in labels(parse_navigation(html, BASE))

    def test_contentinfo_role_is_also_excluded(self):
        html = MEGA_MENU + (
            '<div role="contentinfo"><nav><ul>'
            '<li><a href="/sitemap/">Sitemap</a></li>'
            "</ul></nav></div>"
        )
        assert "Sitemap" not in labels(parse_navigation(html, BASE))

    def test_a_footer_only_page_yields_nothing(self):
        html = '<footer><nav><ul><li><a href="/privacy/">Privacy</a></li></ul></nav></footer>'
        assert parse_navigation(html, BASE).is_empty


class TestRealWorldMarkup:
    def test_duplicate_desktop_and_mobile_menus_are_deduplicated(self):
        """Most sites ship both; counting each twice doubles the whole tree."""
        tree = parse_navigation(MEGA_MENU + MEGA_MENU, BASE)
        assert labels(tree) == ["GEP Quantum Intelligence", "Company", "Contact Us"]

    def test_unlinked_section_headings_are_kept(self):
        """Dropping them would flatten the two levels beneath into one."""
        html = """
        <nav><ul>
          <li><a href="/solutions/">Solutions</a>
            <ul>
              <li><span>By Industry</span>
                <ul><li><a href="/solutions/retail/">Retail</a></li></ul>
              </li>
            </ul>
          </li>
        </ul></nav>
        """
        tree = parse_navigation(html, BASE)
        assert tree.roots[0].label == "Solutions"
        assert tree.roots[0].children[0].children[0].label == "Retail"

    def test_fragment_links_collapse_to_their_page(self):
        """`/contact#rfp` and `/contact` are one destination, not two."""
        html = """
        <nav><ul>
          <li><a href="/contact/">Contact</a></li>
          <li><a href="/contact/#rfp">Contact - RFP</a></li>
          <li><a href="#top">Back to top</a></li>
        </ul></nav>
        """
        urls = {node.url for node in parse_navigation(html, BASE).linked_nodes()}
        assert urls == {"https://e.com/contact/"}

    def test_off_host_links_are_dropped(self):
        """A careers portal on another domain is not part of this site."""
        html = (
            '<nav><ul><li><a href="/a/">A</a></li>'
            '<li><a href="https://jobs.example.org/">Jobs</a></li></ul></nav>'
        )
        urls = {node.url for node in parse_navigation(html, BASE).linked_nodes()}
        assert urls == {"https://e.com/a/"}

    def test_a_div_based_menu_yields_a_flat_list(self):
        """No list nesting means no recoverable hierarchy. Flat is honest."""
        html = '<nav><div><a href="/a/">A</a><a href="/b/">B</a><a href="/c/">C</a></div></nav>'
        tree = parse_navigation(html, BASE)
        assert labels(tree) == ["A", "B", "C"]
        assert all(not root.children for root in tree.roots)

    def test_depth_is_capped(self):
        """Past three levels the grouping stops resembling the visible site."""
        html = (
            "<nav><ul><li><a href='/1/'>1</a><ul><li><a href='/2/'>2</a>"
            "<ul><li><a href='/3/'>3</a><ul><li><a href='/4/'>4</a>"
            "</li></ul></li></ul></li></ul></li></ul></nav>"
        )
        depths = {node.depth for node in parse_navigation(html, BASE).linked_nodes()}
        assert max(depths) <= MAX_NAV_DEPTH - 1

    def test_deep_items_are_kept_not_dropped(self):
        html = (
            "<nav><ul><li><a href='/1/'>1</a><ul><li><a href='/2/'>2</a>"
            "<ul><li><a href='/3/'>3</a><ul><li><a href='/4/'>4</a>"
            "</li></ul></li></ul></li></ul></li></ul></nav>"
        )
        urls = {node.url for node in parse_navigation(html, BASE).linked_nodes()}
        assert "https://e.com/4/" in urls


class TestFallbacks:
    def test_a_client_rendered_menu_falls_back_to_jsonld(self):
        """A React header leaves the served HTML with no anchors at all."""
        html = """
        <header><nav id="root"></nav></header>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"SiteNavigationElement","name":"Solutions","url":"https://e.com/solutions/"},
          {"@type":"SiteNavigationElement","name":"Company","url":"https://e.com/company/"}
        ]}
        </script>
        """
        tree = parse_navigation(html, BASE)
        assert tree.source.strategy == "jsonld"
        assert labels(tree) == ["Solutions", "Company"]

    def test_dom_wins_over_jsonld_when_both_exist(self):
        """The DOM has nesting; the markup does not."""
        html = MEGA_MENU + (
            '<script type="application/ld+json">'
            '{"@type":"SiteNavigationElement","name":"X","url":"https://e.com/x/"}'
            "</script>"
        )
        assert parse_navigation(html, BASE).source.strategy == "dom"

    def test_malformed_jsonld_does_not_raise(self):
        html = '<nav></nav><script type="application/ld+json">{not json</script>'
        assert parse_navigation(html, BASE).is_empty

    @pytest.mark.parametrize("payload", ["", "   ", "<html><body>no nav</body></html>"])
    def test_pages_without_navigation_yield_an_empty_tree(self, payload):
        tree = parse_navigation(payload, BASE)
        assert tree.is_empty
        assert tree.linked_nodes() == []

    def test_an_empty_tree_is_distinguishable_from_an_unsearched_one(self):
        """`strategy` says which happened; the UI has to be able to tell."""
        assert parse_navigation("<nav></nav>", BASE).source.strategy == "none"
        assert parse_navigation("", BASE).source.strategy == "none"

    def test_malformed_markup_does_not_raise(self):
        html = "<nav><ul><li><a href='/a/'>A<ul><li><a href='/b/'>B</nav>"
        assert isinstance(parse_navigation(html, BASE), NavigationTree)


class TestDecorativeAnchors:
    """Real menus are full of anchors that are not sections.

    Observed live on gep.com: the parsed top tabs were
    `['', '', 'Company', 'Solutions', 'Industries', 'Knowledge Bank', '›', ...]`.
    """

    def test_chevrons_and_bullets_do_not_become_sections(self):
        html = (
            "<nav><ul>"
            "<li><a href='/a/'>Solutions</a></li>"
            "<li><a href='/b/'>&#8250;</a></li>"
            "<li><a href='/c/'>&bull;</a></li>"
            "</ul></nav>"
        )
        assert "›" not in labels(parse_navigation(html, BASE))
        assert "•" not in labels(parse_navigation(html, BASE))

    def test_an_icon_only_link_is_named_from_its_url(self):
        """A blank label would render as a nameless top-level section."""
        html = "<nav><ul><li><a href='/login'><svg></svg></a></li></ul></nav>"
        assert labels(parse_navigation(html, BASE)) == ["Login"]

    def test_a_multi_segment_url_uses_its_last_segment(self):
        html = "<nav><ul><li><a href='/company/contact-us'><i></i></a></li></ul></nav>"
        assert labels(parse_navigation(html, BASE)) == ["Contact Us"]

    def test_a_root_icon_link_is_named_home(self):
        html = "<nav><ul><li><a href='/'><img src='logo.png'></a></li></ul></nav>"
        assert labels(parse_navigation(html, BASE)) == ["Home"]

    def test_a_real_label_is_never_replaced_by_its_url(self):
        html = "<nav><ul><li><a href='/company/'>Company</a></li></ul></nav>"
        assert labels(parse_navigation(html, BASE)) == ["Company"]
