"""The five ADR 0038 "All URLs" columns, one rule at a time.

Each test is a case the approved rules name, built from the stored fields the
crawl writes. The cases that matter most are the ones a wrong reading would
present as a finding: an undeclared page that reads as "Self", a page with two
canonicals that reads as one, and a page the crawl never read that reads as
"no breadcrumb" or as a measured zero.
"""

from __future__ import annotations

from src.modules.seo.page_classifier.discovery import (
    OUTCOME_NOT_FOUND,
    OUTCOME_NOT_FETCHED,
    OUTCOME_NOT_HTML,
    OUTCOME_OK,
)
from src.modules.seo.page_classifier.fetch_status import LABEL_NOT_RECORDED
from src.modules.seo.page_classifier.report_columns import (
    BREADCRUMB_PARENT_HEADER,
    CANONICAL_LINKS_HEADER,
    CANONICAL_STATUS_HEADER,
    CANONICAL_URL_HEADER,
    TRAILING_HEADERS,
    UNIQUE_CONTENT_INLINKS_HEADER,
    breadcrumb_parent,
    canonical_links,
    canonical_status,
    canonical_url_cell,
    trailing_cells,
    unique_content_inlinks,
)
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from tests.modules.seo.page_classifier.report_profile_factory import legacy_page, make_page

URL = "https://e.com/p/"
ELSEWHERE = "https://e.com/other/"


def _declared(**fields: object) -> FullPageIntelligenceProfile:
    """A page the crawl fetched as HTML and read: declared fields filled in."""
    base: dict[str, object] = {
        "canonical_declared": True,
        "canonical_link_count": 1,
        "canonical_url": URL,
        "body_link_count": 2,
        "unique_content_inlinks": 1,
        "breadcrumb_parent_url": "https://e.com/",
    }
    base.update(fields)
    return make_page(URL, **base)


class TestCanonicalStatus:
    def test_an_undeclared_page_is_missing_and_never_self(self):
        """The classifier writes the page's own URL into `canonical_url` when none is
        declared. Read naively, that is "Self". `canonical_declared` says it is not."""
        page = _declared(canonical_declared=False, canonical_link_count=0)
        assert page.canonical_url == URL, "the stored value really is the page itself"
        assert canonical_status(page) == "Missing"

    def test_a_declaration_naming_the_page_is_self(self):
        assert canonical_status(_declared()) == "Self"

    def test_a_declaration_naming_another_url_is_elsewhere(self):
        assert canonical_status(_declared(canonical_url=ELSEWHERE)) == "Elsewhere"

    def test_self_compares_normalised_urls(self):
        """A trailing slash is not a different page."""
        assert canonical_status(_declared(canonical_url="https://e.com/p")) == "Self"

    def test_two_canonicals_are_multiple_even_when_the_first_names_the_page(self):
        page = _declared(canonical_link_count=2, canonical_url=URL)
        assert canonical_status(page) == "Multiple"

    def test_a_tag_naming_nothing_usable_reads_missing_with_its_count_kept(self):
        """Stored as undeclared, because the profile cannot hold an empty canonical.
        The count still records that a tag was there."""
        page = _declared(canonical_declared=False, canonical_link_count=1, canonical_url=URL)
        assert canonical_status(page) == "Missing"
        assert canonical_links(page) == 1

    def test_a_page_never_fetched_is_blank(self):
        page = make_page(
            URL,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            http_status=None,
            canonical_declared=None,
            canonical_link_count=None,
        )
        assert canonical_status(page) is None

    def test_a_fetched_non_html_answer_is_blank(self):
        page = make_page(
            URL,
            fetch_outcome=OUTCOME_NOT_HTML,
            canonical_declared=None,
            canonical_link_count=None,
        )
        assert canonical_status(page) is None

    def test_a_profile_from_before_the_capture_is_not_recorded(self):
        assert canonical_status(legacy_page()) == LABEL_NOT_RECORDED

    def test_a_pre_capture_profile_with_a_fetch_outcome_is_not_recorded_not_blank(self):
        """Stored after the fetch outcome existed but before this field did."""
        page = make_page(URL, fetch_outcome=OUTCOME_OK, canonical_declared=None)
        assert canonical_status(page) == LABEL_NOT_RECORDED


