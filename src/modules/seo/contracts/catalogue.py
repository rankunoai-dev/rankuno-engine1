"""The SEO issue catalogue as typed, committed data.

RAE kept its catalogue in a database table, in two copies that disagreed in 30
places and held twelve blank severities. This module is the single replacement:
one row per issue, enum-typed so a blank is unrepresentable, and committed as
Python so a test can pin every value.

Decisions applied (plan `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §1):

* D1 - disagreements resolved mechanically: a silent table yields; the two
  never-scored rows take the dashboard value; otherwise stricter wins
  (Issue > Warning > Opportunity, High > Medium > Low).
* D3 - the ten Security issues RAE never wired are pointed at the files a real
  Screaming Frog export actually produces.

Rows with no source file have no producible input today. They stay in the
catalogue so an adapter can declare them ``NOT_MEASURED`` instead of forgetting
them (ADR 0011 §5). This module imports only from ``core`` and the sibling
``issue_ids``; it must never import ``page_classifier`` or ``deliverables``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from src.core.schemas import StrictModel
from src.modules.seo.contracts.issue_ids import IssueCategory, IssueId, Priority, Severity

__all__ = [
    "ISSUE_CATALOGUE",
    "ISSUE_SPECS",
    "RAE_LABELS",
    "IssueCategory",
    "IssueId",
    "IssueSpec",
    "Priority",
    "RaeLabel",
    "Severity",
]


class IssueSpec(StrictModel):
    """One catalogue row.

    ``sf_sources`` names the Screaming Frog export files whose ``Address`` column
    populates the issue; more than one name means the union. Empty means no
    export produces the issue today.
    """

    id: IssueId
    category: IssueCategory
    label: str
    severity: Severity
    priority: Priority
    sf_sources: tuple[str, ...] = ()


class RaeLabel(StrictModel):
    """RAE's original ``category`` / ``issue_label`` spelling.

    For the differential check only (plan §7). Never shown to a client.
    """

    category: str
    label: str


_I, _S, _P = IssueId, Severity, Priority

# A row is (id, severity, priority, label, *source filenames). Rows are grouped
# by category below and laid out as a table on purpose: one issue per entry,
# readable in a diff, and the format is what ruff would otherwise explode.
_Row = tuple[IssueId, Severity, Priority, str, *tuple[str, ...]]


def _rows(category: IssueCategory, *rows: _Row) -> tuple[IssueSpec, ...]:
    return tuple(
        IssueSpec(
            id=id_, category=category, label=label, severity=sev, priority=pri, sf_sources=src
        )
        for id_, sev, pri, label, *src in rows
    )


# fmt: off
ISSUE_CATALOGUE: Final[tuple[IssueSpec, ...]] = (
    *_rows(
        IssueCategory.RESPONSE_CODES_INTERNAL,
        (_I.RESPONSE_CODES_3XX_REDIRECTION, _S.WARNING, _P.HIGH,
         "3xx (Redirection)", "response_codes_internal_redirection_(3xx).csv"),
        (_I.RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX, _S.ISSUE, _P.HIGH,
         "Internal Client Error (4xx)", "response_codes_internal_client_error_(4xx).csv"),
        (_I.RESPONSE_CODES_INTERNAL_SERVER_ERROR_5XX, _S.ISSUE, _P.HIGH,
         "Internal Server Error (5xx)", "response_codes_internal_server_error_(5xx).csv"),
        (_I.RESPONSE_CODES_INTERNAL_NO_RESPONSE, _S.ISSUE, _P.HIGH,
         "Internal No Response", "response_codes_internal_no_response.csv"),
        (_I.RESPONSE_CODES_INTERNAL_REDIRECT_CHAIN, _S.ISSUE, _P.HIGH,
         "Internal Redirect Chain", "response_codes_internal_redirect_chain.csv"),
        (_I.RESPONSE_CODES_INTERNAL_REDIRECT_LOOP, _S.ISSUE, _P.HIGH,
         "Internal Redirect Loop", "response_codes_internal_redirect_loop.csv"),
        (_I.RESPONSE_CODES_INTERNAL_BLOCKED_BY_ROBOTS_TXT, _S.WARNING, _P.HIGH,
         "Internal Blocked by Robots.txt", "response_codes_internal_blocked_by_robots_txt.csv"),
    ),
    *_rows(
        IssueCategory.URL_ISSUES,
        (_I.URL_UPPERCASE, _S.WARNING, _P.LOW, "Uppercase", "url_uppercase.csv"),
        (_I.URL_UNDERSCORES, _S.OPPORTUNITY, _P.LOW, "Underscores", "url_underscores.csv"),
        (_I.URL_PARAMETERS, _S.WARNING, _P.LOW, "Parameters", "url_parameters.csv"),
        (_I.URL_MULTIPLE_SLASHES, _S.ISSUE, _P.LOW, "Multiple Slashes", "url_multiple_slashes.csv"),
        (_I.URL_REPETITIVE_PATH, _S.WARNING, _P.LOW, "Repetitive Path", "url_repetitive_path.csv"),
        (_I.URL_CONTAINS_SPACE, _S.ISSUE, _P.MEDIUM, "Contains Space", "url_contains_space.csv"),
    ),
    *_rows(
        IssueCategory.PAGE_TITLES,
        (_I.PAGE_TITLES_MISSING, _S.ISSUE, _P.HIGH, "Missing", "page_titles_missing.csv"),
        (_I.PAGE_TITLES_DUPLICATE, _S.OPPORTUNITY, _P.LOW,
         "Duplicate", "page_titles_duplicate.csv"),
        (_I.PAGE_TITLES_OVER_561_PIXELS, _S.OPPORTUNITY, _P.LOW,
         "Over 561 Pixels", "page_titles_over_561_pixels.csv"),
        (_I.PAGE_TITLES_BELOW_200_PIXELS, _S.OPPORTUNITY, _P.LOW,
         "Below 200 Pixels", "page_titles_below_200_pixels.csv"),
        (_I.PAGE_TITLES_SAME_AS_H1, _S.OPPORTUNITY, _P.LOW,
         "Same as H1", "page_titles_same_as_h1.csv"),
        (_I.PAGE_TITLES_MULTIPLE, _S.ISSUE, _P.HIGH, "Multiple", "page_titles_multiple.csv"),
        (_I.PAGE_TITLES_OUTSIDE_HEAD, _S.ISSUE, _P.HIGH,
         "Outside <Head>", "page_titles_outside_head.csv"),
    ),
    *_rows(
        IssueCategory.META_DESCRIPTION,
        (_I.META_DESCRIPTION_MISSING, _S.OPPORTUNITY, _P.MEDIUM,
         "Missing", "meta_description_missing.csv"),
        (_I.META_DESCRIPTION_DUPLICATE, _S.OPPORTUNITY, _P.LOW,
         "Duplicate", "meta_description_duplicate.csv"),
        (_I.META_DESCRIPTION_OVER_985_PIXELS, _S.OPPORTUNITY, _P.LOW,
         "Over 985 Pixels", "meta_description_over_985_pixels.csv"),
        (_I.META_DESCRIPTION_BELOW_400_PIXELS, _S.OPPORTUNITY, _P.LOW,
         "Below 400 Pixels", "meta_description_below_400_pixels.csv"),
        (_I.META_DESCRIPTION_MULTIPLE, _S.ISSUE, _P.MEDIUM,
         "Multiple", "meta_description_multiple.csv"),
        (_I.META_DESCRIPTION_OUTSIDE_HEAD, _S.ISSUE, _P.MEDIUM,
         "Outside <Head>", "meta_description_outside_head.csv"),
    ),
    *_rows(
        IssueCategory.H1,
        (_I.H1_MISSING, _S.ISSUE, _P.HIGH, "Missing", "h1_missing.csv"),
        (_I.H1_DUPLICATE, _S.OPPORTUNITY, _P.LOW, "Duplicate", "h1_duplicate.csv"),
        (_I.H1_OVER_70_CHARACTERS, _S.OPPORTUNITY, _P.LOW,
         "Over 70 Characters", "h1_over_70_characters.csv"),
        (_I.H1_MULTIPLE, _S.WARNING, _P.MEDIUM, "Multiple", "h1_multiple.csv"),
    ),
    *_rows(
        IssueCategory.CANONICALS,
        (_I.CANONICALS_CANONICALISED, _S.ISSUE, _P.HIGH,
         "Canonicalised", "canonicals_canonicalised.csv"),
        (_I.CANONICALS_MISSING, _S.ISSUE, _P.HIGH, "Missing", "canonicals_missing.csv"),
        (_I.CANONICALS_MULTIPLE, _S.ISSUE, _P.HIGH, "Multiple", "canonicals_multiple.csv"),
        (_I.CANONICALS_NON_INDEXABLE_CANONICAL, _S.ISSUE, _P.HIGH,
         "Non-Indexable Canonical", "canonicals_nonindexable_canonical.csv"),
        (_I.CANONICALS_MULTIPLE_CONFLICTING, _S.ISSUE, _P.HIGH,
         "Multiple Conflicting", "canonicals_multiple_conflicting.csv"),
        (_I.CANONICALS_CANONICAL_IS_RELATIVE, _S.WARNING, _P.HIGH,
         "Canonical Is Relative", "canonicals_canonical_is_relative.csv"),
        (_I.CANONICALS_UNLINKED, _S.WARNING, _P.MEDIUM, "Unlinked", "canonicals_unlinked.csv"),
        (_I.CANONICALS_INVALID_ATTRIBUTE_IN_ANNOTATION, _S.ISSUE, _P.HIGH,
         "Invalid Attribute In Annotation"),
        (_I.CANONICALS_CONTAINS_FRAGMENT_URL, _S.ISSUE, _P.HIGH, "Contains Fragment URL"),
        (_I.CANONICALS_OUTSIDE_HEAD, _S.ISSUE, _P.HIGH,
         "Outside <head>", "canonicals_outside_head.csv"),
    ),
    *_rows(
        IssueCategory.DIRECTIVES,
        (_I.DIRECTIVES_NOINDEX, _S.WARNING, _P.HIGH, "Noindex", "directives_noindex.csv"),
        (_I.DIRECTIVES_NOFOLLOW, _S.WARNING, _P.HIGH, "Nofollow", "directives_nofollow.csv"),
    ),
    *_rows(
        IssueCategory.SITEMAPS,
        (_I.SITEMAPS_URLS_NOT_IN_SITEMAP, _S.ISSUE, _P.MEDIUM,
         "URLs Not in Sitemap", "sitemaps_urls_not_in_sitemap.csv"),
        (_I.SITEMAPS_ORPHAN_URLS, _S.ISSUE, _P.HIGH, "Orphan URLs", "sitemaps_orphan_urls.csv"),
        (_I.SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP, _S.ISSUE, _P.MEDIUM,
         "Non-Indexable URLs in Sitemap", "sitemaps_nonindexable_urls_in_sitemap.csv"),
        (_I.SITEMAPS_XML_SITEMAP_OVER_50K_URLS, _S.ISSUE, _P.HIGH,
         "XML Sitemap with over 50k URLs", "sitemaps_xml_sitemap_with_over_50k_urls.csv"),
    ),
    *_rows(
        IssueCategory.SECURITY,
        (_I.SECURITY_HTTP_URLS, _S.ISSUE, _P.HIGH, "HTTP URLs", "security_http_urls.csv"),
        (_I.SECURITY_MIXED_CONTENT, _S.ISSUE, _P.HIGH,
         "Mixed Content", "security_mixed_content.csv"),
        (_I.SECURITY_FORM_URL_INSECURE, _S.ISSUE, _P.HIGH,
         "Form URL Insecure", "form_url_insecure.csv"),
        (_I.SECURITY_FORM_ON_HTTP_URL, _S.ISSUE, _P.HIGH,
         "Form On HTTP URL", "security_form_on_http_url.csv"),
        (_I.SECURITY_MISSING_HSTS_HEADER, _S.WARNING, _P.LOW,
         "Missing HSTS Header", "security_missing_hsts_header.csv"),
        (_I.SECURITY_UNSAFE_CROSS_ORIGIN_LINKS, _S.WARNING, _P.LOW,
         "Unsafe Cross Origin Links", "unsafe_crossorigin_links.csv"),
        (_I.SECURITY_PROTOCOL_RELATIVE_RESOURCE_LINKS, _S.WARNING, _P.LOW,
         "Protocol-Relative Resource Links", "protocolrelative_outlinks.csv"),
        (_I.SECURITY_MISSING_CONTENT_SECURITY_POLICY_HEADER, _S.WARNING, _P.LOW,
         "Missing Content-Security-Policy Header",
         "security_missing_contentsecuritypolicy_header.csv"),
        (_I.SECURITY_MISSING_X_CONTENT_TYPE_OPTIONS_HEADER, _S.WARNING, _P.LOW,
         "Missing X-Content-Type-Options Header",
         "security_missing_xcontenttypeoptions_header.csv"),
        (_I.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER, _S.WARNING, _P.LOW,
         "Missing X-Frame-Options Header", "security_missing_xframeoptions_header.csv"),
        (_I.SECURITY_MISSING_SECURE_REFERRER_POLICY_HEADER, _S.WARNING, _P.LOW,
         "Missing Secure Referrer-Policy Header",
         "security_missing_secure_referrerpolicy_header.csv"),
        (_I.SECURITY_BAD_CONTENT_TYPE, _S.WARNING, _P.LOW,
         "Bad Content Type", "security_bad_content_type.csv"),
    ),
    *_rows(
        IssueCategory.PAGE_SPEED_CWV,
        (_I.PAGE_SPEED_LCP, _S.ISSUE, _P.HIGH, "Largest Contentful Paint (LCP)"),
        (_I.PAGE_SPEED_INP, _S.ISSUE, _P.HIGH, "Interaction to Next Paint (INP)"),
        (_I.PAGE_SPEED_CLS, _S.ISSUE, _P.HIGH, "Cumulative Layout Shift (CLS)"),
        (_I.PAGE_SPEED_FCP, _S.ISSUE, _P.HIGH, "First Contentful Paint (FCP)"),
        (_I.PAGE_SPEED_TTFB, _S.ISSUE, _P.HIGH, "Time to First Byte (TTFB)"),
    ),
    *_rows(
        IssueCategory.STRUCTURED_DATA,
        (_I.STRUCTURED_DATA_MISSING, _S.OPPORTUNITY, _P.HIGH,
         "Missing Structured Data", "structured_data_missing.csv"),
        (_I.STRUCTURED_DATA_VALIDATION_ERRORS, _S.ISSUE, _P.HIGH,
         "Validation Errors", "structured_data_validation_errors.csv"),
        (_I.STRUCTURED_DATA_VALIDATION_WARNINGS, _S.WARNING, _P.LOW,
         "Validation Warnings", "structured_data_validation_warnings.csv"),
        (_I.STRUCTURED_DATA_PARSE_ERRORS, _S.ISSUE, _P.HIGH,
         "Parse Errors", "structured_data_parse_errors.csv"),
        (_I.STRUCTURED_DATA_RICH_RESULT_VALIDATION_ERRORS, _S.ISSUE, _P.HIGH,
         "Rich Result Validation Errors"),
        (_I.STRUCTURED_DATA_RICH_RESULT_VALIDATION_WARNINGS, _S.WARNING, _P.LOW,
         "Rich Result Validation Warnings"),
    ),
    *_rows(
        IssueCategory.INTERNAL_LINKS,
        (_I.INTERNAL_LINKS_CANONICAL_ISSUE_INLINKS, _S.ISSUE, _P.HIGH, "Canonical Issue - Inlinks",
         "canonicalised_inlinks.csv", "nonindexable_canonical_inlinks.csv"),
        (_I.INTERNAL_LINKS_SECURITY_HTTP_URLS_INLINKS, _S.ISSUE, _P.HIGH,
         "Security HTTP URLs - Inlinks", "http_urls_inlinks.csv"),
        (_I.INTERNAL_LINKS_4XX_INLINKS, _S.ISSUE, _P.HIGH,
         "Internal 4xx - Inlinks", "internal_client_error_(4xx)_inlinks.csv"),
        (_I.INTERNAL_LINKS_5XX_INLINKS, _S.ISSUE, _P.HIGH,
         "Internal 5xx - Inlinks", "internal_server_error_(5xx)_inlinks.csv"),
        (_I.INTERNAL_LINKS_3XX_INLINKS, _S.ISSUE, _P.HIGH,
         "Internal 3xx - Inlinks", "internal_redirection_(3xx)_inlinks.csv"),
        (_I.INTERNAL_LINKS_NO_RESPONSE_INLINKS, _S.ISSUE, _P.HIGH,
         "Internal No Response URLs - Inlinks", "internal_no_response_inlinks.csv"),
        (_I.INTERNAL_LINKS_BLOCKED_BY_ROBOTS_TXT_INLINKS, _S.WARNING, _P.LOW,
         "Internal Blocked by Robots.txt - Inlinks", "internal_blocked_by_robots_txt_inlinks.csv"),
        (_I.INTERNAL_LINKS_BLOCKED_RESOURCE_INLINKS, _S.WARNING, _P.LOW,
         "Internal Blocked Resource - Inlinks", "internal_blocked_resource_inlinks.csv"),
        (_I.INTERNAL_LINKS_FUNCTIONAL_ANALYSIS, _S.OPPORTUNITY, _P.HIGH,
         "Functional Internal Links Analysis"),
    ),
    *_rows(
        IssueCategory.CONTENT_ISSUES,
        (_I.CONTENT_LOW_CONTENT_PAGES, _S.WARNING, _P.HIGH,
         "Low Content Pages", "content_low_content_pages.csv"),
        (_I.CONTENT_SOFT_404_PAGES, _S.WARNING, _P.HIGH,
         "Soft 404 Pages", "content_soft_404_pages.csv"),
        (_I.CONTENT_SPELLING_ERRORS, _S.WARNING, _P.MEDIUM,
         "Spelling Errors", "content_spelling_errors.csv"),
        (_I.CONTENT_GRAMMAR_ERRORS, _S.WARNING, _P.MEDIUM,
         "Grammar Errors", "content_grammar_errors.csv"),
        (_I.CONTENT_READABILITY_DIFFICULT, _S.WARNING, _P.MEDIUM, "Readability Difficult"),
        (_I.CONTENT_READABILITY_VERY_DIFFICULT, _S.WARNING, _P.MEDIUM,
         "Readability Very Difficult"),
        (_I.CONTENT_LOREM_IPSUM_PLACEHOLDER, _S.OPPORTUNITY, _P.MEDIUM,
         "Lorem Ipsum Placeholder", "content_lorem_ipsum_placeholder.csv"),
        (_I.CONTENT_NEAR_DUPLICATES, _S.ISSUE, _P.MEDIUM,
         "Near Duplicates", "content_near_duplicates.csv"),
        (_I.CONTENT_EXACT_DUPLICATES, _S.ISSUE, _P.HIGH,
         "Exact Duplicates", "content_exact_duplicates.csv"),
    ),
    *_rows(
        IssueCategory.CUSTOM_SEARCH,
        (_I.CUSTOM_SEARCH_GA4_TAGS, _S.ISSUE, _P.HIGH, "GA4 Tags Implementation"),
        (_I.CUSTOM_SEARCH_GTM_TAGS, _S.ISSUE, _P.HIGH, "GTM Tags Implementation"),
        (_I.CUSTOM_SEARCH_OG_TAGS, _S.ISSUE, _P.LOW, "OG Tags"),
        (_I.CUSTOM_SEARCH_TWITTER_CARD, _S.ISSUE, _P.LOW, "Twitter Card"),
    ),
    *_rows(
        IssueCategory.PAGINATION,
        (_I.PAGINATION_URL_NOT_IN_ANCHOR_TAG, _S.ISSUE, _P.LOW,
         "Pagination URL Not in Anchor Tag", "pagination_pagination_url_not_in_anchor_tag.csv"),
        (_I.PAGINATION_UNLINKED_URLS, _S.ISSUE, _P.HIGH,
         "Unlinked Pagination URLs", "pagination_unlinked_pagination_urls.csv"),
        (_I.PAGINATION_NON_INDEXABLE, _S.ISSUE, _P.HIGH,
         "Non-Indexable", "pagination_nonindexable.csv"),
        (_I.PAGINATION_MULTIPLE_URLS, _S.ISSUE, _P.LOW,
         "Multiple Pagination URLs", "pagination_multiple_pagination_urls.csv"),
        (_I.PAGINATION_LOOP, _S.ISSUE, _P.LOW, "Pagination Loop", "pagination_pagination_loop.csv"),
        (_I.PAGINATION_SEQUENCE_ERROR, _S.ISSUE, _P.HIGH,
         "Sequence Error", "pagination_sequence_error.csv"),
    ),
    *_rows(
        IssueCategory.HREFLANG_TAGS,
        (_I.HREFLANG_NON_200_URLS, _S.ISSUE, _P.HIGH,
         "Non-200 hreflang URLs", "hreflang_non200_hreflang_urls.csv"),
        (_I.HREFLANG_UNLINKED_URLS, _S.ISSUE, _P.HIGH,
         "Unlinked hreflang URLs", "hreflang_unlinked_hreflang_urls.csv"),
        (_I.HREFLANG_MISSING_RETURN_LINKS, _S.ISSUE, _P.HIGH,
         "Missing Return Links", "hreflang_missing_return_links.csv"),
        (_I.HREFLANG_NON_CANONICAL_RETURN_LINKS, _S.ISSUE, _P.HIGH,
         "Non-Canonical Return Links", "hreflang_noncanonical_return_links.csv"),
        (_I.HREFLANG_NOINDEX_RETURN_LINKS, _S.ISSUE, _P.HIGH,
         "Noindex Return Links", "hreflang_noindex_return_links.csv"),
        (_I.HREFLANG_INCORRECT_LANGUAGE_REGION_CODES, _S.ISSUE, _P.HIGH,
         "Incorrect Language & Region Codes", "hreflang_incorrect_language_region_codes.csv"),
        (_I.HREFLANG_MULTIPLE_ENTRIES, _S.ISSUE, _P.HIGH,
         "Multiple Entries", "hreflang_multiple_entries.csv"),
        (_I.HREFLANG_MISSING_SELF_REFERENCE, _S.ISSUE, _P.MEDIUM,
         "Missing Self Reference", "hreflang_missing_self_reference.csv"),
        (_I.HREFLANG_INCONSISTENT_LANGUAGE_REGION_RETURN_LINKS, _S.ISSUE, _P.HIGH,
         "Inconsistent Language & Region Return Links",
         "hreflang_inconsistent_language_region_return_links.csv"),
        (_I.HREFLANG_NOT_USING_CANONICAL, _S.ISSUE, _P.HIGH,
         "Not Using Canonical", "hreflang_not_using_canonical.csv"),
        (_I.HREFLANG_MISSING_X_DEFAULT, _S.WARNING, _P.HIGH,
         "Missing X-Default", "hreflang_missing_xdefault.csv"),
        (_I.HREFLANG_MISSING, _S.ISSUE, _P.HIGH, "Missing", "hreflang_missing.csv"),
        (_I.HREFLANG_OUTSIDE_HEAD, _S.ISSUE, _P.HIGH,
         "Outside <head>", "hreflang_outside_head.csv"),
    ),
)
# fmt: on
"""Every issue the deliverables know about, in RAE's original row order."""

