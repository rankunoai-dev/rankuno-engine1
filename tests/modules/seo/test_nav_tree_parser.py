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
    NavNode,
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


# Anthropic's header, reduced to the structure that matters. Taken verbatim in
# shape from the live page: the tab that opens a dropdown is not a link, not a
# `<button>`, and carries no `role` or `aria-haspopup` — it is nested `<div>`s.
# The dropdown panel is its own `<nav>` inside the tab's `<li>`.
WEBFLOW_DROPDOWN = """
<header>
  <a href="/" class="logo"><div class="logo_lottie"></div></a>
  <nav role="navigation" class="nav_desktop_layout">
    <ul role="list" class="nav_links_wrap">
      <li><a href="/research"><div class="nav_links_text">Research</div></a></li>
      <li><a href="/policy"><div class="nav_links_text">Policy</div></a></li>
      <li>
        <div class="nav_dropdown_component w-dropdown">
          <div class="nav_links_link w-dropdown-toggle">
            <div class="nav_links_text">Commitments</div>
            <div class="nav_links_svg"><svg viewBox="0 0 12 24"></svg></div>
          </div>
          <nav class="nav_dropdown_main_wrap w-dropdown-list">
            <div class="nav_dropdown_main_content">
              <div class="nav_dropdown_eyebrow">Initiatives</div>
              <ul role="list">
                <li><a href="/constitution"><div>Constitution</div></a></li>
                <li><a href="/transparency"><div>Transparency</div></a></li>
              </ul>
            </div>
          </nav>
        </div>
      </li>
      <li><a href="/news"><div class="nav_links_text">News</div></a></li>
      <li class="nav_buttons_item">
        <div class="btn_main_wrap">
          <a href="https://claude.ai/login" data-cta="">Log in to Claude</a>
        </div>
      </li>
      <li>
        <div class="w-locales-item"><a href="#">This is some text inside of a div block.</a></div>
      </li>
    </ul>
  </nav>
</header>
"""


class TestNonLinkDropdownTabs:
    """A top tab that opens a dropdown is often not a link at all.

    Before this, the tab produced no node, and `_build_tree` attached its whole
    dropdown to the previous tab that did. On anthropic.com that put
    `Transparency`, `Claude's Constitution` and eleven other pages under
    `Policy`, and lost the `Commitments`, `Learn` and `Company` tabs entirely.

    The live page has no `<button>`, no `role="button"`, no `role="menuitem"`
    and no `aria-haspopup` anywhere in its header — the tab is three nested
    `<div>`s. Anything keyed to those attributes would not have fired.
    """

    def test_an_unlinked_tab_becomes_a_root(self):
        tree = parse_navigation(WEBFLOW_DROPDOWN, BASE)
        # `Home` is the logo anchor, named from its URL because its only content
        # is an image. Asserted rather than filtered out: a logo inside the
        # header does become a top-level entry, and that is worth stating so a
        # later reader is not surprised by it. On the live page the logo sits
        # outside the nav container, so it does not appear there.
        assert [root.label for root in tree.roots] == [
            "Home",
            "Research",
            "Policy",
            "Commitments",
            "News",
        ]

    def test_dropdown_children_stay_under_their_own_tab(self):
        """The reported defect: `Transparency` sat under `Policy`."""
        tree = parse_navigation(WEBFLOW_DROPDOWN, BASE)
        by_label = {root.label: root for root in tree.roots}

        assert by_label["Policy"].children == ()
        urls = {node.url for node in by_label["Commitments"].walk() if node.url}
        assert urls == {"https://e.com/constitution", "https://e.com/transparency"}

    def test_a_dropdown_group_heading_is_a_level_below_the_tab(self):
        """`Initiatives` labels a group *inside* Commitments, not beside it.

        It sits at the same list depth as the tabs — only the nested `<nav>`
        distinguishes them — so without that signal it became a sibling tab and
        stole the children the tab should have had.
        """
        tree = parse_navigation(WEBFLOW_DROPDOWN, BASE)
        commitments = next(r for r in tree.roots if r.label == "Commitments")
        assert [child.label for child in commitments.children] == ["Initiatives"]
        assert commitments.children[0].depth == 1
        assert [node.label for node in commitments.children[0].children] == [
            "Constitution",
            "Transparency",
        ]

    def test_an_anchor_wrapping_a_div_keeps_its_href(self):
        """`</div>` inside an open anchor must not close it and strip the URL."""
        tree = parse_navigation(WEBFLOW_DROPDOWN, BASE)
        research = next(r for r in tree.roots if r.label == "Research")
        assert research.url == "https://e.com/research"


