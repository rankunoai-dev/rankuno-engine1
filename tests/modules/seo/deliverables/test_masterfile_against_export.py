"""What each of the twenty-one services produces from a real-shaped export.

This is the test that build-log 0116 says was missing. Every assertion here is
an exact column header and an exact row count, never a byte length: an empty
openpyxl workbook is several thousand bytes, so `len(result) > 0` held for
thirteen services that rendered nothing and for one that could not run at all.

The expected counts below are derived from `sf_export.py`'s rows by hand and
are written out per service rather than computed, so that a service quietly
starting to drop or duplicate rows fails here instead of agreeing with a
formula that changed with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_base import NOT_MEASURED
from src.modules.seo.deliverables.masterfile_registry import (
    AVAILABLE_SERVICES,
    get_masterfile_service,
)
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, urls_in
from tests.modules.seo.deliverables.sf_export import (
    ABOUT,
    ABSENT_FROM_SPINE,
    FORMULA_URL,
    GONE,
    HOME,
    NOINDEX,
    SEARCH_CONSOLE,
    search_console_bytes,
    write_export,
)

URL_COLUMNS = ("URL", "Inlinks", "Impressions", "Clicks")
"""The detail-table header every single-sheet service writes today. Pinned so
that the column *shape* cannot drift unnoticed - reshaping it is a separate,
unapproved change (build-log 0116 §scope)."""

# slug -> (sheet or None for the first, expected header, expected URL column)
EXPECTED: dict[str, tuple[str | None, tuple[str, ...], list[str]]] = {
    "canonicals": (None, URL_COLUMNS, [ABOUT]),
    "content_issues": (None, URL_COLUMNS, [HOME]),
    "directives": (None, URL_COLUMNS, [NOINDEX]),
    "duplicate_content": (None, URL_COLUMNS, [HOME, ABOUT]),
    "h1": (None, URL_COLUMNS, [HOME]),
    "hreflang": ("Detailed Data", URL_COLUMNS, [HOME]),
    "lorem_ipsum": (None, URL_COLUMNS, [ABOUT]),
    "meta_description": (None, URL_COLUMNS, [HOME]),
    "non_functional_internal_links": (None, URL_COLUMNS, [GONE]),
    "page_titles": (None, URL_COLUMNS, [HOME, HOME, ABOUT]),
    "pagination": (None, URL_COLUMNS, [ABOUT]),
    "response_codes": (
        None,
        ("URL", "Status Code", "Inlinks", "Impressions", "Clicks"),
        [GONE],
    ),
    "security": (None, URL_COLUMNS, [ABOUT, HOME]),
    "sitemaps": (None, URL_COLUMNS, [ABOUT]),
    "structured_data": ("Detailed Data", URL_COLUMNS, [HOME]),
    "url_issues": (None, URL_COLUMNS, [ABOUT, f"'{FORMULA_URL}"]),
}
"""Sixteen services with a catalogue-backed input. `page_titles` lists `HOME`
twice on purpose: it is named by both `page_titles_missing.csv` and
`page_titles_duplicate.csv`, and nothing deduplicates across source files.
`url_issues` expects the formula cell to arrive apostrophe-prefixed."""

NOT_MEASURABLE = (
    "custom_search_ga4_gtm",
    "custom_search_og_twitter",
    "functional_internal_links",
)
"""No catalogue row gives these an `sf_sources`, and the export RAE used is
neither requested by `export_manifest.py` nor admitted by the upload
allow-list. ADR 0011 §5: say "not measured", never "no issues"."""


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_a_service_reports_the_rows_its_export_holds(slug: str, sf_export: Path) -> None:
    sheet, columns, urls = EXPECTED[slug]
    payload = get_masterfile_service(slug, "job-1", sf_export).generate()

    header, body = detail_table(payload, sheet)

    assert header == columns
    assert urls_in(body) == urls
    assert len(body) == len(urls)


@pytest.mark.parametrize("slug", NOT_MEASURABLE)
def test_a_service_with_no_producible_export_says_so(slug: str, sf_export: Path) -> None:
    payload = get_masterfile_service(slug, "job-1", sf_export).generate()

    assert first_cell(payload) == NOT_MEASURED


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_every_service_still_renders_without_an_export(slug: str, empty_export: Path) -> None:
    """The absent-input branch still produces a readable workbook, not a crash.

    Read from the first sheet, not the detail sheet: the two eight-sheet
    services collapse to a single `Summary` when they have no input at all.
    """
    payload = get_masterfile_service(slug, "job-1", empty_export).generate()

    assert detail_table(payload) == ((), [])
    assert isinstance(first_cell(payload), str)


def test_the_non_indexable_services_are_exactly_the_three_that_declare_it() -> None:
    """A service filtering an issue defined by non-indexability finds nothing.

    Directives, Response Codes and the inlink report each describe pages that
    are `Non-Indexable` by construction, which is why all three rendered zero
    rows before build-log 0116 however correct their filenames were.
    """
    declared = {
        slug
        for slug in AVAILABLE_SERVICES
        if not get_masterfile_service(slug, "job-1", Path()).INDEXABLE_ONLY
    }

    assert declared == {
        "directives",
        "response_codes",
        "non_functional_internal_links",
        "overview_report",
    }


class TestNotMeasuredIsNotZero:
    """ADR 0011 §5, at the cell level."""

    def test_absent_search_console_reports_not_measured(self, sf_export: Path) -> None:
        header, body = detail_table(
            get_masterfile_service("page_titles", "job-1", sf_export).generate()
        )

        assert header.index("Impressions") == 2
        assert [row[2] for row in body] == [NOT_MEASURED] * 3
        assert [row[3] for row in body] == [NOT_MEASURED] * 3

    def test_a_measured_zero_is_still_zero(self, tmp_path: Path) -> None:
        """A page missing from a *present* Search Console export measured 0."""
        export = write_export(
            tmp_path / "e",
            extra={SEARCH_CONSOLE: search_console_bytes([(HOME, "4", "99", "0.04", "3.1")])},
        )

        _, body = detail_table(get_masterfile_service("page_titles", "job-1", export).generate())

        by_url = {row[0]: (row[2], row[3]) for row in body}
        assert by_url[HOME] == (99, 4)
        assert by_url[ABOUT] == (0, 0)


class TestTheEdgeCasesThatCausedBugs:
    def test_a_bom_on_the_first_header_cell_does_not_hide_the_address_column(
        self, sf_export: Path
    ) -> None:
        assert (sf_export / "h1_missing.csv").read_bytes().startswith(b"\xef\xbb\xbf")

        _, body = detail_table(get_masterfile_service("h1", "job-1", sf_export).generate())

        assert urls_in(body) == [HOME]

    def test_crlf_and_quote_all_survive(self, sf_export: Path) -> None:
        raw = (sf_export / "canonicals_missing.csv").read_bytes()

        assert b"\r\n" in raw
        assert raw.split(b"\r\n")[0].endswith(b'"')

    def test_a_url_absent_from_the_spine_is_dropped_not_invented(self, sf_export: Path) -> None:
        """`sitemaps_orphan_urls.csv` names a URL `internal_all.csv` does not."""
        _, body = detail_table(get_masterfile_service("sitemaps", "job-1", sf_export).generate())

        assert ABSENT_FROM_SPINE not in urls_in(body)
        assert urls_in(body) == [ABOUT]

    def test_an_edge_list_export_is_read_by_destination_not_by_address(
        self, sf_export: Path
    ) -> None:
        """`internal_client_error_(4xx)_inlinks.csv` has no `Address` column.

        Before the fix this frame concatenated into a `nan` address column and
        the workbook listed the string "nan" as a URL.
        """
        _, body = detail_table(
            get_masterfile_service("non_functional_internal_links", "job-1", sf_export).generate()
        )

        assert urls_in(body) == [GONE]
        assert "nan" not in urls_in(body)

    def test_an_edge_list_export_is_read_by_source_where_the_page_is_the_source(
        self, sf_export: Path
    ) -> None:
        """`form_url_insecure.csv` is `Source,Form Action Link`."""
        _, body = detail_table(get_masterfile_service("security", "job-1", sf_export).generate())

        assert HOME in urls_in(body)

    def test_a_formula_cell_is_neutralised(self, sf_export: Path) -> None:
        _, body = detail_table(get_masterfile_service("url_issues", "job-1", sf_export).generate())

        assert f"'{FORMULA_URL}" in urls_in(body)
        assert FORMULA_URL not in urls_in(body)

    def test_one_url_in_several_issue_files_yields_one_row_per_file(self, sf_export: Path) -> None:
        """One row per source file, not one per URL.

        Pinned, not endorsed: the flattened shape carries no column saying
        which issue applied, so `HOME` appears once per source file that names
        it. Reshaping the workbook is a separate change (build-log 0116).
        """
        _, body = detail_table(get_masterfile_service("page_titles", "job-1", sf_export).generate())

        assert urls_in(body).count(HOME) == 2


class TestOverviewReport:
    """The one service that crashed outright, and the union it synthesises."""

    def test_the_notes_sheet_no_longer_raises_on_its_own_name(self, sf_export: Path) -> None:
        import io

        import openpyxl

        payload = get_masterfile_service("overview_report", "job-1", sf_export).generate()
        book = openpyxl.load_workbook(io.BytesIO(payload))

        assert book.sheetnames == [
            "Overview",
            "Issues Summary",
            "Pages at Risk",
            "Notes_Recommendations",
        ]

    def test_it_unions_every_affected_url_including_the_non_indexable_ones(
        self, sf_export: Path
    ) -> None:
        payload = get_masterfile_service("overview_report", "job-1", sf_export).generate()

        header, body = detail_table(payload, "Overview")

        assert header == ("URL", "Impressions", "Clicks")
        assert set(urls_in(body)) == {
            HOME,
            ABOUT,
            GONE,
            NOINDEX,
            ABSENT_FROM_SPINE,
            f"'{FORMULA_URL}",
        }


class TestTheServicesWaitingOnAnExport:
    """The three that render "not measured" still have a working renderer.

    Their `generate()` bodies are unreachable today only because
    `SOURCE_FILES` is empty - not because the rendering is wrong. Subclassing
    with a real catalogue source proves the day `export_manifest.py` gains the
    missing tab (Phase 4), these produce rows without further change, and
    keeps the branch under test rather than rotting.
    """

    @pytest.mark.parametrize("slug", NOT_MEASURABLE)
    def test_it_renders_rows_once_a_source_exists(self, slug: str, sf_export: Path) -> None:
        service = get_masterfile_service(slug, "job-1", sf_export)
        wired = type(
            f"Wired{type(service).__name__}",
            (type(service),),
            {"SOURCE_FILES": ("content_low_content_pages.csv",)},
        )

        header, body = detail_table(wired("job-1", sf_export).generate())

        assert header == URL_COLUMNS
        assert urls_in(body) == [HOME]
