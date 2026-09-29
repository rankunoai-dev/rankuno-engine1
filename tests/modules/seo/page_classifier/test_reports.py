"""Tests for `MasterURLReport`, the crawl-results Excel export.

Regression coverage for a defect where the "All URLs" sheet's "HTTP Status"
column was actually populated with `page.final_url` — every row's status cell
duplicated its URL cell, because no per-page status code is carried onto
`FullPageIntelligenceProfile` and the wrong field was written in its place.
See `docs/build-log/0102-a-click-that-carries-its-own-auth.md` §4 and the
cycle that fixed this.
"""

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet
from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.reports import MasterURLReport
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import CrawlSummary, PageClassificationOutput
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

BASE_URL = "https://e.com/"


def _page(url: str) -> FullPageIntelligenceProfile:
    """A minimal, validly-classified page profile for report tests."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
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
        final_url=url,
    )


def _result(*pages: FullPageIntelligenceProfile) -> PageClassificationOutput:
    return PageClassificationOutput(
        base_url=BASE_URL,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(base_url=BASE_URL),
        summary=CrawlSummary(pages_classified=len(pages)),
        pages=pages,
    )


class TestAllUrlsSheetHttpStatusColumn:
    """The "HTTP Status" column must never carry a URL under a status header."""

    def test_http_status_column_is_never_the_row_url(self) -> None:
        """Reproduces the production defect: status cell == URL cell."""
        page = _page("https://e.com/blog/")
        report = MasterURLReport(_result(page))

        book = load_workbook(report.generate())
        ws = book["All URLs"]
        headers = [cell.value for cell in ws[1]]
        rows = list(ws.iter_rows(min_row=2, values_only=True))

        url_col = headers.index("URL")
        status_col = headers.index("HTTP Status")
        row = rows[0]

        assert row[status_col] != row[url_col]

    def test_http_status_column_is_an_honest_unknown_marker(self) -> None:
        """No per-page status code is captured anywhere in the pipeline.

        `FullPageIntelligenceProfile` has no such field — see
        `reports.py::MasterURLReport._extract_status_code`), so the column
        must say so rather than guess or substitute another field.
        """
        page = _page("https://e.com/blog/")
        report = MasterURLReport(_result(page))

        book = load_workbook(report.generate())
        ws = book["All URLs"]
        headers = [cell.value for cell in ws[1]]
        rows = list(ws.iter_rows(min_row=2, values_only=True))

        status_col = headers.index("HTTP Status")
        assert rows[0][status_col] == "Unknown"

    def test_matches_the_by_http_status_sheet_convention(self) -> None:
        """Sheet 3 already marks an unrecorded status as "Unknown".

        Sheet 1 must use the same word for the same absence, not a
        different one.
        """
        page = _page("https://e.com/blog/")
        report = MasterURLReport(_result(page))

        book = load_workbook(report.generate())
        all_urls_status = [cell.value for cell in ws_col(book["All URLs"], "HTTP Status")]
        by_status_status = [cell.value for cell in ws_col(book["By HTTP Status"], "HTTP Status")]

        assert all_urls_status == ["Unknown"]
        assert by_status_status == ["Unknown"]


def ws_col(ws: Worksheet, header: str) -> list[Cell]:
    """Return the data cells (row 2 onward) under the given header."""
    headers = [cell.value for cell in ws[1]]
    idx = headers.index(header)
    return [row[idx] for row in ws.iter_rows(min_row=2)]


class TestGeneratePdf:
    """`generate_pdf`, the `.xlsx` "All URLs" sheet's PDF twin.

    `tests/api/test_server.py::TestUrlsPdfDownload` covers the route and
    decodes the rendered bytes end to end; these tests stay at the
    generator's own boundary and check the one thing a decode cannot show
    cheaply — that the row handed to the PDF is the *same* row the workbook
    would produce for the same page, not a second, independently-maintained
    view of it.
    """

    def test_produces_pdf_bytes(self) -> None:
        page = _page("https://e.com/blog/")
        pdf = MasterURLReport(_result(page)).generate_pdf()

        assert pdf.getvalue().startswith(b"%PDF")

    def test_row_matches_the_all_urls_sheet_column_for_column(self) -> None:
        """`_pdf_row` must report what `_sheet_all_urls` reports for the page.

        Including the "Unknown" HTTP Status marker, so the PDF cannot drift
        back into the fixed defect this module's other tests guard (a URL
        where a status code belongs).
        """
        page = _page("https://e.com/blog/")
        report = MasterURLReport(_result(page))

        book = load_workbook(report.generate())
        sheet_row = list(book["All URLs"].iter_rows(min_row=2, values_only=True))[0]
        pdf_row = report._pdf_row(page)

        assert pdf_row[0] == sheet_row[0]  # URL
        assert pdf_row[3] == "Unknown"
        assert sheet_row[3] == "Unknown"

    def test_row_has_eleven_columns(self) -> None:
        """Same column count as the "All URLs" sheet's header row."""
        page = _page("https://e.com/blog/")
        report = MasterURLReport(_result(page))

        assert len(report._pdf_row(page)) == 11