class TestUnlinkedLeafPruning:
    """An unlinked node earns its place by naming the section its children sit in.

    One with no children reaches nothing and groups nothing. Pruning them is
    what makes accepting `<div>` labels safe: a header carries far more unlinked
    text than menu structure.
    """

    def test_off_host_call_to_action_is_not_a_section(self):
        labels = {r.label for r in parse_navigation(WEBFLOW_DROPDOWN, BASE).roots}
        assert "Log in to Claude" not in labels

    def test_a_fragment_only_placeholder_is_not_a_section(self):
        """An unfilled Webflow locale switcher, observed live on anthropic.com."""
        labels = {r.label for r in parse_navigation(WEBFLOW_DROPDOWN, BASE).roots}
        assert "This is some text inside of a div block." not in labels

    def test_a_heading_with_children_survives(self):
        labels = {r.label for r in parse_navigation(WEBFLOW_DROPDOWN, BASE).roots}
        assert "Commitments" in labels

    def test_a_heading_whose_children_were_all_pruned_is_pruned_too(self):
        """Bottom-up, or an empty wrapper survives its emptied contents."""
        html = """
        <header><nav><ul>
          <li><a href="/real/">Real</a></li>
          <li><div class="toggle"><div>Ghost</div></div>
            <nav><ul><li><a href="#">nothing</a></li></ul></nav>
          </li>
        </ul></nav></header>
        """
        assert [r.label for r in parse_navigation(html, BASE).roots] == ["Real"]


class TestDuplicateMenuSuppression:
    """Most sites render the menu twice, once for desktop and once for mobile."""

    def test_a_repeated_menu_does_not_double_the_tabs(self):
        one = """
          <nav><ul>
            <li><div class="toggle"><div>Commitments</div></div>
              <nav><ul><li><a href="/transparency">Transparency</a></li></ul></nav>
            </li>
          </ul></nav>
        """
        tree = parse_navigation("<header>" + one + one + "</header>", BASE)
        assert [root.label for root in tree.roots] == ["Commitments"]


class TestNavNestingDoesNotShiftDepth:
    """Only a nav opened *inside a list* is a dropdown.

    `<header><nav>` wraps the entire menu and opens before any list. Counting it
    would push every top tab to depth 1 and leave the tree with no roots at all.
    """

    def test_header_wrapping_nav_leaves_tabs_at_depth_zero(self):
        html = """
        <header><nav><ul>
          <li><a href="/a/">A</a></li>
          <li><a href="/b/">B</a></li>
        </ul></nav></header>
        """
        tree = parse_navigation(html, BASE)
        assert [root.depth for root in tree.roots] == [0, 0]

    def test_depth_stays_within_the_ceiling(self):
        deep = "<header><nav><ul><li><div><div>T</div></div>"
        deep += "<nav><ul><li><div>G</div><ul><li><div>S</div>"
        deep += '<ul><li><a href="/x/">X</a></li></ul></li></ul></li></ul></nav>'
        deep += "</li></ul></nav></header>"
        tree = parse_navigation(deep, BASE)
        assert all(node.depth < MAX_NAV_DEPTH for root in tree.roots for node in root.walk())


