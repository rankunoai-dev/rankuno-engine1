"""GA4 page metrics for one crawl: one host-scoped report, joined by path (ADR 0038).

Runs after Search Console enrichment and never fails the crawl. Every outcome
is a fixed status with a fixed reason, so an operator can tell "not requested",
"not mapped", "not authorised" and "Google was unavailable" apart. A silent empty
result is the one thing this module must never produce.

Design stance:

* **The org's mapping decides, never the request alone.** The request names a
  property, but it is checked against the organisation's stored mapping at the
  crawl, not at intake, because a mapping can be removed between the two. A
  mismatch is `unmapped`, not a silent use of some other property.
* **No environment fallback.** The GA4 token comes only from the org's store.
  `GOOGLE_OAUTH_REFRESH_TOKEN` and the `.env.local` GSC profiles are never
  consulted (CLAUDE.md §8, ADR 0038).
* **One report per crawl.** The whole crawl is joined from a single
  host-filtered request, so the call count is independent of the page count.
* **Path-level join, stated as such.** GA4 reports `pagePath`, which excludes
  the query string. Every crawled URL sharing a path therefore receives the same
  totals. The report says so rather than pretending the join is per URL.
* **Refusals are fixed reasons.** `reason` is one of the constants below, never
  a provider message, a response body or an exception's text (C8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from src.core.errors import (
    ConfigurationError,
    Ga4AccessStoreUnavailableError,
    Ga4CredentialDecryptionError,
    Ga4NotAuthorizedError,
    Ga4UnavailableError,
    IntegrationError,
)
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.integrations.ga4_budget import DAILY_BUDGET
from src.integrations.ga4_client import Ga4ApiClient
from src.integrations.ga4_schemas import Ga4HostReport, Ga4PageMetrics
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.core.ga4_access_store import Ga4AccessStore

__all__ = [
    "Ga4EnrichmentReport",
    "Ga4EnrichmentStatus",
    "run_ga4_enrichment",
]

_logger = get_logger(__name__)

Ga4EnrichmentStatus = Literal[
    "not_requested",
    "succeeded",
    "unmapped",
    "not_authorized",
    "over_cap",
    "over_budget",
    "failed",
]
"""What GA4 enrichment did. A closed set the UI reads, so a `Literal`, as GSC's is."""

REASON_NOT_REQUESTED = "not requested: no GA4 property was selected for this crawl"
REASON_UNMAPPED = "not requested: no GA4 property is mapped for this organisation"
REASON_NOT_CONFIGURED = "not requested: GA4 is not configured on this server"
REASON_OVER_CAP = "not requested: this crawl has more pages than the GA4 page cap"
REASON_OVER_BUDGET = "skipped: this organisation has used its GA4 calls for today"
REASON_NOT_AUTHORIZED = "not authorized, re-add the account"
REASON_FAILED = "GA4 data could not be fetched; the crawl completed without it"
REASON_OAUTH_CLIENT = "GA4 is not configured on this server: the shared OAuth client is missing"


class Ga4EnrichmentReport(StrictModel):
    """Whether GA4 metrics were attached, and why they were not.

    Attributes:
        status: Which of the outcomes occurred.
        property_id: The property queried. A numeric id, not a credential.
        pages_crawled: Pages offered to the join.
        pages_matched: Pages that received GA4 totals.
        rows_available: Rows the property holds for the host and window.
        rows_used: Rows read from the report.
        truncated: True when the report held more rows than were read.
        reason: A fixed explanation, or empty when the status needs none.
    """

    status: Ga4EnrichmentStatus = "not_requested"
    property_id: str | None = None
    pages_crawled: int = 0
    pages_matched: int = 0
    rows_available: int = 0
    rows_used: int = 0
    truncated: bool = False
    reason: str = ""


def _path_key(url: str) -> str:
    """The path GA4 would report for a URL: no host, no query, no trailing slash."""
    path = urlparse(url).path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return path


def _attach(
    pages: tuple[FullPageIntelligenceProfile, ...], report: Ga4HostReport
) -> tuple[tuple[FullPageIntelligenceProfile, ...], int]:
    """Join path totals onto pages. Returns the pages and how many received totals."""
    totals: dict[str, Ga4PageMetrics] = {}
    for row in report.rows:
        key = _path_key(row.path)
        previous = totals.get(key)
        if previous is None:
            totals[key] = row
        else:
            totals[key] = Ga4PageMetrics(
                path=key,
                screen_page_views=previous.screen_page_views + row.screen_page_views,
                sessions=previous.sessions + row.sessions,
            )
    matched = 0
    enriched: list[FullPageIntelligenceProfile] = []
    for page in pages:
        total = totals.get(_path_key(page.url))
        if total is None:
            enriched.append(page)
            continue
        matched += 1
        enriched.append(
            page.model_copy(
                update={
                    "ga4_screen_page_views": total.screen_page_views,
                    "ga4_sessions": total.sessions,
                }
            )
        )
    return tuple(enriched), matched


