"""`BaseAPIClient` — the mandatory base for every external API connector.

No module may call an external API directly. Connectors subclass this so that
quota protection, retry/backoff, credential handling and audit logging are
uniform and reviewable in one place.

A subclass declares its `service_name`, its documented quota, and implements
transport. The `call()` wrapper supplies everything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar, TypeVar

from src.core.config import Settings, get_settings
from src.core.errors import IntegrationError
from src.core.logger import get_logger
from src.core.rate_limiter import RateLimiterRegistry, TokenBucket
from src.core.retry import with_retries

__all__ = ["BaseAPIClient"]

_logger = get_logger("integrations.base_client")

# Connectors to the same vendor share this registry, so two clients pointed at
# the same quota throttle jointly.
_SHARED_LIMITERS = RateLimiterRegistry()

ResultT = TypeVar("ResultT")


class BaseAPIClient(ABC):
    """Common behaviour for every outbound API connector.

    Class variables a subclass must set:

    * `service_name` — audit-log identity, e.g. `"google.search_console"`.
    * `rate_limit_key` — shared quota bucket. Clients hitting one vendor quota
      must share a key.
    * `requests_per_minute` — the vendor's documented sustained limit.
    """

    service_name: ClassVar[str]
    rate_limit_key: ClassVar[str]
    requests_per_minute: ClassVar[int] = 60

    def __init__(self, settings: Settings | None = None) -> None:
        """Build a client.

        Args:
            settings: Configuration override, primarily for tests.
        """
        for attr in ("service_name", "rate_limit_key"):
            if not getattr(type(self), attr, None):
                msg = f"{type(self).__name__} must declare a class-level '{attr}'."
                raise TypeError(msg)

        self._settings = settings or get_settings()
        self._bucket: TokenBucket = _SHARED_LIMITERS.get_or_create(
            type(self).rate_limit_key, type(self).requests_per_minute
        )

    @abstractmethod
    def authenticate(self) -> None:
        """Acquire or refresh credentials.

        Implementations must read credentials via `self._settings.require(...)`
        so a missing key fails with an actionable message instead of a 401.
        """
        raise NotImplementedError

    def call(self, operation: str, func: Callable[[], ResultT]) -> ResultT:
        """Run one outbound request under the platform's standard protections.

        Order matters: the rate limiter runs *before* the retry wrapper, so a
        retry storm cannot bypass the quota it is meant to respect.

        Args:
            operation: Short label for the audit log, e.g. `"query_analytics"`.
            func: Zero-argument callable performing the actual request. Bind
                arguments with a lambda or `functools.partial`.

        Returns:
            Whatever `func` returns.

        Raises:
            IntegrationError: If the call fails after all retries.
        """
        service = type(self).service_name

        def attempt() -> ResultT:
            self._bucket.acquire(timeout_s=self._settings.default_timeout_s)
            return func()

        try:
            result = with_retries(attempt)
        except IntegrationError:
            raise
        except Exception as exc:
            _logger.exception("api_call_failed", extra={"service": service, "op": operation})
            raise IntegrationError(service, f"{operation}: {exc}") from exc

        _logger.debug("api_call_ok", extra={"service": service, "op": operation})
        return result
