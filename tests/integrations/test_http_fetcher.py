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
from src.core.retry import with_async_retries
from src.core.robots import DEFAULT_USER_AGENT, RobotsTxt, parse_robots_txt
from src.core.url_safety import SafeUrl, UrlSafetyPolicy
from src.integrations.http_fetcher import (
    BROWSER_USER_AGENT,
    DEFAULT_MAX_CONNECTIONS,
    FETCH_RETRY_ON,
    MAX_CONNECTIONS,
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


class TestRobotsAccessor:
    """`robots_for()`/`arobots_for()` — the public window sitemap discovery reads."""

    ROBOTS_WITH_SITEMAPS = (
        "User-agent: *\nDisallow:\nSitemap: https://e.com/sitemap.xml\n"
        "Sitemap: https://e.com/news-sitemap.xml\n"
    )

    def test_returns_the_sitemap_lines(self, settings):
        transport = route_map({"/robots.txt": httpx.Response(200, text=self.ROBOTS_WITH_SITEMAPS)})
        robots = make_fetcher(transport, settings).robots_for("https://e.com/anything")
        assert robots.sitemaps == (
            "https://e.com/sitemap.xml",
            "https://e.com/news-sitemap.xml",
        )

    def test_reuses_the_cache_fetch_already_populated(self, settings):
        """No second request: the accessor must not open a parallel fetch path."""
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(request.url.path)
            return httpx.Response(200, text=self.ROBOTS_WITH_SITEMAPS)

        fetcher = make_fetcher(httpx.MockTransport(handler), settings)
        fetcher.fetch("https://e.com/page")  # populates the cache
        fetcher.robots_for("https://e.com/other")
        assert hits.count("/robots.txt") == 1

    def test_an_unreachable_robots_yields_no_sitemaps(self, settings):
        transport = route_map({"/robots.txt": httpx.Response(500)})
        robots = make_fetcher(transport, settings).robots_for("https://e.com")
        assert robots.sitemaps == ()

    def test_async_accessor_returns_the_sitemap_lines(self, settings):
        transport = route_map({"/robots.txt": httpx.Response(200, text=self.ROBOTS_WITH_SITEMAPS)})
        fetcher = make_async_fetcher(transport, settings)

        async def scenario() -> tuple[str, ...]:
            async with fetcher:
                robots = await fetcher.arobots_for("https://e.com/anything")
                return robots.sitemaps

        assert asyncio.run(scenario()) == (
            "https://e.com/sitemap.xml",
            "https://e.com/news-sitemap.xml",
        )

    def test_sync_accessor_refuses_to_run_inside_a_loop(self, settings):
        transport = route_map({"/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW_ALL)})
        fetcher = make_fetcher(transport, settings)

        async def scenario() -> None:
            fetcher.robots_for("https://e.com")

        with pytest.raises(RuntimeError, match="afetch"):
            asyncio.run(scenario())


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

    @pytest.mark.parametrize("blank", ["", "   ", "	"])
    def test_a_blank_token_is_treated_as_unset(self, settings, blank):
        """Blank means "not named", so browser mode substitutes as it should.

        `PageClassificationInput` enforces `min_length=1`, but this class is
        constructed directly by scripts and by future callers. An empty token
        used to reach the wire verbatim: browser mode was requested and the
        equality test against the default did not match, so the crawl went out
        with an empty `User-Agent` — which edges reject on sight, and which is
        the opposite of what asking for browser mode means.
        """
        fetcher = HttpFetcher(
            settings=settings,
            user_agent=blank,
            browser_headers=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._headers()["User-Agent"] == BROWSER_USER_AGENT

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_token_never_reaches_the_wire(self, settings, blank):
        """Even without browser mode. No header at all is worse than any value.

        An empty `User-Agent` is also unmatchable against robots.txt, so a crawl
        sending one cannot honestly claim to be obeying it.
        """
        fetcher = HttpFetcher(
            settings=settings,
            user_agent=blank,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._headers()["User-Agent"] == DEFAULT_USER_AGENT

    def test_surrounding_whitespace_is_trimmed_from_a_named_token(self, settings):
        """A pasted token carries whitespace; the wire should not."""
        fetcher = HttpFetcher(
            settings=settings,
            user_agent="  AcmeAudit/1.0  ",
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._headers()["User-Agent"] == "AcmeAudit/1.0"


class TestRateLimitReconciliation:
    """A declared `Crawl-delay` and a configured rate combine with `min`.

    Both directions matter. A site asking to be crawled slowly must never be
    sped up by a Turbo setting — that is the instruction robots.txt exists to
    carry. And a site permitting speed must not override a deliberately polite
    choice, or "Polite" would crawl ten times faster than the operator asked on
    any host declaring `Crawl-delay: 0.1`.
    """

    @staticmethod
    def _fetcher(settings, **kwargs: object) -> HttpFetcher:
        """A fetcher whose transport never touches the network."""
        return HttpFetcher(
            settings=settings,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
            **kwargs,
        )

    def test_the_configured_rate_applies_with_no_declared_delay(self, settings):
        fetcher = self._fetcher(settings, rate_limit_rps=25.0)
        assert fetcher._host_rpm(RobotsTxt()) == 1500

    def test_a_slower_crawl_delay_wins_over_a_faster_setting(self, settings):
        """The site said 10 seconds between requests. Turbo does not get a vote."""
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: 10\n")
        fetcher = self._fetcher(settings, rate_limit_rps=25.0)
        assert fetcher._host_rpm(robots) == 6

    def test_a_faster_crawl_delay_does_not_override_a_polite_setting(self, settings):
        """`Crawl-delay: 0.1` permits 10 rps; a 1 rps choice must still hold."""
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: 0.1\n")
        fetcher = self._fetcher(settings, rate_limit_rps=1.0)
        assert fetcher._host_rpm(robots) == 60

    def test_the_default_applies_when_nothing_is_configured(self, settings):
        fetcher = self._fetcher(settings)
        assert fetcher._host_rpm(RobotsTxt()) == settings.default_requests_per_minute

    def test_the_rate_never_falls_below_one_per_minute(self, settings):
        """A rate of zero would stall the crawl rather than slow it."""
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: 3600\n")
        assert self._fetcher(settings, rate_limit_rps=25.0)._host_rpm(robots) >= 1


class TestConnectionPool:
    def test_the_pool_defaults_to_the_documented_size(self, settings):
        fetcher = HttpFetcher(
            settings=settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
        )
        assert fetcher._max_connections == DEFAULT_MAX_CONNECTIONS

    def test_the_pool_can_be_sized_to_the_crawl(self, settings):
        """Below the worker count, requests queue on sockets not on the limiter."""
        fetcher = HttpFetcher(
            settings=settings,
            max_connections=50,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._max_connections == 50

    def test_an_absurd_pool_request_is_capped(self, settings):
        """Sockets are finite; asking for thousands is a mistake, not a choice."""
        fetcher = HttpFetcher(
            settings=settings,
            max_connections=100_000,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        assert fetcher._max_connections == MAX_CONNECTIONS


class _StubNetworkStream:
    """Duck-typed the same way `_peer_address` already treats its input."""

    def __init__(self, peer_ip: str, port: int = 443) -> None:
        self._peer_ip = peer_ip
        self._port = port

    def get_extra_info(self, name: str) -> tuple[str, int] | None:
        if name == "server_addr":
            return (self._peer_ip, self._port)
        return None


def _peer_response(peer_ip: str) -> httpx.Response:
    """A response reporting a specific connected peer, no real socket involved."""
    return httpx.Response(200, extensions={"network_stream": _StubNetworkStream(peer_ip)})


def _safe_url(*resolved_ips: str, host: str = "e.com") -> SafeUrl:
    return SafeUrl(
        original=f"https://{host}/",
        url=f"https://{host}/",
        scheme="https",
        host=host,
        port=443,
        resolved_ips=resolved_ips,
    )


class TestVerifyPeer:
    """`_verify_peer` refuses a peer that classifies as unsafe.

    Not merely one absent from the validation snapshot.

    Observed live: job 0f69b80025874d30b57f54de33b8f705 (infosys.com) hit an
    exact-match failure against a CDN's own address rotation — a public peer
    that simply was not in the validated snapshot — and was refused as if it
    were DNS rebinding. A mismatch is only evidence of an attack when the
    connected peer itself classifies as unsafe (private, loopback, link-local,
    reserved). See the docstring on `_verify_peer` itself.
    """

    @staticmethod
    def _fetcher(settings) -> HttpFetcher:
        """A fetcher whose transport is never actually exercised by these tests."""
        return HttpFetcher(
            settings=settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
        )

    def test_an_exact_match_takes_the_fast_path(self, settings, monkeypatch):
        """The common case never needs to classify anything."""
        calls: list[str] = []
        monkeypatch.setattr(
            "src.integrations.http_fetcher.describe_ip_block",
            lambda addr: calls.append(addr),
        )
        fetcher = self._fetcher(settings)
        safe = _safe_url("93.184.216.1")

        fetcher._verify_peer(_peer_response("93.184.216.1"), safe)

        assert calls == []

    def test_a_public_mismatch_is_rotation_not_rebinding(self, settings):
        """A CDN edge answering from a public address absent from the snapshot is not refused.

        This is the direct regression test for the diagnosed false positive
        (job 0f69b80025874d30b57f54de33b8f705, infosys.com).
        """
        fetcher = self._fetcher(settings)
        safe = _safe_url("93.184.216.1")

        fetcher._verify_peer(_peer_response("93.184.216.9"), safe)  # must not raise

    def test_a_multi_ip_cdn_pool_mismatch_is_not_refused(self, settings):
        """Synthetic Akamai-style scenario: several validated addresses.

        The connection lands on a public one outside that snapshot.
        """
        fetcher = self._fetcher(settings)
        safe = _safe_url("23.1.1.1", "23.1.1.2")

        fetcher._verify_peer(_peer_response("23.1.1.3"), safe)  # must not raise

    def test_a_loopback_mismatch_is_refused_as_rebinding(self, settings):
        """Zero behavior change for the attack this guard exists to catch."""
        fetcher = self._fetcher(settings)
        safe = _safe_url("93.184.216.1")

        with pytest.raises(UnsafeUrlError) as exc_info:
            fetcher._verify_peer(_peer_response("127.0.0.1"), safe)
        assert "127.0.0.1" in str(exc_info.value)

    def test_a_private_rfc1918_mismatch_is_refused_as_rebinding(self, settings):
        """Zero behavior change for the attack this guard exists to catch."""
        fetcher = self._fetcher(settings)
        safe = _safe_url("93.184.216.1")

        with pytest.raises(UnsafeUrlError) as exc_info:
            fetcher._verify_peer(_peer_response("10.0.0.5"), safe)
        assert "10.0.0.5" in str(exc_info.value)


class TestNonRetryableExceptionsPropagateOnFirstAttempt:
    """`FETCH_RETRY_ON` must never include a guardrail refusal.

    `UnsafeUrlError` (the SSRF guard) and `RobotsDisallowedError` are decisions
    already made before any socket opened — retrying either just re-asks a
    question that has been answered, spending backoff time on a request that
    cannot succeed. This locks in the exclusion directly against
    `with_async_retries(..., retry_on=FETCH_RETRY_ON)`, the exact call
    `afetch()` makes, so a future edit that widens `FETCH_RETRY_ON` to include
    either type fails here rather than only being caught by inspection.
    """

    @pytest.mark.parametrize("exc_type", [UnsafeUrlError, RobotsDisallowedError])
    def test_first_attempt_exception_propagates_unchanged(self, exc_type: type[Exception]) -> None:
        calls = 0

        def make_exc() -> Exception:
            # Mirrors the real constructors closely enough to be a faithful
            # stand-in for what `_prepare`/`_afetch_chain` actually raise.
            if exc_type is UnsafeUrlError:
                return UnsafeUrlError("https://blocked.example/", "private address")
            return RobotsDisallowedError("https://blocked.example/", "RankunoBot")

        async def fake_afetch_chain() -> FetchResult:
            nonlocal calls
            calls += 1
            raise make_exc()

        async def run() -> None:
            with pytest.raises(exc_type):
                await with_async_retries(fake_afetch_chain, retry_on=FETCH_RETRY_ON)

        asyncio.run(run())

        assert calls == 1
