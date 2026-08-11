"""Tests for the safety-wired HTTP fetcher.

Every test runs against `httpx.MockTransport`. No socket is opened, so the
SSRF, robots and redirect rules are exercised exhaustively and deterministically.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from src.core.errors import IntegrationError, RobotsDisallowedError, UnsafeUrlError
from src.core.robots import DEFAULT_USER_AGENT
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import (
    BROWSER_USER_AGENT,
    FetchResult,
    HttpFetcher,
)

PUBLIC_IP = "93.184.216.34"

ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"
ROBOTS_DENY_PRIVATE = "User-agent: *\nDisallow: /private/\n"


def route_map(paths: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Build a transport answering by exact path, 404 for anything unmapped."""

    def handler(request: httpx.Request) -> httpx.Response:
        return paths.get(request.url.path, httpx.Response(404, text="not found"))

    return httpx.MockTransport(handler)


def policy(mapping: dict[str, list[str]] | None = None) -> UrlSafetyPolicy:
    """Build an SSRF policy with a stubbed resolver."""
    table = mapping or {}

    def resolver(host: str) -> list[str]:
        return table.get(host, [PUBLIC_IP])

    return UrlSafetyPolicy(resolver=resolver)


def make_fetcher(transport: httpx.MockTransport, settings, **kwargs: Any) -> HttpFetcher:
    """Build a sync-path fetcher wired to a mock transport."""
    kwargs.setdefault("url_policy", policy())
    return HttpFetcher(settings=settings, transport=transport, **kwargs)


def make_async_fetcher(transport: httpx.MockTransport, settings, **kwargs: Any) -> HttpFetcher:
    """Build an async-path fetcher wired to a mock transport."""
    kwargs.setdefault("url_policy", policy())
    return HttpFetcher(settings=settings, async_transport=transport, **kwargs)


class TestBasicFetch:
    def test_fetches_and_reports_status(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/page": httpx.Response(
                    200, text="<html>hi</html>", headers={"content-type": "text/html"}
                ),
            }
        )
        result = make_fetcher(transport, settings).fetch("https://e.com/page")
        assert isinstance(result, FetchResult)
        assert result.ok is True
        assert result.status_code == 200
        assert result.body == "<html>hi</html>"
        assert result.is_html is True

    def test_reports_non_2xx_without_raising(self, settings):
        transport = route_map({"/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL)})
        result = make_fetcher(transport, settings).fetch("https://e.com/missing")
        assert result.ok is False
        assert result.status_code == 404

    def test_normalises_content_type(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/page": httpx.Response(
                    200, text="x", headers={"content-type": "TEXT/HTML; charset=utf-8"}
                ),
            }
        )
        result = make_fetcher(transport, settings).fetch("https://e.com/page")
        assert result.content_type == "text/html"

    def test_truncates_an_oversized_body(self, settings):
        """A 2 GB response would take out a 512 MB worker."""
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/big": httpx.Response(200, text="x" * 5000),
            }
        )
        result = make_fetcher(transport, settings, max_body_bytes=100).fetch("https://e.com/big")
        assert result.truncated is True
        assert len(result.body) == 100


