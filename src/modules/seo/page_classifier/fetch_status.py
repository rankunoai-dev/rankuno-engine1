"""How a page's fetch result is worded for a reader.

One place, because the XLSX, the PDF and the audit export must say the same
thing about the same page, and because the wording carries a claim. A status
column that prints "Unknown" for every row cannot be told apart from one that
is honest about a page never requested; the three labels below keep three
different facts apart:

* `NOT_FETCHED` -- the crawl never sent a request (sitemap-only, CMS-only,
  skipped, depth-capped, excluded on resume, disallowed by robots.txt).
* `NO_RESPONSE` -- a request was attempted and nothing answered (timeout,
  transport error, SSRF guard refusal).
* `NOT_RECORDED` -- the result predates the capture, or came from an import,
  a bundle or a Screaming Frog merge, where no fetch was made by this engine.

A label is never a status code and never implies a fetch that did not happen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .discovery import (
    OUTCOME_GUARDRAIL_REFUSED,
    OUTCOME_NOT_FETCHED,
    OUTCOME_ROBOTS_DISALLOWED,
    OUTCOME_TRANSPORT,
    OUTCOME_TRANSPORT_DEADLINE,
    OUTCOME_TRANSPORT_REFUSED,
    OUTCOME_TRANSPORT_TIMEOUT,
)

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile

__all__ = [
    "LABEL_NOT_FETCHED",
    "LABEL_NOT_RECORDED",
    "LABEL_NO_RESPONSE",
    "NO_REDIRECT",
    "STATUS_LEGEND",
    "first_redirect_label",
    "http_status_label",
]

LABEL_NOT_FETCHED = "Not fetched"
LABEL_NO_RESPONSE = "No response"
LABEL_NOT_RECORDED = "Not recorded (older crawl)"
NO_REDIRECT = "—"

_NOT_FETCHED_OUTCOMES = frozenset({OUTCOME_NOT_FETCHED, OUTCOME_ROBOTS_DISALLOWED})
_NO_RESPONSE_OUTCOMES = frozenset(
    {
        OUTCOME_TRANSPORT,
        OUTCOME_TRANSPORT_TIMEOUT,
        OUTCOME_TRANSPORT_REFUSED,
        OUTCOME_TRANSPORT_DEADLINE,
        OUTCOME_GUARDRAIL_REFUSED,
    }
)

STATUS_LEGEND = (
    "HTTP Status is the status of the last attempt (the page the fetch landed on). "
    "First Redirect is the first hop's status when the URL redirected. "
    f"{LABEL_NOT_FETCHED}: the crawl never requested the URL (sitemap-only, skipped, "
    "disallowed by robots.txt, or not reached after a resume). "
    f"{LABEL_NO_RESPONSE}: requested, but no HTTP response came back (timeout, "
    f"connection error, or refused by the safety guard). {LABEL_NOT_RECORDED}: the stored "
    "result predates status capture or was imported, so nothing is known."
)


def http_status_label(page: FullPageIntelligenceProfile) -> str:
    """The HTTP Status cell for one page: the literal code, or one of three labels."""
    if page.http_status is not None:
        return str(page.http_status)
    outcome = page.fetch_outcome
    if outcome in _NOT_FETCHED_OUTCOMES:
        return LABEL_NOT_FETCHED
    if outcome in _NO_RESPONSE_OUTCOMES:
        return LABEL_NO_RESPONSE
    return LABEL_NOT_RECORDED


def first_redirect_label(page: FullPageIntelligenceProfile) -> str:
    """The First Redirect cell: the first hop's code, or a dash when none applies."""
    if page.first_redirect_status is None:
        return NO_REDIRECT
    return str(page.first_redirect_status)