def _stop(
    status: Ga4EnrichmentStatus,
    *,
    crawled: int,
    property_id: str | None,
    reason: str,
) -> Ga4EnrichmentReport:
    """A report for an outcome that attached nothing."""
    return Ga4EnrichmentReport(
        status=status, property_id=property_id, pages_crawled=crawled, reason=reason
    )


def run_ga4_enrichment(
    pages: tuple[FullPageIntelligenceProfile, ...],
    *,
    base_url: str,
    ga4_property_id: str | None,
    org_id: str,
    store: Ga4AccessStore | None,
    settings: Settings,
) -> tuple[tuple[FullPageIntelligenceProfile, ...], Ga4EnrichmentReport]:
    """Attach GA4 path totals to the crawled pages, or explain why none were attached.

    Args:
        pages: Classified pages, already enriched by Search Console when asked.
        base_url: The crawl root. Its hostname is the report's host filter.
        ga4_property_id: The property the crawl asked for, or `None`.
        org_id: The organisation whose mapping and credential apply.
        store: The org's GA4 access store, or `None` when this deployment has none.
        settings: Caps and the shared OAuth client.

    Returns:
        The pages, with GA4 fields set where a path matched, and the report.
    """
    crawled = len(pages)
    if ga4_property_id is None:
        return pages, _stop("not_requested", crawled=crawled, property_id=None, reason="")
    if store is None:
        return pages, _stop(
            "unmapped", crawled=crawled, property_id=ga4_property_id, reason=REASON_NOT_CONFIGURED
        )
    if crawled > settings.ga4_max_pages_per_crawl:
        return pages, _stop(
            "over_cap", crawled=crawled, property_id=ga4_property_id, reason=REASON_OVER_CAP
        )
    try:
        mapped = store.status(org_id).property_id
    except Ga4AccessStoreUnavailableError:
        return pages, _stop(
            "failed", crawled=crawled, property_id=ga4_property_id, reason=REASON_FAILED
        )
    if mapped is None or mapped != ga4_property_id:
        return pages, _stop(
            "unmapped", crawled=crawled, property_id=ga4_property_id, reason=REASON_UNMAPPED
        )
    if not DAILY_BUDGET.try_spend(org_id, limit=settings.ga4_daily_calls_per_org):
        _logger.warning("ga4_daily_budget_reached", extra={"org": org_id})
        return pages, _stop(
            "over_budget", crawled=crawled, property_id=ga4_property_id, reason=REASON_OVER_BUDGET
        )

    host = (urlparse(base_url).hostname or "").lower()
    try:
        secret = store.refresh_token(org_id)
        if secret is None:
            return pages, _stop(
                "unmapped", crawled=crawled, property_id=ga4_property_id, reason=REASON_UNMAPPED
            )
        client = Ga4ApiClient(settings)
        token = client.refresh_access_token(secret)
        report = client.run_host_report(
            token,
            property_id=ga4_property_id,
            host=host,
            row_limit=settings.ga4_max_rows_per_request,
        )
    except Ga4NotAuthorizedError:
        return pages, _stop(
            "not_authorized",
            crawled=crawled,
            property_id=ga4_property_id,
            reason=REASON_NOT_AUTHORIZED,
        )
    except ConfigurationError:
        return pages, _stop(
            "failed", crawled=crawled, property_id=ga4_property_id, reason=REASON_OAUTH_CLIENT
        )
    except (
        Ga4UnavailableError,
        Ga4AccessStoreUnavailableError,
        Ga4CredentialDecryptionError,
        IntegrationError,
        ValueError,
    ) as exc:
        # The class name only. A decryption failure names no org, token or key,
        # and a transport failure's text can quote a request.
        _logger.warning(
            "ga4_enrichment_failed",
            extra={"org": org_id, "error": type(exc).__name__},
        )
        return pages, _stop(
            "failed", crawled=crawled, property_id=ga4_property_id, reason=REASON_FAILED
        )

    enriched, matched = _attach(pages, report)
    _logger.info(
        "ga4_enrichment_complete",
        extra={
            "org": org_id,
            "property_id_length": len(ga4_property_id),
            "pages_matched": matched,
            "rows_used": len(report.rows),
            "truncated": report.truncated,
        },
    )
    return enriched, Ga4EnrichmentReport(
        status="succeeded",
        property_id=ga4_property_id,
        pages_crawled=crawled,
        pages_matched=matched,
        rows_available=report.row_count,
        rows_used=len(report.rows),
        truncated=report.truncated,
    )
