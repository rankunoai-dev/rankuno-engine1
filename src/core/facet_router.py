"""Facet management and multi-tenant routing for tool execution.

A facet is an isolated execution context with its own concurrency cap, rate
limits, and cost budgets. This module is the single source of truth for:

* Facet definitions (which facets exist)
* Org → facet access control (which orgs can use which facets)
* Facet configuration (concurrency limits, rate limit keys)

Phase 1 supports three facets:
* `seo.page_classifier`: Web crawling and page classification
* `seo.health_engine`: (Placeholder, not yet implemented)
* `seo.theme_classification`: (Placeholder, not yet implemented)

All three share the same rate limit key (`web.crawl`) and cost ledger in Phase 1.
Isolation happens at the concurrency level only; Phase 1.5 will add per-facet
rate limit buckets and cost tracking.

Multi-tenant access is controlled here. An unknown facet or an org denied access
raises immediately so the API can return `400` or `403`.
"""

from __future__ import annotations

from typing import NamedTuple

from src.core.logger import get_logger

__all__ = ["FacetConfig", "FacetRouter"]

_logger = get_logger("core.facet_router")


class FacetConfig(NamedTuple):
    """Configuration for one facet.

    Attributes:
        facet_id: Facet identifier (e.g., 'seo.page_classifier').
        display_name: Human-readable name for UI display.
        description: What this facet does.
        max_concurrent: Maximum concurrent jobs allowed for this facet.
    """

    facet_id: str
    display_name: str
    description: str
    max_concurrent: int


class FacetRouter:
    """Central facet management and org access control.

    A single instance exists per application. It maps facet_id to configuration
    and validates org access at admission time.

    Phase 1 hard-codes the facets and org access. Phase 2 will read from config.
    """

    # Phase 1 hardcoded org access: all orgs have access to all facets
    # Phase 2 will read this from Settings or a database
    _ORG_ACCESS = {
        None: {"seo.page_classifier", "seo.health_engine", "seo.theme_classification"},
        "default": {"seo.page_classifier", "seo.health_engine", "seo.theme_classification"},
    }

    def __init__(self, max_concurrent: int | None = None) -> None:
        """Initialize the facet router with Phase 1 defaults.

        Args:
            max_concurrent: Override the default max_concurrent for seo.page_classifier.
                Defaults to 3. This is typically set from Settings.max_concurrent_crawls.
        """
        # Use provided max_concurrent for the primary facet, or default to 3
        primary_max = max_concurrent if max_concurrent is not None else 3

        # Create instance-level facet definitions with potentially overridden concurrency
        self._FACETS = {
            "seo.page_classifier": FacetConfig(
                facet_id="seo.page_classifier",
                display_name="Page Classification",
                description="Crawl a site and classify every page by hierarchy, type, and intent.",
                max_concurrent=primary_max,
            ),
            "seo.health_engine": FacetConfig(
                facet_id="seo.health_engine",
                display_name="Health Analyze",
                description="(Unimplemented) Analyze site health metrics and recommendations.",
                max_concurrent=2,
            ),
            "seo.theme_classification": FacetConfig(
                facet_id="seo.theme_classification",
                display_name="Theme Classification",
                description=(
                    "(Unimplemented) Classify pages by visual design theme and content pattern."
                ),
                max_concurrent=2,
            ),
        }

    def get_facet_config(self, facet_id: str) -> FacetConfig:
        """Return configuration for a facet.

        Args:
            facet_id: The facet to look up.

        Returns:
            FacetConfig for the facet.

        Raises:
            KeyError: If the facet is unknown.
        """
        if facet_id not in self._FACETS:
            msg = f"Unknown facet '{facet_id}'. Available: {', '.join(sorted(self._FACETS.keys()))}"
            raise KeyError(msg)
        return self._FACETS[facet_id]

    def validate_org_access(self, org_id: str | None, facet_id: str) -> None:
        """Check if an org is allowed to use a facet.

        In Phase 1, all orgs have access to all facets. Phase 2 will read access
        control from org configuration.

        Args:
            org_id: Organization identifier, or None for default org.
            facet_id: Facet to access.

        Raises:
            KeyError: If the facet does not exist.
            PermissionError: If the org does not have access to the facet.
        """
        # Validate facet exists
        self.get_facet_config(facet_id)

        # In Phase 1, all orgs have access to all facets
        # Phase 2 will check org_config.allowed_facets here

    def facets_for_org(self, org_id: str | None) -> list[FacetConfig]:
        """Return all facets available to an org.

        Args:
            org_id: Organization identifier, or None for default org.

        Returns:
            List of FacetConfigs the org can access, sorted by facet_id.
        """
        facet_ids = self._ORG_ACCESS.get(org_id, set())
        configs = [self._FACETS[fid] for fid in facet_ids if fid in self._FACETS]
        return sorted(configs, key=lambda cfg: cfg.facet_id)

    def default_facet(self) -> str:
        """Return the default facet for backward compatibility.

        Always 'seo.page_classifier' — the only Phase 1 facet.
        """
        return "seo.page_classifier"

    def all_facets(self) -> list[FacetConfig]:
        """Return all facets, sorted by facet_id.

        Used by the UI to populate facet pickers.
        """
        return sorted(self._FACETS.values(), key=lambda cfg: cfg.facet_id)
