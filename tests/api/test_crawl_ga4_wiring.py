"""The live crawl runner hands the org's GA4 access store to the tool (ADR 0038).

The GA4 unit tests call `run_ga4_enrichment` directly, so they cannot see a crawl
runner that forgets to pass the store: every real crawl then reports `unmapped`
with "GA4 is not configured on this server". This test drives the real crawl
runner (`_run_job`, via `POST /jobs`) over a mock HTTP transport, with an
in-memory store that maps the org to a property and a fake Google client.
Nothing reaches the network.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import get_settings
from src.core.ga4_access_store import Ga4AccessSummary
from src.core.state_store import DiskJobStore, DiskOrgConfigStore, JobStatus
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.ga4_budget import Ga4DailyBudget
from src.integrations.ga4_schemas import Ga4AccessToken, Ga4HostReport, Ga4PageMetrics
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier import ga4_enrichment
from src.modules.seo.page_classifier.tool import PageClassificationTool

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"
PROPERTY = "123456789"
HOME = "<html><head><title>Home</title></head><body><a href='/pricing/'>Pricing</a></body></html>"
PRICING = "<html><head><title>Pricing</title></head><body><p>Plans</p></body></html>"


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if path == "/":
        return httpx.Response(200, text=HOME, headers={"content-type": "text/html"})
    if path == "/pricing/":
        return httpx.Response(200, text=PRICING, headers={"content-type": "text/html"})
    return httpx.Response(404, text="not found")


class InMemoryGa4Store:
    """A `Ga4AccessStore` holding one row for the default org, mapped to PROPERTY."""

    def status(self, org_id: str) -> Ga4AccessSummary:
        return Ga4AccessSummary(has_credential=True, property_id=PROPERTY)

    def refresh_token(self, org_id: str) -> SecretStr | None:
        return SecretStr("fake-refresh-token")


class FakeGoogleClient:
    """Stands in for `Ga4ApiClient`. Returns one host report, touches no network."""

    def __init__(self, settings: object = None) -> None:
        """Test double: no setup needed."""

    def refresh_access_token(self, refresh_token: SecretStr) -> Ga4AccessToken:
        return Ga4AccessToken(access_token=SecretStr("fake-access-token"))

    def run_host_report(
        self, token: Ga4AccessToken, *, property_id: str, host: str, row_limit: int
    ) -> Ga4HostReport:
        assert property_id == PROPERTY
        return Ga4HostReport(
            host="e.com",
            rows=(
                Ga4PageMetrics(path="/pricing", screen_page_views=40, sessions=12),
                Ga4PageMetrics(path="/", screen_page_views=7, sessions=3),
            ),
            row_count=2,
        )


@pytest.fixture
def store(tmp_path: Any) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def mock_org_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(get_settings(), "_org_config_store", DiskOrgConfigStore(tmp_path / "orgs"))


@pytest.fixture
def mock_network(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    """The real tool, with its crawl fetcher on a mock transport (no sockets)."""

    class MockNetworkTool(PageClassificationTool):
        def __init__(self, **kwargs: object) -> None:
            fetcher = HttpFetcher(
                settings=settings,
                url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
                transport=httpx.MockTransport(_handler),
                async_transport=httpx.MockTransport(_handler),
            )
            super().__init__(fetcher=fetcher, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(server_module, "PageClassificationTool", MockNetworkTool)


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ga4_enrichment, "Ga4ApiClient", FakeGoogleClient)
    monkeypatch.setattr(ga4_enrichment, "DAILY_BUDGET", Ga4DailyBudget())


def _wait_terminal(store: DiskJobStore, job_id: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if store.get(job_id).is_terminal:
            return
        time.sleep(0.02)
    pytest.fail(f"job {job_id} never reached a terminal status")


def test_a_live_crawl_with_a_mapped_property_gets_ga4_totals(
    store, mock_org_store, mock_network, fake_google
):
    app: FastAPI = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        ga4_access_store=InMemoryGa4Store(),
    )

    with TestClient(app, headers=auth_headers()) as client:
        response = client.post(
            f"{API_PREFIX}/jobs",
            json={
                "base_url": SAFE_URL,
                "max_pages": 10,
                "crawl_dom": True,
                "concurrency": 1,
                "ga4_property_id": PROPERTY,
            },
        )
        assert response.status_code == 202, response.text
        job_id: str = response.json()["id"]
        _wait_terminal(store, job_id)

    record = store.get(job_id)
    assert record.status is JobStatus.SUCCEEDED, record.error
    result = store.read_result(job_id)
    ga4 = result["ga4"]
    assert isinstance(ga4, dict)
    assert ga4["status"] == "succeeded", ga4
    assert ga4["property_id"] == PROPERTY
    assert ga4["pages_matched"] >= 1, "the mocked GA4 totals reached a crawled page"
    assert ga4["reason"] == ""
