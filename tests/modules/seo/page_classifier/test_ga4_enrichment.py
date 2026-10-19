"""GA4 page enrichment: every outcome is a fixed status, and nothing is inferred (ADR 0038).

The store and the connector are both fakes. What is tested is the decision the
crawl makes: which property may be read, whether the request is spent, what the
join attaches, and what the report says when it does not. Each refusal path is
checked for absence of the planted canaries in its report and in the log.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from src.core.config import Settings
from src.core.errors import (
    ConfigurationError,
    Ga4AccessStoreUnavailableError,
    Ga4CredentialDecryptionError,
    Ga4NotAuthorizedError,
    Ga4UnavailableError,
    IntegrationError,
)
from src.core.ga4_access_store import Ga4AccessSummary
from src.integrations.ga4_budget import Ga4DailyBudget
from src.integrations.ga4_schemas import Ga4AccessToken, Ga4HostReport, Ga4PageMetrics
from src.modules.seo.page_classifier import ga4_enrichment
from src.modules.seo.page_classifier.ga4_enrichment import (
    REASON_FAILED,
    REASON_NOT_AUTHORIZED,
    REASON_NOT_CONFIGURED,
    REASON_UNMAPPED,
    Ga4EnrichmentReport,
    run_ga4_enrichment,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import PageClassificationInput

BASE = "https://e.com/"
PROPERTY = "123456789"
REFRESH_CANARY = "1//0gGA4-REFRESH-CANARY"  # noqa: S105 - fake canary
ENV_CANARY = "1//0gENV-GSC-DEFAULT-CANARY"  # noqa: S105 - fake canary
DETAIL_CANARY = "RESPONSE-BODY-CANARY"


def _page(url: str) -> FullPageIntelligenceProfile:
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.9,
            ),
        ),
        final_confidence_score=0.9,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        final_url=url,
    )


class FakeStore:
    """A `Ga4AccessStore` holding one row per org, as the Postgres store would."""

    def __init__(self) -> None:
        """Test double: the store starts empty."""
        self.mapping: dict[str, str | None] = {}
        self.tokens: dict[str, SecretStr] = {}
        self.status_error: Exception | None = None
        self.token_error: Exception | None = None

    def status(self, org_id: str) -> Ga4AccessSummary:
        if self.status_error is not None:
            raise self.status_error
        if org_id not in self.mapping:
            return Ga4AccessSummary(has_credential=False, property_id=None)
        return Ga4AccessSummary(has_credential=True, property_id=self.mapping[org_id])

    def refresh_token(self, org_id: str) -> SecretStr | None:
        if self.token_error is not None:
            raise self.token_error
        return self.tokens.get(org_id)


class FakeClient:
    """Stands in for `Ga4ApiClient`. Behaviour is set by the `scripted` fixture."""

    scripted: Any = None
    calls: list[tuple[str, Any]] = []

    def __init__(self, settings: Settings | None = None) -> None:
        """Test double: the connector needs no setup here."""
        FakeClient.calls.append(("init", None))

    def refresh_access_token(self, refresh_token: SecretStr) -> Ga4AccessToken:
        FakeClient.calls.append(("refresh", refresh_token.get_secret_value()))
        if FakeClient.scripted.refresh_error is not None:
            raise FakeClient.scripted.refresh_error
        return Ga4AccessToken(access_token=SecretStr("ACCESS"))

    def run_host_report(
        self, token: Ga4AccessToken, *, property_id: str, host: str, row_limit: int
    ) -> Ga4HostReport:
        FakeClient.calls.append(("report", (property_id, host, row_limit)))
        if FakeClient.scripted.report_error is not None:
            raise FakeClient.scripted.report_error
        return FakeClient.scripted.report


class Scripted:
    def __init__(self) -> None:
        """Test double: the connector needs no setup here."""
        self.refresh_error: Exception | None = None
        self.report_error: Exception | None = None
        self.report = Ga4HostReport(
            host="e.com",
            rows=(
                Ga4PageMetrics(path="/pricing", screen_page_views=40, sessions=12),
                Ga4PageMetrics(path="/blog", screen_page_views=5, sessions=2),
                Ga4PageMetrics(path="/pricing", screen_page_views=10, sessions=3),
            ),
            row_count=3,
        )


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Scripted:
    FakeClient.calls = []
    behaviour = Scripted()
    FakeClient.scripted = behaviour
    monkeypatch.setattr(ga4_enrichment, "Ga4ApiClient", FakeClient)
    monkeypatch.setattr(ga4_enrichment, "DAILY_BUDGET", Ga4DailyBudget())
    return behaviour


@pytest.fixture
def store() -> FakeStore:
    fake = FakeStore()
    fake.mapping["acme"] = PROPERTY
    fake.tokens["acme"] = SecretStr(REFRESH_CANARY)
    return fake


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _run(
    store_: FakeStore | None,
    *,
    org: str = "acme",
    property_id: str | None = PROPERTY,
    pages: tuple[FullPageIntelligenceProfile, ...] | None = None,
    settings: Settings | None = None,
) -> tuple[tuple[FullPageIntelligenceProfile, ...], Ga4EnrichmentReport]:
    return run_ga4_enrichment(
        pages if pages is not None else (_page(BASE), _page("https://e.com/blog?x=1")),
        base_url=BASE,
        ga4_property_id=property_id,
        org_id=org,
        store=store_,
        settings=settings or _settings(),
    )


# ---- the decision -------------------------------------------------------------


def test_not_requested_touches_nothing(store: FakeStore, scripted: Scripted) -> None:
    pages, report = _run(store, property_id=None)
    assert report.status == "not_requested"
    assert report.reason == ""
    assert FakeClient.calls == []
    assert all(p.ga4_sessions is None for p in pages)


def test_no_store_is_reported_as_not_configured(scripted: Scripted) -> None:
    _, report = _run(None)
    assert report.status == "unmapped"
    assert report.reason == REASON_NOT_CONFIGURED
    assert FakeClient.calls == []


def test_a_different_property_than_the_mapping_is_refused(
    store: FakeStore, scripted: Scripted
) -> None:
    _, report = _run(store, property_id="999")
    assert report.status == "unmapped"
    assert report.reason == REASON_UNMAPPED
    assert FakeClient.calls == []


def test_an_unmapped_org_is_not_requested_with_the_fixed_reason(
    store: FakeStore, scripted: Scripted
) -> None:
    store.mapping["acme"] = None
    _, report = _run(store)
    assert report.status == "unmapped"
    assert report.reason == REASON_UNMAPPED
    assert FakeClient.calls == []


def test_more_pages_than_the_cap_is_over_cap_and_not_joined(
    store: FakeStore, scripted: Scripted
) -> None:
    _, report = _run(store, settings=_settings(ga4_max_pages_per_crawl=1))
    assert report.status == "over_cap"
    assert FakeClient.calls == []


def test_an_exhausted_daily_budget_is_over_budget(store: FakeStore, scripted: Scripted) -> None:
    _, report = _run(store, settings=_settings(ga4_daily_calls_per_org=0))
    assert report.status == "over_budget"
    assert FakeClient.calls == []


def test_success_joins_by_path_within_the_host_and_counts_matches(
    store: FakeStore, scripted: Scripted
) -> None:
    pages, report = _run(
        store,
        pages=(
            _page("https://e.com/pricing/"),
            _page("https://e.com/blog?x=1"),
            _page("https://e.com/about"),
        ),
    )
    assert report.status == "succeeded"
    assert report.property_id == PROPERTY
    assert report.pages_crawled == 3
    assert report.pages_matched == 2
    assert report.rows_used == 3
    by_url = {p.url: p for p in pages}
    # Two /pricing rows are summed: the join is by path, not by row.
    assert by_url["https://e.com/pricing/"].ga4_sessions == 15
    assert by_url["https://e.com/pricing/"].ga4_screen_page_views == 50
    assert by_url["https://e.com/blog?x=1"].ga4_sessions == 2
    assert by_url["https://e.com/about"].ga4_sessions is None


def test_one_host_scoped_report_is_requested_per_crawl(
    store: FakeStore, scripted: Scripted
) -> None:
    _run(store, settings=_settings(ga4_max_rows_per_request=77))
    reports = [c for c in FakeClient.calls if c[0] == "report"]
    assert reports == [("report", (PROPERTY, "e.com", 77))]


def test_a_truncated_report_says_so(store: FakeStore, scripted: Scripted) -> None:
    scripted.report = Ga4HostReport(
        host="e.com",
        rows=(Ga4PageMetrics(path="/blog", screen_page_views=1, sessions=1),),
        row_count=500,
        truncated=True,
    )
    _, report = _run(store)
    assert report.truncated is True
    assert report.rows_available == 500
    assert report.rows_used == 1


# ---- refusals and outages: fixed reasons only ---------------------------------


def test_a_scope_refusal_is_not_authorized_with_the_fixed_reason(
    store: FakeStore, scripted: Scripted
) -> None:
    scripted.refresh_error = Ga4NotAuthorizedError()
    pages, report = _run(store)
    assert report.status == "not_authorized"
    assert report.reason == REASON_NOT_AUTHORIZED
    assert all(p.ga4_sessions is None for p in pages)


def test_a_report_refusal_is_not_authorized(store: FakeStore, scripted: Scripted) -> None:
    scripted.report_error = Ga4NotAuthorizedError()
    _, report = _run(store)
    assert report.status == "not_authorized"


@pytest.mark.parametrize(
    "error",
    [
        Ga4UnavailableError(),
        IntegrationError("google.analytics", "run_host_report: HTTP 503"),
        Ga4CredentialDecryptionError(),
        ValueError("bad host"),
    ],
)
def test_an_outage_or_a_bad_row_is_failed_with_the_fixed_reason(
    store: FakeStore, scripted: Scripted, error: Exception
) -> None:
    scripted.report_error = error
    pages, report = _run(store)
    assert report.status == "failed"
    assert report.reason == REASON_FAILED
    assert all(p.ga4_sessions is None for p in pages)


def test_a_store_outage_is_failed_not_unmapped(store: FakeStore, scripted: Scripted) -> None:
    """Unknown is not the same as unmapped: an outage must not look like a choice."""
    store.status_error = Ga4AccessStoreUnavailableError()
    _, report = _run(store)
    assert report.status == "failed"
    assert report.reason == REASON_FAILED


def test_a_missing_oauth_client_is_failed_with_its_own_reason(
    store: FakeStore, scripted: Scripted
) -> None:
    scripted.refresh_error = ConfigurationError("GOOGLE_OAUTH_CLIENT_ID is missing")
    _, report = _run(store)
    assert report.status == "failed"
    assert "shared OAuth client" in report.reason


# ---- isolation ----------------------------------------------------------------


def test_the_environment_refresh_token_is_never_used_for_ga4(
    store: FakeStore, scripted: Scripted
) -> None:
    """A mapped org with no stored token gets `unmapped`, never the GSC default token."""
    store.tokens.clear()
    settings = _settings(google_oauth_refresh_token=SecretStr(ENV_CANARY))
    _, report = _run(store, settings=settings)
    assert report.status == "unmapped"
    assert FakeClient.calls == []
    assert ENV_CANARY not in report.model_dump_json()


def test_another_org_gets_the_same_result_as_an_org_with_no_row(
    store: FakeStore, scripted: Scripted
) -> None:
    """Org isolation: `globex` asking for acme's property sees what a stranger sees."""
    _, stranger = _run(store, org="nobody-here")
    _, globex = _run(store, org="globex")
    assert globex == stranger
    assert globex.status == "unmapped"
    assert FakeClient.calls == []


