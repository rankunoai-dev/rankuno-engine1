"""Masterfile service registry and factory.

Maps service slugs to service classes and provides factory methods for instantiation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.modules.seo.deliverables.masterfile_base import MasterfileService

__all__ = [
    "get_masterfile_service",
    "AVAILABLE_SERVICES",
]

_logger = get_logger(__name__)

# Import services (lazy import to avoid circular dependencies)
_SERVICES: Final[dict[str, str]] = {
    "response_codes": "src.modules.seo.deliverables.masterfile_response_codes:ResponseCodesService",
    "page_titles": "src.modules.seo.deliverables.masterfile_page_titles:PageTitlesService",
    # Additional services to be implemented in subsequent cycles
}

AVAILABLE_SERVICES: Final[frozenset[str]] = frozenset(_SERVICES.keys())


def get_masterfile_service(
    slug: str, job_id: str, sf_export_dir: Path, rulebook_path: Path | None = None
) -> MasterfileService:
    """Factory: instantiate a masterfile service by slug.

    Args:
        slug: Service slug (e.g., "response_codes")
        job_id: Job ID (for logging)
        sf_export_dir: Path to sf_export/ directory
        rulebook_path: Optional rulebook for theming

    Returns:
        Instantiated service

    Raises:
        ValueError: Unknown service slug
    """
    if slug not in _SERVICES:
        msg = f"Unknown masterfile service: {slug}"
        raise ValueError(msg)

    module_path, class_name = _SERVICES[slug].split(":")
    module_name, _, attr = module_path.rpartition(".")

    try:
        # Lazy import to avoid circular dependencies
        module = __import__(module_path, fromlist=[attr.split(":")[0]])
        service_class = getattr(module, class_name)
        return service_class(job_id, sf_export_dir, rulebook_path)  # type: ignore[no-any-return]
    except (ImportError, AttributeError) as exc:
        msg = f"Failed to instantiate masterfile service {slug}: {exc}"
        raise ValueError(msg) from exc
