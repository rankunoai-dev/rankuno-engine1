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
    Severity,
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


def filler(count: int, section: tuple[str, ...] = ("Z",)) -> list:
    """Pages that only exist to give the site a realistic size.

    `SITEWIDE_LINK_SHARE` is a share *of the site*, so a two-page fixture makes
    every link count site-wide and every hub disappear. These carry one inbound
    link each so they do not trip the orphan-reliability gate either.
    """
    return [profile(f"https://e.com/filler{n}/", section, inbound=1) for n in range(count)]


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
            filler(40)
            + [
                profile("https://e.com/hub/", ("S",), inbound=6),
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

    def test_a_site_wide_link_is_not_a_hub(self):
        """A site-wide link is navigation, not a hub to link from.

        The first real run named `/info-guide` — in the footer of 78% of
        gep.com — as the page to link from, for every finding in its section.
        The homepage at 88% and the locale switchers at 85% were named for
        others. "Check whether that page links here" was advice about the
        footer, delivered with a score attached.
        """
        pages = filler(40) + [
            # Linked from most of the site: the footer, not a hub.
            profile("https://e.com/footer-link/", ("S",), inbound=30),
            # A real topical hub, well linked but not site-wide.
            profile("https://e.com/topic-hub/", ("S",), inbound=5),
            profile("https://e.com/weak/", ("S",), inbound=1),
        ]
        rows = [
            gsc("https://e.com/footer-link/", 400, 1000, position=2.0),
            gsc("https://e.com/topic-hub/", 50, 1000, position=3.0),
            gsc("https://e.com/weak/", 1, 900, position=12.0),
        ]
        found = of_kind(report(pages, rows), OpportunityKind.UNDERPERFORMING_SIBLING)
        assert [item.url for item in found] == ["https://e.com/weak/"]
        # The topical hub, never the footer link.
        assert found[0].reference_url == "https://e.com/topic-hub/"

    def test_a_page_beating_its_section_is_not_underperforming(self):
        """A page beating its own section is not underperforming.

        `gep.com/login` was reported at position 5.3 while taking 89,220 clicks
        on 589,390 impressions — a 15% click-through rate. That is a page
        winning a navigational query, not one starved of links. The benchmark is
        the section's own combined rate, so no click-through curve is assumed.
        """
        result = report(
            filler(40)
            + [
                profile("https://e.com/hub/", ("S",), inbound=6),
                profile("https://e.com/login/", ("S",), inbound=1),
                profile("https://e.com/dull/", ("S",), inbound=1),
            ],
            [
                gsc("https://e.com/hub/", 10, 5000, position=2.0),
                gsc("https://e.com/login/", 900, 6000, position=5.3),
                gsc("https://e.com/dull/", 1, 5000, position=12.0),
            ],
        )
        found = of_kind(result, OpportunityKind.UNDERPERFORMING_SIBLING)
        assert [item.url for item in found] == ["https://e.com/dull/"]

    def test_a_page_is_reported_under_one_kind_only(self):
        """A page is reported under one kind only.

        The first real run produced seven pages appearing as both buried and
        underperforming — the third such pairing, after 0041 and 0042 each
        caught one of the other two. One page, one instruction.
        """
        pages = [profile(f"https://e.com/f{n}/", ("A", "B", "C"), inbound=1) for n in range(9)]
        pages.append(profile("https://e.com/hub/", ("A", "B", "C"), inbound=2))
        pages.append(profile("https://e.com/deep/", ("A", "B", "C"), inbound=1))
        rows = [
            gsc("https://e.com/hub/", 50, 500, position=2.0),
            gsc("https://e.com/deep/", 40, 9000, position=12.0),
        ]
        result = report(pages, rows)
        appearances = [i.kind for i in result.opportunities if i.url == "https://e.com/deep/"]
        assert appearances == [OpportunityKind.BURIED_WITH_TRAFFIC]

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


class TestIndexedSubdomains:
    """The one finding here that can be a security matter, not an SEO one."""

    def rows(self, host: str, count: int, clicks: int) -> list:
        return [gsc(f"https://{host}/p{n}/", clicks, clicks * 10) for n in range(count)]

    def test_a_subdomain_google_indexes_and_the_crawl_missed(self):
        result = report(
            [profile("https://e.com/a/", inbound=3)],
            [gsc("https://e.com/a/", 10, 100), *self.rows("staging.e.com", 4, 900)],
        )
        found = of_kind(result, OpportunityKind.INDEXED_SUBDOMAIN)
        assert [item.url for item in found] == ["staging.e.com"]
        assert found[0].severity is Severity.CRITICAL
        assert "4 URLs on staging.e.com" in found[0].reason
        # It points at a real address, so the claim can be checked.
        assert found[0].reference_url is not None

    def test_a_suspicious_name_sharpens_the_wording(self):
        """5 of gep.com's 11 subdomains name themselves — including the largest."""
        result = report(
            [profile("https://e.com/a/", inbound=3)],
            [gsc("https://e.com/a/", 10, 100), *self.rows("uat-auth.e.com", 4, 900)],
        )
        reason = of_kind(result, OpportunityKind.INDEXED_SUBDOMAIN)[0].reason
        assert "never meant to be public" in reason
        assert "noindex" in reason

    def test_an_unremarkable_name_is_still_reported(self):
        """An unremarkable name is still reported.

        `leodsaks-us.gep.com` carries 275 of the 558 spam URLs and names itself
        nothing at all. Firing on the name would have hidden half of it.
        """
        result = report(
            [profile("https://e.com/a/", inbound=3)],
            [gsc("https://e.com/a/", 10, 100), *self.rows("leodsaks-us.e.com", 4, 900)],
        )
        found = of_kind(result, OpportunityKind.INDEXED_SUBDOMAIN)
        assert len(found) == 1
        # No diagnosis it cannot support: both branches are offered.
        assert "If it is a real property" in found[0].reason

    def test_severity_is_magnitude_not_the_name(self):
        """A login host with two indexed URLs and no clicks is not critical.

        An earlier version made a suspicious name sufficient, which put exactly
        that above findings worth thousands of clicks.
        """
        result = report(
            [profile(f"https://e.com/p{n}/", inbound=3) for n in range(200)],
            [
                *[gsc(f"https://e.com/p{n}/", 50, 500) for n in range(200)],
                gsc("https://loginqc.e.com/x/", 0, 1),
            ],
        )
        found = of_kind(result, OpportunityKind.INDEXED_SUBDOMAIN)
        assert [item.severity for item in found] == [Severity.ROUTINE]
        # Still named as non-production, because it is.
        assert "never meant to be public" in found[0].reason

    def test_an_unrelated_domain_is_not_reported_here(self):
        """It is somebody else's site. Nothing to recommend about it."""
        result = report(
            [profile("https://e.com/a/", inbound=3)],
            [gsc("https://e.com/a/", 10, 100), gsc("https://elsewhere.org/x/", 900, 9000)],
        )
        assert of_kind(result, OpportunityKind.INDEXED_SUBDOMAIN) == []

    def test_a_critical_finding_sorts_above_every_other_kind(self):
        """A critical finding sorts above every other kind.

        `score` ranks within a kind and says nothing across kinds, so without
        severity this sorted by enum position — below link suggestions.
        """
        pages = [profile(f"https://e.com/p{n}/", inbound=0) for n in range(3)]
        pages += [profile(f"https://e.com/q{n}/", inbound=7) for n in range(7)]
        result = report(
            pages,
            [
                *[gsc(f"https://e.com/p{n}/", 500, 5000) for n in range(3)],
                *self.rows("staging.e.com", 3, 10),
            ],
        )
        first = result.opportunities[0]
        assert first.kind is OpportunityKind.INDEXED_SUBDOMAIN
        assert first.severity is Severity.CRITICAL


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
