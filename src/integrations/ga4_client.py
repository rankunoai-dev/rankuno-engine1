"""Google Analytics 4 connector: the access gate, the property list and one host report (ADR 0038).

Three operations, all read-only:

1. `refresh_access_token` exchanges the organisation's GA4 refresh token for an
   access token, and **requires the analytics read scope** in the response
   before anything else runs. A missing or different scope is
   `Ga4NotAuthorizedError`: a GSC-only token must never read GA4 by accident.
2. `list_properties` lists the properties that token can see, for the picker.
3. `run_host_report` makes exactly one report request per crawl, filtered to
   the crawl's host, over an allowlisted set of dimensions and metrics.

Design stance:

* **Every request is a `BaseAPIClient.call()`.** The shared rate bucket runs
  before the retry wrapper, so a retry storm cannot bypass the quota (base
  client). Calls are made from methods on this subclass only (CLAUDE.md §1).
* **Retries are capped per operation.** A 429 or transient failure is retried
  once (`max_attempts=2`). A 401, 403 or 404 is never retried: it is a
  decision by Google, and retrying a revoked token only adds requests.
* **Refusals are data, not exceptions inside the retry loop.** `attempt()`
  returns `None` for a refusal, so it leaves `call()` without being retried or
  re-wrapped. The public methods then raise the fixed-reason exceptions.
* **Nothing from a response body reaches an exception, a log or a return
  value** except the fields this module names. Transport failures are recorded
  by exception class only (C8, C9).
* **A service-level breaker** (process-wide, `Settings`-tuned) stops calls after
  repeated transport failures. Refusals do not trip it, because a 403 means the
  service answered.
* **Quotas are Settings, not constants.** The request rate, row limit and page
  caps are operator values marked UNVERIFIED in `Settings`.
* **The refresh and listing calls use the shared OAuth client** from
  `Settings`. A GA4 credential does not carry its own client id (ADR 0038).

The endpoint paths and field names below are the documented shapes as this
code was written. They are UNVERIFIED against a live property here, because no
live credential is available to this repository. Confirm before relying on them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import requests
from pydantic import SecretStr

from src.core.circuit_breaker import CircuitBreaker
from src.core.config import Settings
from src.core.errors import (
    ConfigurationError,
    Ga4NotAuthorizedError,
    Ga4UnavailableError,
    IntegrationError,
)
from src.core.ga4_access_store import is_valid_ga4_property_id
from src.core.logger import get_logger
from src.integrations.base_client import BaseAPIClient
from src.integrations.ga4_schemas import (
    Ga4AccessToken,
    Ga4HostReport,
    Ga4PageMetrics,
    Ga4PropertyChoice,
    Ga4PropertyList,
)

__all__ = [
    "ALLOWED_DIMENSIONS",
    "ALLOWED_METRICS",
    "GA4_READONLY_SCOPE",
    "Ga4ApiClient",
    "validate_report_fields",
]

_logger = get_logger("integrations.ga4_client")

GA4_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
"""ASSUMPTION, to confirm against Google's current scope list: the read-only GA4
scope. Read from the refresh response and required, never assumed granted."""

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint URL
ADMIN_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
"""UNVERIFIED path: the Admin API account-summaries listing."""
REPORT_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
"""UNVERIFIED path: the Data API run-report method for one property."""

ALLOWED_DIMENSIONS: frozenset[str] = frozenset({"hostName", "pagePath"})
"""Host and path only. No user-level or client-level dimension is ever requested."""
ALLOWED_METRICS: frozenset[str] = frozenset({"screenPageViews", "sessions"})
REPORT_WINDOW = ("365daysAgo", "today")
"""UNVERIFIED window: the relative date strings the Data API documents."""
_ADMIN_PAGE_SIZE = 200
"""UNVERIFIED page size for account summaries."""
_REFUSED_OAUTH_ERRORS = frozenset({"invalid_grant", "unauthorized_client"})
"""OAuth error codes meaning the grant itself is revoked or not usable. Any other
refusal (such as `invalid_client`) is our configuration, not the operator's
credential, and is reported as unavailable instead."""
_HOST_RE = re.compile(r"[a-z0-9.-]{1,253}")
_REFUSED_STATUSES = frozenset({401, 403, 404})
_SERVICE = "google.analytics"

_BREAKER: CircuitBreaker | None = None


def validate_report_fields(
    names: frozenset[str] | tuple[str, ...], *, allowed: frozenset[str]
) -> None:
    """Refuse any dimension or metric outside the allowlist.

    Raises:
        ValueError: A name is not in `allowed`. The name is quoted, because it
            is a code-side constant, never operator or user data.
    """
    for name in names:
        if name not in allowed:
            msg = f"GA4 field '{name}' is not in the allowlist"
            raise ValueError(msg)


def _service_breaker(settings: Settings) -> CircuitBreaker:
    """The one breaker every GA4 client in this process shares (service-level)."""
    global _BREAKER  # noqa: PLW0603 - a process-wide breaker is the point
    if _BREAKER is None:
        _BREAKER = CircuitBreaker(
            failure_threshold=settings.ga4_breaker_failure_threshold,
            recovery_timeout_s=settings.ga4_breaker_recovery_s,
        )
    return _BREAKER


def _reset_breaker_for_tests() -> None:
    """Forget the shared breaker. Tests only; production never resets it."""
    global _BREAKER  # noqa: PLW0603
    _BREAKER = None


def _parse_property_id(resource: object) -> str | None:
    """`properties/123` to `123`, or `None` for anything else."""
    if not isinstance(resource, str) or not resource.startswith("properties/"):
        return None
    candidate = resource.removeprefix("properties/")
    return candidate if is_valid_ga4_property_id(candidate) else None


def _as_int(value: object) -> int | None:
    """A GA4 metric value, which the API sends as a decimal string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class Ga4ApiClient(BaseAPIClient):
    """Google Analytics 4 connector, read-only (ADR 0038).

    Class variables from `BaseAPIClient`: `service_name` is the audit identity,
    and `rate_limit_key` names the shared GA4 bucket. The request rate comes from
    `Settings.ga4_requests_per_minute` through `_quota_per_minute`, not a constant.
    """

    service_name = _SERVICE
    rate_limit_key = "ga4_quota"

    def __init__(self, settings: Settings | None = None) -> None:
        """Build the connector and bind it to the process-wide breaker.

        Raises:
            ConfigurationError: The shared OAuth client is not configured.
        """
        super().__init__(settings=settings)
        self._breaker = _service_breaker(self._settings)
        self.authenticate()

    def _quota_per_minute(self) -> int:
        """The operator's GA4 request rate (UNVERIFIED default in `Settings`)."""
        return self._settings.ga4_requests_per_minute

    def authenticate(self) -> None:
        """Check the shared OAuth client is configured.

        Per-organisation tokens are read by the caller and passed in, so there is
        no session to establish here. Only the client identity is checked.

        Raises:
            ConfigurationError: The client id or secret is missing. The message
                names the variables, never their values.
        """
        if (
            not self._settings.google_oauth_client_id
            or self._settings.google_oauth_client_secret is None
        ):
            msg = (
                "GA4 needs the shared OAuth client: set GOOGLE_OAUTH_CLIENT_ID and "
                "GOOGLE_OAUTH_CLIENT_SECRET."
            )
            raise ConfigurationError(msg)

    def _guarded(self, operation: str, attempt: Callable[[], Any], *, max_attempts: int) -> Any:
        """Run one operation under the breaker, the bucket and the retry cap.

        Raises:
            Ga4UnavailableError: The breaker is open, or the call failed after
                its retries. Never carries the upstream detail.
        """
        if self._breaker.is_open():
            raise Ga4UnavailableError
        try:
            result = self.call(operation, attempt, max_attempts=max_attempts)
        except IntegrationError as exc:
            self._breaker.record_failure(exc)
            raise Ga4UnavailableError from None
        self._breaker.record_success()
        return result

    def _request_json(
        self,
        operation: str,
        method: str,
        url: str,
        token: SecretStr,
        *,
        params: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """One authorised request. `None` for a refusal, a dict for success.

        Raises:
            IntegrationError: Transport failure, 429 or 5xx. Transient, so the
                caller's retry cap applies. Detail is the class or status only.
        """
        headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=self._settings.default_timeout_s,
            )
        except requests.RequestException as exc:
            raise IntegrationError(_SERVICE, f"{operation}: {type(exc).__name__}") from None
        status = response.status_code
        if status in _REFUSED_STATUSES:
            return None
        if status == 429 or status >= 500:
            raise IntegrationError(_SERVICE, f"{operation}: HTTP {status}")
        if not 200 <= status < 300:
            raise Ga4UnavailableError
        try:
            payload = response.json()
        except ValueError:
            raise IntegrationError(_SERVICE, f"{operation}: unreadable response") from None
        if not isinstance(payload, dict):
            raise IntegrationError(_SERVICE, f"{operation}: unexpected response shape")
        return payload

    def refresh_access_token(self, refresh_token: SecretStr) -> Ga4AccessToken:
        """Exchange a GA4 refresh token, and require the read scope in the grant.

        Runs outside the retry loop by design: a revoked token must fail once.

        Raises:
            Ga4NotAuthorizedError: The grant is revoked, or it does not include
                the analytics read scope. Fails closed, before any report.
            Ga4UnavailableError: Google could not be reached or refused for a
                transient reason.
        """
        self.authenticate()
        client_id: str = self._settings.google_oauth_client_id or ""
        client_secret = self._settings.google_oauth_client_secret
        secret_value: str = client_secret.get_secret_value() if client_secret is not None else ""
        refresh_value: str = refresh_token.get_secret_value()

        def attempt() -> Ga4AccessToken | None:
            try:
                response = requests.post(
                    GOOGLE_TOKEN_URI,
                    data={
                        "client_id": client_id,
                        "client_secret": secret_value,
                        "refresh_token": refresh_value,
                        "grant_type": "refresh_token",
                    },
                    timeout=self._settings.default_timeout_s,
                )
            except requests.RequestException as exc:
                raise IntegrationError(_SERVICE, f"refresh: {type(exc).__name__}") from None
            if response.status_code >= 400:
                # Google answers a revoked grant with HTTP 400 `invalid_grant`, so
                # the status alone does not decide it. The error code does.
                error = _oauth_error_code(response)
                if error in _REFUSED_OAUTH_ERRORS:
                    return None
                if response.status_code in _REFUSED_STATUSES and error is None:
                    return None
                raise IntegrationError(_SERVICE, f"refresh: HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                raise IntegrationError(_SERVICE, "refresh: unreadable response") from None
            if not isinstance(payload, dict):
                raise IntegrationError(_SERVICE, "refresh: unexpected response shape")
            access = payload.get("access_token")
            if not isinstance(access, str) or not access:
                raise IntegrationError(_SERVICE, "refresh: no access token")
            granted = payload.get("scope")
            scopes = granted.split() if isinstance(granted, str) else []
            if GA4_READONLY_SCOPE not in scopes:
                return None
            return Ga4AccessToken(access_token=SecretStr(access))

        token: Ga4AccessToken | None = self._guarded(
            "refresh_access_token", attempt, max_attempts=1
        )
        if token is None:
            raise Ga4NotAuthorizedError
        return token

    def list_properties(self, access_token: Ga4AccessToken) -> Ga4PropertyList:
        """Every property the token can see, up to `Settings.ga4_max_list_pages` pages.

        Raises:
            Ga4NotAuthorizedError: Google refused the listing.
            Ga4UnavailableError: Google could not be reached.
        """
        token = access_token.access_token
        choices: list[Ga4PropertyChoice] = []
        page_token: str | None = None
        truncated = False
        for page_index in range(self._settings.ga4_max_list_pages):
            params: dict[str, str | int] = {"pageSize": _ADMIN_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token

            def attempt(query: dict[str, str | int] = params) -> dict[str, Any] | None:
                return self._request_json(
                    "list_properties", "GET", ADMIN_SUMMARIES_URL, token, params=query
                )

            payload = self._guarded("list_properties", attempt, max_attempts=2)
            if payload is None:
                raise Ga4NotAuthorizedError
            choices.extend(_choices_from_page(payload))
            page_token = (
                payload.get("nextPageToken")
                if isinstance(payload.get("nextPageToken"), str)
                else None
            )
            if not page_token:
                break
            if page_index == self._settings.ga4_max_list_pages - 1:
                truncated = True
        return Ga4PropertyList(properties=tuple(choices), truncated=truncated)

    def run_host_report(
        self,
        access_token: Ga4AccessToken,
        *,
        property_id: str,
        host: str,
        row_limit: int,
    ) -> Ga4HostReport:
        """One report for one property, filtered to one host, over allowlisted fields.

        Args:
            access_token: A token that has passed the scope gate.
            property_id: The numeric property id, already validated.
            host: The crawl's host, lowercase, with no port, scheme or path.
            row_limit: Rows requested. Clamped to `Settings.ga4_max_rows_per_request`.

        Raises:
            ValueError: The property id, host or fields are malformed. Refused
                before any request is made.
            Ga4NotAuthorizedError: Google refused this property for this token.
            Ga4UnavailableError: Google could not be reached.
        """
        if not is_valid_ga4_property_id(property_id):
            msg = "GA4 property id is not in the expected numeric form"
            raise ValueError(msg)
        if _HOST_RE.fullmatch(host) is None:
            msg = "GA4 host filter is not a plain lowercase hostname"
            raise ValueError(msg)
        dimensions = ("hostName", "pagePath")
        metrics = ("screenPageViews", "sessions")
        validate_report_fields(dimensions, allowed=ALLOWED_DIMENSIONS)
        validate_report_fields(metrics, allowed=ALLOWED_METRICS)
        limit = max(1, min(row_limit, self._settings.ga4_max_rows_per_request))
        # UNVERIFIED body shape: field names follow the documented Data API
        # RunReportRequest. The host filter is exact, so no other host's rows
        # can join to this crawl's pages.
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": REPORT_WINDOW[0], "endDate": REPORT_WINDOW[1]}],
            "dimensions": [{"name": name} for name in dimensions],
            "metrics": [{"name": name} for name in metrics],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "hostName",
                    "stringFilter": {"matchType": "EXACT", "value": host},
                }
            },
            "limit": str(limit),
        }
        url = REPORT_URL.format(property_id=property_id)
        token = access_token.access_token

        def attempt() -> dict[str, Any] | None:
            return self._request_json("run_host_report", "POST", url, token, body=body)

        payload = self._guarded("run_host_report", attempt, max_attempts=2)
        if payload is None:
            raise Ga4NotAuthorizedError
        return _report_from_payload(payload, host=host)


