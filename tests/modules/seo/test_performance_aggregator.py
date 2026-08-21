"""Tests for rolling Google metrics up the navigation tree.

Every test here is a way the obvious implementation gets a plausible-looking
wrong number. Rates that were averaged instead of recomputed, rows that were
assigned instead of summed, a section keyed by its label, traffic dropped
because it resolved to nothing — none of those raise, and all of them produce a
dashboard that reconciles against nothing.
"""

from __future__ import annotations

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
from src.modules.seo.performance.aggregator import aggregate, section_path_of
from src.modules.seo.performance.schemas import Ga4PageMetrics, GscPageMetrics
from src.modules.seo.performance.url_identity import UrlResolutionIndex


def profile(
    url: str, trail: tuple[str, ...] = (), *, canonical: str | None = None
) -> FullPageIntelligenceProfile:
    """A crawled page sitting at `trail`."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=canonical if canonical is not None else url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
        breadcrumb_path=trail,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.9,
            ),
        ),
        final_confidence_score=0.9,
        consensus_method=ConsensusMethod.WEIGHTED_CONSENSUS,
    )


def gsc(url: str, clicks: int = 0, impressions: int = 0, position: float = 0.0):
    return GscPageMetrics(url=url, clicks=clicks, impressions=impressions, position=position)


def rollup(pages, gsc_rows=(), ga4_rows=()):
    return aggregate(UrlResolutionIndex(pages), gsc_rows, ga4_rows)


def section(report, path: tuple[str, ...]):
    found = [s for s in report.sections if s.path == path]
    assert found, f"no section {path} in {[s.path for s in report.sections]}"
    return found[0]


class TestTheRollupAddsUp:
    def test_top_level_sections_sum_to_the_site(self):
        """The property everything else depends on.

        Each page carries exactly one trail, so it is counted once per ancestor
        level. If a page ever gained a second placement this would silently
        double-count, which is why it is asserted rather than assumed.
        """
        report = rollup(
            [
                profile("https://e.com/a/", ("Products", "CRM")),
                profile("https://e.com/b/", ("Products", "ERP")),
                profile("https://e.com/c/", ("Company",)),
            ],
            [
                gsc("https://e.com/a/", 10, 100),
                gsc("https://e.com/b/", 5, 50),
                gsc("https://e.com/c/", 2, 20),
            ],
        )
        roots = [s for s in report.sections if s.depth == 1]
        assert sum(s.clicks for s in roots) == report.site.clicks == 17
        assert sum(s.pages for s in roots) == report.site.pages == 3

    def test_a_page_lands_in_every_ancestor_of_its_trail(self):
        report = rollup(
            [profile("https://e.com/a/", ("Products", "CRM", "Pricing"))],
            [gsc("https://e.com/a/", 7, 70)],
        )
        for path in (("Products",), ("Products", "CRM"), ("Products", "CRM", "Pricing")):
            assert section(report, path).clicks == 7, path
        assert report.site.clicks == 7


class TestRatesAreRecomputedNotAveraged:
    def test_ctr_comes_from_the_sums(self):
        """Averaging CTRs weights a 2-impression page like a 20,000 one."""
        report = rollup(
            [
                profile("https://e.com/a/", ("S",)),
                profile("https://e.com/b/", ("S",)),
            ],
            [gsc("https://e.com/a/", 1, 2), gsc("https://e.com/b/", 100, 20_000)],
        )
        # Mean of the two page CTRs would be ~0.2525. The real answer is
        # 101/20002.
        assert section(report, ("S",)).ctr == pytest.approx(101 / 20_002)

    def test_position_is_impression_weighted(self):
        """Position is weighted by impressions.

        A page seen 10 times must not pull the section average as hard as one
        seen 990 times.
        """
        report = rollup(
            [
                profile("https://e.com/a/", ("S",)),
                profile("https://e.com/b/", ("S",)),
            ],
            [
                gsc("https://e.com/a/", 0, 10, position=1.0),
                gsc("https://e.com/b/", 0, 990, position=51.0),
            ],
        )
        # Unweighted mean would be 26.0.
        assert section(report, ("S",)).position == pytest.approx(50.5, abs=0.01)

    def test_no_impressions_means_no_position_not_zero(self):
        """No impressions means no position, not zero.

        Zero would read as better than rank 1 and sort to the top of a
        best-performing list purely for having no data.
        """
        report = rollup([profile("https://e.com/a/", ("S",))])
        assert section(report, ("S",)).position is None
        assert section(report, ("S",)).ctr == 0.0


class TestSeveralRowsForOnePage:
    def test_rows_are_summed_not_overwritten(self):
        """Canonical tags are many-to-one, so this is the normal case.

        Assigning instead of adding drops clicks and leaves a total that still
        looks plausible.
        """
        report = rollup(
            [profile("https://e.com/a/?page=2", ("S",), canonical="https://e.com/a/")],
            [gsc("https://e.com/a/?page=2", 10, 100), gsc("https://e.com/a/", 5, 50)],
        )
        assert section(report, ("S",)).clicks == 15
        assert section(report, ("S",)).impressions == 150

    def test_merging_two_rows_weights_their_positions(self):
        """Merging two rows weights their positions.

        Each row carries an average over its own impression volume, so the mean
        of the two averages is not the page's average position.
        """
        report = rollup(
            [profile("https://e.com/a/?page=2", ("S",), canonical="https://e.com/a/")],
            [
                gsc("https://e.com/a/?page=2", 0, 1, position=2.0),
                gsc("https://e.com/a/", 0, 99, position=12.0),
            ],
        )
        assert section(report, ("S",)).position == pytest.approx(11.9, abs=0.01)

    def test_one_page_measured_twice_is_still_one_page(self):
        report = rollup(
            [profile("https://e.com/a/?page=2", ("S",), canonical="https://e.com/a/")],
            [gsc("https://e.com/a/?page=2", 1, 1), gsc("https://e.com/a/", 1, 1)],
        )
        assert section(report, ("S",)).pages == 1
        assert section(report, ("S",)).pages_with_data == 1


class TestSectionIdentity:
    def test_the_same_label_under_two_parents_stays_two_sections(self):
        """One label under two parents stays two sections.

        Measured: up to 68 labels per crawl are reused under different parents.
        Keying by label merges unrelated sections into one wrong row.
        """
        report = rollup(
            [
                profile("https://e.com/a/", ("Products", "Overview")),
                profile("https://e.com/b/", ("Company", "Overview")),
            ],
            [gsc("https://e.com/a/", 9, 90), gsc("https://e.com/b/", 1, 10)],
        )
        assert section(report, ("Products", "Overview")).clicks == 9
        assert section(report, ("Company", "Overview")).clicks == 1

    def test_a_section_that_is_also_a_page_separates_its_own_traffic(self):
        """1,220 trails in the corpus are a strict prefix of a deeper trail.

        Without `direct_*`, "is this section big or is its landing page big" has
        no answer in the data.
        """
        report = rollup(
            [
                profile("https://e.com/products/", ("Products",)),
                profile("https://e.com/products/crm/", ("Products", "CRM")),
            ],
            [gsc("https://e.com/products/", 3, 30), gsc("https://e.com/products/crm/", 97, 970)],
        )
        products = section(report, ("Products",))
        assert products.clicks == 100
        assert products.direct_clicks == 3
        assert products.pages == 2
        assert products.direct_pages == 1

    def test_a_trail_that_repeats_a_label_is_not_collapsed(self):
        """3,833 pages in the corpus carry a trail with a repeated segment."""
        report = rollup(
            [profile("https://e.com/a/", ("Products", "Products"))],
            [gsc("https://e.com/a/", 4, 40)],
        )
        assert section(report, ("Products",)).clicks == 4
        assert section(report, ("Products", "Products")).clicks == 4


class TestNothingIsQuietlyDropped:
    def test_unresolved_rows_are_held_not_discarded(self):
        """Unresolved rows are held, not discarded.

        Otherwise the section total is smaller than the Search Console UI and
        nothing on screen explains the gap.
        """
        report = rollup(
            [profile("https://e.com/a/", ("S",))],
            [gsc("https://e.com/a/", 40, 400), gsc("https://e.com/gone/", 60, 600)],
        )
        assert report.site.clicks == 40
        assert report.unattributed.clicks == 60
        assert report.unattributed.rows == 1
        assert report.attributed_share == pytest.approx(0.4)

    def test_the_export_is_partitioned_between_sections_and_unattributed(self):
        rows = [gsc("https://e.com/a/", 5, 50), gsc("https://e.com/x/", 7, 70), gsc("junk", 3, 30)]
        report = rollup([profile("https://e.com/a/", ("S",))], rows)
        assert report.site.clicks + report.unattributed.clicks == sum(r.clicks for r in rows)

    def test_an_export_with_no_clicks_explains_everything(self):
        report = rollup([profile("https://e.com/a/", ("S",))])
        assert report.attributed_share == 1.0

    def test_the_resolution_report_travels_with_the_numbers(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",))],
            [gsc("https://e.com/a/"), gsc("https://e.com/gone/")],
        )
        assert report.gsc_resolution.total == 2
        assert report.gsc_resolution.match_rate_pct == 50.0
        assert report.gsc_resolution.is_reliable is False

    def test_a_page_with_no_data_is_counted_but_not_measured(self):
        """A page with no data is counted but not measured.

        A section of 400 pages with 3 measured is a different object from one
        with 400 measured, and their click totals can be identical.
        """
        report = rollup(
            [profile("https://e.com/a/", ("S",)), profile("https://e.com/b/", ("S",))],
            [gsc("https://e.com/a/", 1, 10)],
        )
        found = section(report, ("S",))
        assert found.pages == 2
        assert found.pages_with_data == 1
        assert found.data_coverage == 0.5

    def test_a_row_of_zeroes_is_data(self):
        """Search Console exports such rows.

        "Reported with no clicks" and "never reported" are different findings —
        the first says the page is indexed and losing, the second says nothing
        at all. Counting a zero row as absent would undo the reason
        `PagePerformance.gsc` is optional rather than a row of zeroes.
        """
        report = rollup([profile("https://e.com/a/", ("S",))], [gsc("https://e.com/a/", 0, 0)])
        assert section(report, ("S",)).pages_with_data == 1

    def test_pages_nothing_placed_land_in_a_visible_bucket(self):
        """Unplaced pages land in a visible bucket.

        4 of the stored crawls express "unplaced" as an empty trail and 53 as
        `(OTHERS, <type>)`. Neither may vanish from the section list.
        """
        report = rollup(
            [profile("https://e.com/a/"), profile("https://e.com/b/", ("OTHERS", "UNKNOWN"))],
            [gsc("https://e.com/a/", 4, 40), gsc("https://e.com/b/", 6, 60)],
        )
        assert section(report, ("OTHERS",)).clicks == 10
        assert report.site.clicks == 10

    def test_section_path_of_folds_an_empty_trail(self):
        assert section_path_of(profile("https://e.com/a/")) == ("OTHERS",)
        assert section_path_of(profile("https://e.com/a/", ("S",))) == ("S",)


class TestGa4:
    def test_paths_resolve_and_roll_up(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",))],
            (),
            [Ga4PageMetrics(path="/a/", sessions=12, engaged_sessions=8, revenue=99.5)],
        )
        found = section(report, ("S",))
        assert found.sessions == 12
        assert found.engaged_sessions == 8
        assert found.revenue == pytest.approx(99.5)

    def test_ga4_alone_still_marks_a_page_as_measured(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",))],
            (),
            [Ga4PageMetrics(path="/a/", sessions=1)],
        )
        assert section(report, ("S",)).pages_with_data == 1

    def test_unresolved_ga4_sessions_are_held_too(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",))],
            (),
            [Ga4PageMetrics(path="/gone/", sessions=30)],
        )
        assert report.unattributed.sessions == 30
        assert report.unattributed.rows == 1

    def test_engagement_time_is_summed_not_averaged(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",)), profile("https://e.com/b/", ("S",))],
            (),
            [
                Ga4PageMetrics(path="/a/", engagement_time_sec=100.0),
                Ga4PageMetrics(path="/b/", engagement_time_sec=300.0),
            ],
        )
        assert section(report, ("S",)).engagement_time_sec == pytest.approx(400.0)


class TestDuplicateProfiles:
    def test_the_better_placed_copy_decides_the_section(self):
        """The better-placed copy decides the section.

        516 of 2,544 duplicate groups in the corpus disagree about placement —
        one copy under `("Home",)`, the other in `("OTHERS", "UNKNOWN")`.

        Keeping whichever arrived first would hand a fifth of them to the wrong
        section, and the totals built on top would be wrong with nothing to
        indicate it. Asserted in both input orders, because "first seen" is
        exactly what must not decide this.
        """
        placed = profile("https://e.com/a/", ("Home",))
        unplaced = profile("https://e.com/a/?ref=nav", ("OTHERS", "UNKNOWN"))
        for pages in ([unplaced, placed], [placed, unplaced]):
            report = rollup(pages, [gsc("https://e.com/a/", 5, 50)])
            assert section(report, ("Home",)).clicks == 5
            assert report.duplicate_profiles == 1
            assert report.site.pages == 1

    def test_the_duplicate_count_is_carried_into_the_rollup(self):
        report = rollup(
            [profile("https://e.com/a/", ("S",)), profile("https://e.com/a/?ref=x", ("S",))]
        )
        assert report.duplicate_profiles == 1


class TestDegenerateInputs:
    def test_an_empty_crawl_produces_a_site_row_and_no_sections(self):
        report = rollup([])
        assert report.site.pages == 0
        assert report.site.position is None
        assert report.sections == ()
        assert report.site.data_coverage == 0.0

    def test_metrics_with_no_crawl_are_entirely_unattributed(self):
        report = rollup([], [gsc("https://e.com/a/", 9, 90)])
        assert report.unattributed.clicks == 9
        assert report.attributed_share == 0.0

    def test_a_deep_trail_is_handled_iteratively(self):
        """Trails run to depth 6 in the corpus; nothing here recurses."""
        trail = tuple(f"L{n}" for n in range(6))
        report = rollup([profile("https://e.com/a/", trail)], [gsc("https://e.com/a/", 1, 1)])
        assert section(report, trail).depth == 6
        assert len([s for s in report.sections if s.clicks == 1]) == 6
