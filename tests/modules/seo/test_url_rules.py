"""Tests for Layer 0 URL normalisation and pre-fetch classification."""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.schemas import (
    MAX_CRAWL_DEPTH,
    HierarchyLevel,
    PrimaryPageType,
)
from src.modules.seo.page_classifier.url_rules import (
    decode_percent_escapes,
    depth_of,
    is_crawlable_url,
    is_faceted_filter,
    is_malformed_url,
    is_spider_trap,
    is_tracking_param,
    normalize_path,
    normalize_url,
    safe_split,
    same_site,
    site_host,
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
        # `www.` is folded out of the dedup key — see `TestHostVariantFolding`.
        assert normalize_url(raw) == "https://amazon.com/dp/b0001234/?color=red&size=xl"

    def test_locale_variants_are_distinct_pages(self):
        """`/de/pricing/` is a URL Google indexes and ranks on its own.

        Folding them was the original default and it cost real reporting: on
        highradius.com `/de/software/order-to-cash/` shared a key with the
        English page, so the surviving node's language depended on which variant
        was crawled first — a German `Startseite` root inside an English tree.
        """
        assert normalize_url("https://e.com/de/software/") != normalize_url(
            "https://e.com/software/"
        )

    def test_locale_folding_is_still_available(self):
        """Kept for the different question: duplicate *content* across locales."""
        assert normalize_url("https://e.com/de/x/", strip_locale=True) == normalize_url(
            "https://e.com/x/"
        )

    def test_trailing_slash_is_unified(self):
        assert normalize_url("https://e.com/a/b") == normalize_url("https://e.com/a/b/")

    def test_host_variants_share_one_key(self):
        """One page served four ways was becoming four graph nodes.

        On highradius.com that split `/resources/?ps=templates` into three
        separate nodes with three different trails, and left 11 header-menu
        links unmatchable against the page set.
        """
        keys = {
            normalize_url("https://www.e.com/a/"),
            normalize_url("https://e.com/a/"),
            normalize_url("http://e.com/a/"),
            normalize_url("http://www.e.com/a/"),
        }
        assert len(keys) == 1

    def test_other_subdomains_are_not_folded(self):
        """`blog.e.com` is a different property; merging it loses a real one."""
        assert normalize_url("https://blog.e.com/a/") != normalize_url("https://e.com/a/")

    def test_a_host_merely_starting_with_www_is_untouched(self):
        assert "wwwx.e.com" in normalize_url("https://wwwx.e.com/a/")

    def test_the_port_is_kept(self):
        """`site_host` drops it for same-site comparison; a dedup key must not.

        `localhost:8000` and `localhost:9000` are different servers, and fixture
        crawls run against both.
        """
        assert normalize_url("http://localhost:8000/a/") != normalize_url(
            "http://localhost:9000/a/"
        )

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
            # Design sources. WordPress media libraries publish these into
            # `attachment-sitemap.xml` beside the images.
            "https://e.com/uploads/logo.eps",
            "https://e.com/uploads/brand.ai",
            "https://e.com/uploads/mockup.psd",
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
            # Documents stay: a whitepaper is an indexable B2B asset, ruled on
            # by the operator in cycle 0020.
            "https://e.com/whitepaper.pdf",
            "https://e.com/datasheet.docx",
            "https://e.com/pricing.xlsx",
            "https://e.com/deck.pptx",
            # `.ai` as a *section*, not a file. These must survive: an AI
            # practice page is exactly the sort of thing this site publishes.
            "https://e.com/ai/",
            "https://e.com/solutions/ai/",
            "https://e.com/solutions/ai",
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


class TestSameSite:
    """`www` is a serving convention, not a different site.

    An exact host comparison made a crawl seeded at the bare host discard every
    absolute link on its own homepage — most sites emit `www`-qualified ones —
    and report a one-page site.
    """

    @pytest.mark.parametrize(
        ("netloc", "expected"),
        [
            ("www.example.com", "example.com"),
            ("example.com", "example.com"),
            ("WWW.Example.COM", "example.com"),
            ("example.com:8443", "example.com"),
            ("user:pw@www.example.com", "example.com"),
            ("[::1]:8000", "[::1]"),
            # Not a `www.` prefix, and must not be truncated as one.
            ("wwwx.example.com", "wwwx.example.com"),
        ],
    )
    def test_site_host(self, netloc, expected):
        assert site_host(netloc) == expected

    def test_www_and_bare_host_are_one_site(self):
        assert same_site("https://e.com/a/", "https://www.e.com/b/") is True

    def test_other_subdomains_stay_separate(self):
        """Folding them would turn a bounded crawl into an unbounded one."""
        assert same_site("https://e.com/a/", "https://blog.e.com/b/") is False
        assert same_site("https://www.e.com/a/", "https://shop.e.com/b/") is False

    def test_different_domains_are_not_the_same_site(self):
        assert same_site("https://e.com/a/", "https://other.com/a/") is False

    def test_scheme_and_port_do_not_split_a_site(self):
        assert same_site("http://e.com/a/", "https://e.com:443/b/") is True

    def test_an_unparseable_url_matches_nothing(self):
        assert same_site("http://[abc", "https://e.com/") is False
        assert same_site("http://[abc", "http://[abc") is False


class TestSpiderTrap:
    """Self-referential loops from relative hrefs.

    Every URL below is real, taken from stored crawls. The heuristic was chosen
    by measuring it against 55,645 URLs from six sites: it flagged 21,242 of
    33,447 on highradius.com, 11 of 17,458 on infosys.com, and none at all on
    rankuno.com, gep.com or caeliusconsulting.com. Each of the 11 infosys hits
    was itself malformed, so the measured false-positive count was zero.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # The originating bug: `href="software/b2b-payments/..."` with no
            # leading slash, resolving one level deeper on every hop.
            "https://www.highradius.com/resources/Blog/b2b-payments"
            "/software/b2b-payments/credit-card-surcharge/",
            "http://www.highradius.com/product/financial-reporting/software"
            "/record-to-report/software/record-to-report/financial-reporting",
            # A doubled locale prefix.
            "https://www.highradius.com/en-gb/en-gb/value-creation/konica-minolta-treasury/",
            # A doubled listing segment.
            "https://www.highradius.com/resources/templates/templates/",
            # A truncated href produced this on infosys.com.
            "https://www.infosys.com/content/infosys-web/en/content/infosys-web/en/services/cloud",
        ],
    )
    def test_real_traps_are_refused(self, url):
        assert is_spider_trap(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://e.com/",
            "https://www.highradius.com/software/order-to-cash/credit-cloud/",
            "https://www.gep.com/software/procurement/source-to-pay/",
            "https://www.infosys.com/services/engineering-services/insights/",
            # Short segments recur legitimately and must not count: a locale
            # under a locale-scoped section, an `lp` landing-page prefix.
            "https://e.com/en/products/en/",
            "https://e.com/lp/demo/lp/",
            # Distinct segments that merely share a prefix are not repeats.
            "https://e.com/blog/blog-post-title/",
            "https://e.com/press/press-releases/press-release-2026/",
        ],
    )
    def test_real_pages_are_kept(self, url):
        assert is_spider_trap(url) is False

    def test_depth_ceiling_is_the_shared_constant(self):
        """Reuses `MAX_CRAWL_DEPTH` so a second ceiling cannot drift from it."""
        deep = "https://e.com/" + "/".join(f"s{i}" for i in range(MAX_CRAWL_DEPTH + 1)) + "/"
        assert is_spider_trap(deep) is True
        shallow = "https://e.com/" + "/".join(f"s{i}" for i in range(MAX_CRAWL_DEPTH)) + "/"
        assert is_spider_trap(shallow) is False

    def test_repetition_is_case_insensitive(self):
        """`/Blog/blog/` is the same segment twice however it was cased."""
        assert is_spider_trap("https://e.com/Templates/templates/") is True

    def test_an_unparseable_url_is_not_blamed_on_a_trap(self):
        """`safe_split` already reports it; this must not misattribute it."""
        assert is_spider_trap("http://[abc") is False


class TestIsMalformedUrl:
    """URLs fabricated by broken markup, refused before they become nodes.

    The hard part is not catching them, it is *not* catching legitimate URLs
    that happen to contain whitespace. Measured across 65 stored crawls and
    392,835 URLs: 387 carry whitespace inside a real filename, and every one of
    them must survive.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # `href=" blog/post/"` — the space survived into a sitemap <loc>.
            "https://kinsta.com/ blog/disk-usage-wordpress/",
            "https://kinsta.com/%20blog/how-to-install-a-wordpress-theme/",
            # A protocol-relative href with a leading space, folded into a path.
            "https://kinsta.com/%20/abookin.com/plugins/booking-calendar/",
            # Unclosed anchor.
            "https://www.highradius.com/about/news/livecube/<a href=",
            # Documentation placeholders published as links.
            "https://www.gep.com/<nolink>",
            "https://linear.app/team/%3Cteam%20ID%3E/new",
            # A curly quote for `"` swallowed a paragraph of body copy.
            "https://kinsta.com/blog/x/%E2%80%9C>MailChimp</a>%20per%20potenziare",
            "https://kinsta.com/blog/shopify-alternatives/%E2%80%9D",
        ],
    )
    def test_markup_artefacts_are_refused(self, url):
        assert is_malformed_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Real published reports. Spaces are part of the filename, and
            # refusing these deletes indexable assets from the audit.
            "https://www.infosys.com/dam/pdf/Infosys ESG - climate change.pdf",
            "https://www.infosys.com/x/digital%20bank%20in%20a%20bank_icici%20bank.pdf",
            "https://www.gep.com/blog/tech/why-data-fragmentation-limits%20-agentic",
            # Ordinary pages.
            "https://e.com/",
            "https://e.com/blog/normal-page/",
            "https://e.com/v1.0/details",
        ],
    )
    def test_legitimate_urls_survive(self, url):
        assert is_malformed_url(url) is False

    def test_only_a_leading_space_is_refused_not_an_interior_one(self):
        """The whole discriminator, stated as one pair.

        A path cannot begin with a space; a filename routinely contains one.
        """
        assert is_malformed_url("https://e.com/ a/b.pdf") is True
        assert is_malformed_url("https://e.com/a/my file.pdf") is False

    def test_the_query_string_is_not_examined(self):
        """A comparison operator in a query is not broken markup."""
        assert is_malformed_url("https://e.com/search?q=a<b") is False

    def test_encoded_and_raw_markers_are_the_same_thing(self):
        assert is_malformed_url("https://e.com/%3Cnolink%3E") is True
        assert is_malformed_url("https://e.com/<nolink>") is True

    def test_an_unparseable_url_is_not_claimed_here(self):
        """`safe_split` refuses it earlier; claiming it would misattribute it."""
        assert is_malformed_url("http://[abc") is False