def _oauth_error_code(response: requests.Response) -> str | None:
    """The OAuth `error` code of a refusal, or `None`. The body is never returned."""
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) and code.islower() and len(code) <= 40 else None


def _choices_from_page(payload: dict[str, Any]) -> list[Ga4PropertyChoice]:
    """Properties from one account-summaries page. Malformed entries are skipped."""
    choices: list[Ga4PropertyChoice] = []
    for summary in payload.get("accountSummaries", []) or []:
        if not isinstance(summary, dict):
            continue
        for prop in summary.get("propertySummaries", []) or []:
            if not isinstance(prop, dict):
                continue
            property_id = _parse_property_id(prop.get("property"))
            if property_id is None:
                continue
            name = prop.get("displayName")
            display = name[:200] if isinstance(name, str) else ""
            choices.append(Ga4PropertyChoice(property_id=property_id, display_name=display))
    return choices


def _report_from_payload(payload: dict[str, Any], *, host: str) -> Ga4HostReport:
    """Parse a run-report response, keeping only this host's rows and allowlisted values."""
    rows: list[Ga4PageMetrics] = []
    for row in payload.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensionValues") or []
        mets = row.get("metricValues") or []
        if len(dims) != 2 or len(mets) != 2:
            continue
        row_host = dims[0].get("value") if isinstance(dims[0], dict) else None
        path = dims[1].get("value") if isinstance(dims[1], dict) else None
        views = _as_int(mets[0].get("value") if isinstance(mets[0], dict) else None)
        sessions = _as_int(mets[1].get("value") if isinstance(mets[1], dict) else None)
        if row_host != host or not isinstance(path, str) or views is None or sessions is None:
            continue
        rows.append(Ga4PageMetrics(path=path[:2048], screen_page_views=views, sessions=sessions))
    row_count = _as_int(payload.get("rowCount")) or len(rows)
    return Ga4HostReport(
        host=host,
        rows=tuple(rows),
        row_count=row_count,
        truncated=row_count > len(rows),
    )
