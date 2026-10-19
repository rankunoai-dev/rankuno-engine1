"""Derivation rules for the trailing "All URLs" columns, one page at a time.

Each column is checked against the rule that defines it: the not-fetched and
redirect edge cases, the orphan definition against an inlinked sitemap-only
page, the precedence that resolves an overlap between discovery paths, and the
labelled "Not recorded (older crawl)" answer a legacy profile must get rather
than a guessed value. The workbook and PDF tests live in
`test_report_columns_workbook.py`.
"""

from __future__ import annotations

from openpyxl import load_workbook
from src.modules.seo.page_classifier.discovery import (
    OUTCOME_NOT_FETCHED,
    OUTCOME_TRANSPORT_TIMEOUT,
)
from src.modules.seo.page_classifier.fetch_status import LABEL_NOT_RECORDED
from src.modules.seo.page_classifier.report_columns import (
    CTR_DECIMAL_FORMAT,
    CTR_DECIMAL_HEADER,
    TRAILING_HEADERS,
    final_url,
    found_via,
    gsc_ctr_decimal,
    in_sitemap,
    indexability,
    indexability_reason,
    orphan,
    trailing_cells,
    unique_inlinks,
    unique_outlinks,
)
from src.modules.seo.page_classifier.reports import MasterURLReport
from src.modules.seo.page_classifier.schemas import DiscoverySource, Indexability
from tests.modules.seo.page_classifier.report_profile_factory import (
    legacy_page,
    make_page,
    make_result,
)


class TestFoundVia:
    def test_a_followed_link_beats_a_sitemap_entry(self) -> None:
        page = make_page(discovery_sources=DiscoverySource(sitemap=True, dom_link=True))
        assert found_via(page) == "Crawl link"

    def test_a_cms_record_beats_a_sitemap_entry(self) -> None:
        page = make_page(discovery_sources=DiscoverySource(sitemap=True, cms_api=True))
        assert found_via(page) == "CMS"

    def test_a_link_beats_a_cms_record(self) -> None:
        page = make_page(discovery_sources=DiscoverySource(dom_link=True, cms_api=True))
        assert found_via(page) == "Crawl link"

    def test_sitemap_only_reads_sitemap(self) -> None:
        page = make_page(discovery_sources=DiscoverySource(sitemap=True))
        assert found_via(page) == "Sitemap"

    def test_no_recorded_path_is_a_legacy_label(self) -> None:
        assert found_via(legacy_page()) == LABEL_NOT_RECORDED


class TestInSitemap:
    def test_listed_by_a_sitemap_is_yes(self) -> None:
        assert in_sitemap(make_page(discovery_sources=DiscoverySource(sitemap=True))) == "Yes"

    def test_not_listed_is_no(self) -> None:
        assert in_sitemap(make_page(discovery_sources=DiscoverySource(dom_link=True))) == "No"

    def test_legacy_is_a_legacy_label_not_no(self) -> None:
        assert in_sitemap(legacy_page()) == LABEL_NOT_RECORDED


class TestOrphan:
    def test_sitemap_only_with_no_inlinks_is_an_orphan(self) -> None:
        page = make_page(
            discovery_sources=DiscoverySource(sitemap=True),
            inbound_internal_links_count=0,
        )
        assert orphan(page) == "Yes"

    def test_inlinked_sitemap_only_page_is_not_an_orphan(self) -> None:
        """The contrast the definition turns on: same discovery, one inlink."""
        page = make_page(
            discovery_sources=DiscoverySource(sitemap=True),
            inbound_internal_links_count=2,
        )
        assert orphan(page) == "No"

    def test_a_linked_page_in_the_sitemap_is_not_an_orphan(self) -> None:
        page = make_page(
            discovery_sources=DiscoverySource(sitemap=True, dom_link=True),
            inbound_internal_links_count=0,
        )
        assert orphan(page) == "No"

    def test_a_cms_known_page_is_not_an_orphan(self) -> None:
        page = make_page(
            discovery_sources=DiscoverySource(sitemap=True, cms_api=True),
            inbound_internal_links_count=0,
        )
        assert orphan(page) == "No"

    def test_a_crawl_link_only_page_is_not_an_orphan(self) -> None:
        page = make_page(discovery_sources=DiscoverySource(dom_link=True))
        assert orphan(page) == "No"

    def test_legacy_profile_is_a_legacy_label(self) -> None:
        assert orphan(legacy_page()) == LABEL_NOT_RECORDED