class TestSiblingHeadingsStaySiblings:
    """A mega-menu's column headings are siblings, not a chain.

    rankuno.com's Our Expertise panel sits behind a wrapper the collector
    counts, so its entries arrive as `0, 2, 3, 3, 2, 2, 3` — the tab, a column
    heading, its items, the next heading. Clamping each entry against the stack
    height closed that 0→2 jump for the *first* heading only: it dropped to 1
    and every heading after it stayed at 2, becoming its child. Live, that put
    all six columns under `Marketing Strategy & Transformation`, left `SEO`
    beside `Digital Channels` instead of under it, and gave `/perspective/` a
    two-step menu ancestry it does not have on the site.
    """

    MEGA_MENU = """
    <header><nav><ul>
      <li><a href="/expertise/">Expertise</a>
        <ul><li><ul>
          <li><a href="/strategy/">Strategy</a>
            <ul><li><a href="/strategy/roadmap/">Roadmap</a></li></ul>
          </li>
          <li><a href="/channels/">Channels</a>
            <ul><li><a href="/channels/seo/">SEO</a></li></ul>
          </li>
          <li><a href="/perspective/">Perspective</a></li>
        </ul></li></ul>
      </li>
    </ul></nav></header>
    """

    def _tab(self) -> NavNode:
        tree = parse_navigation(self.MEGA_MENU, BASE)
        assert len(tree.roots) == 1
        return tree.roots[0]

    def test_every_column_heading_is_a_child_of_the_tab(self):
        assert [child.label for child in self._tab().children] == [
            "Strategy",
            "Channels",
            "Perspective",
        ]

    def test_each_heading_keeps_its_own_items(self):
        strategy, channels, perspective = self._tab().children
        assert [node.label for node in strategy.children] == ["Roadmap"]
        assert [node.label for node in channels.children] == ["SEO"]
        assert perspective.children == ()

    def test_a_promo_column_gets_a_one_step_ancestry(self):
        """`/perspective/` sits under the tab, not under another column."""
        perspective = self._tab().children[2]
        assert perspective.depth == 1


class TestBreadcrumbIsNotTheMenu:
    """A breadcrumb marked `role="navigation"` is not the site menu.

    Allbirds publishes `<nav role='navigation' aria-label='breadcrumbs'>`, and
    its `Home` and `Men's Shoes` crumbs were parsed as top-level tabs beside the
    real ones — on every product page, each with a different trail. A breadcrumb
    describes one page's ancestry; the menu describes the site.
    """

    MIXED = """
    <header><nav><ul><li><a href="/shop">Shop</a></li></ul></nav></header>
    <nav role="navigation" aria-label="breadcrumbs">
      <ol>
        <li><a href="/">Home</a></li>
        <li><a href="/mens">Mens</a></li>
        <li><a href="/mens/shoes">Shoes</a></li>
      </ol>
    </nav>
    """

    def test_crumbs_do_not_become_tabs(self):
        tree = parse_navigation(self.MIXED, BASE)
        assert [root.label for root in tree.roots] == ["Shop"]

    def test_the_real_menu_still_parses(self):
        tree = parse_navigation(self.MIXED, BASE)
        assert tree.roots[0].url == "https://e.com/shop"

    def test_a_class_named_breadcrumb_is_excluded_too(self):
        html = """
        <header><nav><ul><li><a href="/shop">Shop</a></li></ul></nav></header>
        <div class="breadcrumbs"><a href="/">Home</a><a href="/mens">Mens</a></div>
        """
        assert [root.label for root in parse_navigation(html, BASE).roots] == ["Shop"]


