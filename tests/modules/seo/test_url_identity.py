"""Tests for the Google-URL to crawled-page join.

The join is the whole risk of the performance pillar, and it fails silently by
default: an unresolved URL produces a section total that is simply too low, with
nothing on screen to say so. So most of what is asserted here is not "does the
happy path work" but "does a wrong answer get refused rather than guessed", and
"is the reason for a miss specific enough to act on".
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
from src.modules.seo.performance.schemas import (
    Ga4PageMetrics,
    GscPageMetrics,
    MatchFailure,
    MatchTier,
    PagePerformance,
    ResolutionOutcome,
    UrlMatch,
)
from src.modules.seo.performance.url_identity import UrlResolutionIndex


def profile(
    url: str,
    *,
    canonical: str | None = None,
    final: str = "",
) -> FullPageIntelligenceProfile:
    """A crawled page. `canonical` defaults to the page's own address."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=canonical if canonical is not None else url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
        final_url=final,
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


def index(*pages: FullPageIntelligenceProfile) -> UrlResolutionIndex:
    return UrlResolutionIndex(pages)


class TestTheFourShapesGoogleSendsUs:
    """Search Console and GA4 do not spell an address the way a crawler does."""

    def test_the_address_as_crawled(self):
        idx = index(profile("https://e.com/pricing/"))
        assert idx.resolve_url("https://e.com/pricing/") == "https://e.com/pricing/"

    def test_scheme_www_and_trailing_slash_are_the_same_page(self):
        """All four of these are one page served four ways.

        Search Console reports whichever variant it settled on, which is not
        necessarily the one the site links internally.
        """
        idx = index(profile("https://e.com/pricing/"))
        for variant in (
            "http://e.com/pricing/",
            "https://www.e.com/pricing/",
            "http://www.e.com/pricing",
            "https://e.com/PRICING",
        ):
            assert idx.resolve_url(variant) == "https://e.com/pricing/", variant

    def test_ga4_sends_a_path_with_no_host_at_all(self):
        """`pagePath` is a path; the host is a property setting, not a column."""
        idx = index(profile("https://e.com/blog/post/"))
        assert idx.resolve_url("/blog/post/") == "https://e.com/blog/post/"

    def test_tracking_parameters_do_not_break_the_join(self):
        idx = index(profile("https://e.com/blog/post/"))
        assert idx.resolve_url("/blog/post/?utm_source=nl&gclid=x") == "https://e.com/blog/post/"

    def test_percent_encoding_folds(self):
        """Encoding an octet that needed no encoding does not change the URL."""
        idx = index(profile("https://e.com/blog/my-post/"))
        assert idx.resolve_url("https://e.com/blog/%6Dy-post/") == "https://e.com/blog/my-post/"


class TestEvidenceTiers:
    """Three ways a page can be known by an address, and they are not equal."""

    def test_a_redirect_destination_resolves_to_the_page_we_crawled(self):
        """Google reports where a URL lands, not where the site linked it.

        Without this, every redirecting page on the site contributes nothing to
        its section and looks like it has no demand.
        """
        idx = index(profile("https://e.com/old/", final="https://e.com/new/"))
        match = idx.resolve("https://e.com/new/")
        assert isinstance(match, UrlMatch)
        assert match.page_url == "https://e.com/old/"
        assert match.via is MatchTier.REDIRECT_TARGET

    def test_a_declared_canonical_resolves_to_the_page_that_declared_it(self):
        """A tag is the only thing connecting these two addresses.

        `?page=2` is a real parameter, not tracking, so the two do not normalise
        together on their own.
        """
        idx = index(profile("https://e.com/a/?page=2", canonical="https://e.com/a/"))
        match = idx.resolve("https://e.com/a/")
        assert isinstance(match, UrlMatch)
        assert match.page_url == "https://e.com/a/?page=2"
        assert match.via is MatchTier.CANONICAL_TAG

    def test_the_crawled_address_outranks_another_pages_canonical_claim(self):
        """The tier order is load-bearing, not cosmetic.

        `/b/` exists and was crawled. `/a/` claims `/b/` as its canonical. A
        Google row for `/b/` is about `/b/` — attributing it to `/a/` because a
        tag said so would move a real page's traffic onto a duplicate.
        """
        idx = index(
            profile("https://e.com/b/"),
            profile("https://e.com/a/", canonical="https://e.com/b/"),
        )
        match = idx.resolve("https://e.com/b/")
        assert isinstance(match, UrlMatch)
        assert match.page_url == "https://e.com/b/"
        assert match.via is MatchTier.CRAWLED_URL

    def test_a_cross_domain_canonical_is_still_resolvable(self):
        """A cross-domain canonical resolves.

        This is why the host check happens *after* the lookup, not before:
        Google reports the other host, and the index already knows that address.
        """
        idx = index(profile("https://e.com/a/", canonical="https://other.com/a/"))
        assert idx.resolve_url("https://other.com/a/") == "https://e.com/a/"


