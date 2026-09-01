"""Exception hierarchy for the Rankuno automation platform.

Every exception raised by first-party code inherits from `RankunoError` so a
caller can distinguish "our code decided to stop" from "a dependency blew up".
"""

from __future__ import annotations

__all__ = [
    "ApprovalRequiredError",
    "BudgetExceededError",
    "ConfigurationError",
    "CrawlBlockedError",
    "GscAuthenticationError",
    "GscAuthorizationError",
    "GscPropertyNotFoundError",
    "GscQuotaExceededError",
    "GscApiDeprecatedError",
    "GuardrailViolationError",
    "IntegrationError",
    "RankunoError",
    "RateLimitExceededError",
    "RobotsDisallowedError",
    "ToolExecutionError",
    "UnsafeUrlError",
]


class RankunoError(Exception):
    """Base class for all first-party errors."""


class ConfigurationError(RankunoError):
    """Required settings are missing, malformed, or mutually inconsistent."""


class CrawlBlockedError(RankunoError):
    """A crawl retrieved nothing at all: no page, no sitemap, no CMS record.

    A hard error rather than an empty report, because an empty report is not
    what the caller would see. The crawl root is seeded as a graph node before
    the first request, so a fully blocked site yields exactly one node,
    classified `HOMEPAGE` at high confidence from the URL string alone — visually
    identical to a successful crawl of a one-page site.

    Observed live: macys.com returned 403 to every request including
    `robots.txt`, and the job reported `succeeded` with one page at 0.97
    confidence.
    """


class GuardrailViolationError(RankunoError):
    """An action was attempted that policy forbids outright."""


class ApprovalRequiredError(GuardrailViolationError):
    """A MANDATORY_HITL action was attempted without operator approval.

    This is deliberately a hard error rather than a silent no-op: an unapproved
    write or spend must never be mistaken for a completed one.
    """

    def __init__(self, tool: str, reason: str) -> None:
        """Record which tool was blocked and why."""
        self.tool = tool
        self.reason = reason
        super().__init__(f"Human approval required for '{tool}': {reason}")


class RateLimitExceededError(RankunoError):
    """The local token bucket refused the call before it reached the network."""

    def __init__(self, key: str, retry_after_s: float) -> None:
        """Record the exhausted bucket and when capacity returns."""
        self.key = key
        self.retry_after_s = retry_after_s
        super().__init__(f"Rate limit '{key}' exhausted; retry in {retry_after_s:.2f}s")


class BudgetExceededError(RankunoError):
    """The call would push cumulative spend past the configured ceiling."""

    def __init__(self, attempted_usd: float, spent_usd: float, ceiling_usd: float) -> None:
        """Record the spend attempt that was refused."""
        self.attempted_usd = attempted_usd
        self.spent_usd = spent_usd
        self.ceiling_usd = ceiling_usd
        super().__init__(
            f"Spend of ${attempted_usd:.4f} refused: ${spent_usd:.4f} already spent "
            f"against a ${ceiling_usd:.2f} ceiling."
        )


class UnsafeUrlError(GuardrailViolationError):
    """A URL was rejected before any socket was opened.

    Raised by the SSRF guard. This is a guardrail violation rather than a plain
    validation error because the URLs it rejects are frequently hostile: an
    operator-supplied crawl target pointing at `169.254.169.254` is an attempt to
    read cloud instance credentials, not a typo.
    """

    def __init__(self, url: str, reason: str) -> None:
        """Record the rejected URL and the rule that rejected it."""
        self.url = url
        self.reason = reason
        super().__init__(f"Refused to fetch '{url}': {reason}")


class RobotsDisallowedError(GuardrailViolationError):
    """The target host's robots.txt forbids fetching this path.

    Honouring robots.txt is a hard rule, not a heuristic: ignoring it is what
    gets a crawler's IP range banned and exposes Rankuno to a client complaint.
    """

    def __init__(self, url: str, user_agent: str) -> None:
        """Record the refused URL and the agent it was refused for."""
        self.url = url
        self.user_agent = user_agent
        super().__init__(f"robots.txt disallows '{url}' for user-agent '{user_agent}'.")


class IntegrationError(RankunoError):
    """An external API failed in a way retries could not resolve."""

    def __init__(self, service: str, detail: str) -> None:
        """Record which upstream service failed."""
        self.service = service
        self.detail = detail
        super().__init__(f"Integration '{service}' failed: {detail}")


class ToolExecutionError(RankunoError):
    """A tool's own logic failed. Wraps the original exception as `__cause__`."""


class GscAuthenticationError(IntegrationError):
    """OAuth token is invalid, expired, or revoked.

    Covers: 401 Unauthorized, invalid_grant, token refresh failure.
    """

    def __init__(self, reason: str) -> None:
        """Record the authentication failure reason."""
        self.reason = reason
        super().__init__("google.search_console", f"Authentication failed: {reason}")


class GscAuthorizationError(IntegrationError):
    """Authenticated user lacks permission for the requested resource.

    Covers: 403 Forbidden for property access, scope mismatch.
    """

    def __init__(self, reason: str) -> None:
        """Record the authorization failure reason."""
        self.reason = reason
        super().__init__("google.search_console", f"Authorization failed: {reason}")


class GscPropertyNotFoundError(IntegrationError):
    """GSC property does not exist or has been deleted.

    Covers: 404 Not Found for a specific property.
    """

    def __init__(self, property_url: str) -> None:
        """Record the missing property."""
        self.property_url = property_url
        super().__init__(
            "google.search_console",
            f"Property '{property_url}' not found in GSC. It may have been deleted.",
        )


class GscQuotaExceededError(IntegrationError):
    """Rate limit or quota exhausted on GSC API.

    Covers: 429 Too Many Requests (quota throttling).
    """

    def __init__(self, retry_after_s: float | None = None) -> None:
        """Record the quota exhaustion and optional retry window."""
        self.retry_after_s = retry_after_s
        msg = "GSC API quota exhausted"
        if retry_after_s:
            msg += f"; retry after {retry_after_s:.1f}s"
        super().__init__("google.search_console", msg)


class GscApiDeprecatedError(IntegrationError):
    """GSC API endpoint is deprecated or no longer available.

    Covers: 410 Gone, 501 Not Implemented.
    """

    def __init__(self, http_status: int, detail: str) -> None:
        """Record the HTTP status and details."""
        self.http_status = http_status
        super().__init__(
            "google.search_console",
            f"API endpoint deprecated or unavailable ({http_status}): {detail}",
        )
