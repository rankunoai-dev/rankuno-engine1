"""The platform's only outbound web fetcher.

This is where `UrlSafetyPolicy` and `robots` stop being libraries and start
being enforcement. Until this module existed, both were correct, tested and
called by nothing.

Every request passes through, in order:

1. **`UrlSafetyPolicy.validate()`** — no URL reaches a socket without producing
   a `SafeUrl` first.
2. **`robots.can_fetch()`** — per path, with the host's own `Crawl-delay`
   honoured. `/robots.txt` itself is exempt, or the check could never bootstrap.
3. **Per-host throttling** — a bucket per host, so a site declaring
   `Crawl-delay: 10` is throttled independently of one that does not.
4. **Retry with backoff** — shared policy from `src.core.retry`.
5. **Peer verification** — the address actually connected to is checked against
   the addresses that were validated.

Redirects are followed manually
-------------------------------
`follow_redirects=True` would defeat the SSRF guard entirely: a public URL that
302s to `http://169.254.169.254/` is validated once, then transparently
followed to the instance metadata service. Every hop is re-validated here, and
the chain is bounded.

DNS rebinding
-------------
`SafeUrl.resolved_ips` records what was validated; `_verify_peer` compares it
against the address actually connected to and refuses the response on mismatch.
This is **detection after connect, not prevention** — the TCP connection has
already been made by the time the check runs. It closes the window in which a
rebound address could return data, which is the part that matters, but it does
not prevent the connection attempt itself. Stated plainly because a guard that
is believed to do more than it does is worse than none.

Both sync and async paths
-------------------------
`fetch()` uses `httpx.Client`; `afetch()` uses `httpx.AsyncClient`. They are
genuinely separate — the sync path never calls `asyncio.run()`, which would
deadlock inside a running event loop. Calling `fetch()` from within a running
loop raises with an actionable message rather than silently blocking it.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import ClassVar

import httpx
from pydantic import Field

from src.core.config import Settings
from src.core.errors import IntegrationError, RobotsDisallowedError, UnsafeUrlError
from src.core.logger import get_logger
from src.core.rate_limiter import (
    AsyncRateLimiterRegistry,
    AsyncTokenBucket,
    RateLimiterRegistry,
)
from src.core.robots import DEFAULT_USER_AGENT, RobotsTxt, parse_robots_txt
from src.core.schemas import StrictModel
from src.core.url_safety import SafeUrl, UrlSafetyPolicy
from src.integrations.base_client import BaseAPIClient

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "FetchResult",
    "HttpFetcher",
]

_logger = get_logger("integrations.http_fetcher")

DEFAULT_MAX_REDIRECTS = 5
"""Redirect hops permitted. Each is independently re-validated."""

DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024
"""Response body ceiling. A 2 GB response would take out a 512 MB worker."""

_ROBOTS_PATH = "/robots.txt"


class FetchResult(StrictModel):
    """One completed fetch.

    Attributes:
        requested_url: URL as supplied by the caller.
        final_url: URL after redirects, all of them re-validated.
        status_code: HTTP status of the final response.
        content_type: `Content-Type` header, lowercased, parameters stripped.
        body: Decoded response body, truncated at the size ceiling.
        elapsed_ms: Wall-clock duration.
        redirect_chain: Intermediate URLs traversed, in order.
        peer_address: Address actually connected to, when the transport
            reported it. `None` under a mock transport or when unavailable.
        truncated: Whether the body hit the size ceiling.
        headers: Response headers, keys lower-cased. Needed because pagination
            state lives only in headers: Shopify signals the next cursor via
            `Link`, and WordPress reports `X-WP-TotalPages`. Without these a
            caller can only guess when a collection has been exhausted.
    """

    requested_url: str
    final_url: str
    status_code: int = Field(ge=100, le=599)
    content_type: str = ""
    body: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    redirect_chain: tuple[str, ...] = ()
    peer_address: str | None = None
    truncated: bool = False

    @property
    def ok(self) -> bool:
        """True for a 2xx response."""
        return 200 <= self.status_code < 300

    @property
    def is_html(self) -> bool:
        """True when the body is HTML worth parsing."""
        return "html" in self.content_type


class HttpFetcher(BaseAPIClient):
    """Safety-wired HTTP client for crawling arbitrary sites.

    Not a general-purpose HTTP client: it is deliberately restrictive, because
    its inputs are operator- and client-supplied URLs.
    """

    service_name: ClassVar[str] = "web.fetch"
    rate_limit_key: ClassVar[str] = "web.fetch"
    requests_per_minute: ClassVar[int] = 600

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        url_policy: UrlSafetyPolicy | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        respect_robots: bool = True,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a fetcher.

        Args:
            settings: Configuration override, primarily for tests.
            url_policy: SSRF policy. Defaults to the deny-by-default policy.
            user_agent: Product token sent, and matched against robots.txt.
            respect_robots: Disabling is permitted only for fetching a site you
                own. It is logged loudly, because the usual reason a crawler
                gets an IP range banned is someone turning this off.
            max_redirects: Hop ceiling. Every hop is re-validated regardless.
            max_body_bytes: Response size ceiling.
            transport: Sync transport override. Tests inject
                `httpx.MockTransport`.
            async_transport: Async transport override.
        """
        super().__init__(settings)

        self._policy = url_policy or UrlSafetyPolicy()
        self._user_agent = user_agent
        self._respect_robots = respect_robots
        self._max_redirects = max_redirects
        self._max_body_bytes = max_body_bytes
        self._transport = transport
        self._async_transport = async_transport

        self._client: httpx.Client | None = None
        self._aclient: httpx.AsyncClient | None = None
        self._robots: dict[str, RobotsTxt] = {}
        self._host_buckets = RateLimiterRegistry()
        self._async_host_buckets = AsyncRateLimiterRegistry(
            default_requests_per_minute=self._settings.default_requests_per_minute
        )

        if not respect_robots:
            _logger.warning("robots_compliance_disabled", extra={"user_agent": user_agent})

    def authenticate(self) -> None:
        """No credentials: this client fetches the public web."""
        return

    # -- sync path ---------------------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        """Fetch a URL synchronously.

        Args:
            url: Absolute URL to fetch.

        Returns:
            The completed fetch.

        Raises:
            RuntimeError: If called from inside a running event loop. Use
                `afetch()` there — blocking the loop would stall every other
                in-flight request.
            UnsafeUrlError: If the URL, or any redirect hop, fails validation.
            RobotsDisallowedError: If robots.txt forbids the path.
            IntegrationError: If the request fails after retries.
        """
        self._guard_event_loop()
        return self.call("fetch", lambda: self._fetch_chain(url))

    def close(self) -> None:
        """Release the underlying sync connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> HttpFetcher:
        """Enter a context that closes the sync pool on exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the sync pool."""
        self.close()

    # -- async path --------------------------------------------------------

    async def afetch(self, url: str) -> FetchResult:
        """Fetch a URL asynchronously.

        Args:
            url: Absolute URL to fetch.

        Returns:
            The completed fetch.

        Raises:
            UnsafeUrlError: If the URL, or any redirect hop, fails validation.
            RobotsDisallowedError: If robots.txt forbids the path.
            IntegrationError: If the request fails after retries.
        """
        from src.core.retry import with_async_retries

        try:
            return await with_async_retries(lambda: self._afetch_chain(url))
        except (UnsafeUrlError, RobotsDisallowedError, IntegrationError):
            raise
        except Exception as exc:
            _logger.exception("async_fetch_failed", extra={"url": url})
            raise IntegrationError(type(self).service_name, f"fetch: {exc}") from exc

    async def aclose(self) -> None:
        """Release the underlying async connection pool."""
        if self._aclient is not None:
            await self._aclient.aclose()
            self._aclient = None

    async def __aenter__(self) -> HttpFetcher:
        """Enter a context that closes the async pool on exit."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the async pool."""
        await self.aclose()

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _guard_event_loop() -> None:
        """Refuse a blocking call from inside a running event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        msg = (
            "HttpFetcher.fetch() is blocking and was called from a running event "
            "loop. Use `await fetcher.afetch(url)` instead."
        )
        raise RuntimeError(msg)

    def _sync_client(self) -> httpx.Client:
        """Lazily build the sync client. Redirects are handled manually."""
        if self._client is None:
            self._client = httpx.Client(
                http2=False,
                follow_redirects=False,
                timeout=self._settings.default_timeout_s,
                headers={"User-Agent": self._user_agent},
                transport=self._transport,
            )
        return self._client

    def _async_client(self) -> httpx.AsyncClient:
        """Lazily build the async client. Redirects are handled manually."""
        if self._aclient is None:
            self._aclient = httpx.AsyncClient(
                http2=False,
                follow_redirects=False,
                timeout=self._settings.default_timeout_s,
                headers={"User-Agent": self._user_agent},
                transport=self._async_transport,
            )
        return self._aclient

    def _prepare(self, url: str, *, is_robots: bool = False) -> tuple[SafeUrl, RobotsTxt | None]:
        """Validate a URL and load the robots rules governing it."""
        safe = self._policy.validate(url)
        if is_robots or not self._respect_robots:
            return safe, None
        robots = self._robots_for_sync(safe)
        self._enforce_robots(safe, robots)
        return safe, robots

    def _enforce_robots(self, safe: SafeUrl, robots: RobotsTxt) -> None:
        """Refuse a path the host's robots.txt disallows."""
        path = httpx.URL(safe.url).raw_path.decode() or "/"
        if not robots.can_fetch(path, self._user_agent):
            raise RobotsDisallowedError(safe.url, self._user_agent)

    def _robots_for_sync(self, safe: SafeUrl) -> RobotsTxt:
        """Return cached robots rules for a host, fetching them once."""
        host = safe.host
        cached = self._robots.get(host)
        if cached is not None:
            return cached

        robots_url = f"{safe.scheme}://{safe.host}:{safe.port}{_ROBOTS_PATH}"
        try:
            result = self._fetch_chain(robots_url, is_robots=True)
            parsed = parse_robots_txt(result.body) if result.ok else RobotsTxt()
        except (UnsafeUrlError, IntegrationError, httpx.HTTPError) as exc:
            # An unreachable robots.txt means "no rules", per RFC 9309. Failing
            # the crawl instead would let one 500 block an entire site.
            _logger.info("robots_unavailable", extra={"host": host, "error": str(exc)})
            parsed = RobotsTxt()

        self._robots[host] = parsed
        return parsed

    def _throttle_sync(self, safe: SafeUrl, robots: RobotsTxt | None) -> None:
        """Block until the host's bucket allows a request."""
        delay = robots.crawl_delay(self._user_agent) if robots else None
        rpm = max(1, int(60 / delay)) if delay else self._settings.default_requests_per_minute
        bucket = self._host_buckets.get_or_create(f"host:{safe.host}", rpm)
        bucket.acquire(timeout_s=self._settings.default_timeout_s)

    async def _throttle_async(self, safe: SafeUrl, robots: RobotsTxt | None) -> None:
        """Await the host's bucket."""
        delay = robots.crawl_delay(self._user_agent) if robots else None
        bucket: AsyncTokenBucket = self._async_host_buckets.get_or_create(
            f"host:{safe.host}", delay
        )
        await bucket.acquire(timeout_s=self._settings.default_timeout_s)

    def _fetch_chain(self, url: str, *, is_robots: bool = False) -> FetchResult:
        """Follow redirects synchronously, re-validating every hop."""
        chain: list[str] = []
        current = url

        for _ in range(self._max_redirects + 1):
            safe, robots = self._prepare(current, is_robots=is_robots)
            self._throttle_sync(safe, robots)

            started = time.perf_counter()
            response = self._sync_client().get(safe.url)
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._verify_peer(response, safe)

            location = self._redirect_target(response, safe)
            if location is None:
                return self._build_result(url, safe, response, tuple(chain), elapsed_ms)

            chain.append(safe.url)
            current = location

        raise IntegrationError(type(self).service_name, f"too many redirects from '{url}'")

    async def _afetch_chain(self, url: str, *, is_robots: bool = False) -> FetchResult:
        """Follow redirects asynchronously, re-validating every hop."""
        chain: list[str] = []
        current = url

        for _ in range(self._max_redirects + 1):
            safe = self._policy.validate(current)
            robots = None
            if not is_robots and self._respect_robots:
                robots = await self._robots_for_async(safe)
                self._enforce_robots(safe, robots)

            await self._throttle_async(safe, robots)

            started = time.perf_counter()
            response = await self._async_client().get(safe.url)
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._verify_peer(response, safe)

            location = self._redirect_target(response, safe)
            if location is None:
                return self._build_result(url, safe, response, tuple(chain), elapsed_ms)

            chain.append(safe.url)
            current = location

        raise IntegrationError(type(self).service_name, f"too many redirects from '{url}'")

    async def _robots_for_async(self, safe: SafeUrl) -> RobotsTxt:
        """Return cached robots rules for a host, fetching them once."""
        host = safe.host
        cached = self._robots.get(host)
        if cached is not None:
            return cached

        robots_url = f"{safe.scheme}://{safe.host}:{safe.port}{_ROBOTS_PATH}"
        try:
            result = await self._afetch_chain(robots_url, is_robots=True)
            parsed = parse_robots_txt(result.body) if result.ok else RobotsTxt()
        except (UnsafeUrlError, IntegrationError, httpx.HTTPError) as exc:
            _logger.info("robots_unavailable", extra={"host": host, "error": str(exc)})
            parsed = RobotsTxt()

        self._robots[host] = parsed
        return parsed

    @staticmethod
    def _redirect_target(response: httpx.Response, safe: SafeUrl) -> str | None:
        """Return the absolute redirect target, or `None` if not a redirect."""
        if not (300 <= response.status_code < 400):
            return None
        location = response.headers.get("location")
        if not location:
            return None
        return str(httpx.URL(safe.url).join(location))

    def _verify_peer(self, response: httpx.Response, safe: SafeUrl) -> None:
        """Refuse a response served from an address that was never validated.

        Detection after connect, not prevention — see the module docstring.
        """
        peer = self._peer_address(response)
        if peer is None or peer in safe.resolved_ips:
            return
        _logger.warning(
            "dns_rebinding_suspected",
            extra={"host": safe.host, "connected": peer, "validated": safe.resolved_ips},
        )
        raise UnsafeUrlError(safe.url, f"connected to unvalidated address {peer}")

    @staticmethod
    def _peer_address(response: httpx.Response) -> str | None:
        """Best-effort peer address. `None` under a mock transport."""
        stream = response.extensions.get("network_stream")
        if stream is None:
            return None
        try:
            info = stream.get_extra_info("server_addr")
        except Exception:  # noqa: BLE001 - diagnostics must never break a fetch
            return None
        if isinstance(info, tuple) and info:
            return str(info[0])
        return None

    def _build_result(
        self,
        requested: str,
        safe: SafeUrl,
        response: httpx.Response,
        chain: tuple[str, ...],
        elapsed_ms: float,
    ) -> FetchResult:
        """Assemble a validated result, enforcing the body size ceiling."""
        raw = response.content
        truncated = len(raw) > self._max_body_bytes
        if truncated:
            raw = raw[: self._max_body_bytes]
            _logger.info("response_truncated", extra={"url": safe.url})

        try:
            body = raw.decode(response.encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            body = raw.decode("utf-8", errors="replace")

        return FetchResult(
            requested_url=requested,
            final_url=safe.url,
            status_code=response.status_code,
            content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
            body=body,
            headers={key.lower(): value for key, value in response.headers.items()},
            elapsed_ms=elapsed_ms,
            redirect_chain=chain,
            peer_address=self._peer_address(response),
            truncated=truncated,
        )