class TestAmbiguityIsRefused:
    """Guessing here is worse than failing: a wrong answer is invisible."""

    def test_two_pages_claiming_one_canonical_resolve_to_neither(self):
        """This is the normal, intended use of canonical tags, so it is common.

        Picking one would silently attribute a whole URL's clicks to an
        arbitrary member of the set, and the dashboard would look correct.
        """
        idx = index(
            profile("https://e.com/a/?x=1", canonical="https://e.com/a/"),
            profile("https://e.com/a/?x=2", canonical="https://e.com/a/"),
        )
        failure = idx.resolve("https://e.com/a/")
        assert failure.reason is MatchFailure.AMBIGUOUS

    def test_an_ambiguous_strong_tier_is_not_rescued_by_a_weak_one(self):
        """A clash at the deciding tier stops the search.

        Falling through to canonical tags here would answer a harder question
        with weaker evidence, which is exactly backwards.
        """
        idx = index(
            profile("https://e.com/a/", final="https://e.com/t/"),
            profile("https://e.com/b/", final="https://e.com/t/"),
            profile("https://e.com/c/", canonical="https://e.com/t/"),
        )
        assert idx.resolve("https://e.com/t/").reason is MatchFailure.AMBIGUOUS

    def test_one_page_emitted_twice_is_not_a_conflict(self):
        """The crawl really does ship duplicate rows, and they are not a clash.

        Measured on a fresh 12,807-page highradius crawl: 20 addresses appear
        as two profiles with an identical dedup key — `?ref=navbar` against the
        bare URL, and a doubled slash against a single one. Refusing those would
        drop real traffic over a defect the analyst cannot see, so the engine's
        own key settles them. The count stays visible.
        """
        idx = index(
            profile("https://e.com/whats-new/"),
            profile("https://e.com/whats-new/?ref=navbar"),
            profile("https://e.com/a//b/"),
            profile("https://e.com/a/b/"),
        )
        assert idx.duplicate_profiles == 2
        assert idx.page_count == 2
        assert idx.resolve_url("https://e.com/whats-new/") == "https://e.com/whats-new/"
        assert idx.resolve_url("/a/b/") == "https://e.com/a//b/"

    def test_one_path_served_by_two_hosts_is_refused(self):
        """The path maps carry no host, because GA4 supplies none.

        A crawl spanning two hosts therefore has two owners for `/pricing/`, and
        a GA4 row cannot say which. Refusing falls out of the same clash rule
        rather than needing a host special case.
        """
        idx = index(profile("https://e.com/pricing/"), profile("https://shop.e.com/pricing/"))
        assert idx.resolve("/pricing/").reason is MatchFailure.AMBIGUOUS


class TestTheBarePathFallback:
    """Last resort, and reported under its own tier so it can be discounted."""

    def test_a_query_is_dropped_only_when_one_page_owns_the_path(self):
        idx = index(profile("https://e.com/search/?q=a"))
        match = idx.resolve("/search/")
        assert isinstance(match, UrlMatch)
        assert match.page_url == "https://e.com/search/?q=a"
        assert match.via is MatchTier.BARE_PATH

    def test_an_exact_query_match_is_preferred_over_the_fallback(self):
        idx = index(profile("https://e.com/search/"), profile("https://e.com/search/?q=a"))
        match = idx.resolve("/search/")
        assert isinstance(match, UrlMatch)
        assert match.page_url == "https://e.com/search/"
        assert match.via is MatchTier.CRAWLED_URL

    def test_several_query_variants_and_no_bare_page_is_refused(self):
        idx = index(profile("https://e.com/s/?q=a"), profile("https://e.com/s/?q=b"))
        assert idx.resolve("/s/").reason is MatchFailure.AMBIGUOUS


class TestFailuresNameSomethingActionable:
    """A match rate says the join is bad; these say who has to fix it."""

    def test_a_url_on_this_site_that_was_never_crawled(self):
        idx = index(profile("https://e.com/a/"))
        assert idx.resolve("https://e.com/missing/").reason is MatchFailure.NOT_CRAWLED

    def test_a_host_the_crawl_never_covered(self):
        idx = index(profile("https://e.com/a/"))
        assert idx.resolve("https://elsewhere.com/a/").reason is MatchFailure.OFF_SITE

    def test_a_subdomain_is_off_site_not_missing(self):
        """A subdomain is off-site, not missing.

        `blog.e.com` is a different property, and merging it would collapse a
        real distinction the rest of the engine is careful to keep.
        """
        idx = index(profile("https://e.com/a/"))
        assert idx.resolve("https://blog.e.com/a/").reason is MatchFailure.OFF_SITE

    def test_things_that_are_not_urls(self):
        idx = index(profile("https://e.com/a/"))
        for junk in ("", "   ", "not a url", "Page", "mailto:x@e.com", "sc-domain:e.com"):
            assert idx.resolve(junk).reason is MatchFailure.UNPARSEABLE, junk

    def test_a_bracket_that_makes_urlsplit_raise(self):
        """A bracket that makes `urlsplit` raise.

        `safe_split` exists because one malformed link once failed a whole crawl.
        The same input must not fail a whole export.
        """
        idx = index(profile("https://e.com/a/"))
        assert idx.resolve("https://[e.com/a/").reason is MatchFailure.UNPARSEABLE


