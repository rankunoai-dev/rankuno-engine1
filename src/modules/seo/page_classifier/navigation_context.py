"""Navigation context classification — analyst-friendly discoverability metadata.

Phase 8a enhancement: enriches page profiles with 4 navigation context dimensions
that explain WHERE a page was discovered, HOW EASY it is to reach, WHAT TYPE OF
PAGE links to it, and WHETHER THE ROUTE MAKES SENSE. These fields provide human-
readable insight into site structure without replacing the existing hierarchy/
type classification.

Design note: This module runs AFTER the main classification cascade completes.
It analyzes the already-classified page and trail_source to assign context.
See build-log 0065 for edge case analysis and rationale.
"""

from __future__ import annotations

from src.core.logger import get_logger
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    HierarchyLevel,
    NavigationDiscoveryMethod,
    NavigationPathQuality,
    NavigationReachabilityTier,
    NavigationSourceAuthority,
)

__all__ = ["NavigationContextClassifier"]

_logger = get_logger(__name__)


class NavigationContextClassifier:
    """Enriches pages with navigation context dimensions.

    Runs post-classification to add discoverable context without modifying
    the core hierarchy/type classification. All 4 dimensions default to None
    and are only set when sufficient evidence exists.
    """

    def enrich(self, page: FullPageIntelligenceProfile) -> FullPageIntelligenceProfile:
        """Enrich a page profile with navigation context.

        Args:
            page: Page profile from cascading pipeline (already classified)

        Returns:
            Same page with 4 new optional context fields populated
        """
        page.navigation_discovery_method = self._determine_discovery_method(page)
        page.navigation_reachability_tier = self._calculate_reachability_tier(page)
        page.navigation_source_authority = self._assign_source_authority(page)
        page.navigation_path_quality = self._assess_path_quality(page)

        return page

    def _determine_discovery_method(
        self, page: FullPageIntelligenceProfile
    ) -> NavigationDiscoveryMethod:
        """Determine WHERE this page was discovered.

        Strategy (in order):
        1. If trail_source is "menu" → PRIMARY_NAV
        2. If trail_source is "breadcrumb" → BREADCRUMB
        3. If in OTHERS but has inbound links → SECONDARY_NAV or BODY_LINK
        4. If in OTHERS, no inbound links, only sitemap → SITEMAP_ONLY
        5. If no links and no sitemap → ORPHANED
        """
        # Rule 1: Menu-based discovery = primary navigation
        if page.trail_source == "menu":
            return NavigationDiscoveryMethod.PRIMARY_NAV

        # Rule 2: Breadcrumb-based discovery
        if page.trail_source == "breadcrumb":
            return NavigationDiscoveryMethod.BREADCRUMB

        # Rule 3: Page in OTHERS but still has inbound links
        if page.trail_source == "none" and page.inbound_internal_links_count > 0:
            # Distinguish secondary nav from body links by context
            # If at low hierarchy level and many links, likely secondary nav
            if page.hierarchy_level in (
                HierarchyLevel.L0_HOMEPAGE,
                HierarchyLevel.L1_PRIMARY_NAV_HUB,
            ):
                return NavigationDiscoveryMethod.SECONDARY_NAV
            # Otherwise more likely body content link
            return NavigationDiscoveryMethod.BODY_LINK

        # Rule 4: In sitemap only (no inbound links)
        if (
            page.trail_source == "none"
            and page.inbound_internal_links_count == 0
            and NavigationDiscoveryMethod.SITEMAP_ONLY
            in [d.value for d in NavigationDiscoveryMethod]
            and page.discovery_sources
        ):
            # If only discovered via sitemap discovery method
            return NavigationDiscoveryMethod.SITEMAP_ONLY

        # Rule 5: Completely orphaned (no links, no sitemap)
        return NavigationDiscoveryMethod.ORPHANED

    def _calculate_reachability_tier(
        self, page: FullPageIntelligenceProfile
    ) -> NavigationReachabilityTier:
        """Calculate HOW MANY HOPS from homepage to reach this page.

        Strategy based on depth_from_l0:
        - 1 hop (homepage to page) → TIER_0_HERO
        - 1-2 hops (standard nav path) → TIER_1_STANDARD
        - 3+ hops (deep discovery) → TIER_2_DEEP
        - Sitemap/metadata only → TIER_3_METADATA
        - Completely unreachable → TIER_4_ORPHANED
        """
        # Orphaned pages are unreachable
        if page.inbound_internal_links_count == 0 and page.trail_source == "none":
            return NavigationReachabilityTier.TIER_4_ORPHANED

        # Direct links from homepage = hero tier
        if page.depth_from_l0 == 1:
            # If trail_source suggests it's in nav, it's HERO
            if page.trail_source in ("menu", "breadcrumb"):
                return NavigationReachabilityTier.TIER_0_HERO
            # If discovered but not in nav, still 1 hop so HERO
            if page.inbound_internal_links_count > 0:
                return NavigationReachabilityTier.TIER_0_HERO

        # 2 hops = standard navigation path
        if page.depth_from_l0 == 2:
            return NavigationReachabilityTier.TIER_1_STANDARD

        # 3+ hops = deep discovery
        if page.depth_from_l0 >= 3:
            return NavigationReachabilityTier.TIER_2_DEEP

        # No path but in sitemap = metadata only
        if page.inbound_internal_links_count == 0:
            return NavigationReachabilityTier.TIER_3_METADATA

        # Fallback: if depth_from_l0 not set or default, treat as standard
        return NavigationReachabilityTier.TIER_1_STANDARD

    def _assign_source_authority(
        self, page: FullPageIntelligenceProfile
    ) -> NavigationSourceAuthority:
        """Determine WHAT TYPE OF PAGE links to this page.

        Weights the authority of inbound links:
        - Homepage link = highest authority
        - L1 hub link = high authority
        - Content page link = medium authority
        - Footer/sidebar = lower authority
        - No links = NONE

        Strategy: analyze depth_from_l0 and link characteristics.
        """
        # No inbound links = no authority source
        if page.inbound_internal_links_count == 0:
            return NavigationSourceAuthority.NONE

        # Homepage link (depth 1 and in nav) = highest authority
        if page.depth_from_l0 == 1 and page.trail_source in ("menu", "breadcrumb"):
            return NavigationSourceAuthority.FROM_HOMEPAGE

        # Footer only: in OTHERS at low depth with few/moderate links
        # (typical footer pattern: about, contact, careers at depth 1 but not in header menu)
        if page.depth_from_l0 == 1 and page.trail_source == "none":
            # Likely footer-only
            return NavigationSourceAuthority.FROM_FOOTER

        # L1 hub pages link to it (depth 2 with nav placement)
        if page.depth_from_l0 == 2 and page.hierarchy_level in (
            HierarchyLevel.L1_PRIMARY_NAV_HUB,
            HierarchyLevel.L2_SUB_NAV_HUB,
        ):
            return NavigationSourceAuthority.FROM_MAIN_HUB

        # Content pages link to it (depth 3+ or scattered links)
        if page.depth_from_l0 >= 3:
            return NavigationSourceAuthority.FROM_CONTENT

        # Sidebar/secondary area links (in OTHERS but reachable)
        if page.trail_source == "none" and page.inbound_internal_links_count > 0:
            return NavigationSourceAuthority.FROM_SIDEBAR

        # Default fallback
        return NavigationSourceAuthority.FROM_CONTENT

    def _assess_path_quality(self, page: FullPageIntelligenceProfile) -> NavigationPathQuality:
        """Assess WHETHER THE NAVIGATION PATH MAKES LOGICAL SENSE.

        Evaluates coherence of the route from homepage to this page:
        - Clean parent-child hierarchy = LOGICAL
        - Linked from similar pages = LATERAL
        - Disconnected but reachable = DISCONNECTED
        - Can't determine = UNKNOWN

        Strategy: check breadcrumb_path, nav_parent_url, and hierarchy.
        """
        # No path at all = unknown
        if not page.breadcrumb_path and page.trail_source == "none":
            if page.inbound_internal_links_count == 0:
                return NavigationPathQuality.UNKNOWN
            # Has links but no breadcrumb = disconnected
            return NavigationPathQuality.DISCONNECTED

        # Has breadcrumb path = likely logical hierarchy
        if page.breadcrumb_path and page.trail_source in ("menu", "breadcrumb"):
            return NavigationPathQuality.LOGICAL_HIERARCHY

        # Has nav parent = logical structure
        if page.nav_parent_url:
            return NavigationPathQuality.LOGICAL_HIERARCHY

        # In same category/topic silo = lateral linking
        if page.topical_category and page.is_cross_silo_link is False:
            # Links within same topical silo = lateral/coherent
            return NavigationPathQuality.LATERAL_LINKED

        # Has links but path is unclear = disconnected
        if page.inbound_internal_links_count > 0:
            return NavigationPathQuality.DISCONNECTED

        # Fallback
        return NavigationPathQuality.UNKNOWN