def test_the_same_org_gets_identical_results_on_repeat(
    store: FakeStore, scripted: Scripted
) -> None:
    first = _run(store)[1]
    second = _run(store)[1]
    assert first.status == second.status == "succeeded"
    assert first.pages_matched == second.pages_matched


# ---- leakage ------------------------------------------------------------------


def test_no_canary_reaches_a_report_or_a_log_on_any_refusal(
    store: FakeStore, scripted: Scripted, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    scripted.report_error = IntegrationError(
        "google.analytics", f"run_host_report: {DETAIL_CANARY} {REFRESH_CANARY}"
    )
    _, report = _run(store)
    assert report.status == "failed"
    surfaces = (report.model_dump_json(), caplog.text)
    for canary in (REFRESH_CANARY, DETAIL_CANARY, ENV_CANARY):
        for surface in surfaces:
            assert canary not in surface


def test_the_property_id_itself_is_not_logged(
    store: FakeStore, scripted: Scripted, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _run(store)
    assert PROPERTY not in caplog.text


# ---- the intake shape ---------------------------------------------------------


@pytest.mark.parametrize("good", [None, "1", "123456789", "9" * 20])
def test_crawl_input_accepts_a_numeric_property_or_none(good: str | None) -> None:
    payload = PageClassificationInput(base_url=BASE, ga4_property_id=good)
    assert payload.ga4_property_id == good


@pytest.mark.parametrize("bad", ["0123", "12 3", "123\n", "properties/123", "9" * 21, ""])
def test_crawl_input_refuses_anything_else(bad: str) -> None:
    with pytest.raises(ValidationError):
        PageClassificationInput(base_url=BASE, ga4_property_id=bad)