class TestCanonicalURLAndCount:
    def test_an_undeclared_page_shows_no_canonical_url(self):
        page = _declared(canonical_declared=False, canonical_link_count=0)
        assert canonical_url_cell(page) is None

    def test_a_declared_canonical_is_shown(self):
        assert canonical_url_cell(_declared(canonical_url=ELSEWHERE)) == ELSEWHERE

    def test_a_legacy_profile_says_not_recorded(self):
        assert canonical_url_cell(legacy_page()) == LABEL_NOT_RECORDED

    def test_a_fetched_page_with_no_canonical_counts_zero(self):
        assert canonical_links(_declared(canonical_declared=False, canonical_link_count=0)) == 0

    def test_a_page_never_read_has_a_blank_count_not_a_zero(self):
        page = make_page(
            URL,
            fetch_outcome=OUTCOME_NOT_FETCHED,
            canonical_declared=None,
            canonical_link_count=None,
        )
        assert canonical_links(page) is None

    def test_a_legacy_profile_has_a_not_recorded_count(self):
        assert canonical_links(legacy_page()) == LABEL_NOT_RECORDED


class TestUniqueContentInlinks:
    def test_a_fetched_page_shows_its_distinct_content_count(self):
        assert unique_content_inlinks(_declared(unique_content_inlinks=7)) == 7

    def test_a_zero_is_a_measured_zero_on_a_fetched_page(self):
        assert unique_content_inlinks(_declared(unique_content_inlinks=0)) == 0

    def test_a_page_whose_fetch_was_not_ok_is_blank(self):
        """The approved rule, and its known cost: a 404 with content links shows blank."""
        page = make_page(URL, fetch_outcome=OUTCOME_NOT_FOUND, http_status=404, unique_content_inlinks=3)
        assert unique_content_inlinks(page) is None

    def test_a_legacy_profile_is_not_recorded(self):
        assert unique_content_inlinks(legacy_page()) == LABEL_NOT_RECORDED

    def test_a_pre_capture_ok_profile_is_not_recorded_not_zero(self):
        page = make_page(URL, fetch_outcome=OUTCOME_OK, unique_content_inlinks=None)
        assert unique_content_inlinks(page) == LABEL_NOT_RECORDED


class TestBreadcrumbParent:
    def test_the_stored_parent_is_shown(self):
        assert breadcrumb_parent(_declared()) == "https://e.com/"

    def test_a_read_page_with_no_breadcrumb_is_blank(self):
        assert breadcrumb_parent(_declared(breadcrumb_parent_url="")) is None

    def test_a_page_never_read_is_blank(self):
        page = make_page(URL, fetch_outcome=OUTCOME_NOT_FETCHED, breadcrumb_parent_url=None)
        assert breadcrumb_parent(page) is None

    def test_a_legacy_profile_is_not_recorded(self):
        assert breadcrumb_parent(legacy_page()) == LABEL_NOT_RECORDED

    def test_a_pre_capture_ok_profile_is_not_recorded_not_blank(self):
        page = make_page(URL, fetch_outcome=OUTCOME_OK, breadcrumb_parent_url=None)
        assert breadcrumb_parent(page) == LABEL_NOT_RECORDED


class TestTheAppendedColumns:
    def test_the_five_new_headers_follow_the_nine_in_order(self):
        assert TRAILING_HEADERS[9:] == (
            CANONICAL_STATUS_HEADER,
            CANONICAL_URL_HEADER,
            CANONICAL_LINKS_HEADER,
            UNIQUE_CONTENT_INLINKS_HEADER,
            BREADCRUMB_PARENT_HEADER,
        )

    def test_one_cell_per_header_for_every_kind_of_page(self):
        for page in (_declared(), legacy_page(), make_page(URL, fetch_outcome=OUTCOME_NOT_FETCHED)):
            assert len(trailing_cells(page)) == len(TRAILING_HEADERS) == 14
