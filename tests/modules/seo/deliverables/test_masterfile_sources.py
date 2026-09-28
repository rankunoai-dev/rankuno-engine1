"""No service may ask for a file the upload boundary would refuse.

This is the test that closes build-log 0116 permanently. Roughly thirty-seven
of the forty-nine filenames the masterfile services requested existed in no
Screaming Frog export: they had been derived from the service's own module
name (`masterfile_page_titles.py` -> `title_missing.csv`) rather than read
from a source, and nothing could notice because a service whose every input is
absent still returns a valid, empty workbook.

`ALLOWED_BUNDLE_FILENAMES` is derived from `ISSUE_CATALOGUE`'s `sf_sources`
(ADR 0018) and `SOURCE_FILES` is now derived from the same place, so the two
cannot disagree by construction. This module asserts the construction, so that
a service that goes back to hand-keeping a list fails here rather than
shipping green and blank.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.contracts.issue_ids import IssueCategory
from src.modules.seo.contracts.sources import sources_for_categories, sources_for_issues
from src.modules.seo.deliverables.masterfile_enrichment import url_column_for
from src.modules.seo.deliverables.masterfile_registry import (
    AVAILABLE_SERVICES,
    get_masterfile_service,
)
from src.modules.seo.screaming_frog_control.upload_manifest import (
    ALLOWED_BUNDLE_FILENAMES,
    SPINE_FILENAME,
)

DYNAMIC_SOURCES = {"custom_extraction"}
"""The one service whose filenames are discovered, not declared: Screaming
Frog writes one `custom_extraction_*.csv` per configured extractor, so the set
is only knowable from the bundle. Exempt from the declared-sources check and
covered instead by `test_masterfile_custom_extraction.py`."""

OPTIONAL_ENRICHMENT = frozenset({"search_console_all.csv", "analytics_all.csv"})
"""Read by `masterfile_enrichment` rather than declared by a service, and
deliberately *not* allow-listed: the `Search Console:All` and `Analytics:All`
tabs are not in `export_manifest.py`, so these can never arrive. They are
pinned here so that adding either becomes a visible decision, not a drift."""


def services() -> list[str]:
    return sorted(AVAILABLE_SERVICES)


@pytest.mark.parametrize("slug", services())
def test_every_declared_source_is_a_file_the_upload_boundary_accepts(slug: str) -> None:
    declared = set(get_masterfile_service(slug, "job-1", Path()).SOURCE_FILES)

    assert declared <= ALLOWED_BUNDLE_FILENAMES


@pytest.mark.parametrize("slug", [s for s in services() if s not in DYNAMIC_SOURCES])
def test_no_service_hardcodes_a_csv_filename(slug: str) -> None:
    """A `.csv` literal in a service module is how the bug got in.

    The only admissible literals are the two optional enrichment names, which
    live in `masterfile_enrichment.py`, not in a service.
    """
    module = type(get_masterfile_service(slug, "job-1", Path())).__module__
    source = Path(*module.split(".")).with_suffix(".py").read_text(encoding="utf-8")

    quoted = {
        line.split('"')[1]
        for line in source.splitlines()
        if line.count('"') >= 2 and line.split('"')[1].endswith(".csv")
    }

    assert quoted == set()


def test_the_overview_report_covers_the_whole_catalogue() -> None:
    """It synthesises every other service, so it reads every catalogue file."""
    overview = set(get_masterfile_service("overview_report", "job-1", Path()).SOURCE_FILES)

    assert overview == {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources}
    assert overview == ALLOWED_BUNDLE_FILENAMES - {SPINE_FILENAME}


def test_the_union_of_every_service_is_the_catalogue_minus_the_unmeasurable() -> None:
    """Nothing in the catalogue is orphaned, and nothing extra is requested."""
    union: set[str] = set()
    for slug in services():
        union |= set(get_masterfile_service(slug, "job-1", Path()).SOURCE_FILES)

    assert union == ALLOWED_BUNDLE_FILENAMES - {SPINE_FILENAME}


def test_every_allow_listed_file_has_a_known_url_column() -> None:
    """`url_column_for` must have an answer for every file that can arrive."""
    for name in ALLOWED_BUNDLE_FILENAMES:
        assert url_column_for(name) in {"Address", "Source", "Destination"}


def test_the_enrichment_files_are_deliberately_outside_the_allow_list() -> None:
    assert OPTIONAL_ENRICHMENT.isdisjoint(ALLOWED_BUNDLE_FILENAMES)


class TestTheDerivation:
    def test_a_category_yields_its_catalogue_files_in_order(self) -> None:
        assert sources_for_categories(IssueCategory.PAGE_TITLES) == (
            "page_titles_missing.csv",
            "page_titles_duplicate.csv",
            "page_titles_over_561_pixels.csv",
            "page_titles_below_200_pixels.csv",
            "page_titles_same_as_h1.csv",
            "page_titles_multiple.csv",
            "page_titles_outside_head.csv",
        )

    def test_a_category_with_no_producible_export_yields_nothing(self) -> None:
        assert sources_for_categories(IssueCategory.CUSTOM_SEARCH) == ()
        assert sources_for_categories(IssueCategory.PAGE_SPEED_CWV) == ()

    def test_a_file_named_by_two_issues_is_read_once(self) -> None:
        internal = sources_for_categories(IssueCategory.INTERNAL_LINKS)

        assert len(internal) == len(set(internal))

    def test_naming_issues_splits_a_category_between_workbooks(self) -> None:
        from src.modules.seo.contracts.issue_ids import IssueId

        assert sources_for_issues(IssueId.CONTENT_LOREM_IPSUM_PLACEHOLDER) == (
            "content_lorem_ipsum_placeholder.csv",
        )
        assert "content_lorem_ipsum_placeholder.csv" not in sources_for_issues(
            IssueId.CONTENT_EXACT_DUPLICATES, IssueId.CONTENT_NEAR_DUPLICATES
        )
