"""Tests for Layer 0 URL normalisation and pre-fetch classification."""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.schemas import (
    MAX_CRAWL_DEPTH,
    HierarchyLevel,
    PrimaryPageType,
)
from src.modules.seo.page_classifier.url_rules import (
    depth_of,
    is_crawlable_url,
    is_faceted_filter,
    is_tracking_param,
    normalize_path,
    normalize_url,
    safe_split,
    strip_locale_prefix,
    url_fast_path,
)


class TestTrackingParams:
    @pytest.mark.parametrize(
        "name",
        ["utm_source", "UTM_Medium", "gclid", "fbclid", "ref", "qid", "sr", "pf_rd_p", "_ga"],
    )
    def test_recognises_tracking_noise(self, name):
        assert is_tracking_param(name) is True

    @pytest.mark.parametrize("name", ["page", "category", "id", "q", "lang"])
    def test_leaves_meaningful_params_alone(self, name):
        assert is_tracking_param(name) is False


class TestNormalizeUrl:
    def test_strips_tracking_and_keeps_content_params(self):
        result = normalize_url("https://e.com/shop?page=2&utm_source=x&gclid=y")
        assert result == "https://e.com/shop/?page=2"

    def test_parameter_order_does_not_fork_the_dedup_key(self):
        """Rule 2: order must not create duplicate frontier entries."""
        a = normalize_url("https://e.com/p?b=2&a=1")
        b = normalize_url("https://e.com/p?a=1&b=2")
        assert a == b

    def test_amazon_style_url_collapses(self):
        """The worked example from the Amazon-scale specification."""
        raw = "https://www.amazon.com/dp/B0001234?color=red&size=xl&ref=nav_1&qid=1723456&sr=8-1"
        assert normalize_url(raw) == "https://www.amazon.com/dp/b0001234/?color=red&size=xl"

    def test_folds_locale_variants_onto_one_key(self):
        assert normalize_url("https://e.com/de/software/") == normalize_url(
            "https://e.com/software/"
        )

    def test_locale_folding_can_be_disabled(self):
        assert normalize_url("https://e.com/de/x/", strip_locale=False) != normalize_url(
            "https://e.com/x/"
        )

    def test_trailing_slash_is_unified(self):
        assert normalize_url("https://e.com/a/b") == normalize_url("https://e.com/a/b/")

    def test_host_and_scheme_are_lowercased(self):
        assert normalize_url("HTTPS://E.COM/A/") == "https://e.com/a/"

    def test_fragment_is_dropped(self):
        assert normalize_url("https://e.com/a/#section") == "https://e.com/a/"

    def test_root_normalises_to_slash(self):
        assert normalize_url("https://e.com") == "https://e.com/"


class TestLocaleAndPath:
    @pytest.mark.parametrize(
        ("path", "expected", "locale"),
        [
            ("/de/software/", "/software/", "de"),
            ("/en-gb/pricing/", "/pricing/", "en-gb"),
            ("/pt_BR/x/", "/x/", "pt_br"),
            ("/software/", "/software/", None),
            ("/", "/", None),
        ],
    )
    def test_strip_locale_prefix(self, path, expected, locale):
        stripped, found = strip_locale_prefix(path)
        assert stripped == expected
        assert found == locale

    @pytest.mark.parametrize("segment", ["dp", "ai", "hr", "it", "us", "b2b", "qa"])
    def test_does_not_mistake_a_content_slug_for_a_locale(self, segment):
        """Regression: shape-matching any 2-letter segment deleted real paths.

        `/dp/` is Amazon's product path; `/ai/`, `/hr/` and `/it/` are ordinary
        content sections. Stripping them silently corrupts the dedup key.
        """
        stripped, locale = strip_locale_prefix(f"/{segment}/agents/")
        assert locale is None
        assert stripped == f"/{segment}/agents/"

    def test_amazon_product_path_survives_normalisation(self):
        """The concrete failure the shape-based regex caused."""
        assert "/dp/" in normalize_url("https://www.amazon.com/dp/B0001234")

    def test_known_locales_override_removes_all_guesswork(self):
        """A crawler that observed the site's real locales should say so."""
        stripped, locale = strip_locale_prefix("/it/prodotti/", frozenset({"it"}))
        assert locale == "it"
        assert stripped == "/prodotti/"

    def test_known_locales_exclude_everything_else(self):
        stripped, locale = strip_locale_prefix("/de/x/", frozenset({"it"}))
        assert locale is None
        assert stripped == "/de/x/"

    def test_regional_locales_are_unambiguous_without_a_list(self):
        for path in ("/en-gb/x/", "/pt_BR/x/", "/zh-hans/x/"):
            _, locale = strip_locale_prefix(path)
            assert locale is not None, f"{path} should be recognised"

    def test_normalize_path_lowercases_and_pads(self):
        assert normalize_path("/A//B") == "/a/b/"


class TestDepth:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [("/", 0), ("/a/", 1), ("/a/b/c/", 3), ("/de/a/b/", 2)],
    )
    def test_counts_segments_excluding_locale(self, path, expected):
        assert depth_of(path) == expected

    def test_clamps_at_the_crawl_ceiling(self):
        assert depth_of("/" + "/".join(str(i) for i in range(40))) == MAX_CRAWL_DEPTH


class TestFacetedFilter:
    def test_no_query_is_never_a_filter(self):
        assert is_faceted_filter("https://e.com/shop/") is False

    def test_known_facet_param_triggers(self):
        assert is_faceted_filter("https://e.com/shop?color=red") is True

    def test_tracking_only_query_is_not_a_filter(self):
        """A campaign link to a real page must stay a real page."""
        assert is_faceted_filter("https://e.com/shop?utm_source=newsletter") is False

    def test_too_many_params_triggers(self):
        assert is_faceted_filter("https://e.com/s?a=1&b=2&c=3&d=4&e=5&f=6") is True

    def test_pagination_alone_is_not_a_filter(self):
        assert is_faceted_filter("https://e.com/blog?page=2") is False


