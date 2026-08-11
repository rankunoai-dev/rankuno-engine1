"""Client-side rate limiting and spend control.

Two independent protections, both applied *before* a request leaves the process:

* `TokenBucket` — throttles request volume against a provider's documented
  quota. Cheaper and far more reliable than discovering the limit via 429s, and
  it keeps us from getting an API key banned during a scrape.
* `CostLedger` — a hard ceiling on cumulative spend for the process lifetime, so
  a runaway agent loop cannot quietly burn a budget.

Both are thread-safe and use a monotonic clock, so they behave correctly across
NTP adjustments and daylight-saving transitions.

Sync and async variants
-----------------------
`TokenBucket` blocks the calling thread; `AsyncTokenBucket` awaits. Both exist
because governance and politeness happen at different layers (see
`docs/adr/0003-job-level-governance-and-async-internals.md`): the governed
pipeline is synchronous and runs once per job, while per-request throttling
happens inside an async crawl where a blocking sleep would stall the event loop.
The token accounting itself is shared, so the two cannot drift apart.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

from src.core.config import get_settings
from src.core.errors import BudgetExceededError, RateLimitExceededError
from src.core.logger import get_logger

__all__ = [
    "AsyncRateLimiterRegistry",
    "AsyncTokenBucket",
    "CostLedger",
    "RateLimiterRegistry",
    "TokenBucket",
]

_logger = get_logger("core.rate_limiter")

# Never spin: even a satisfied deficit yields for a tick so a contended bucket
# cannot pin a core or starve an event loop.
_MIN_SLEEP_S = 0.001


def _validate_bucket_config(key: str, capacity: int, refill_per_second: float) -> None:
    """Reject a bucket configuration that could never grant a token.

    Raises:
        ValueError: If capacity or refill rate is not positive.
    """
    if capacity <= 0:
        msg = f"Bucket '{key}' capacity must be positive."
        raise ValueError(msg)
    if refill_per_second <= 0:
        msg = f"Bucket '{key}' refill rate must be positive."
        raise ValueError(msg)


def _accrued_tokens(
    current: float, updated_at: float, capacity: int, refill_per_second: float, now: float
) -> float:
    """Return the token count after accrual since `updated_at`, capped at capacity.

    Shared by both bucket variants so the refill maths exists in exactly one
    place. A backwards clock step contributes zero rather than draining tokens.
    """
    elapsed = max(0.0, now - updated_at)
    return min(float(capacity), current + elapsed * refill_per_second)


@dataclass
class TokenBucket:
    """A classic token bucket.

    Attributes:
        key: Identifier of the upstream quota this bucket protects.
        capacity: Maximum burst size, in tokens.
        refill_per_second: Sustained rate at which tokens are replenished.
    """

    key: str
    capacity: int
    refill_per_second: float

    _tokens: float = field(init=False)
    _updated_at: float = field(init=False)
    _lock: threading.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the configuration and start the bucket full."""
        _validate_bucket_config(self.key, self.capacity, self.refill_per_second)

        self._tokens = float(self.capacity)
        self._updated_at = time.monotonic()
        self._lock = threading.Lock()

    @classmethod
    def per_minute(
        cls, key: str, requests_per_minute: int, burst: int | None = None
    ) -> TokenBucket:
        """Build a bucket from a requests-per-minute quota.

        Args:
            key: Quota identifier.
            requests_per_minute: Sustained rate.
            burst: Tokens available at once. Defaults to a full minute's worth,
                which is right for an API quota — spending it early is allowed
                as long as the minute balances.

                It is **wrong for pacing a crawler**. At 60 rpm the default lets
                60 requests leave instantly, so a crawl of fewer pages than that
                never throttles at all: measured on gep.com, a "1 req/sec"
                setting peaked at 10.2 requests/sec and the limiter never
                engaged. Callers pacing a host should pass roughly one second's
                worth.
        """
        return cls(
            key=key,
            capacity=max(1, burst if burst is not None else requests_per_minute),
            refill_per_second=requests_per_minute / 60.0,
        )

    def _refill_locked(self) -> None:
        """Add tokens accrued since the last update. Caller must hold the lock."""
        now = time.monotonic()
        self._tokens = _accrued_tokens(
            self._tokens, self._updated_at, self.capacity, self.refill_per_second, now
        )
        self._updated_at = now

    def try_acquire(self, tokens: int = 1) -> bool:
        """Take `tokens` if available, without blocking.

        Returns:
            True if the tokens were taken, False if the bucket is short.
        """
        if tokens > self.capacity:
            msg = f"Cannot acquire {tokens} tokens from '{self.key}' (capacity {self.capacity})."
            raise ValueError(msg)

        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def time_until_available(self, tokens: int = 1) -> float:
        """Seconds until `tokens` would be available. Zero if available now."""
        with self._lock:
            self._refill_locked()
            deficit = tokens - self._tokens
            return max(0.0, deficit / self.refill_per_second)

    def acquire(self, tokens: int = 1, *, timeout_s: float | None = None) -> None:
        """Block until `tokens` are available.

        Args:
            tokens: How many tokens to take.
            timeout_s: Give up after this long. `None` waits indefinitely.

        Raises:
            RateLimitExceededError: If `timeout_s` elapsed first.
        """
        deadline = None if timeout_s is None else time.monotonic() + timeout_s

        while True:
            if self.try_acquire(tokens):
                return

            wait_s = self.time_until_available(tokens)
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or wait_s > remaining:
                    raise RateLimitExceededError(self.key, wait_s)

            _logger.debug("rate_limit_wait", extra={"bucket": self.key, "wait_s": round(wait_s, 3)})
            time.sleep(max(wait_s, _MIN_SLEEP_S))


