"""Tests for the site-profile probe pass.

Runs against `httpx.MockTransport`, so platform detection is exercised against
realistic response shapes without touching a live site.
"""

from __future__ import annotations

import httpx
import pytest
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.site_profile import (
    detect_client_side_rendering,
    locales_from_sitemaps,
    probe_site,
)
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

PUBLIC_IP = "93.184.216.34"
ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"

SERVER_RENDERED_HTML = (
    "<html><body><nav><a href='/services/'>Services</a></nav>"
    "<main><h1>Enterprise Order to Cash Automation</h1>"
    "<p>" + ("Real server rendered prose about invoicing. " * 12) + "</p></main></body></html>"
)

SPA_SHELL_HTML = (
    '<html><head><script src="/bundle.js"></script></head><body><div id="root"></div></body></html>'
)


def profiling_fetcher(routes: dict[str, httpx.Response], settings) -> HttpFetcher:
    """Build a fetcher answering the probe paths from a fixed table."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404, text="not found"))

    def resolver(host: str) -> list[str]:
        return [PUBLIC_IP]

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=resolver),
        transport=httpx.MockTransport(handler),
    )


def html_response(body: str) -> httpx.Response:
    """An HTML 200."""
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def json_response(payload: str = '{"ok": true}') -> httpx.Response:
    """A JSON 200."""
    return httpx.Response(200, text=payload, headers={"content-type": "application/json"})


class TestClientSideRenderingDetection:
    def test_spa_shell_is_detected(self):
        assert detect_client_side_rendering(SPA_SHELL_HTML) is True

    def test_server_rendered_page_is_not(self):
        assert detect_client_side_rendering(SERVER_RENDERED_HTML) is False

    def test_hydration_root_with_real_content_is_not_a_spa(self):
        """Plenty of server-rendered React sites keep a <div id="root">."""
        html = (
            '<html><body><div id="root"><h1>Widgets</h1><p>'
            + ("Server rendered content that a crawler can read. " * 10)
            + "</p></div></body></html>"
        )
        assert detect_client_side_rendering(html) is False

    def test_thin_page_without_a_hydration_root_is_not_a_spa(self):
        """A genuinely short page is not a SPA; both conditions must hold."""
        assert detect_client_side_rendering("<html><body><p>Short.</p></body></html>") is False

    def test_script_heavy_shell_still_counts_as_empty(self):
        """Script bodies must not be mistaken for readable content."""
        html = (
            '<html><body><div id="__next"></div>'
            "<script>" + ("var x = 1; " * 200) + "</script></body></html>"
        )
        assert detect_client_side_rendering(html) is True

    @pytest.mark.parametrize("root_id", ["root", "__next", "app", "__nuxt", "svelte"])
    def test_recognises_common_hydration_roots(self, root_id):
        html = f'<html><body><div id="{root_id}"></div></body></html>'
        assert detect_client_side_rendering(html) is True

    def test_empty_html_is_not_a_spa(self):
        assert detect_client_side_rendering("") is False


class TestLocaleExtraction:
    def test_extracts_locales_from_sitemap_urls(self):
        sitemaps = (
            "https://e.com/sitemap_index.xml",
            "https://e.com/de/sitemap.xml",
            "https://e.com/en-gb/sitemap.xml",
        )
        assert locales_from_sitemaps(sitemaps) == ("de", "en-gb")

    def test_ignores_content_segments_that_look_like_locales(self):
        """The /dp/ class of bug: shape alone must not imply a locale."""
        assert locales_from_sitemaps(("https://e.com/dp/sitemap.xml",)) == ()

    def test_no_locale_prefixes_yields_empty(self):
        assert locales_from_sitemaps(("https://e.com/sitemap.xml",)) == ()

    def test_deduplicates(self):
        sitemaps = ("https://e.com/de/a.xml", "https://e.com/de/b.xml")
        assert locales_from_sitemaps(sitemaps) == ("de",)


class TestPlatformDetection:
    def test_detects_wordpress(self, settings):
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/wp-json/wp/v2/types": json_response('{"post": {}, "page": {}}'),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.WORDPRESS
        assert profile.weight_profile_name == "wordpress"

    def test_detects_shopify(self, settings):
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/products.json": json_response('{"products": []}'),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.SHOPIFY
        assert profile.has_catalogue is True

    def test_detects_headless(self, settings):
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/": html_response(SPA_SHELL_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.HEADLESS
        assert profile.renders_client_side is True

    def test_unrecognised_platform_is_unknown(self, settings):
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.UNKNOWN
        assert profile.weight_profile_name == "default"

    def test_woocommerce_resolves_to_wordpress(self, settings):
        """A WooCommerce store answers both probes; /wp-json is the stronger."""
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/wp-json/wp/v2/types": json_response(),
                "/products.json": json_response('{"products": []}'),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.WORDPRESS
        assert profile.has_catalogue is True, "catalogue is still recorded"


class TestSoftFailureHandling:
    def test_html_error_page_is_not_a_positive_detection(self, settings):
        """Soft 404s are why detection parses the body instead of trusting 200."""
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/wp-json/wp/v2/types": httpx.Response(
                    200, text="<html>Page not found</html>", headers={"content-type": "text/html"}
                ),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        assert probe_site(fetcher, "https://e.com").cms_family is CmsFamily.UNKNOWN

    def test_blocked_probe_does_not_abort_profiling(self, settings):
        """A probe is a question, and 'no' is a valid answer."""
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /wp-json/\n"),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        profile = probe_site(fetcher, "https://e.com")
        assert isinstance(profile, SiteProfile)
        assert profile.cms_family is CmsFamily.UNKNOWN

    def test_total_probe_failure_still_returns_a_profile(self, settings):
        fetcher = profiling_fetcher({}, settings)
        profile = probe_site(fetcher, "https://e.com")
        assert profile.cms_family is CmsFamily.UNKNOWN
        assert profile.weight_profile_name == "default"

    def test_trailing_slash_in_base_url_is_tolerated(self, settings):
        routes = {
            "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
            "/wp-json/wp/v2/types": json_response(),
            "/": html_response(SERVER_RENDERED_HTML),
        }
        with_slash = probe_site(profiling_fetcher(routes, settings), "https://e.com/")
        without = probe_site(profiling_fetcher(routes, settings), "https://e.com")
        assert with_slash.cms_family is without.cms_family is CmsFamily.WORDPRESS


class TestLocaleDiscovery:
    def test_locales_come_from_the_sites_own_sitemaps(self, settings):
        """The site tells us its locales; we never guess from path shape."""
        robots = (
            "User-agent: *\nDisallow:\n"
            "Sitemap: https://e.com/sitemap_index.xml\n"
            "Sitemap: https://e.com/de/sitemap.xml\n"
        )
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=robots),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        assert probe_site(fetcher, "https://e.com").locale_prefixes == ("de",)


class TestSeamActivation:
    def test_probe_output_feeds_the_weight_seam(self, settings):
        """The point of this module: SiteProfile finally has a producer."""
        fetcher = profiling_fetcher(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/products.json": json_response('{"products": []}'),
                "/": html_response(SERVER_RENDERED_HTML),
            },
            settings,
        )
        from src.modules.seo.page_classifier.weights import get_weight_profile

        profile = probe_site(fetcher, "https://e.com")
        assert profile.weight_profile_name == "shopify"
        # Adaptive selection is still disabled, so the default vector applies.
        assert get_weight_profile(profile) == get_weight_profile(None)