class TestPercentEscapeDecoding:
    """One address spelled two ways is one page.

    RFC 3986 §6.2.2.2. Reported from a live gep.com audit, where the same blog
    post appeared under a percent-encoded and a raw non-breaking hyphen and was
    published to the client as a duplicate-content defect on their site.
    """

    def test_the_gep_pair_lands_on_one_key(self):
        encoded = "https://www.gep.com/blog/technology/procurement%E2%80%91ai%E2%80%91agents"
        raw = "https://www.gep.com/blog/technology/procurement\u2011ai\u2011agents"
        assert normalize_url(encoded) == normalize_url(raw)

    def test_a_multi_byte_sequence_decodes_whole(self):
        """The trap that made an earlier attempt at this a no-op.

        `%E2%80%91` is three octets of one character. Decoding escape by escape
        yields replacement characters and quietly corrupts the key it was meant
        to repair, while still appearing to do something.
        """
        assert decode_percent_escapes("/a%E2%80%91b") == "/a\u2011b"
        assert "\ufffd" not in decode_percent_escapes("/a%E2%80%91b")

    def test_encoded_unreserved_ascii_folds(self):
        """`%6D%79` is `my`. Observed on kinsta.com."""
        assert normalize_url("https://kinsta.com/%6D%79%6B%69%6E%73%74%61/") == normalize_url(
            "https://kinsta.com/mykinsta/"
        )

    def test_an_encoded_slash_is_not_a_separator(self):
        """The reason decoding cannot be blanket.

        `/a%2Fb` is one segment containing a slash and `/a/b` is two. Folding
        them would merge two different addresses onto one node.
        """
        assert normalize_url("https://e.com/a%2Fb/") != normalize_url("https://e.com/a/b/")

    def test_the_escape_character_itself_is_preserved(self):
        """`%2520` must decode once to `%20`, never twice to a space."""
        assert decode_percent_escapes("/a%2520b") == "/a%2520b"

    def test_invalid_utf8_is_left_encoded_rather_than_replaced(self):
        """Distinct broken URLs must stay distinct.

        `errors="replace"` would map every undecodable sequence onto U+FFFD and
        collapse unrelated URLs onto one key.
        """
        assert decode_percent_escapes("/bad%FF%FE/") == "/bad%FF%FE/"
        assert normalize_url("https://e.com/bad%FF/") != normalize_url("https://e.com/bad%FE/")

    def test_a_decoded_trailing_space_does_not_fork_a_page(self):
        """Observed on backlinko.com: `/x%20` and `/x` are one page."""
        assert normalize_url("https://backlinko.com/youtube-ranking-factors%20") == normalize_url(
            "https://backlinko.com/youtube-ranking-factors"
        )

    def test_an_interior_space_is_part_of_the_filename(self):
        """Whitespace inside a segment is real and must survive.

        387 URLs across the stored corpus carry a space that belongs to a
        published filename — `Infosys ESG - climate change.pdf` among them.
        Stripping whitespace anywhere but the segment edges would delete them.
        """
        assert normalize_path("/pdf/Infosys%20ESG%20-%20climate%20change.pdf") == (
            "/pdf/infosys esg - climate change.pdf/"
        )

    def test_a_path_with_no_escapes_is_untouched(self):
        """The overwhelmingly common case must cost nothing and change nothing."""
        assert decode_percent_escapes("/blog/post/") == "/blog/post/"
        assert normalize_url("https://e.com/blog/post/") == "https://e.com/blog/post/"

    def test_the_menu_matcher_agrees_with_the_page_key(self):
        """`_path_key` and `normalize_url` both go through `normalize_path`.

        A menu href spelled one way and a crawled URL spelled the other would
        otherwise fail to match, and the page would lose its navigation
        placement for a reason invisible in the report.
        """
        assert normalize_path("/a%E2%80%91b") == normalize_path("/a‑b")