@dataclass
class AsyncTokenBucket:
    """A token bucket for use inside an async crawl.

    Behaviourally identical to `TokenBucket`, but `acquire()` awaits instead of
    blocking. Per ADR 0003 this is what enforces per-domain politeness inside
    `execute()`, where a `time.sleep()` would stall every other in-flight
    request on the same event loop.

    Not thread-safe across event loops: an instance belongs to the loop that
    uses it. Sharing one across threads requires the synchronous `TokenBucket`.

    Attributes:
        key: Identifier of the upstream quota this bucket protects.
        capacity: Maximum burst size, in tokens.
        refill_per_second: Sustained rate at which tokens are replenished.
    """

    key: str
    capacity: int
    refill_per_second: float

    _tokens: float = field(init=False)
    _updated_at: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the configuration and start the bucket full."""
        _validate_bucket_config(self.key, self.capacity, self.refill_per_second)

        self._tokens = float(self.capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    @classmethod
    def per_minute(
        cls, key: str, requests_per_minute: int, burst: int | None = None
    ) -> AsyncTokenBucket:
        """Build a bucket from a requests-per-minute quota.

        See `TokenBucket.per_minute` for why a crawler must pass `burst`.
        """
        return cls(
            key=key,
            capacity=max(1, burst if burst is not None else requests_per_minute),
            refill_per_second=requests_per_minute / 60.0,
        )

    @classmethod
    def from_crawl_delay(cls, key: str, crawl_delay_s: float) -> AsyncTokenBucket:
        """Build a bucket honouring a robots.txt `Crawl-delay`.

        Capacity is 1: a declared crawl delay asks for evenly spaced requests,
        so allowing a burst would violate the spirit of the directive.

        Args:
            key: Quota identifier, conventionally the target host.
            crawl_delay_s: Seconds the host asked us to wait between requests.

        Raises:
            ValueError: If `crawl_delay_s` is not positive.
        """
        if crawl_delay_s <= 0:
            msg = f"Crawl delay for '{key}' must be positive."
            raise ValueError(msg)
        return cls(key=key, capacity=1, refill_per_second=1.0 / crawl_delay_s)

    def _refill_locked(self) -> None:
        """Add tokens accrued since the last update. Caller must hold the lock."""
        now = time.monotonic()
        self._tokens = _accrued_tokens(
            self._tokens, self._updated_at, self.capacity, self.refill_per_second, now
        )
        self._updated_at = now

    async def try_acquire(self, tokens: int = 1) -> bool:
        """Take `tokens` if available, without waiting.

        Returns:
            True if the tokens were taken, False if the bucket is short.

        Raises:
            ValueError: If `tokens` exceeds capacity, which could never succeed.
        """
        if tokens > self.capacity:
            msg = f"Cannot acquire {tokens} tokens from '{self.key}' (capacity {self.capacity})."
            raise ValueError(msg)

        async with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def time_until_available(self, tokens: int = 1) -> float:
        """Seconds until `tokens` would be available. Zero if available now."""
        async with self._lock:
            self._refill_locked()
            deficit = tokens - self._tokens
            return max(0.0, deficit / self.refill_per_second)

    async def acquire(self, tokens: int = 1, *, timeout_s: float | None = None) -> None:
        """Wait until `tokens` are available.

        Args:
            tokens: How many tokens to take.
            timeout_s: Give up after this long. `None` waits indefinitely.

        Raises:
            RateLimitExceededError: If `timeout_s` elapsed first.
        """
        deadline = None if timeout_s is None else time.monotonic() + timeout_s

        while True:
            if await self.try_acquire(tokens):
                return

            wait_s = await self.time_until_available(tokens)
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or wait_s > remaining:
                    raise RateLimitExceededError(self.key, wait_s)

            _logger.debug(
                "rate_limit_wait_async", extra={"bucket": self.key, "wait_s": round(wait_s, 3)}
            )
            await asyncio.sleep(max(wait_s, _MIN_SLEEP_S))


class RateLimiterRegistry:
    """Process-wide map of quota key to bucket.

    Tools sharing an upstream quota MUST share a key (see
    `ToolMetadata.rate_limit_key`) so their traffic is limited jointly rather
    than each getting a full allowance.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        key: str,
        requests_per_minute: int | None = None,
        burst: int | None = None,
    ) -> TokenBucket:
        """Return the bucket for `key`, creating it on first use.

        Args:
            key: Quota identifier.
            requests_per_minute: Sustained rate. Defaults to the configured one.
            burst: Tokens available back to back. Omit for an API quota; pass
                roughly one second's worth when pacing a crawler, or the rate
                will not bind on a crawl shorter than a minute's allowance.
        """
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                rpm = requests_per_minute or get_settings().default_requests_per_minute
                bucket = TokenBucket.per_minute(key, rpm, burst)
                self._buckets[key] = bucket
                _logger.debug("bucket_created", extra={"bucket": key, "rpm": rpm})
            return bucket

    def reset(self) -> None:
        """Drop all buckets. Tests only."""
        with self._lock:
            self._buckets.clear()


