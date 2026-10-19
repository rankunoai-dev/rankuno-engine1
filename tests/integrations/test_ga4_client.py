"""`Ga4ApiClient`: the scope gate, the caps, the retry rules and the leak rules (ADR 0038).

Every HTTP call is replaced. The shared rate buckets and the process-wide breaker
are reset per test, and the retry sleep is patched out so the suite stays fast.
Planted canaries (token, secret, response body) are carried through every
failure path and must appear in no exception text and no log record.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import requests
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import ConfigurationError, Ga4NotAuthorizedError, Ga4UnavailableError
from src.core.rate_limiter import RateLimiterRegistry
from src.integrations import base_client, ga4_client
from src.integrations.ga4_client import (
    ALLOWED_DIMENSIONS,
    ALLOWED_METRICS,
    GA4_READONLY_SCOPE,
    Ga4ApiClient,
    validate_report_fields,
)
from src.integrations.ga4_schemas import Ga4AccessToken

REFRESH = "1//0gREFRESH-CANARY-token"  # noqa: S105 - fake canary
ACCESS = "ya29.ACCESS-CANARY-token"  # noqa: S105 - fake canary
SECRET = "GOCSPX-SECRET-CANARY"  # noqa: S105 - fake canary
BODY = "RESPONSE-BODY-CANARY-quotes-the-request"
PROPERTY = "123456789"
HOST = "www.example.com"


class FakeResponse:
    def __init__(self, status: int, body: Any = None, *, text: str | None = None) -> None:
        """Test double: the scripted queue is filled per test."""
        self.status_code = status
        self._body = body
        self._text = text

    def json(self) -> Any:
        if self._text is not None:
            raise ValueError(self._text)
        return self._body


class Recorder:
    """Scripted HTTP: a queue of responses per method, and every call recorded."""

    def __init__(self) -> None:
        """Test double: the body and status are set per call."""
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.queue: list[object] = []

    def __call__(self, method: str, url: str | None = None, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url or "", kwargs))
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, FakeResponse)
        return item

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self("POST", url, **kwargs)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_client, "_SHARED_LIMITERS", RateLimiterRegistry())
    ga4_client._reset_breaker_for_tests()
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(ga4_client.requests, "post", recorder.post)
    monkeypatch.setattr(ga4_client.requests, "request", recorder)
    return recorder


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr(SECRET),
        "ga4_requests_per_minute": 6000,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _token(http: Recorder, *, scope: str | None = GA4_READONLY_SCOPE) -> Ga4AccessToken:
    body: dict[str, Any] = {"access_token": ACCESS}
    if scope is not None:
        body["scope"] = f"{scope} openid"
    http.queue.append(FakeResponse(200, body))
    return Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))


def _token_obj() -> Ga4AccessToken:
    return Ga4AccessToken(access_token=SecretStr(ACCESS))


# ---- the scope gate -----------------------------------------------------------


def test_refresh_with_the_read_scope_yields_a_token(http: Recorder) -> None:
    token = _token(http)
    assert token.access_token.get_secret_value() == ACCESS
    assert len(http.calls) == 1
    assert http.calls[0][2]["data"]["refresh_token"] == REFRESH


def test_refresh_without_a_scope_field_fails_closed(http: Recorder) -> None:
    http.queue.append(FakeResponse(200, {"access_token": ACCESS}))
    with pytest.raises(Ga4NotAuthorizedError) as info:
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    assert str(info.value) == "not authorized, re-add the account"


def test_refresh_with_only_a_gsc_scope_fails_closed(http: Recorder) -> None:
    """A Search Console token must never read GA4 by accident."""
    http.queue.append(
        FakeResponse(
            200,
            {
                "access_token": ACCESS,
                "scope": "https://www.googleapis.com/auth/webmasters.readonly",
            },
        )
    )
    with pytest.raises(Ga4NotAuthorizedError):
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))


def test_invalid_grant_is_a_refusal_not_an_outage_and_is_not_retried(http: Recorder) -> None:
    http.queue.append(FakeResponse(400, {"error": "invalid_grant", "detail": BODY}))
    with pytest.raises(Ga4NotAuthorizedError):
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    assert len(http.calls) == 1


def test_invalid_client_is_our_configuration_not_the_operators_credential(http: Recorder) -> None:
    http.queue.append(FakeResponse(401, {"error": "invalid_client"}))
    with pytest.raises(Ga4UnavailableError):
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))


def test_refresh_server_error_is_unavailable_and_called_exactly_once(http: Recorder) -> None:
    http.queue.append(FakeResponse(500, {"error": "server_error"}))
    with pytest.raises(Ga4UnavailableError):
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    assert len(http.calls) == 1  # a revoked or failing token is tried once


def test_refresh_transport_failure_names_the_class_only(
    http: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    http.queue.append(requests.ConnectionError(f"could not reach {REFRESH} {SECRET}"))
    with pytest.raises(Ga4UnavailableError) as info:
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    _assert_no_canary(str(info.value), caplog.text)


def test_missing_shared_oauth_client_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="GOOGLE_OAUTH_CLIENT_ID"):
        Ga4ApiClient(settings=_settings(google_oauth_client_id=None))


# ---- listing ------------------------------------------------------------------


def test_lists_properties_across_pages_and_skips_malformed_entries(http: Recorder) -> None:
    token = _token_obj()
    http.queue.append(
        FakeResponse(
            200,
            {
                "accountSummaries": [
                    {
                        "propertySummaries": [
                            {"property": "properties/111", "displayName": "Acme site"},
                            {"property": "properties/0", "displayName": "invalid id"},
                            {"property": "accounts/9", "displayName": "not a property"},
                            "not-a-dict",
                        ]
                    }
                ],
                "nextPageToken": "page-2",
            },
        )
    )
    http.queue.append(
        FakeResponse(
            200,
            {
                "accountSummaries": [
                    {"propertySummaries": [{"property": "properties/222", "displayName": "Two"}]}
                ]
            },
        )
    )
    listing = Ga4ApiClient(settings=_settings()).list_properties(token)
    assert [p.property_id for p in listing.properties] == ["111", "222"]
    assert listing.truncated is False
    assert http.calls[1][2]["params"]["pageToken"] == "page-2"


def test_listing_stops_at_the_page_cap_and_says_so(http: Recorder) -> None:
    token = _token_obj()
    http.queue.append(FakeResponse(200, {"accountSummaries": [], "nextPageToken": "more"}))
    listing = Ga4ApiClient(settings=_settings(ga4_max_list_pages=1)).list_properties(token)
    assert listing.truncated is True
    assert len(http.calls) == 1


def test_listing_refusal_is_not_authorized_and_not_retried(http: Recorder) -> None:
    token = _token_obj()
    http.queue.append(FakeResponse(403, {"error": {"message": BODY}}))
    with pytest.raises(Ga4NotAuthorizedError) as info:
        Ga4ApiClient(settings=_settings()).list_properties(token)
    assert str(info.value) == "not authorized, re-add the account"
    assert len(http.calls) == 1


def test_listing_429_is_retried_once_then_unavailable(http: Recorder) -> None:
    token = _token_obj()
    http.queue.extend([FakeResponse(429, {}), FakeResponse(429, {})])
    with pytest.raises(Ga4UnavailableError):
        Ga4ApiClient(settings=_settings()).list_properties(token)
    assert len(http.calls) == 2  # the first attempt and exactly one retry


# ---- the report ---------------------------------------------------------------


def _report_body(rows: list[dict[str, Any]], row_count: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"rows": rows}
    if row_count is not None:
        body["rowCount"] = row_count
    return body


def _row(host: str, path: str, views: str, sessions: str) -> dict[str, Any]:
    return {
        "dimensionValues": [{"value": host}, {"value": path}],
        "metricValues": [{"value": views}, {"value": sessions}],
    }


def test_report_keeps_only_this_host_and_parses_the_metrics(http: Recorder) -> None:
    http.queue.append(
        FakeResponse(
            200,
            _report_body(
                [
                    _row(HOST, "/pricing", "40", "12"),
                    _row("other.example.org", "/pricing", "999", "999"),
                    _row(HOST, "/bad", "not-a-number", "3"),
                ]
            ),
        )
    )
    report = Ga4ApiClient(settings=_settings()).run_host_report(
        _token_obj(), property_id=PROPERTY, host=HOST, row_limit=100
    )
    assert [(r.path, r.screen_page_views, r.sessions) for r in report.rows] == [
        ("/pricing", 40, 12)
    ]


def test_report_request_is_host_scoped_and_allowlisted(http: Recorder) -> None:
    http.queue.append(FakeResponse(200, _report_body([])))
    Ga4ApiClient(settings=_settings()).run_host_report(
        _token_obj(), property_id=PROPERTY, host=HOST, row_limit=100
    )
    _, url, kwargs = http.calls[0]
    body = kwargs["json"]
    assert url.endswith(f"/properties/{PROPERTY}:runReport")
    assert {d["name"] for d in body["dimensions"]} == ALLOWED_DIMENSIONS
    assert {m["name"] for m in body["metrics"]} == ALLOWED_METRICS
    assert body["dimensionFilter"]["filter"]["stringFilter"] == {
        "matchType": "EXACT",
        "value": HOST,
    }
    assert "userId" not in str(body) and "clientId" not in str(body)


def test_row_limit_is_clamped_to_the_settings_cap(http: Recorder) -> None:
    http.queue.append(FakeResponse(200, _report_body([])))
    Ga4ApiClient(settings=_settings(ga4_max_rows_per_request=50)).run_host_report(
        _token_obj(), property_id=PROPERTY, host=HOST, row_limit=10_000
    )
    assert http.calls[0][2]["json"]["limit"] == "50"


def test_truncation_is_reported_when_the_property_holds_more_rows(http: Recorder) -> None:
    http.queue.append(FakeResponse(200, _report_body([_row(HOST, "/a", "1", "1")], row_count=900)))
    report = Ga4ApiClient(settings=_settings()).run_host_report(
        _token_obj(), property_id=PROPERTY, host=HOST, row_limit=10
    )
    assert report.truncated is True
    assert report.row_count == 900


def test_a_429_is_retried_once_and_then_succeeds(http: Recorder) -> None:
    http.queue.extend([FakeResponse(429, {}), FakeResponse(200, _report_body([]))])
    report = Ga4ApiClient(settings=_settings()).run_host_report(
        _token_obj(), property_id=PROPERTY, host=HOST, row_limit=10
    )
    assert report.rows == ()
    assert len(http.calls) == 2


def test_two_consecutive_429s_stop_after_one_retry(http: Recorder) -> None:
    http.queue.extend([FakeResponse(429, {}), FakeResponse(429, {}), FakeResponse(200, {})])
    with pytest.raises(Ga4UnavailableError):
        Ga4ApiClient(settings=_settings()).run_host_report(
            _token_obj(), property_id=PROPERTY, host=HOST, row_limit=10
        )
    assert len(http.calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404])
def test_refusals_are_never_retried(http: Recorder, status: int) -> None:
    http.queue.append(FakeResponse(status, {"error": BODY}))
    with pytest.raises(Ga4NotAuthorizedError):
        Ga4ApiClient(settings=_settings()).run_host_report(
            _token_obj(), property_id=PROPERTY, host=HOST, row_limit=10
        )
    assert len(http.calls) == 1


def test_malformed_property_or_host_is_refused_before_any_request(http: Recorder) -> None:
    client = Ga4ApiClient(settings=_settings())
    with pytest.raises(ValueError, match="numeric form"):
        client.run_host_report(_token_obj(), property_id="12 3", host=HOST, row_limit=1)
    with pytest.raises(ValueError, match="hostname"):
        client.run_host_report(
            _token_obj(), property_id=PROPERTY, host="evil.com/path", row_limit=1
        )
    assert http.calls == []


def test_allowlist_refuses_a_user_level_dimension() -> None:
    with pytest.raises(ValueError, match="userId"):
        validate_report_fields(("userId",), allowed=ALLOWED_DIMENSIONS)
    assert "userId" not in ALLOWED_DIMENSIONS
    assert "clientId" not in ALLOWED_DIMENSIONS
    assert frozenset({"screenPageViews", "sessions"}) == ALLOWED_METRICS


def test_the_request_rate_comes_from_settings_not_a_constant() -> None:
    client = Ga4ApiClient(settings=_settings(ga4_requests_per_minute=42))
    assert client._quota_per_minute() == 42


# ---- the service-level breaker -----------------------------------------------


def test_breaker_opens_after_threshold_and_refuses_without_a_request(http: Recorder) -> None:
    settings = _settings(ga4_breaker_failure_threshold=2)
    client = Ga4ApiClient(settings=settings)
    for _ in range(2):
        http.queue.extend([FakeResponse(500, {}), FakeResponse(500, {})])
        with pytest.raises(Ga4UnavailableError):
            client.run_host_report(_token_obj(), property_id=PROPERTY, host=HOST, row_limit=1)
    calls_before = len(http.calls)
    with pytest.raises(Ga4UnavailableError):
        client.run_host_report(_token_obj(), property_id=PROPERTY, host=HOST, row_limit=1)
    assert len(http.calls) == calls_before


def test_refusals_do_not_trip_the_breaker(http: Recorder) -> None:
    settings = _settings(ga4_breaker_failure_threshold=2)
    client = Ga4ApiClient(settings=settings)
    for _ in range(3):
        http.queue.append(FakeResponse(403, {}))
        with pytest.raises(Ga4NotAuthorizedError):
            client.run_host_report(_token_obj(), property_id=PROPERTY, host=HOST, row_limit=1)
    http.queue.append(FakeResponse(200, _report_body([])))
    report = client.run_host_report(_token_obj(), property_id=PROPERTY, host=HOST, row_limit=1)
    assert report.rows == ()


# ---- leakage ------------------------------------------------------------------


def _assert_no_canary(*surfaces: str) -> None:
    for surface in surfaces:
        for canary in (REFRESH, ACCESS, SECRET, BODY):
            assert canary not in surface


def test_no_canary_reaches_an_exception_or_a_log_on_any_failure_path(
    http: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    failures: list[Ga4UnavailableError | Ga4NotAuthorizedError] = []

    http.queue.append(FakeResponse(400, {"error": "invalid_grant", "detail": BODY}))
    try:
        Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    except Ga4NotAuthorizedError as exc:
        failures.append(exc)

    http.queue.append(FakeResponse(500, {"error": BODY, "token": ACCESS}))
    http.queue.append(FakeResponse(500, {"error": BODY, "token": ACCESS}))
    try:
        Ga4ApiClient(settings=_settings()).run_host_report(
            _token_obj(), property_id=PROPERTY, host=HOST, row_limit=1
        )
    except Ga4UnavailableError as exc:
        failures.append(exc)

    http.queue.append(FakeResponse(403, {"error": {"message": BODY}}))
    try:
        Ga4ApiClient(settings=_settings()).list_properties(_token_obj())
    except Ga4NotAuthorizedError as exc:
        failures.append(exc)

    assert len(failures) == 3
    _assert_no_canary(*(str(f) for f in failures), caplog.text)


def test_no_canary_reaches_a_success_path_log_either(
    http: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    http.queue.append(
        FakeResponse(200, {"access_token": ACCESS, "scope": GA4_READONLY_SCOPE, "x": BODY})
    )
    token = Ga4ApiClient(settings=_settings()).refresh_access_token(SecretStr(REFRESH))
    http.queue.append(FakeResponse(200, _report_body([_row(HOST, "/a", "1", "1")])))
    Ga4ApiClient(settings=_settings()).run_host_report(
        token, property_id=PROPERTY, host=HOST, row_limit=10
    )
    _assert_no_canary(caplog.text, repr(token))
