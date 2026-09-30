"""Tests for the derived measurability flag on masterfile services.

The defect this covers is not a crash: `/masterfiles/available` offered all
twenty-one services identically, four of which read an export this engine's
manifest never requests, so they returned `202`, downloaded cleanly, and
handed back an empty workbook. The flag has to be *derived* to be worth
having — a hand-kept list of four slugs would be wrong the moment
`export_manifest.py` grows a tab — so the tests below drive the answer from
the data on both sides: what a service declares, and what the allow-list
admits.
"""

from __future__ import annotations

from typing import ClassVar

from src.modules.seo.deliverables.masterfile_availability import (
    NO_REACHABLE_SOURCE_REASON,
    ServiceAvailability,
    availability_of,
    masterfile_availability,
)
from src.modules.seo.deliverables.masterfile_base import MasterfileMetadata, MasterfileService
from src.modules.seo.deliverables.masterfile_registry import AVAILABLE_SERVICES
from src.modules.seo.screaming_frog_control.upload_manifest import ALLOWED_BUNDLE_FILENAMES

CUSTOM_EXTRACTION_EXPORT = "custom_extraction_all.csv"
"""`Custom Extraction:All`. Present in 45 of 45 real export folders checked;
absent from every bundle this engine can produce, because the tab is not in
`export_manifest.EXPORT_TABS`."""

FUNCTIONAL_INLINKS_EXPORT = "internal_success_(2xx)_inlinks.csv"
"""`Response Codes:Internal:Internal Success (2xx) Inlinks`. Same story."""

UNMEASURABLE_TODAY = frozenset(
    {
        "custom_extraction",
        "custom_search_ga4_gtm",
        "custom_search_og_twitter",
        "functional_internal_links",
    }
)
"""The four as of this cycle. Written down *only* as the expected output of
the derivation - nothing in `src/` holds this list, and a fifth service or a
widened allow-list must change this constant rather than be absorbed by it."""


class _DeclaredSourceService(MasterfileService):
    """A service that names one real export, for driving the flag from data.

    Never instantiated: `reachable_sources` is a classmethod, and the point is
    to prove the flag follows `SOURCE_FILES` rather than a slug.
    """

    SOURCE_FILES: ClassVar[tuple[str, ...]] = (FUNCTIONAL_INLINKS_EXPORT,)

    @property
    def metadata(self) -> MasterfileMetadata:  # pragma: no cover - never built
        return MasterfileMetadata(slug="declared", label="Declared", sheets=1, is_complex=False)

    def generate(self) -> bytes:  # pragma: no cover - never built
        return b""


def by_slug(entries: tuple[ServiceAvailability, ...]) -> dict[str, ServiceAvailability]:
    return {entry.slug: entry for entry in entries}


class TestAgainstTheRealAllowList:
    def test_every_registered_service_is_returned_none_hidden(self) -> None:
        """An operator must be able to find a service and learn why it is off."""
        entries = masterfile_availability()

        assert {entry.slug for entry in entries} == set(AVAILABLE_SERVICES)
        assert [entry.slug for entry in entries] == sorted(AVAILABLE_SERVICES)

    def test_exactly_four_services_cannot_measure_anything(self) -> None:
        """The other seventeen have at least one admissible source file."""
        entries = masterfile_availability()

        unmeasurable = {entry.slug for entry in entries if not entry.measurable}
        assert unmeasurable == UNMEASURABLE_TODAY
        assert len([entry for entry in entries if entry.measurable]) == 17

    def test_a_reason_accompanies_every_refusal_and_nothing_else(self) -> None:
        """`reason` is the sentence the menu shows; a working service has none."""
        for entry in masterfile_availability():
            assert (entry.reason is None) is entry.measurable

    def test_the_reason_does_not_blame_the_crawl_configuration(self) -> None:
        """The reason must not point at the operator's own configuration.

        The defect being fixed is wording that sent operators to their own
        `.seospiderconfig` for a gap that is ours.
        """
        reason = by_slug(masterfile_availability())["custom_extraction"].reason

        assert reason == NO_REACHABLE_SOURCE_REASON
        assert "the gap is here, not in the crawl settings" in reason.lower()
        assert reason.startswith("Not measured by this crawl")


class TestTheFlagIsDerived:
    def test_custom_extraction_measures_the_moment_its_export_is_admitted(self) -> None:
        """Driven from the allow-list, not from the slug.

        `custom_extraction` names no file - it discovers `custom_extraction_*`
        at build time - so this also pins that `SOURCE_FILE_PREFIXES` is what
        the derivation reads for it.
        """
        widened = masterfile_availability(ALLOWED_BUNDLE_FILENAMES | {CUSTOM_EXTRACTION_EXPORT})

        entry = by_slug(widened)["custom_extraction"]
        assert entry.measurable
        assert entry.reason is None

    def test_admitting_one_export_does_not_flip_a_service_that_never_asked(self) -> None:
        """Admitting a file only helps the services that ask for it.

        The two Custom Search services read the same file in RAE but declare
        nothing here, so the honest answer stays "cannot measure" until a
        catalogue row gives them a source.
        """
        widened = by_slug(
            masterfile_availability(ALLOWED_BUNDLE_FILENAMES | {CUSTOM_EXTRACTION_EXPORT})
        )

        assert not widened["custom_search_ga4_gtm"].measurable
        assert not widened["custom_search_og_twitter"].measurable
        assert not widened["functional_internal_links"].measurable

    def test_a_declared_source_flips_the_flag_when_the_allow_list_admits_it(self) -> None:
        """Driven from `SOURCE_FILES`, the other half of the derivation."""
        today = availability_of("declared", _DeclaredSourceService, ALLOWED_BUNDLE_FILENAMES)
        admitted = availability_of(
            "declared",
            _DeclaredSourceService,
            ALLOWED_BUNDLE_FILENAMES | {FUNCTIONAL_INLINKS_EXPORT},
        )

        assert not today.measurable
        assert admitted.measurable

    def test_a_declared_but_inadmissible_source_is_named_in_the_reason(self) -> None:
        """A refused file is named; asking for nothing is said differently.

        A service that asks for a file the boundary refuses gets a different
        sentence from one that asks for nothing at all - the two are different
        facts and only one of them is about the export manifest.
        """
        entry = availability_of("declared", _DeclaredSourceService, ALLOWED_BUNDLE_FILENAMES)

        assert entry.reason is not None
        assert FUNCTIONAL_INLINKS_EXPORT in entry.reason
        assert entry.reason != NO_REACHABLE_SOURCE_REASON

    def test_reachable_sources_reports_the_files_not_merely_a_verdict(self) -> None:
        """The base-class primitive the flag rests on, checked directly."""
        assert _DeclaredSourceService.reachable_sources(
            frozenset({FUNCTIONAL_INLINKS_EXPORT, "internal_all.csv"})
        ) == frozenset({FUNCTIONAL_INLINKS_EXPORT})
        assert _DeclaredSourceService.reachable_sources(frozenset({"internal_all.csv"})) == (
            frozenset()
        )