class TestTheReport:
    def test_rate_tiers_and_reasons_are_all_reported(self):
        idx = index(
            profile("https://e.com/a/"),
            profile("https://e.com/b/", final="https://e.com/b-new/"),
        )
        report = idx.build_resolution_report(
            ["https://e.com/a/", "https://e.com/b-new/", "https://e.com/gone/", "junk"]
        )
        assert report.total == 4
        assert report.matched_count == 2
        assert report.match_rate_pct == 50.0
        assert report.is_reliable is False
        assert report.by_tier[MatchTier.CRAWLED_URL] == 1
        assert report.by_tier[MatchTier.REDIRECT_TARGET] == 1
        assert report.by_failure[MatchFailure.NOT_CRAWLED] == 1
        assert report.by_failure[MatchFailure.UNPARSEABLE] == 1

    def test_the_threshold_decides_reliability(self):
        idx = index(*(profile(f"https://e.com/p{n}/") for n in range(10)))
        urls = [f"https://e.com/p{n}/" for n in range(9)] + ["https://e.com/gone/"]
        assert idx.build_resolution_report(urls).is_reliable is True
        assert idx.build_resolution_report(urls, threshold_pct=95.0).is_reliable is False

    def test_an_empty_export_is_not_reliable(self):
        """Vacuous truth is the wrong answer to "can I trust the totals".

        There are no totals. Returning True would present an empty dashboard as
        a healthy one, which is the failure this whole module exists to prevent.
        """
        report = index(profile("https://e.com/a/")).build_resolution_report([])
        assert report.total == 0
        assert report.match_rate_pct == 0.0
        assert report.is_reliable is False

    def test_duplicate_rows_are_counted_as_uploaded(self):
        """The denominator is the analyst's file, not a set we derived from it."""
        idx = index(profile("https://e.com/a/"))
        report = idx.build_resolution_report(["https://e.com/a/"] * 3)
        assert report.total == 3
        assert report.matched_count == 3

    def test_an_empty_crawl_resolves_nothing_without_raising(self):
        report = UrlResolutionIndex([]).build_resolution_report(["https://e.com/a/"])
        assert report.matched_count == 0
        assert report.by_failure[MatchFailure.OFF_SITE] == 1

    def test_page_count_reports_distinct_pages(self):
        idx = index(profile("https://e.com/a/"), profile("https://e.com/b/"))
        assert idx.page_count == 2


class TestMetricContracts:
    """Rates are derived, and a missing metric is not a zero."""

    def test_ctr_is_computed_not_stored(self):
        assert GscPageMetrics(url="https://e.com/a/", clicks=5, impressions=100).ctr == 0.05

    def test_no_impressions_gives_no_ctr_rather_than_an_error(self):
        """A Search Console export can contain such a row; it is not a fault."""
        assert GscPageMetrics(url="https://e.com/a/").ctr == 0.0

    def test_absent_and_zero_are_different_states(self):
        """Absent and zero are different states.

        A page missing from the export and a page with no clicks roll up
        identically if both are written as zero — and only one of them is a
        defect in the join.
        """
        absent = PagePerformance(page_url="https://e.com/a/")
        measured = PagePerformance(
            page_url="https://e.com/b/", gsc=GscPageMetrics(url="https://e.com/b/")
        )
        assert absent.has_data is False
        assert measured.has_data is True
        assert absent.gsc is None

    def test_ga4_metrics_hold_a_path_not_a_url(self):
        metrics = Ga4PageMetrics(path="/blog/post/", sessions=12, engagement_time_sec=340.5)
        assert metrics.path == "/blog/post/"
        assert metrics.sessions == 12

    def test_the_outcome_serialises_its_derived_fields(self):
        """Derived fields survive serialisation.

        The UI has to show the match rate, so it cannot live in a plain property
        that `model_dump` drops.
        """
        dumped = ResolutionOutcome(total=2, matches=()).model_dump()
        assert dumped["match_rate_pct"] == 0.0
        assert dumped["is_reliable"] is False
        assert "by_failure" in dumped