class TestUniqueInlinks:
    def test_a_not_fetched_page_keeps_its_real_count(self) -> None:
        """Links to a page were read from other pages, so the count is known."""
        page = make_page(
            http_status=None,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            final_url="",
            discovery_sources=DiscoverySource(sitemap=True),
            inbound_internal_links_count=3,
        )
        assert unique_inlinks(page) == 3

    def test_a_fetched_page_reports_its_count(self) -> None:
        assert unique_inlinks(make_page(inbound_internal_links_count=5)) == 5

    def test_legacy_profile_is_a_legacy_label(self) -> None:
        assert unique_inlinks(legacy_page()) == LABEL_NOT_RECORDED


class TestUniqueOutlinks:
    def test_a_fetched_page_reports_its_count(self) -> None:
        assert unique_outlinks(make_page(outbound_internal_links_count=7)) == 7

    def test_a_page_with_no_outlinks_reports_zero_not_blank(self) -> None:
        """Zero is a measured fact here: the body was read and had no links."""
        assert unique_outlinks(make_page(outbound_internal_links_count=0)) == 0

    def test_a_not_fetched_page_is_blank_not_zero(self) -> None:
        page = make_page(
            http_status=None,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            final_url="",
            discovery_sources=DiscoverySource(sitemap=True),
        )
        assert unique_outlinks(page) is None

    def test_a_no_response_page_is_blank_not_zero(self) -> None:
        page = make_page(
            http_status=None,
            fetch_outcome=OUTCOME_TRANSPORT_TIMEOUT,
            final_url="",
        )
        assert unique_outlinks(page) is None

    def test_legacy_profile_is_a_legacy_label(self) -> None:
        assert unique_outlinks(legacy_page()) == LABEL_NOT_RECORDED


class TestGscCtrDecimal:
    def test_zero_impressions_is_blank(self) -> None:
        assert gsc_ctr_decimal(make_page(gsc_clicks=0, gsc_impressions=0)) is None

    def test_gsc_absent_is_blank(self) -> None:
        """No join happened: impressions are `None`, not a measured zero."""
        assert gsc_ctr_decimal(make_page(gsc_clicks=None, gsc_impressions=None)) is None

    def test_is_a_decimal_not_a_percent(self) -> None:
        """23 clicks on 1,000 impressions is 0.023, shown with three places."""
        value = gsc_ctr_decimal(make_page(gsc_clicks=23, gsc_impressions=1000))
        assert value is not None
        assert abs(value - 0.023) < 1e-12
        assert CTR_DECIMAL_FORMAT == "0.000"


class TestFinalUrl:
    def test_a_redirect_reports_where_the_fetch_landed(self) -> None:
        page = make_page(
            "https://e.com/moved/",
            final_url="https://e.com/moved-to/",
            first_redirect_status=301,
        )
        assert final_url(page) == "https://e.com/moved-to/"

    def test_a_not_fetched_page_is_blank(self) -> None:
        page = make_page(
            http_status=None,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            final_url="",
            discovery_sources=DiscoverySource(sitemap=True),
        )
        assert final_url(page) is None

    def test_legacy_profile_is_a_legacy_label(self) -> None:
        assert final_url(legacy_page()) == LABEL_NOT_RECORDED


class TestIndexability:
    def test_reports_the_stored_verdict(self) -> None:
        page = make_page(indexability=Indexability.NOINDEX, indexability_reason="Says noindex.")
        assert indexability(page) == "NOINDEX"
        assert indexability_reason(page) == "Says noindex."

    def test_an_empty_reason_is_blank(self) -> None:
        assert indexability_reason(make_page()) is None

    def test_legacy_profile_is_a_legacy_label(self) -> None:
        assert indexability(legacy_page()) == LABEL_NOT_RECORDED
        assert indexability_reason(legacy_page()) == LABEL_NOT_RECORDED


class TestTrailingCells:
    def test_returns_one_value_per_trailing_header(self) -> None:
        assert len(trailing_cells(make_page())) == len(TRAILING_HEADERS) == 14

    def test_workbook_cell_for_a_not_fetched_page_is_empty(self) -> None:
        """A blank cell is `None` in the workbook, not the text "None"."""
        page = make_page(
            "https://e.com/sitemap-only/",
            http_status=None,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            final_url="",
            discovery_sources=DiscoverySource(sitemap=True),
        )
        ws = load_workbook(MasterURLReport(make_result(page)).generate())["All URLs"]
        headers = [cell.value for cell in ws[1]]
        row = dict(zip(headers, [cell.value for cell in ws[2]], strict=True))

        assert row["Final URL"] is None
        assert row[CTR_DECIMAL_HEADER] is None
