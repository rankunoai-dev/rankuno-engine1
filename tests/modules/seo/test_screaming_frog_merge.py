"""Tests for folding Screaming Frog's missed pages into a crawl result.

The load-bearing property is **selectivity**. Only `MISSED_PAGE` is merged; every
other frog-side reason is a difference the engine holds on purpose, and merging
one would re-import the noise cycles 0020 and 0021 exist to reject. Most of these
tests pin that down.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.screaming_frog_merge import merge_reconciled_urls
from src.modules.seo.page_classifier.tool import CrawlSummary, PageClassificationOutput
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

BASE = "https://www.e.com/"

HEADER = (
    "Address,Status Code,Content Type,Indexability,Indexability Status,"
    "Redirect URL,Crawl Depth,Unique Inlinks"
)


def csv_of(*lines: str) -> str:
    """An export with the real header and the given rows."""
    return "\n".join((HEADER, *lines))


def live(url: str, inlinks: int = 4, depth: int = 3) -> str:
    """A row for a live, indexable HTML page."""
    return f'"{url}",200,text/html; charset=UTF-8,Indexable,,,{depth},{inlinks}'


def profile(url: str) -> FullPageIntelligenceProfile:
    """A minimal valid profile, built in full so the model validates it."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
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
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
    )


@pytest.fixture
def crawl() -> PageClassificationOutput:
    """A two-page crawl to merge into."""
    pages = (profile("https://www.e.com/a/"), profile("https://www.e.com/b/"))
    return PageClassificationOutput(
        base_url=BASE,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport(profile_name="default", detected_profile_name="default"),
        discovery=DiscoveryReport(base_url=BASE, total_urls=2, orphans=1),
        summary=CrawlSummary(pages_classified=2, llm_spend_usd=1.25),
        pages=pages,
    )


class TestOnlyMissedPagesAreMerged:
    """Every other frog-side reason is a difference, not a defect."""

    @pytest.mark.parametrize(
        "line",
        [
            # A redirect source: not a page, and its destination is already held.
            '"https://www.e.com/old/",301,text/html,Non-Indexable,Redirected,https://www.e.com/a/,2,1',
            '"https://www.e.com/gone/",404,text/html,Non-Indexable,,,4,0',
            '"https://blog.other.com/x/",200,text/html,Indexable,,,1,3',
            '"https://www.e.com/hero.jpg",200,image/jpeg,Indexable,,,2,9',
            '"https://www.e.com/dupe/",200,text/html,Non-Indexable,Canonicalised,,3,4',
        ],
    )
    def test_noise_is_never_merged(self, crawl, line):
        outcome = merge_reconciled_urls(crawl, csv_of(line))
        assert outcome.merged == 0
        assert len(outcome.output.pages) == 2

    def test_a_live_indexable_page_is_merged(self, crawl):
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        assert outcome.merged == 1
        assert "https://www.e.com/c/" in {page.url for page in outcome.output.pages}

    def test_noise_and_a_real_gap_in_one_export(self, crawl):
        """The mix is the realistic case; the filter must survive it."""
        outcome = merge_reconciled_urls(
            crawl,
            csv_of(
                live("https://www.e.com/c/"),
                '"https://www.e.com/gone/",404,text/html,Non-Indexable,,,4,0',
                '"https://www.e.com/hero.png",200,image/png,Indexable,,,2,9',
            ),
        )
        assert outcome.merged == 1


class TestTheInputIsNeverMutated:
    def test_the_original_result_is_untouched(self, crawl):
        before = len(crawl.pages)
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        assert len(crawl.pages) == before
        assert outcome.output is not crawl

    def test_an_export_with_no_gap_returns_the_same_object(self, crawl):
        """A check must not become a rewrite.

        Pushing a no-op through `reparse_placement` would recompute
        `trail_source` across the whole crawl, so a merge asked only to look
        would quietly change what it was looking at.
        """
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/a/")))
        assert outcome.merged == 0
        assert outcome.output is crawl

    def test_an_empty_export_is_a_noop(self, crawl):
        outcome = merge_reconciled_urls(crawl, HEADER + "\n")
        assert outcome.merged == 0
        assert outcome.output is crawl


class TestTheMergedPage:
    def test_it_carries_screaming_frogs_inlink_count(self, crawl):
        """The one signal an export adds that the engine could not have."""
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/", inlinks=17)))
        added = next(p for p in outcome.output.pages if p.url.endswith("/c/"))
        assert added.inbound_internal_links_count == 17

    def test_it_is_placed_by_the_normal_rules(self, crawl):
        """No breadcrumb of its own and no menu, so it lands in OTHERS.

        Visible rather than hidden: a page nothing places belongs in the bucket
        for pages nothing places.
        """
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        added = next(p for p in outcome.output.pages if p.url.endswith("/c/"))
        assert added.breadcrumb_path[0] == "OTHERS"
        assert added.trail_source == "none"

    def test_it_is_not_as_confident_as_a_crawled_page(self, crawl):
        """An export carries no HTML, so the structural parsers cannot run.

        The gap must stay visible in the score. A merged page presented at the
        same confidence as a fetched one is the misreading this guards.
        """
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        added = next(p for p in outcome.output.pages if p.url.endswith("/c/"))
        assert added.final_confidence_score < 0.9


class TestTotalsStayCoherent:
    def test_the_summary_is_recounted(self, crawl):
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        assert outcome.output.summary.pages_classified == 3

    def test_llm_spend_is_carried_through_not_zeroed(self, crawl):
        """A merge spends nothing, and must not erase what the crawl spent."""
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        assert outcome.output.summary.llm_spend_usd == 1.25

    def test_nav_coverage_counts_the_new_pages(self, crawl):
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        coverage = outcome.output.nav_coverage
        assert coverage.total_urls == 3
        assert coverage.placed + coverage.unmatched == 3

    def test_the_report_still_describes_both_directions(self, crawl):
        """Merging one side must not blank the other side's finding."""
        outcome = merge_reconciled_urls(crawl, csv_of(live("https://www.e.com/c/")))
        report = outcome.report
        assert len(report.missed_pages) == 1
        # `/a/` and `/b/` are in the crawl and absent from the export.
        assert report.engine_urls == 2
        assert len(report.engine_only) == 2
