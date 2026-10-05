"""A crawl that reaches the memory budget ends PARTIAL, never FAILED (ADR 0031).

The failure this guards against was a container OOM-kill: every running crawl
came back `FAILED`, "interrupted by a server restart". The end-to-end test here
runs the real `PageClassificationTool` through `_run_job` over a mock transport
and asserts the job ends as a partial result carrying the fixed reason.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import get_settings
from src.core.memory_budget import MEMORY_BUDGET_REASON, MIB, MemoryAccount, MemoryBudget
from src.core.state_store import DiskJobStore, DiskOrgConfigStore, JobStatus
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.tool import PageClassificationTool

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"
CHILDREN = 20
PAD = "<p>" + "x" * 49_990 + "</p>"
HOME = (
    "<html><head><title>Home</title></head><body>"
    + "".join(f'<a href="/p{i}/">P{i}</a>' for i in range(CHILDREN))
    + PAD
    + "</body></html>"
)
LEAF = f"<html><head><title>Leaf</title></head><body>{PAD}</body></html>"


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if path == "/":
        return httpx.Response(200, text=HOME, headers={"content-type": "text/html"})
    if path.startswith("/p") and path.endswith("/"):
        return httpx.Response(200, text=LEAF, headers={"content-type": "text/html"})
    return httpx.Response(404, text="not found")


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def mock_org_store(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "_org_config_store", DiskOrgConfigStore(tmp_path / "orgs"))


@pytest.fixture
def mock_network(monkeypatch, settings):
    """The real tool, with its fetcher swapped for one over a mock transport."""

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


def _app(store: DiskJobStore) -> FastAPI:
    return create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
    )


def _wait_terminal(store: DiskJobStore, job_id: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if store.get(job_id).is_terminal:
            return
        time.sleep(0.02)
    pytest.fail(f"job {job_id} never reached a terminal status")


def _crawl(client: TestClient, store: DiskJobStore) -> str:
    response = client.post(
        f"{API_PREFIX}/jobs",
        json={"base_url": SAFE_URL, "max_pages": 50, "crawl_dom": True, "concurrency": 1},
    )
    assert response.status_code == 202, response.text
    job_id: str = response.json()["id"]
    _wait_terminal(store, job_id)
    return job_id


def test_a_small_budget_job_ends_partial_with_the_memory_reason_not_failed(
    store, mock_org_store, mock_network
):
    app = _app(store)
    state = app.state.api
    state.memory_budget = MemoryBudget(300_000, 5)

    with TestClient(app, headers=auth_headers()) as client:
        job_id = _crawl(client, store)

    record = store.get(job_id)
    assert record.status is JobStatus.PARTIAL, record.error
    assert record.error == MEMORY_BUDGET_REASON, "fixed, numberless, tenant-visible"
    result = store.read_result(job_id)
    discovery = result["discovery"]
    assert isinstance(discovery, dict)
    assert discovery["stopped_reason"] == MEMORY_BUDGET_REASON
    assert discovery["truncated"] is False
    assert 1 < discovery["pages_fetched"] < CHILDREN + 1
    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["pages_classified"] >= discovery["pages_fetched"], "classification ran"
    assert state.memory_budget.snapshot().accounts == 0, "the account is closed on success"


def test_the_budget_is_process_wide_and_spares_a_crawl_under_its_share(
    store, mock_org_store, mock_network
):
    """Another org's live crawl shrinks this one's headroom but is never the victim."""
    app = _app(store)
    state = app.state.api
    state.memory_budget = MemoryBudget(600_000, 2)  # share 300 KB
    other_org = state.memory_budget.open("other-org-job")
    other_org.charge(100_000)  # 200 KB projected: under its share

    with TestClient(app, headers=auth_headers()) as client:
        shared_id = _crawl(client, store)
    state.memory_budget.close(other_org)
    state.memory_budget = MemoryBudget(600_000, 2)
    with TestClient(app, headers=auth_headers()) as client:
        alone_id = _crawl(client, store)

    shared = store.read_result(shared_id)["discovery"]
    alone = store.read_result(alone_id)["discovery"]
    assert isinstance(shared, dict) and isinstance(alone, dict)
    assert store.get(shared_id).error == MEMORY_BUDGET_REASON
    assert not other_org.stop_requested, "a crawl under its fair share is never stopped"
    assert shared["pages_fetched"] < alone["pages_fetched"], "both crawls draw on one budget"


def test_the_tool_is_handed_an_account_from_the_shared_budget(store, mock_org_store, monkeypatch):
    captured: list[object] = []

    class CapturingTool:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs.get("memory_account"))

        def run(self, _payload: object) -> object:
            raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "PageClassificationTool", CapturingTool)
    app = _app(store)
    state = app.state.api

    with TestClient(app, headers=auth_headers()) as client:
        response = client.post(
            f"{API_PREFIX}/jobs", json={"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False}
        )
        job_id = response.json()["id"]
        _wait_terminal(store, job_id)

    assert isinstance(captured[0], MemoryAccount)
    assert captured[0].account_id == job_id
    assert store.get(job_id).status is JobStatus.FAILED
    assert state.memory_budget.snapshot().accounts == 0, "closed when the job raised"


def test_a_cancelled_crawl_stays_counted_until_its_thread_ends(store, mock_org_store, monkeypatch):
    """C5: `cancel_job` frees the slot at once; the HTML is freed only later."""
    started = threading.Event()
    finish = threading.Event()

    class BlockingTool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self, _payload: object) -> object:
            started.set()
            finish.wait(timeout=30)
            raise RuntimeError("drained after cancel")

    monkeypatch.setattr(server_module, "PageClassificationTool", BlockingTool)
    app = _app(store)
    state = app.state.api

    with TestClient(app, headers=auth_headers()) as client:
        response = client.post(
            f"{API_PREFIX}/jobs", json={"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False}
        )
        job_id = response.json()["id"]
        assert started.wait(timeout=10)
        assert client.post(f"{API_PREFIX}/jobs/{job_id}/cancel").status_code == 200
        assert state.active_count == 0, "the slot is released by cancel"
        assert state.memory_budget.snapshot().accounts == 1, "the zombie is still counted"
        finish.set()
        deadline = time.monotonic() + 10
        while state.memory_budget.snapshot().accounts and time.monotonic() < deadline:
            time.sleep(0.02)

    assert state.memory_budget.snapshot().accounts == 0


def test_a_budget_field_in_the_crawl_payload_is_refused(store, mock_org_store):
    """C1: the budget is operator configuration, never a per-request knob."""
    app = _app(store)
    with TestClient(app, headers=auth_headers()) as client:
        response = client.post(
            f"{API_PREFIX}/jobs",
            json={"base_url": SAFE_URL, "max_pages": 5, "crawl_memory_budget_mib": 100_000},
        )
    assert response.status_code == 422


def test_the_default_budget_comes_from_settings_shared_by_the_crawl_cap(store, mock_org_store):
    state = _app(store).state.api
    settings = get_settings()
    assert state.memory_budget.budget_bytes == settings.crawl_memory_budget_mib * MIB
    assert state.memory_budget.fair_share_bytes == (
        settings.crawl_memory_budget_mib * MIB // state.max_concurrent_jobs
    )