ISSUE_SPECS: Final[Mapping[IssueId, IssueSpec]] = MappingProxyType(
    {spec.id: spec for spec in ISSUE_CATALOGUE}
)
"""``ISSUE_CATALOGUE`` keyed by id for O(1) lookup."""

# RAE's category spellings. Only the two misspelt ones differ from ours.
_RAE_CATEGORY_NAMES: Final[Mapping[IssueCategory, str]] = MappingProxyType(
    {
        IssueCategory.RESPONSE_CODES_INTERNAL: "Response Codes - Internal",
        IssueCategory.URL_ISSUES: "URL Issues",
        IssueCategory.PAGE_TITLES: "Page Titles",
        IssueCategory.META_DESCRIPTION: "Meta Description",
        IssueCategory.H1: "H1",
        IssueCategory.CANONICALS: "Canonicals",
        IssueCategory.DIRECTIVES: "Directives",
        IssueCategory.SITEMAPS: "Sitemaps",
        IssueCategory.SECURITY: "Security",
        IssueCategory.PAGE_SPEED_CWV: "Page Speed/CWV",
        IssueCategory.STRUCTURED_DATA: "Strucured Tags",
        IssueCategory.INTERNAL_LINKS: "Internal Links",
        IssueCategory.CONTENT_ISSUES: "Content Issues",
        IssueCategory.CUSTOM_SEARCH: "Custom Search ",
        IssueCategory.PAGINATION: "Pagination",
        IssueCategory.HREFLANG_TAGS: "Hreflang Tags",
    }
)

# Labels we corrected. Everything else is spelt as RAE spelt it.
_RAE_LABEL_OVERRIDES: Final[Mapping[IssueId, str]] = MappingProxyType(
    {
        _I.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER: "Missing X-Frames-Options Header",
        _I.INTERNAL_LINKS_SECURITY_HTTP_URLS_INLINKS: "Security http URLs- Inlinks",
        _I.INTERNAL_LINKS_NO_RESPONSE_INLINKS: "Internal No response URLs - Inlinks",
        _I.CONTENT_READABILITY_DIFFICULT: "Redability Difficult",
        _I.CONTENT_READABILITY_VERY_DIFFICULT: "Redability Very Difficult",
    }
)

RAE_LABELS: Final[Mapping[IssueId, RaeLabel]] = MappingProxyType(
    {
        spec.id: RaeLabel(
            category=_RAE_CATEGORY_NAMES[spec.category],
            label=_RAE_LABEL_OVERRIDES.get(spec.id, spec.label),
        )
        for spec in ISSUE_CATALOGUE
    }
)
"""Original RAE spellings for every row, so the differential check (P0-7) can
match by ``IssueId`` and spelling fixes never register as differences."""
