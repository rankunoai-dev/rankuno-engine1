"""Request and response helpers for the Search Console page and query fetches.

These live apart from `gsc_client.py` for two reasons. The client's file-size
ceiling would otherwise be breached by the paging, error mapping and row parsing
that both fetches need. And keeping one copy of "what a row means" means the
page-metrics fetch and the query fetch cannot quietly disagree about how a
property is named, how a 403 is classified, or how a row's counters are read.

Nothing here performs I/O. Every function is a pure transformation of a value
already received, so each one can be tested without a network or a mock client.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, Final, NoReturn

from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from src.core.errors import (
    GscApiDeprecatedError,
    GscAuthorizationError,
    GscPropertyNotFoundError,
    GscQuotaExceededError,
)
from src.integrations.gsc_schemas import GscPageMetrics, GscQueryRow

__all__ = [
    "DOMAIN_PROPERTY_PREFIX",
    "MAX_PAGES",
    "ROW_LIMIT_MAX",
    "api_property_url",
    "check_row_limit",
    "page_metrics",
    "query_rows",
    "raise_mapped_http_error",
]

MAX_PAGES: Final[int] = 40
"""Ceiling on requests in one paged fetch.

At Search Console's 25,000-row page size this is one million rows, which bounds
both the quota one fetch can spend and the memory the response can occupy. A
fetch that reaches it reports `row_cap` rather than pretending to be complete.
"""

ROW_LIMIT_MAX: Final[int] = 25000
"""Search Console's per-request row ceiling. A larger `rowLimit` is refused by the API."""

DOMAIN_PROPERTY_PREFIX: Final[str] = "sc-domain:"
"""How Search Console names a Domain property: `sc-domain:example.com`."""


def api_property_url(property_url: str) -> str:
    """The `siteUrl` a property must be sent as, which is not always the input.

    A URL-prefix property is listed with a trailing slash. A domain property is
    not, and `sc-domain:example.com/` names nothing. Matched case-insensitively,
    as the form and the validator do, and sent in the lowercase form Search
    Console lists it under.
    """
    if property_url.lower().startswith(DOMAIN_PROPERTY_PREFIX):
        return property_url.rstrip("/").lower()
    if property_url.endswith("/"):
        return property_url
    return f"{property_url}/"


def check_row_limit(row_limit: int) -> None:
    """Refuse a page size the API would reject, before any request is made.

    Raises:
        ValueError: If `row_limit` is outside 1 to 25,000.
    """
    if not 1 <= row_limit <= ROW_LIMIT_MAX:
        msg = f"row_limit must be between 1 and {ROW_LIMIT_MAX}, got {row_limit}"
        raise ValueError(msg)


def raise_mapped_http_error(exc: HttpError, property_url: str) -> NoReturn:
    """Raise the typed error for an HTTP status, or re-raise `exc` for retry to handle.

    A 404 or 403 becomes a refusal the caller can act on, because an empty result
    would read as "no search data". A 429, 410 or 501 becomes a mapped error that
    the caller degrades on. Anything else is re-raised unchanged so the retry
    policy sees the original transport error.
    """
    status_code = exc.resp.status
    reason = exc.resp.reason or "Unknown"

    if status_code == 404:
        raise GscPropertyNotFoundError(property_url) from exc
    if status_code == 403:
        raise GscAuthorizationError(
            f"Property not accessible or verification pending: {reason}"
        ) from exc
    if status_code == 429:
        retry_after = None
        if "retry-after" in exc.resp:
            with suppress(ValueError, TypeError):
                retry_after = float(exc.resp["retry-after"])
        raise GscQuotaExceededError(retry_after_s=retry_after) from exc
    if status_code == 410:
        raise GscApiDeprecatedError(410, f"Endpoint deprecated: {reason}") from exc
    if status_code == 501:
        raise GscApiDeprecatedError(501, f"Endpoint not implemented: {reason}") from exc
    raise exc


def _counters(row: Mapping[str, Any]) -> tuple[int, int, float]:
    """Clicks, impressions and position from one API row, with absent fields as zero."""
    return (
        int(row.get("clicks", 0)),
        int(row.get("impressions", 0)),
        float(row.get("position", 1.0)),
    )


def page_metrics(rows: Sequence[Mapping[str, Any]]) -> list[GscPageMetrics]:
    """Parse page-level rows, skipping any row that carries no key.

    CTR is derived here from the two counters and clamped to [0, 1]. Search
    Console's own CTR is not read, because a row's CTR is only meaningful beside
    the counters it was computed from.
    """
    parsed: list[GscPageMetrics] = []
    for row in rows:
        keys = row.get("keys", [])
        if not keys:
            continue
        clicks, impressions, position = _counters(row)
        ctr = (clicks / impressions) if impressions > 0 else 0.0
        parsed.append(
            GscPageMetrics(
                url=keys[0],
                impressions=impressions,
                clicks=clicks,
                avg_position=position,
                ctr=min(1.0, max(0.0, ctr)),
            )
        )
    return parsed


def query_rows(rows: Sequence[Mapping[str, Any]]) -> list[GscQueryRow]:
    """Parse (page, query) rows, skipping any row without both keys.

    The request asks for `["page", "query"]` in that order, so `keys[0]` is the
    page and `keys[1]` the query. A row missing either is skipped rather than
    guessed at.
    """
    parsed: list[GscQueryRow] = []
    for row in rows:
        keys = row.get("keys", [])
        if len(keys) < 2:
            continue
        clicks, impressions, position = _counters(row)
        parsed.append(
            GscQueryRow(
                page=keys[0],
                query=keys[1],
                clicks=clicks,
                impressions=impressions,
                avg_position=position,
            )
        )
    return parsed
