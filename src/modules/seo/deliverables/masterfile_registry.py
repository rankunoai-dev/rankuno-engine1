"""Masterfile service registry and factory.

Maps service slugs to service classes and provides factory methods for instantiation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.modules.seo.deliverables.masterfile_base import MasterfileService
    from src.modules.seo.deliverables.masterfile_source import MasterfileSource

__all__ = [
    "get_masterfile_service",
    "service_class",
    "AVAILABLE_SERVICES",
]

_logger = get_logger(__name__)

# Import services (lazy import to avoid circular dependencies).
#
# The longest entries are written as two adjacent string literals so the table
# stays inside 100 columns. That is a wrap, not a change of value: the paths
# concatenate to exactly the same dotted `module:Class` target. The package
# prefix is repeated rather than factored into a constant deliberately — an
# entry that can be read end to end is what makes a wrong slug obvious here.
_SERVICES: Final[dict[str, str]] = {
    # Milestone 1 (2 sample services)
    "response_codes": "src.modules.seo.deliverables.masterfile_response_codes:ResponseCodesService",
    "page_titles": "src.modules.seo.deliverables.masterfile_page_titles:PageTitlesService",
    # Milestone 2: Single-sheet issue services (13)
    "meta_description": "src.modules.seo.deliverables"
    ".masterfile_meta_description:MetaDescriptionService",
    "h1": "src.modules.seo.deliverables.masterfile_h1:H1Service",
    "canonicals": "src.modules.seo.deliverables.masterfile_canonicals:CanonicalService",
    "directives": "src.modules.seo.deliverables.masterfile_directives:DirectivesService",
    "sitemaps": "src.modules.seo.deliverables.masterfile_sitemaps:SitemapsService",
    "security": "src.modules.seo.deliverables.masterfile_security:SecurityService",
    "content_issues": "src.modules.seo.deliverables.masterfile_content_issues:ContentIssuesService",
    "duplicate_content": "src.modules.seo.deliverables"
    ".masterfile_duplicate_content:DuplicateContentService",
    "functional_internal_links": "src.modules.seo.deliverables"
    ".masterfile_functional_internal_links:FunctionalInternalLinksService",
    "non_functional_internal_links": "src.modules.seo.deliverables"
    ".masterfile_non_functional_internal_links:NonFunctionalInternalLinksService",
    "pagination": "src.modules.seo.deliverables.masterfile_pagination:PaginationService",
    "lorem_ipsum": "src.modules.seo.deliverables.masterfile_lorem_ipsum:LoremIpsumService",
    "url_issues": "src.modules.seo.deliverables.masterfile_url_issues:URLIssuesService",
    # Milestone 2: Custom search services (2)
    "custom_search_ga4_gtm": "src.modules.seo.deliverables"
    ".masterfile_custom_search_ga4_gtm:CustomSearchGA4GTMService",
    "custom_search_og_twitter": "src.modules.seo.deliverables"
    ".masterfile_custom_search_og_twitter:CustomSearchOGTwitterService",
    # Milestone 2: Complex multi-sheet services (3)
    "hreflang": "src.modules.seo.deliverables.masterfile_hreflang:HrefLangService",
    "structured_data": "src.modules.seo.deliverables"
    ".masterfile_structured_data:StructuredDataService",
    "custom_extraction": "src.modules.seo.deliverables"
    ".masterfile_custom_extraction:CustomExtractionService",
    # Milestone 2: Master synthesis service (1)
    "overview_report": "src.modules.seo.deliverables"
    ".masterfile_overview_report:OverviewReportService",
}

AVAILABLE_SERVICES: Final[frozenset[str]] = frozenset(_SERVICES.keys())


def get_masterfile_service(
    slug: str,
    job_id: str,
    source: MasterfileSource | Path,
    rulebook_path: Path | None = None,
) -> MasterfileService:
    """Factory: instantiate a masterfile service by slug.

    Args:
        slug: Service slug (e.g., "response_codes")
        job_id: Job ID (for logging)
        source: Where the Screaming Frog CSVs come from - a `MasterfileSource`
            (a zip bundle in memory, say) or a `Path` to an export directory,
            which `MasterfileService` wraps for the caller.
        rulebook_path: Optional rulebook for theming

    Returns:
        Instantiated service

    Raises:
        ValueError: Unknown service slug
    """
    return service_class(slug)(job_id, source, rulebook_path)


def service_class(slug: str) -> type[MasterfileService]:
    """The class registered for `slug`, imported but not instantiated.

    Split out of `get_masterfile_service` for the availability derivation
    (`masterfile_availability.py`), which reads class-level `SOURCE_FILES`
    and `SOURCE_FILE_PREFIXES` to decide whether a service can measure
    anything at all. It has no source and no job to build for, so it must be
    able to ask the question without constructing a service.

    Args:
        slug: Service slug (e.g., "response_codes")

    Returns:
        The service class.

    Raises:
        ValueError: Unknown slug, or a registered target that cannot be
            imported - a typo in `_SERVICES` is a wiring bug, and surfacing
            it as the same `ValueError` the caller already handles keeps a
            broken entry loud rather than silently unavailable.
    """
    if slug not in _SERVICES:
        msg = f"Unknown masterfile service: {slug}"
        raise ValueError(msg)

    module_path, class_name = _SERVICES[slug].split(":")
    module_name, _, attr = module_path.rpartition(".")

    try:
        # Lazy import to avoid circular dependencies
        module = __import__(module_path, fromlist=[attr.split(":")[0]])
        return getattr(module, class_name)  # type: ignore[no-any-return]
    except (ImportError, AttributeError) as exc:
        msg = f"Failed to instantiate masterfile service {slug}: {exc}"
        raise ValueError(msg) from exc
