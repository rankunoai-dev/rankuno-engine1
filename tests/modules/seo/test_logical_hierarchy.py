"""Tests for mapping discovered URLs onto the header navigation menu.

The load-bearing behaviour is **prefix inheritance**. Measured on gep.com, the
header menu holds 168 URLs against 4,427 in the sitemap, so exact matching would
put 96.2% of the site in `OTHERS` — a bucket holding almost everything has
organised nothing. Most of these tests exist to pin that down.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.logical_hierarchy import (
    OTHERS_LABEL,
    assign_navigation,
)
from src.modules.seo.page_classifier.nav_tree_parser import parse_navigation
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)

BASE = "https://e.com/"

MENU = """
<header><nav><ul>
  <li><a href="/company/">Company</a>
    <ul>
      <li><a href="/company/culture/">Culture</a>
        <ul><li><a href="/company/culture/diversity/">Diversity</a></li></ul>
      </li>
      <li><a href="/company/leadership/">Leadership</a></li>
    </ul>
  </li>
  <li><a href="/solutions/">Solutions</a>
    <ul><li><a href="/solutions/sourcing/">Sourcing</a></li></ul>
  </li>
</ul></nav></header>
"""


def profile(url: str, page_type: PrimaryPageType = PrimaryPageType.UNKNOWN):
    """A minimal valid profile; only `url` and `primary_page_type` are read.

    Built in full rather than stubbed because `FullPageIntelligenceProfile`
    validates its own level/type coherence, and a duck-typed stand-in would let
    these tests pass against a shape the pipeline cannot actually produce.
    """
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=page_type,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=page_type,
                confidence=0.5,
            ),
        ),
        final_confidence_score=0.5,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
    )


@pytest.fixture
def tree():
    return parse_navigation(MENU, BASE)


class TestExactMatches:
    def test_a_menu_url_gets_its_own_path(self, tree):
        assigned, _ = assign_navigation(tree, [profile("https://e.com/company/culture/")])
        entry = assigned["https://e.com/company/culture/"]
        assert entry.nav_path == ("Company", "Culture")
        assert entry.matched_exactly is True

    def test_a_top_tab_maps_to_itself(self, tree):
        assigned, _ = assign_navigation(tree, [profile("https://e.com/company/")])
        assert assigned["https://e.com/company/"].nav_path == ("Company",)

    def test_the_group_is_the_top_tab(self, tree):
        assigned, _ = assign_navigation(tree, [profile("https://e.com/solutions/sourcing/")])
        assert assigned["https://e.com/solutions/sourcing/"].group == "Solutions"


class TestPrefixInheritance:
    """Without this the whole feature is cosmetic — see the module docstring."""

    def test_a_page_below_a_menu_item_inherits_it(self, tree):
        url = "https://e.com/company/culture/diversity/2026-report/"
        assigned, _ = assign_navigation(tree, [profile(url)])
        assert assigned[url].nav_path == ("Company", "Culture", "Diversity")
        assert assigned[url].matched_exactly is False

    def test_the_longest_prefix_wins(self, tree):
        """Not merely *a* containing section — the most specific one."""
        url = "https://e.com/company/culture/diversity/team/"
        assigned, _ = assign_navigation(tree, [profile(url)])
        assert assigned[url].nav_path == ("Company", "Culture", "Diversity")

    def test_inheritance_is_distinguishable_from_an_exact_match(self, tree):
        """An exact match is linked from the menu; an inherited one is not."""
        assigned, _ = assign_navigation(
            tree,
            [profile("https://e.com/company/"), profile("https://e.com/company/deep/page/")],
        )
        assert assigned["https://e.com/company/"].matched_exactly is True
        assert assigned["https://e.com/company/deep/page/"].matched_exactly is False

    def test_prefixes_cannot_match_across_a_segment_boundary(self, tree):
        """`/solutions` must not claim `/solutions-pricing`."""
        url = "https://e.com/solutions-pricing/"
        assigned, _ = assign_navigation(tree, [profile(url)])
        assert assigned[url].group == OTHERS_LABEL

    def test_a_trailing_slash_difference_still_matches(self, tree):
        """The menu and the sitemap routinely disagree about the slash."""
        assigned, _ = assign_navigation(tree, [profile("https://e.com/company/leadership")])
        assert assigned["https://e.com/company/leadership"].nav_path == (
            "Company",
            "Leadership",
        )


class TestOthers:
    def test_a_page_outside_every_section_goes_to_others(self, tree):
        url = "https://e.com/lp/black-friday-2026/"
        assigned, _ = assign_navigation(tree, [profile(url)])
        assert assigned[url].group == OTHERS_LABEL
        assert assigned[url].nav_parent_url is None

    def test_others_is_sub_grouped_by_page_type(self, tree):
        """A flat bucket of thousands of URLs is not an improvement."""
        url = "https://e.com/blog/post-1/"
        assigned, _ = assign_navigation(tree, [profile(url, PrimaryPageType.BLOG_ARTICLE)])
        assert assigned[url].nav_path == (OTHERS_LABEL, "BLOG_ARTICLE")

    def test_an_empty_menu_puts_everything_in_others(self):
        """With no menu there is no published structure to report.

        Falling back to a URL-path tree here would present a structure the site
        never published as though it had.
        """
        empty = parse_navigation("<html><body>no nav</body></html>", BASE)
        assigned, report = assign_navigation(empty, [profile("https://e.com/a/")])
        assert assigned["https://e.com/a/"].group == OTHERS_LABEL
        assert report.coverage == 0.0

    def test_page_types_can_be_overridden(self, tree):
        url = "https://e.com/x/"
        assigned, _ = assign_navigation(
            tree, [profile(url)], page_types={url: PrimaryPageType.CASE_STUDY}
        )
        assert assigned[url].nav_path == (OTHERS_LABEL, "CASE_STUDY")


class TestCoverageReport:
    def test_counts_add_up_to_the_total(self, tree):
        profiles = [
            profile("https://e.com/company/"),
            profile("https://e.com/company/culture/deep/"),
            profile("https://e.com/lp/promo/"),
        ]
        _, report = assign_navigation(tree, profiles)
        assert report.total_urls == 3
        assert report.exact_matches + report.inherited_matches + report.unmatched == 3

    def test_coverage_is_reported_not_assumed(self, tree):
        """Menu coverage varies hugely between sites; a caller must be told."""
        profiles = [
            profile("https://e.com/company/"),
            profile("https://e.com/lp/a/"),
            profile("https://e.com/lp/b/"),
            profile("https://e.com/lp/c/"),
        ]
        _, report = assign_navigation(tree, profiles)
        assert report.coverage == 0.25

    def test_coverage_of_an_empty_crawl_is_zero_not_an_error(self, tree):
        _, report = assign_navigation(tree, [])
        assert report.coverage == 0.0
        assert report.total_urls == 0

    def test_groups_follow_menu_order(self, tree):
        """The UI must match the site's own header, not alphabetise it."""
        _, report = assign_navigation(
            tree, [profile("https://e.com/solutions/"), profile("https://e.com/company/")]
        )
        assert report.groups == ("Company", "Solutions")

    def test_others_is_listed_last_and_only_when_used(self, tree):
        _, without = assign_navigation(tree, [profile("https://e.com/company/")])
        assert OTHERS_LABEL not in without.groups

        _, with_others = assign_navigation(tree, [profile("https://e.com/lp/x/")])
        assert with_others.groups[-1] == OTHERS_LABEL

    def test_nav_entries_counts_linked_menu_items(self, tree):
        _, report = assign_navigation(tree, [])
        assert report.nav_entries == 6