class TestFragmentPanels:
    """A tab whose href names the panel it opens.

    The kinsta.com shape. Its dropdown is a `<div>`, not a `<nav>`, so
    `_dropdown_depth` never fired and the `<h6>` column titles inside the panel
    computed the same depth as the tabs themselves. `_build_tree` then closed
    `Platform` with no children at the first `<h6>`, `_prune_unlinked_leaves`
    deleted it as an unlinked leaf, and its column titles were promoted to
    top-level tabs in its place. Live, that turned 5 real tabs into 15 fake
    ones.
    """

    HREF = "https://e.com/"

    def test_a_fragment_panel_nests_its_columns(self):
        html = """<header><nav><ul>
          <li><a href="#panel-0">Platform</a>
            <div id="panel-0">
              <h6>Product</h6>
              <ul><li><a href="/hosting/">Hosting</a></li></ul>
            </div>
          </li>
          <li><a href="/pricing/">Pricing</a></li>
        </ul></nav></header>"""
        roots = parse_navigation(html, self.HREF).roots
        assert [r.label for r in roots] == ["Platform", "Pricing"]
        platform = roots[0]
        assert [c.label for c in platform.children] == ["Product"]
        assert [g.label for g in platform.children[0].children] == ["Hosting"]

    def test_a_plain_page_link_is_not_a_panel(self):
        """`/a#b` addresses another page, not a panel on this one."""
        html = """<header><nav><ul>
          <li><a href="/other#panel-0">Elsewhere</a>
            <div id="panel-0"><h6>Column</h6>
              <ul><li><a href="/deep/">Deep</a></li></ul></div>
          </li>
        </ul></nav></header>"""
        roots = parse_navigation(html, self.HREF).roots
        # No panel recognised, so the heading stays a sibling and takes the
        # links — the pre-fix behaviour, preserved where the signal is absent.
        assert [r.label for r in roots] == ["Elsewhere", "Column"]

    def test_a_bare_hash_is_not_a_panel_id(self):
        """`href="#"` is a placeholder addressing nothing."""
        html = """<header><nav><ul>
          <li><a href="#">Toggle</a><div id=""><h6>C</h6>
            <ul><li><a href="/x/">X</a></li></ul></div></li>
        </ul></nav></header>"""
        assert [r.label for r in parse_navigation(html, self.HREF).roots] == ["C"]

    def test_a_fragment_pointing_at_an_inline_element_is_ignored(self):
        """`<span id="icon">` is not a dropdown, and must not shift depth."""
        html = """<header><nav><ul>
          <li><a href="#icon">Tab</a><span id="icon">*</span>
            <h6>Column</h6>
            <ul><li><a href="/y/">Y</a></li></ul></li>
        </ul></nav></header>"""
        assert [r.label for r in parse_navigation(html, self.HREF).roots] == ["Column"]

    def test_the_panel_closes_at_the_right_div(self):
        """Nested `<div>`s must not close the panel early.

        Matching a panel by tag name would end it at the first inner `</div>`,
        putting everything after that back at tab depth — the same failure with
        a smaller blast radius.
        """
        html = """<header><nav><ul>
          <li><a href="#p">Tab</a>
            <div id="p">
              <div><div><h6>First</h6>
                <ul><li><a href="/1/">One</a></li></ul></div></div>
              <h6>Second</h6>
              <ul><li><a href="/2/">Two</a></li></ul>
            </div>
          </li>
          <li><a href="/after/">After</a></li>
        </ul></nav></header>"""
        roots = parse_navigation(html, self.HREF).roots
        assert [r.label for r in roots] == ["Tab", "After"]
        assert [c.label for c in roots[0].children] == ["First", "Second"]

    def test_unclosed_list_items_do_not_desync_the_panel(self):
        """Menus routinely omit `</li>`; popping only the top would drift."""
        html = """<header><nav><ul>
          <li><a href="#p">Tab</a>
            <div id="p"><h6>Col</h6>
              <ul><li><a href="/1/">One</a><li><a href="/2/">Two</a></ul>
            </div>
          <li><a href="/after/">After</a>
        </ul></nav></header>"""
        roots = parse_navigation(html, self.HREF).roots
        assert [r.label for r in roots] == ["Tab", "After"]
