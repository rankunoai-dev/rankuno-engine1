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