class AsyncRateLimiterRegistry:
    """Per-host map of quota key to `AsyncTokenBucket`, scoped to one crawl.

    A crawl creates one registry and asks it for a bucket per target host, so a
    site that declares `Crawl-delay: 10` is throttled independently of a site
    that does not.

    No lock is needed: `get_or_create` contains no `await`, so it cannot be
    preempted by another coroutine on the same event loop.
    """

    def __init__(self, default_requests_per_minute: int = 60) -> None:
        """Create an empty registry.

        Args:
            default_requests_per_minute: Rate applied to a host that declares no
                `Crawl-delay` of its own.
        """
        self._buckets: dict[str, AsyncTokenBucket] = {}
        self._default_rpm = default_requests_per_minute

    def get_or_create(
        self,
        key: str,
        crawl_delay_s: float | None = None,
        requests_per_minute: int | None = None,
        burst: int | None = None,
    ) -> AsyncTokenBucket:
        """Return the bucket for `key`, creating it on first use.

        Args:
            key: Quota identifier, conventionally the target host.
            crawl_delay_s: Host-declared crawl delay, used when no explicit rate
                is given.
            requests_per_minute: Explicit rate, already reconciled against any
                declared `Crawl-delay` by the caller. Takes precedence.

                This exists because reconciling here would be wrong in one
                direction: a host declaring `Crawl-delay: 0.1` permits 10 rps,
                and letting that override a slower *configured* rate would make
                a "polite" setting crawl ten times faster than asked. The two
                limits have to be combined with `min`, and only the caller knows
                both.
            burst: Tokens available back to back. Pass roughly one second's
                worth when pacing a crawler; the default of a full minute lets a
                short crawl finish before the rate binds at all.

        Returns:
            The bucket governing `key`.
        """
        bucket = self._buckets.get(key)
        if bucket is None:
            if requests_per_minute is not None:
                bucket = AsyncTokenBucket.per_minute(key, requests_per_minute, burst)
            elif crawl_delay_s:
                bucket = AsyncTokenBucket.from_crawl_delay(key, crawl_delay_s)
            else:
                bucket = AsyncTokenBucket.per_minute(key, self._default_rpm)
            self._buckets[key] = bucket
            _logger.debug(
                "async_bucket_created", extra={"bucket": key, "crawl_delay_s": crawl_delay_s}
            )
        return bucket

    def reset(self) -> None:
        """Drop all buckets. Tests and crawl teardown only."""
        self._buckets.clear()


class CostLedger:
    """Tracks cumulative spend against a hard ceiling."""

    def __init__(self, ceiling_usd: float | None = None) -> None:
        """Create a ledger.

        Args:
            ceiling_usd: Maximum cumulative spend. Defaults to
                `MAX_SESSION_SPEND_USD`.
        """
        self._ceiling = (
            ceiling_usd if ceiling_usd is not None else get_settings().max_session_spend_usd
        )
        self._spent = 0.0
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        """Total recorded spend so far."""
        with self._lock:
            return self._spent

    @property
    def remaining_usd(self) -> float:
        """Headroom left under the ceiling."""
        with self._lock:
            return max(0.0, self._ceiling - self._spent)

    def charge(self, amount_usd: float) -> float:
        """Record a spend, refusing it if it would breach the ceiling.

        The check and the increment happen under one lock, so concurrent tools
        cannot both pass a check that only one of them could afford.

        Args:
            amount_usd: Cost of the operation about to be performed.

        Returns:
            The new cumulative total.

        Raises:
            ValueError: If `amount_usd` is negative.
            BudgetExceededError: If the ceiling would be breached.
        """
        if amount_usd < 0:
            msg = "Cost must not be negative."
            raise ValueError(msg)

        with self._lock:
            if self._spent + amount_usd > self._ceiling:
                raise BudgetExceededError(amount_usd, self._spent, self._ceiling)
            self._spent += amount_usd
            total = self._spent

        if amount_usd > 0:
            _logger.info(
                "spend_recorded",
                extra={"amount_usd": amount_usd, "total_usd": round(total, 6)},
            )
        return total

    def reset(self) -> None:
        """Zero the ledger. Tests and explicit session boundaries only."""
        with self._lock:
            self._spent = 0.0
