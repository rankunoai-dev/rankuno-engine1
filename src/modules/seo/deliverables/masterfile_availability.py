"""Which masterfile services can measure anything, and which only look like they can.

A service reads named exports (`SOURCE_FILES`, derived from `ISSUE_CATALOGUE`
through `contracts/sources.py`) and — for `custom_extraction` alone — a family
of names discovered at build time (`SOURCE_FILE_PREFIXES`). An uploaded bundle
may contain nothing outside `ALLOWED_BUNDLE_FILENAMES`. A service whose
reachable set is empty against that allow-list cannot put a single row in its
workbook: it renders `NOT_MEASURED` in full, for every crawl, whatever the
Screaming Frog configuration says.

Four services are in that position today, all for the same reason — the export
manifest never asks for the tab their file comes from. That was already true
before this module and entirely invisible: `/masterfiles/available` offered all
twenty-one slugs identically, the build returned `202`, the download succeeded,
and the operator got an empty workbook. The flag exists so the menu can say so
first.

**Derived, never listed.** Naming the four slugs here would be correct for
exactly as long as `export_manifest.py` stays still. Computing the answer from
what each service declares means a tab added to the manifest — which widens
`ALLOWED_BUNDLE_FILENAMES` through the catalogue — flips its services to
measurable with no edit here, and a service added with no reachable source is
flagged the day it lands.

**Not an enforcement point.** A build is still permitted. A loose export
directory (`scripts/build_deliverable.py`) can legitimately hold files an
upload may not, so refusing here would break a working path in order to fix a
display problem. This module tells the truth about the common case; it does not
withdraw the button.
"""

from __future__ import annotations

from typing import Final

from src.core.schemas import StrictModel
from src.modules.seo.deliverables.masterfile_base import MasterfileService
from src.modules.seo.deliverables.masterfile_registry import AVAILABLE_SERVICES, service_class
from src.modules.seo.screaming_frog_control.upload_manifest import ALLOWED_BUNDLE_FILENAMES

__all__ = [
    "NO_REACHABLE_SOURCE_REASON",
    "ServiceAvailability",
    "availability_of",
    "masterfile_availability",
]

NO_REACHABLE_SOURCE_REASON: Final[str] = (
    "Not measured by this crawl: this engine's export manifest never asks "
    "Screaming Frog for an export this report reads, so no crawl it runs can "
    "produce one. Nothing in the Screaming Frog configuration changes that — "
    "the gap is here, not in the crawl settings."
)
"""Why a service with no declared source at all cannot be built. Opens with
the same words a workbook cell uses (`NOT_MEASURED`, ADR 0011 §5) rather than
a second vocabulary for the same fact, then says the part a cell cannot: that
the export was never requested, which is not "this crawl found none"."""


class ServiceAvailability(StrictModel):
    """One masterfile service, and whether it can report on anything.

    `reason` is `None` exactly when `measurable` is true. A consumer that
    renders an unavailable entry has the sentence to show beside it and does
    not compose its own — the honest wording is the whole point of the flag.
    """

    slug: str
    measurable: bool
    reason: str | None = None


def availability_of(
    slug: str,
    service: type[MasterfileService],
    allowed: frozenset[str],
) -> ServiceAvailability:
    """Whether `service` could read anything from a source limited to `allowed`.

    Args:
        slug: The registry slug the caller knows this service by.
        service: The service class, read for its declared sources only.
        allowed: The filenames such a source may contain.

    Returns:
        `measurable=True` with no reason when at least one file is reachable;
        otherwise the flag and the sentence explaining it.
    """
    if service.reachable_sources(allowed):
        return ServiceAvailability(slug=slug, measurable=True)
    if not service.SOURCE_FILES:
        return ServiceAvailability(slug=slug, measurable=False, reason=NO_REACHABLE_SOURCE_REASON)
    wanted = ", ".join(sorted(service.SOURCE_FILES))
    return ServiceAvailability(
        slug=slug,
        measurable=False,
        reason=(
            "Not measured by this crawl: the exports this report reads "
            f"({wanted}) are not among the files an uploaded bundle may carry, "
            "so none of them can reach the build."
        ),
    )


def masterfile_availability(
    allowed: frozenset[str] = ALLOWED_BUNDLE_FILENAMES,
) -> tuple[ServiceAvailability, ...]:
    """Every registered service, slug order, each with its measurability.

    Every slug is returned, including the ones that cannot measure: an
    operator looking for Custom Extraction has to find it and read why it is
    unavailable. A filtered list would teach them the feature does not exist.

    Args:
        allowed: The filenames a source may contain. Defaults to what an
            uploaded bundle may carry, which is the only input the API build
            path has; a caller feeding a loose export directory can pass its
            own set.

    Returns:
        One `ServiceAvailability` per registered slug, sorted by slug.
    """
    return tuple(
        availability_of(slug, service_class(slug), allowed) for slug in sorted(AVAILABLE_SERVICES)
    )
