"""Tests for `NavigationContextClassifier`'s discovery-method rule.

Regression coverage for a rule that could not be false: "sitemap only" tested
that `SITEMAP_ONLY` was a member of its own enum and that `discovery_sources`
(a model instance, always truthy) existed, so every unlinked page was reported
as sitemap-only and `ORPHANED` was unreachable. The "Discovery Method" column
in urls.xlsx and urls.pdf printed that guess for every such page.
"""

import pytest
from src.modules.seo.page_classifier.navigation_context import NavigationContextClassifier
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    DiscoverySource,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    NavigationDiscoveryMethod,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)

URL = "https://e.com/deep/page/"


def _unlinked_page(sources: DiscoverySource) -> FullPageIntelligenceProfile:
    """A page no menu, breadcrumb or internal link reaches."""
    return FullPageIntelligenceProfile(
        url=URL,
        canonical_url=URL,
        normalized_path=URL,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=3,
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
        final_url=URL,
        trail_source="none",
        inbound_internal_links_count=0,
        discovery_sources=sources,
    )


def _method(sources: DiscoverySource) -> NavigationDiscoveryMethod:
    page = NavigationContextClassifier().enrich(_unlinked_page(sources))
    assert page.navigation_discovery_method is not None
    return page.navigation_discovery_method


def test_an_unlinked_page_in_a_sitemap_is_sitemap_only() -> None:
    assert _method(DiscoverySource(sitemap=True)) is NavigationDiscoveryMethod.SITEMAP_ONLY


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param(DiscoverySource(), id="no-evidence"),
        pytest.param(DiscoverySource(cms_api=True), id="cms-only"),
    ],
)
def test_an_unlinked_page_no_sitemap_lists_is_orphaned(sources: DiscoverySource) -> None:
    """Sitemap-only is a claim about a sitemap; without that flag it is false.

    A CMS-only page is `ORPHANED` rather than sitemap-only: nothing links to
    it and no sitemap lists it, which is exactly the enum member's meaning.
    The CMS API is how this engine *found* it, not a way a visitor reaches it.
    """
    assert _method(sources) is NavigationDiscoveryMethod.ORPHANED