class TestSsrfEnforcement:
    def test_refuses_a_private_target(self, settings):
        with pytest.raises(UnsafeUrlError):
            make_fetcher(route_map({}), settings).fetch("http://192.168.0.1/")

    def test_refuses_a_non_web_scheme(self, settings):
        with pytest.raises(UnsafeUrlError, match="scheme"):
            make_fetcher(route_map({}), settings).fetch("file:///etc/passwd")

    def test_refuses_metadata_endpoint(self, settings):
        with pytest.raises(UnsafeUrlError):
            make_fetcher(route_map({}), settings).fetch("http://169.254.169.254/latest/meta-data/")

    def test_never_opens_a_socket_for_a_refused_url(self, settings):
        """Validation must precede transport, not follow it."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, text="")

        with pytest.raises(UnsafeUrlError):
            make_fetcher(httpx.MockTransport(handler), settings).fetch("http://127.0.0.1/")
        assert calls == []


class TestRedirectSafety:
    def test_follows_a_safe_redirect(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/old": httpx.Response(301, headers={"location": "https://e.com/new"}),
                "/new": httpx.Response(200, text="arrived"),
            }
        )
        result = make_fetcher(transport, settings).fetch("https://e.com/old")
        assert result.body == "arrived"
        assert result.redirect_chain == ("https://e.com/old",)
        assert result.final_url == "https://e.com/new"

    def test_refuses_a_redirect_to_an_internal_address(self, settings):
        """The bypass that `follow_redirects=True` would hand an attacker."""
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/bait": httpx.Response(302, headers={"location": "http://169.254.169.254/"}),
            }
        )
        with pytest.raises(UnsafeUrlError):
            make_fetcher(transport, settings).fetch("https://e.com/bait")

    def test_bounds_a_redirect_loop(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/loop": httpx.Response(302, headers={"location": "https://e.com/loop"}),
            }
        )
        with pytest.raises(IntegrationError, match="too many redirects"):
            make_fetcher(transport, settings, max_redirects=2).fetch("https://e.com/loop")


class TestRobotsEnforcement:
    def test_refuses_a_disallowed_path(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_DENY_PRIVATE),
                "/private/page": httpx.Response(200, text="secret"),
            }
        )
        with pytest.raises(RobotsDisallowedError):
            make_fetcher(transport, settings).fetch("https://e.com/private/page")

    def test_allows_a_permitted_path(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_DENY_PRIVATE),
                "/public": httpx.Response(200, text="fine"),
            }
        )
        assert make_fetcher(transport, settings).fetch("https://e.com/public").body == "fine"

    def test_robots_is_fetched_once_per_host(self, settings):
        """Re-fetching robots.txt per page would double every crawl."""
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(request.url.path)
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(200, text="ok")

        fetcher = make_fetcher(httpx.MockTransport(handler), settings)
        for index in range(3):
            fetcher.fetch(f"https://e.com/page{index}")
        assert hits.count("/robots.txt") == 1

    def test_unreachable_robots_means_no_rules(self, settings):
        """RFC 9309: a 500 on robots.txt must not block an entire site."""
        transport = route_map(
            {
                "/robots.txt": httpx.Response(500, text="boom"),
                "/page": httpx.Response(200, text="allowed anyway"),
            }
        )
        assert make_fetcher(transport, settings).fetch("https://e.com/page").ok is True

    def test_robots_can_be_disabled_for_owned_sites(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /\n"),
                "/page": httpx.Response(200, text="fetched"),
            }
        )
        fetcher = make_fetcher(transport, settings, respect_robots=False)
        assert fetcher.fetch("https://e.com/page").body == "fetched"


class TestEventLoopSafety:
    def test_sync_fetch_refuses_to_run_inside_a_loop(self, settings):
        """The deadlock guard: blocking here would stall every other request."""
        transport = route_map({"/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL)})
        fetcher = make_fetcher(transport, settings)

        async def scenario() -> None:
            fetcher.fetch("https://e.com/page")

        with pytest.raises(RuntimeError, match="afetch"):
            asyncio.run(scenario())

    def test_async_fetch_works_inside_a_loop(self, settings):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(200, text="async ok")

        async def scenario() -> str:
            async with make_async_fetcher(httpx.MockTransport(handler), settings) as fetcher:
                result = await fetcher.afetch("https://e.com/page")
                return result.body

        assert asyncio.run(scenario()) == "async ok"

    def test_async_path_enforces_ssrf_too(self, settings):
        transport = httpx.MockTransport(lambda request: httpx.Response(200))

        async def scenario() -> None:
            async with make_async_fetcher(transport, settings) as fetcher:
                await fetcher.afetch("http://10.0.0.1/")

        with pytest.raises(UnsafeUrlError):
            asyncio.run(scenario())

    def test_async_path_enforces_robots_too(self, settings):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_DENY_PRIVATE)
            return httpx.Response(200, text="secret")

        async def scenario() -> None:
            async with make_async_fetcher(httpx.MockTransport(handler), settings) as fetcher:
                await fetcher.afetch("https://e.com/private/x")

        with pytest.raises(RobotsDisallowedError):
            asyncio.run(scenario())

    def test_async_path_re_validates_redirects(self, settings):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"})

        async def scenario() -> None:
            async with make_async_fetcher(httpx.MockTransport(handler), settings) as fetcher:
                await fetcher.afetch("https://e.com/bait")

        with pytest.raises(UnsafeUrlError):
            asyncio.run(scenario())


class TestLifecycle:
    def test_sync_context_manager_closes_cleanly(self, settings):
        transport = route_map(
            {
                "/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL),
                "/page": httpx.Response(200, text="ok"),
            }
        )
        with make_fetcher(transport, settings) as fetcher:
            assert fetcher.fetch("https://e.com/page").ok is True

    def test_close_is_idempotent(self, settings):
        fetcher = make_fetcher(route_map({}), settings)
        fetcher.close()
        fetcher.close()

    def test_declares_the_base_client_contract(self):
        """Inherited from BaseAPIClient; a connector without these is a defect."""
        assert HttpFetcher.service_name == "web.fetch"
        assert HttpFetcher.rate_limit_key == "web.fetch"

    def test_authenticate_is_a_noop_for_the_public_web(self, settings):
        assert make_fetcher(route_map({}), settings).authenticate() is None


class TestBrowserHeaders:
    """`browser_headers` has to change the product token, not just `Accept`.

    An edge that filters by user agent — which is every edge this option exists
    for — is unaffected by `Accept` headers alone. Shipped without this, the
    option was unreachable: `BROWSER_USER_AGENT` was defined, exported, and
    referenced by nothing.
    """

    def test_off_by_default(self, settings):
        fetcher = HttpFetcher(
            settings=settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
        )
        assert fetcher._headers()["User-Agent"] == DEFAULT_USER_AGENT
        assert "Accept-Language" not in fetcher._headers()

    def test_sends_a_browser_token(self, settings):
        fetcher = HttpFetcher(
            settings=settings,
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._headers()["User-Agent"] == BROWSER_USER_AGENT

    def test_sends_browser_accept_headers(self, settings):
        fetcher = HttpFetcher(
            settings=settings,
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        headers = fetcher._headers()
        assert "text/html" in headers["Accept"]
        assert headers["Accept-Language"].startswith("en")

    def test_an_explicit_user_agent_wins(self, settings):
        """An operator who named an identity meant it.

        Silently replacing it would make the audit log disagree with what was
        actually sent.
        """
        fetcher = HttpFetcher(
            settings=settings,
            user_agent="AcmeAudit/1.0 (+https://acme.test/bot)",
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._headers()["User-Agent"] == "AcmeAudit/1.0 (+https://acme.test/bot)"

    def test_robots_is_matched_against_the_token_actually_sent(self, settings):
        """Presenting one identity and obeying another's rules is incoherent."""
        fetcher = HttpFetcher(
            settings=settings,
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._user_agent == BROWSER_USER_AGENT

    def test_robots_compliance_is_not_relaxed(self, settings):
        fetcher = HttpFetcher(
            settings=settings,
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._respect_robots is True