class TestFastPath:
    def test_root_is_the_homepage(self):
        assert url_fast_path("https://e.com/") == (
            HierarchyLevel.L0_HOMEPAGE,
            PrimaryPageType.HOMEPAGE,
        )

    def test_root_with_tracking_is_still_the_homepage(self):
        assert url_fast_path("https://e.com/?utm_source=x") == (
            HierarchyLevel.L0_HOMEPAGE,
            PrimaryPageType.HOMEPAGE,
        )

    def test_root_with_a_search_query_is_not_the_homepage(self):
        """`/?s=query` is a search results page wearing the root path."""
        level, page_type = url_fast_path("https://e.com/?s=widgets")
        assert level is HierarchyLevel.UTILITY_PAGE
        assert page_type is PrimaryPageType.FACETED_FILTER

    @pytest.mark.parametrize(
        "url",
        [
            "https://e.com/privacy-policy/",
            "https://e.com/terms-of-service/",
            "https://e.com/cookie-policy/",
            "https://e.com/de/impressum/",
        ],
    )
    def test_legal_pages_resolve_instantly(self, url):
        assert url_fast_path(url) == (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.UTILITY_LEGAL)

    def test_faceted_url_resolves_instantly(self):
        assert url_fast_path("https://e.com/shop?color=red&size=xl") == (
            HierarchyLevel.UTILITY_PAGE,
            PrimaryPageType.FACETED_FILTER,
        )

    def test_beyond_depth_ceiling_is_a_crawl_trap(self):
        deep = "https://e.com/" + "/".join(str(i) for i in range(20)) + "/"
        assert url_fast_path(deep) == (
            HierarchyLevel.UTILITY_PAGE,
            PrimaryPageType.FACETED_FILTER,
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://e.com/software/order-to-cash/",
            "https://e.com/capsules",
            "https://e.com/resources/blog/some-post/",
        ],
    )
    def test_stays_silent_on_ambiguous_urls(self, url):
        """Layer 0 must not guess. A wrong answer here is never revisited."""
        assert url_fast_path(url) is None


class TestUnsplittableUrls:
    """`urlsplit` raises on inputs a crawler really does meet.

    An unbalanced bracket gives "Invalid IPv6 URL"; a bracketed host that is
    not a valid IP fails `_check_bracketed_host`. Both are 3.11 hardening.

    `normalize_url` runs on every URL entering the graph, so one such link on
    any page failed the whole crawl — observed live on highradius.com, which
    reported "Invalid IPv6 URL" and produced nothing.
    """

    @pytest.mark.parametrize(
        "hostile",
        [
            "http://[abc",
            "http://[invalid-ipv6]/",
            "http://[::1",
            "https://e.com/ok/][",
        ],
    )
    def test_normalize_url_does_not_raise(self, hostile):
        assert isinstance(normalize_url(hostile), str)

    def test_an_unparseable_url_keeps_a_stable_identity(self):
        """Returned as-is so the graph can still key on it and report it."""
        assert normalize_url("  http://[abc  ") == "http://[abc"

    @pytest.mark.parametrize("hostile", ["http://[abc", "http://[invalid-ipv6]/"])
    def test_faceted_filter_does_not_raise(self, hostile):
        assert is_faceted_filter(hostile) is False

    def test_safe_split_reports_failure_rather_than_raising(self):
        assert safe_split("http://[abc") is None
        assert safe_split("https://e.com/a/") is not None

    def test_a_valid_url_is_unaffected(self):
        """The guard must not change parsing for anything well-formed."""
        assert normalize_url("https://e.com/a/?utm_source=x") == "https://e.com/a/"


class TestIsCrawlableUrl:
    """Whether a URL addresses an HTML page or a file.

    The filter itself predates this class — it screened DOM links from the
    start. What it never screened was the sitemap and CMS paths, so a WordPress
    `attachment-sitemap.xml` put every uploaded image into the graph as a page.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://e.com/wp-content/uploads/2024/01/hero.jpg",
            "https://e.com/logo.PNG",
            "https://e.com/a/b/icon.svg",
            "https://e.com/bundle.js",
            "https://e.com/theme.css",
            "https://e.com/demo.mp4",
            "https://e.com/press-kit.zip",
            "https://e.com/font.woff2",
        ],
    )
    def test_media_is_refused(self, url):
        assert is_crawlable_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            "https://e.com/",
            "https://e.com/services/",
            # Dots inside a path segment are not extensions. An API version
            # prefix is the common case and dropping it would delete a section.
            "https://e.com/v1.0/details",
            "https://e.com/v1.0/details/",
            "https://e.com/index.html",
            "https://e.com/page.php",
            "https://e.com/default.aspx",
            "https://e.com/about.htm",
            # `.txt` stays: `llms.txt` is a Phase 7 input.
            "https://e.com/llms.txt",
            # `.pdf` stays: a whitepaper is a ranking asset.
            "https://e.com/whitepaper.pdf",
        ],
    )
    def test_pages_are_kept(self, url):
        assert is_crawlable_url(url) is True

    def test_only_the_path_is_examined(self):
        """A query string must not be mistaken for an extension, or the reverse."""
        assert is_crawlable_url("https://e.com/download?file=report.jpg") is True
        assert is_crawlable_url("https://e.com/hero.jpg?w=800") is False

    def test_an_unparseable_url_is_not_refused_here(self):
        """It is not media, and it should reach the reporting that surfaces it."""
        assert is_crawlable_url("http://[abc") is True
