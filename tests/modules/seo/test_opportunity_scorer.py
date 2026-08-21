"""Tests for the opportunity scorer.

The scorer's job is to be *sharp*. A finding that fires on a third of the site
is not a finding, and one that fires on a crawl whose signal was never collected
is worse than silence — it is a confident wrong answer an analyst will act on.
So most of what is asserted here is refusal: which crawls get no answer, which
pages are excluded, and whether the report says so out loud.
"""

from __future__ import annotations

from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.performance.aggregator import merge_page_metrics
from src.modules.seo.performance.opportunity_scorer import (
    Opportunity,
    OpportunityKind,
    SignalGap,
    score_opportunities,
)
from src.modules.seo.performance.schemas import GscPageMetrics
from src.modules.seo.performance.url_identity import UrlResolutionIndex


def profile(
    url: str, trail: tuple[str, ...] = ("S",), *, inbound: int = 5
) -> FullPageIntelligenceProfile:
    """A crawled page with a navigation trail and an inbound link count."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
        breadcrumb_path=trail,
        inbound_internal_links_count=inbound,
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


def report(pages, rows=(), **kwargs: int):
    index = UrlResolutionIndex(pages)
    return score_opportunities(index, merge_page_metrics(index, rows), **kwargs)


def of_kind(result, kind: OpportunityKind) -> list[Opportunity]:
    return [item for item in result.opportunities if item.kind is kind]


class TestOrphansWithTraffic:
    def test_a_page_with_clicks_and_no_inbound_link_is_reported(self):
        result = report(
            [profile("https://e.com/a/", inbound=0), profile("https://e.com/b/", inbound=9)],
            [gsc("https://e.com/a/", 40, 400), gsc("https://e.com/b/", 90, 900)],
        )
        found = of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC)
        assert [item.url for item in found] == ["https://e.com/a/"]
        assert "no internal link" in found[0].reason

    def test_an_orphan_with_no_clicks_is_not_an_opportunity(self):
        """An orphan with no clicks is not an opportunity.

        Zero inbound links is a fact about thousands of pages. Proven demand
        is what makes one of them worth an analyst's afternoon.
        """
        result = report([profile("https://e.com/a/", inbound=0)], [gsc("https://e.com/a/", 0, 400)])
        assert of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC) == []

    def test_a_crawl_that_never_counted_links_gets_no_answer(self):
        """The decisive guard.

        Across the 58 stored crawls the zero-inbound share runs 0%–38%, then
        jumps to 54%, 72%, a cluster at 80%, and 97/99/100% — the high group
        being crawls that stopped at their page ceiling, where pages were listed
        but never fetched. Emitting 99,000 orphans from one of those is the
        loudest possible way to be wrong.
        """
        pages = [profile(f"https://e.com/p{n}/", inbound=0) for n in range(9)]
        pages.append(profile("https://e.com/hub/", inbound=20))
        result = report(pages, [gsc(f"https://e.com/p{n}/", 10, 100) for n in range(9)])
        assert result.skipped[OpportunityKind.ORPHAN_WITH_TRAFFIC] is (
            SignalGap.INBOUND_LINKS_UNRELIABLE
        )
        assert of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC) == []

    def test_a_crawl_that_did_count_links_is_answered(self):
        pages = [profile(f"https://e.com/p{n}/", inbound=3) for n in range(9)]
        pages.append(profile("https://e.com/orphan/", inbound=0))
        result = report(pages, [gsc("https://e.com/orphan/", 10, 100)])
        assert OpportunityKind.ORPHAN_WITH_TRAFFIC not in result.skipped
        assert len(of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC)) == 1


class TestBuriedWithTraffic:
    def test_navigation_depth_is_what_counts_not_depth_from_l0(self):
        """Navigation depth is what counts not depth from l0.

        `depth_from_l0` holds URL path depth offset by two, not distance from
        the homepage — 90.4% of stored pages sit at exactly `segments + 2`.

        Both pages here carry `depth_from_l0=1`. Only the one that is genuinely
        three levels down the navigation is reported.
        """
        result = report(
            [
                profile("https://e.com/deep/", ("Products", "CRM", "Pricing")),
                profile("https://e.com/shallow/", ("Products",)),
            ],
            [gsc("https://e.com/deep/", 30, 300), gsc("https://e.com/shallow/", 90, 900)],
        )
        found = of_kind(result, OpportunityKind.BURIED_WITH_TRAFFIC)
        assert [item.url for item in found] == ["https://e.com/deep/"]
        assert "3 levels down" in found[0].reason

    def test_a_deep_page_with_no_clicks_is_not_an_opportunity(self):
        """A deep page with no clicks is not an opportunity.

        26.9% of corpus pages sit three or more levels down. Depth alone is a
        description of the site, not a recommendation — proven demand from down
        there is what makes one worth promoting.
        """
        result = report(
            [profile("https://e.com/deep/", ("A", "B", "C"), inbound=4)],
            [gsc("https://e.com/deep/", 0, 900)],
        )
        assert of_kind(result, OpportunityKind.BURIED_WITH_TRAFFIC) == []

    def test_a_page_is_not_reported_as_both_orphan_and_buried(self):
        """A page is not reported as both orphan and buried.

        Two findings for one page is noise. The orphan is the stronger
        defect, so it wins.
        """
        pages = [profile(f"https://e.com/p{n}/", ("A", "B", "C"), inbound=4) for n in range(9)]
        pages.append(profile("https://e.com/x/", ("A", "B", "C"), inbound=0))
        result = report(pages, [gsc("https://e.com/x/", 20, 200)])
        kinds = [item.kind for item in result.opportunities if item.url == "https://e.com/x/"]
        assert kinds == [OpportunityKind.ORPHAN_WITH_TRAFFIC]

    def test_buried_survives_a_crawl_with_unusable_link_counts(self):
        """Buried survives a crawl with unusable link counts.

        It rests on trail depth and clicks, neither of which depends on the
        inbound count, so it is not gated with the orphan finding.
        """
        pages = [profile(f"https://e.com/p{n}/", ("A", "B", "C"), inbound=0) for n in range(10)]
        result = report(pages, [gsc("https://e.com/p0/", 5, 50)])
        assert OpportunityKind.ORPHAN_WITH_TRAFFIC in result.skipped
        assert len(of_kind(result, OpportunityKind.BURIED_WITH_TRAFFIC)) == 1


class TestIndexedCrawlTraps:
    def test_a_trap_google_indexed_is_read_from_the_export(self):
        """A trap google indexed is read from the export.

        No refusal list is stored — discovery counts refusals but keeps no
        URLs. Working from the export side is also stronger evidence: a trap the
        crawler merely declined costs nothing.
        """
        trap = "https://e.com/software/b2b/software/b2b/software/b2b/"
        result = report(
            [profile("https://e.com/a/")], [gsc("https://e.com/a/", 1, 1), gsc(trap, 0, 900)]
        )
        found = of_kind(result, OpportunityKind.INDEXED_CRAWL_TRAP)
        assert [item.url for item in found] == [trap]
        assert "crawl budget" in found[0].reason

    def test_an_ordinary_uncrawled_url_is_not_a_trap(self):
        """An ordinary uncrawled url is not a trap.

        Most unresolved rows are pages we simply did not reach. Calling those
        crawl traps would bury the real ones.
        """
        result = report(
            [profile("https://e.com/a/")],
            [gsc("https://e.com/a/", 1, 1), gsc("https://e.com/never-crawled/", 5, 50)],
        )
        assert of_kind(result, OpportunityKind.INDEXED_CRAWL_TRAP) == []

    def test_the_same_trap_reported_twice_is_one_finding(self):
        trap = "https://e.com/pricing/plans/pricing/plans/pricing/plans/"
        result = report(
            [profile("https://e.com/x/")],
            [gsc("https://e.com/x/", 1, 1), gsc(trap, 0, 10), gsc(trap, 0, 20)],
        )
        assert len(of_kind(result, OpportunityKind.INDEXED_CRAWL_TRAP)) == 1


class TestUnderperformingSiblings:
    def test_a_striking_distance_page_beside_a_linked_hub(self):
        result = report(
            [
                profile("https://e.com/hub/", ("S",), inbound=40),
                profile("https://e.com/weak/", ("S",), inbound=1),
            ],
            [
                gsc("https://e.com/hub/", 100, 1000, position=2.0),
                gsc("https://e.com/weak/", 5, 900, position=12.0),
            ],
        )
        found = of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING)
        assert [item.url for item in found] == ["https://e.com/weak/"]
        assert found[0].reference_url == "https://e.com/hub/"
        assert "Check whether that page links here" in found[0].reason

    def test_a_page_already_winning_is_not_an_opportunity(self):
        result = report(
            [
                profile("https://e.com/hub/", ("S",), inbound=40),
                profile("https://e.com/good/", ("S",), inbound=1),
            ],
            [
                gsc("https://e.com/hub/", 100, 1000, position=2.0),
                gsc("https://e.com/good/", 80, 900, position=1.4),
            ],
        )
        assert of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING) == []

    def test_a_page_far_off_page_one_is_not_an_opportunity(self):
        """A page far off page one is not an opportunity.

        Past position 20, an internal link is not what stands between the
        page and page one, and saying otherwise wastes the recommendation.
        """
        result = report(
            [
                profile("https://e.com/hub/", ("S",), inbound=40),
                profile("https://e.com/far/", ("S",), inbound=1),
            ],
            [
                gsc("https://e.com/hub/", 100, 1000, position=2.0),
                gsc("https://e.com/far/", 1, 900, position=61.0),
            ],
        )
        assert of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING) == []

    def test_a_section_with_no_well_linked_page_yields_nothing(self):
        """There is no hub to link from, so there is no recommendation to make."""
        result = report(
            [
                profile("https://e.com/a/", ("S",), inbound=0),
                profile("https://e.com/b/", ("S",), inbound=0),
            ],
            [
                gsc("https://e.com/a/", 1, 900, position=12.0),
                gsc("https://e.com/b/", 1, 900, position=12.0),
            ],
        )
        assert of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING) == []

    def test_sections_do_not_borrow_each_others_hubs(self):
        """Sections do not borrow each others hubs.

        The hub has to be a sibling. A strong page in another section is not
        a plausible place to add the link from.
        """
        result = report(
            [
                profile("https://e.com/hub/", ("A",), inbound=40),
                profile("https://e.com/weak/", ("B",), inbound=1),
                profile("https://e.com/other/", ("B",), inbound=0),
            ],
            [
                gsc("https://e.com/hub/", 100, 1000, position=2.0),
                gsc("https://e.com/weak/", 5, 900, position=12.0),
                gsc("https://e.com/other/", 1, 10, position=30.0),
            ],
        )
        assert of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING) == []


class TestRankingAndReporting:
    def test_score_is_relative_to_the_largest_in_its_own_kind(self):
        pages = [profile(f"https://e.com/p{n}/", inbound=0) for n in range(3)]
        pages += [profile(f"https://e.com/linked{n}/", inbound=7) for n in range(7)]
        result = report(
            pages,
            [
                gsc("https://e.com/p0/", 100, 1000),
                gsc("https://e.com/p1/", 50, 500),
                gsc("https://e.com/p2/", 10, 100),
            ],
        )
        found = of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC)
        assert [item.score for item in found] == [100.0, 50.0, 10.0]

    def test_findings_are_ordered_by_kind_then_score(self):
        pages = [profile(f"https://e.com/p{n}/", ("A", "B", "C"), inbound=3) for n in range(8)]
        pages.append(profile("https://e.com/orphan/", ("A", "B", "C"), inbound=0))
        rows = [gsc("https://e.com/orphan/", 5, 50)] + [
            gsc(f"https://e.com/p{n}/", n + 1, 10) for n in range(8)
        ]
        result = report(pages, rows)
        kinds = [item.kind for item in result.opportunities]
        assert kinds[0] is OpportunityKind.ORPHAN_WITH_TRAFFIC
        buried = of_kind(result, OpportunityKind.BURIED_WITH_TRAFFIC)
        assert [item.clicks for item in buried] == sorted(
            (item.clicks for item in buried), reverse=True
        )

    def test_the_cap_is_reported_rather_than_applied_silently(self):
        """A list that stops at two and says nothing reads as "there were two"."""
        pages = [profile(f"https://e.com/p{n}/", inbound=0) for n in range(5)]
        pages += [profile(f"https://e.com/l{n}/", inbound=4) for n in range(5)]
        rows = [gsc(f"https://e.com/p{n}/", n + 1, 10) for n in range(5)]
        result = report(pages, rows, limit_per_kind=2)
        assert result.found[OpportunityKind.ORPHAN_WITH_TRAFFIC] == 5
        assert result.truncated[OpportunityKind.ORPHAN_WITH_TRAFFIC] == 3
        assert len(of_kind(result, OpportunityKind.ORPHAN_WITH_TRAFFIC)) == 2
        assert result.limit_per_kind == 2

    def test_an_export_that_resolved_to_nothing_says_so(self):
        """An export that resolved to nothing says so.

        An empty report with no explanation reads as "your site has no
        opportunities", which is a different and much worse claim.
        """
        result = report([profile("https://e.com/a/")], [gsc("https://e.com/elsewhere/", 90, 900)])
        assert result.opportunities == ()
        assert set(result.skipped) == set(OpportunityKind)
        assert all(gap is SignalGap.NO_SEARCH_DATA for gap in result.skipped.values())

    def test_no_export_at_all_is_the_same_answer(self):
        result = report([profile("https://e.com/a/", inbound=0)])
        assert result.skipped[OpportunityKind.ORPHAN_WITH_TRAFFIC] is SignalGap.NO_SEARCH_DATA

    def test_an_evaluated_kind_that_found_nothing_is_silent_in_both_maps(self):
        """An evaluated kind that found nothing is silent in both maps.

        Absent from `found` and from `skipped` means "looked, found none" —
        which is a real answer and must not be confused with "did not look".
        """
        pages = [profile(f"https://e.com/p{n}/", ("S",), inbound=6) for n in range(4)]
        result = report(pages, [gsc("https://e.com/p0/", 5, 50, position=2.0)])
        assert OpportunityKind.ORPHAN_WITH_TRAFFIC not in result.found
        assert OpportunityKind.ORPHAN_WITH_TRAFFIC not in result.skipped

    def test_an_empty_crawl_does_not_raise(self):
        result = report([])
        assert result.opportunities == ()
        assert result.skipped[OpportunityKind.INDEXED_CRAWL_TRAP] is SignalGap.NO_SEARCH_DATA