class TestScale:
    def test_handles_a_large_crawl(self, tree):
        """20k URLs against ~170 menu entries must not be pathological."""
        profiles = [profile(f"https://e.com/company/culture/p{i}/") for i in range(5_000)]
        assigned, report = assign_navigation(tree, profiles)
        assert len(assigned) == 5_000
        assert report.inherited_matches == 5_000


class TestRootLinkIsNotACatchAll:
    """The logo links to `/`, whose prefix matches every URL on the site.

    Left in the match set it absorbs everything that should have gone to
    `OTHERS`, and coverage reads 100% on every site regardless of what the menu
    covers. Measured on gep.com before the fix: 0 unmatched out of 600.
    """

    def test_a_logo_link_does_not_absorb_the_site(self):
        menu = parse_navigation(
            "<nav><ul>"
            "<li><a href='/'>Home</a></li>"
            "<li><a href='/company/'>Company</a></li>"
            "</ul></nav>",
            BASE,
        )
        assigned, report = assign_navigation(
            menu,
            [profile("https://e.com/lp/promo/"), profile("https://e.com/company/x/")],
        )
        assert assigned["https://e.com/lp/promo/"].group == OTHERS_LABEL
        assert report.unmatched == 1

    def test_a_menu_of_only_a_root_link_covers_nothing(self):
        menu = parse_navigation("<nav><ul><li><a href='/'>Home</a></li></ul></nav>", BASE)
        _, report = assign_navigation(menu, [profile("https://e.com/anything/")])
        assert report.coverage == 0.0

    def test_the_homepage_itself_still_resolves(self):
        """Excluding `/` as a *prefix* must not orphan the homepage."""
        menu = parse_navigation(
            "<nav><ul><li><a href='/'>Home</a></li><li><a href='/a/'>A</a></li></ul></nav>",
            BASE,
        )
        assigned, _ = assign_navigation(menu, [profile("https://e.com/")])
        assert assigned["https://e.com/"].group == OTHERS_LABEL
