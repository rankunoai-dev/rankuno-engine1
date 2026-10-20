"""Row order and column layout of the URL exports, on one shared set of pages.

These exercise `page_classifier/reports.py`, which the brief places beside the
deliverables exports. The fixture is built once here so the four outputs (All
URLs, By Indexability, By HTTP Status, PDF) are compared against the same data.
"""

from __future__ import annotations

from openpyxl import load_workbook
from src.modules.seo.page_classifier.report_columns import TRAILING_HEADERS
from src.modules.seo.page_classifier.reports import MasterURLReport
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from tests.modules.seo.page_classifier.report_profile_factory import (
    make_page,
    make_result,
    pdf_text,
)

LEGACY_HEADERS = [
    "URL",
    "Hierarchy Level",
    "Page Type",
    "HTTP Status",
    "First Redirect",
    "GSC Clicks",
    "GSC Impressions",
    "GSC CTR %",
    "GSC Avg Position",
    "Depth",
    "Discovery Method",
    "Reachability Tier",
]

# Category order: homepage, then categories A to Z (`alpha` before `zeta`), then
# the address that does not parse. Inside `alpha`, raw URL order decides, so the
# capital-A address sorts first.
EXPECTED_ORDER = [
    "https://e.com/",
    "https://e.com/Alpha/c",
    "https://e.com/alpha/a",
    "https://e.com/alpha/b",
    "https://e.com/zeta/x",
    "not a url",
]


def mixed_pages():
    """Pages deliberately listed out of category order, with two HTTP outcomes."""
    return [
        make_page("https://e.com/zeta/x"),
        make_page("https://e.com/alpha/b", http_status=404),
        make_page("https://e.com/"),
        make_page("not a url"),
        make_page("https://e.com/alpha/a"),
        make_page("https://e.com/Alpha/c", http_status=404),
    ]


def workbook_of(*pages: FullPageIntelligenceProfile):
    return load_workbook(MasterURLReport(make_result(*pages)).generate())


class TestAllUrlsSheet:
    def test_rows_are_in_category_order(self) -> None:
        rows = list(workbook_of(*mixed_pages())["All URLs"].iter_rows(min_row=2, values_only=True))

        assert [row[0] for row in rows] == EXPECTED_ORDER

    def test_there_are_no_separator_or_heading_rows(self) -> None:
        rows = list(workbook_of(*mixed_pages())["All URLs"].iter_rows(min_row=2, values_only=True))

        assert len(rows) == len(EXPECTED_ORDER)

    def test_the_legacy_and_trailing_columns_keep_their_positions(self) -> None:
        headers = [cell.value for cell in workbook_of(*mixed_pages())["All URLs"][1]]

        assert headers[:12] == LEGACY_HEADERS
        assert headers[12:26] == list(TRAILING_HEADERS)

    def test_top_queries_then_category_are_appended_last(self) -> None:
        headers = [cell.value for cell in workbook_of(*mixed_pages())["All URLs"][1]]

        assert headers[26:] == ["Top Queries", "Category"]

    def test_the_category_column_names_each_rows_category(self) -> None:
        rows = list(workbook_of(*mixed_pages())["All URLs"].iter_rows(min_row=2, values_only=True))

        assert [row[27] for row in rows] == [
            "/",
            "alpha",
            "alpha",
            "alpha",
            "zeta",
            "(uncategorised)",
        ]


class TestGroupedSheets:
    def test_by_indexability_groups_first_and_keeps_category_order_inside_each(self) -> None:
        rows = list(
            workbook_of(*mixed_pages())["By Indexability"].iter_rows(min_row=2, values_only=True)
        )

        assert [(row[0], row[1]) for row in rows] == [
            ("Indexable", "https://e.com/"),
            ("Indexable", "https://e.com/alpha/a"),
            ("Indexable", "https://e.com/zeta/x"),
            ("Indexable", "not a url"),
            ("Blocked", "https://e.com/Alpha/c"),
            ("Blocked", "https://e.com/alpha/b"),
        ]

    def test_by_http_status_groups_first_and_keeps_category_order_inside_each(self) -> None:
        rows = list(
            workbook_of(*mixed_pages())["By HTTP Status"].iter_rows(min_row=2, values_only=True)
        )

        assert [(row[0], row[2]) for row in rows] == [
            ("200", "https://e.com/"),
            ("200", "https://e.com/alpha/a"),
            ("200", "https://e.com/zeta/x"),
            ("200", "not a url"),
            ("404", "https://e.com/Alpha/c"),
            ("404", "https://e.com/alpha/b"),
        ]


class TestPdf:
    def test_pdf_rows_follow_the_same_category_order(self) -> None:
        pdf = MasterURLReport(make_result(*mixed_pages())).generate_pdf()

        text = pdf_text(pdf.getvalue())
        positions = [text.index(url.encode()) for url in EXPECTED_ORDER]

        assert positions == sorted(positions)

    def test_pdf_has_no_separator_rows_either(self) -> None:
        """Every URL appears exactly once, so nothing was inserted between groups."""
        pdf = MasterURLReport(make_result(*mixed_pages())).generate_pdf()

        text = pdf_text(pdf.getvalue())

        # The homepage address is a prefix of every other one, so it is excluded from the count.
        assert all(
            text.count(url.encode()) == 1 for url in EXPECTED_ORDER if url != "https://e.com/"
        )
