"""`POST /api/v1/jobs/import` (ADR 0034): every binding audit condition, end to end."""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import openpyxl
import psycopg
import pytest
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, create_app
from src.core.circuit_breaker import CircuitBreaker
from src.core.config import get_settings
from src.core.postgres_store import PostgresJobStore
from src.core.schemas import OrgConfig
from src.core.state_store import DiskJobStore, DiskOrgConfigStore
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.deliverables.masterfile_registry import AVAILABLE_SERVICES

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.core.test_postgres_store import _factory, _FakeDB
from tests.modules.seo.job_bundle_factory import SOURCE_JOB_ID, bundle_dict, gz

URL = f"{API_PREFIX}/jobs/import"
PUBLIC_IP = "93.184.216.34"


def _headers(org: str = "org-a", operator: str = "alice", **extra: str) -> dict[str, str]:
    return {**auth_headers(org, operator), "Content-Type": "application/gzip", **extra}


@pytest.fixture(autouse=True)
def orgs(tmp_path, monkeypatch) -> None:
    store = DiskOrgConfigStore(tmp_path / "orgs")
    store.create(OrgConfig(org_id="org-a", display_name="Org A", is_active=True))
    store.create(OrgConfig(org_id="org-b", display_name="Org B", is_active=True))
    monkeypatch.setattr(get_settings(), "_org_config_store", store)


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(tmp_path, store) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda _host: [PUBLIC_IP]),
        deliverable_jobs_root=tmp_path / "deliverable_jobs",
        rulebooks_root=tmp_path / "rulebooks",
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def captured(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    root = logging.getLogger("rankuno")
    root.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="rankuno")
    try:
        yield caplog
    finally:
        root.removeHandler(caplog.handler)


def _import(client: TestClient, bundle: dict[str, Any] | bytes | None = None, **kw: Any) -> Any:
    body = gz(bundle if bundle is not None else bundle_dict())
    return client.post(URL, content=body, headers=kw.pop("headers", None) or _headers(), **kw)


class TestHappyPath:
    def test_lands_as_a_terminal_job_in_the_callers_org(self, client: TestClient) -> None:
        response = _import(client)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["pages"] == 2
        assert body["duplicate"] is False

        job = client.get(f"{API_PREFIX}/jobs/{body['id']}", headers=_headers()).json()
        assert job["org_id"] == "org-a"
        assert job["has_result"] is True
        assert job["has_checkpoint"] is False
        assert job["provenance"]["origin"] == "local_import"
        assert job["provenance"]["imported_by"] == "alice"
        assert job["provenance"]["source_job_id"] == SOURCE_JOB_ID
        listed = client.get(f"{API_PREFIX}/jobs", headers=_headers()).json()
        assert [item["id"] for item in listed] == [body["id"]]

    def test_an_identical_retry_is_a_duplicate_200(self, client: TestClient) -> None:
        first = _import(client).json()
        again = _import(client)
        assert again.status_code == 200
        assert again.json()["id"] == first["id"]
        assert again.json()["duplicate"] is True

    def test_same_source_with_different_content_is_409(self, client: TestClient) -> None:
        _import(client)
        changed = bundle_dict(label="a different label")
        response = _import(client, changed)
        assert response.status_code == 409
        assert "already imported" in response.json()["detail"]

    def test_the_same_source_in_another_org_is_a_separate_job(self, client: TestClient) -> None:
        a = _import(client).json()
        b = _import(client, headers=_headers(org="org-b", operator="bob"))
        assert b.status_code == 201
        assert b.json()["id"] != a["id"]

    def test_the_log_line_names_the_import_and_nothing_secret(
        self, client: TestClient, captured: pytest.LogCaptureFixture
    ) -> None:
        headers = _headers()
        body = _import(client, headers=headers).json()
        records = [r for r in captured.records if r.getMessage() == "job_imported"]
        assert len(records) == 1
        extra = records[0].__dict__
        assert extra["operator_id"] == "alice"
        assert extra["org"] == "org-a"
        assert extra["job_id"] == body["id"]
        assert extra["source_job_id"] == SOURCE_JOB_ID
        assert len(extra["bundle_sha256"]) == 64
        assert extra["pages"] == 2
        assert extra["compressed_bytes"] > 0 < extra["decompressed_bytes"]
        everything = "\n".join(f"{r.getMessage()} {r.__dict__!r}" for r in captured.records)
        token = headers["Authorization"].removeprefix("Bearer ")
        assert token not in everything
        assert "<nav>" not in everything


class TestAdmission:
    def test_no_session_is_401(self, client: TestClient) -> None:
        response = client.post(
            URL, content=gz(bundle_dict()), headers={"Content-Type": "application/gzip"}
        )
        assert response.status_code == 401

    def test_not_gzip_is_415(self, client: TestClient) -> None:
        response = client.post(URL, json=bundle_dict(), headers={**auth_headers("org-a", "alice")})
        assert response.status_code == 415

    def test_malformed_gzip_is_400(self, client: TestClient) -> None:
        response = client.post(URL, content=b"\x1f\x8bnot really", headers=_headers())
        assert response.status_code == 400

    def test_the_operators_hourly_bucket_returns_429(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "job_import_burst", 2)
        assert _import(client).status_code == 201
        assert _import(client).status_code == 200
        limited = _import(client)
        assert limited.status_code == 429
        # Another operator has their own bucket.
        assert _import(client, headers=_headers(operator="carol")).status_code == 200

    def test_a_second_concurrent_import_is_refused_not_queued(self, client: TestClient) -> None:
        lock = client.app.state.api.import_lock  # type: ignore[attr-defined]
        assert lock.acquire(blocking=False)
        try:
            response = _import(client)
        finally:
            lock.release()
        assert response.status_code == 429
        assert "another import" in response.json()["detail"]
        assert _import(client).status_code == 201  # released afterwards


class TestSizeLimits:
    def test_an_oversized_content_length_is_refused_before_reading(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "job_import_max_compressed_bytes", 1000)
        response = _import(client)  # the bundle gzips to well over 1,000 bytes
        assert response.status_code == 413

    def test_an_oversized_chunked_stream_is_refused(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "job_import_max_compressed_bytes", 1000)
        body = gz(bundle_dict())

        def chunks() -> Iterator[bytes]:
            for start in range(0, len(body), 256):
                yield body[start : start + 256]

        response = client.post(URL, content=chunks(), headers=_headers())
        assert response.status_code == 413

    def test_a_gzip_bomb_stops_at_the_decompressed_cap(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "job_import_max_decompressed_bytes", 64 * 1024)
        bomb = gz(b'{"format": "' + b"A" * (8 * 1024 * 1024) + b'"}')
        response = client.post(URL, content=bomb, headers=_headers())
        assert response.status_code == 413


class TestValidation:
    def test_deep_nesting_is_422(self, client: TestClient) -> None:
        nested = b'{"a":' * 50_000 + b"1" + b"}" * 50_000
        assert client.post(URL, content=gz(nested), headers=_headers()).status_code == 422

    def test_a_javascript_url_is_422_with_locations_only(self, client: TestClient, store) -> None:
        data = bundle_dict()
        data["result"]["navigation"]["roots"][0]["url"] = "javascript:alert('MARKER')"
        response = _import(client, data)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["locations"] == ["result.navigation.roots[0].url"]
        assert "MARKER" not in response.text
        assert store.list_jobs() == []

    def test_a_dotted_scheme_less_canonical_is_accepted(self, client: TestClient) -> None:
        data = bundle_dict()
        data["result"]["pages"][0]["canonical_url"] = "www.http://infosys.com/a/b.html"
        assert _import(client, data).status_code == 201

    def test_a_javascript_canonical_is_refused(self, client: TestClient) -> None:
        data = bundle_dict()
        data["result"]["pages"][0]["canonical_url"] = "javascript:alert(1)"
        response = _import(client, data)
        assert response.status_code == 422
        assert response.json()["detail"]["locations"] == ["result.pages[0].canonical_url"]

    @pytest.mark.parametrize(
        "extra",
        [
            {"org_id": "org-b"},
            {"id": "f" * 32},
            {"has_result": True},
            {"telemetry": {"completed": 1}},
            {"tool_name": "seo.screaming_frog"},
        ],
    )
    def test_server_decided_fields_are_refused(self, client: TestClient, extra) -> None:
        response = _import(client, bundle_dict(**extra))
        assert response.status_code == 422
        assert list(extra)[0] in response.json()["detail"]["locations"]

    @pytest.mark.parametrize("status_value", ["queued", "running", "failed"])
    def test_unfinished_or_failed_jobs_are_refused(self, client: TestClient, status_value) -> None:
        response = _import(client, bundle_dict(status=status_value))
        assert response.status_code == 422
        assert response.json()["detail"]["locations"] == ["status"]

    def test_a_result_that_fails_the_contract_is_422_without_echoing_it(
        self, client: TestClient
    ) -> None:
        data = bundle_dict()
        data["result"]["pages"][0]["primary_page_type"] = "NOT_A_TYPE_MARKER"
        response = _import(client, data)
        assert response.status_code == 422
        assert "NOT_A_TYPE_MARKER" not in response.text


class TestOnAnImportedJob:
    @pytest.fixture
    def job_id(self, client: TestClient) -> str:
        return str(_import(client).json()["id"])

    def test_retry_and_resume_are_refused(self, client: TestClient, job_id: str) -> None:
        for verb in ("retry", "resume"):
            response = client.post(f"{API_PREFIX}/jobs/{job_id}/{verb}", headers=_headers())
            assert response.status_code == 409, verb
            assert "imported from a local run" in response.json()["detail"]

    def test_another_org_gets_403_everywhere(self, client: TestClient, job_id: str) -> None:
        other = _headers(org="org-b", operator="bob")
        for method, path in (
            ("get", f"/jobs/{job_id}"),
            ("get", f"/jobs/{job_id}/result"),
            ("get", f"/jobs/{job_id}/urls.xlsx"),
            ("post", f"/jobs/{job_id}/deliverable"),
            ("post", f"/jobs/{job_id}/retry"),
        ):
            response = getattr(client, method)(f"{API_PREFIX}{path}", headers=other)
            assert response.status_code == 403, path

    def test_result_and_url_workbook_download(self, client: TestClient, job_id: str) -> None:
        result = client.get(f"{API_PREFIX}/jobs/{job_id}/result", headers=_headers())
        assert result.status_code == 200
        assert [page["url"] for page in result.json()["pages"]] == [
            "https://example.com/page-0",
            "https://example.com/page-1",
        ]
        workbook = client.get(f"{API_PREFIX}/jobs/{job_id}/urls.xlsx", headers=_headers())
        assert workbook.status_code == 200
        openpyxl.load_workbook(io.BytesIO(workbook.content))

    def test_the_audit_workbook_deliverable_builds_and_downloads(
        self, client: TestClient, job_id: str
    ) -> None:
        accepted = client.post(f"{API_PREFIX}/jobs/{job_id}/deliverable", headers=_headers())
        assert accepted.status_code == 202, accepted.text
        deliverable_id = accepted.json()["id"]
        deadline = time.monotonic() + 10
        status_body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status_body = client.get(
                f"{API_PREFIX}/deliverables/{deliverable_id}", headers=_headers()
            ).json()
            if status_body["status"] in ("succeeded", "partial", "failed"):
                break
            time.sleep(0.02)
        assert status_body["status"] == "succeeded"
        download = client.get(
            f"{API_PREFIX}/deliverables/{deliverable_id}/download", headers=_headers()
        )
        assert download.status_code == 200
        openpyxl.load_workbook(io.BytesIO(download.content))

    def test_checkpoint_is_absent_and_masterfiles_are_refused_as_for_any_native_crawl(
        self, client: TestClient, job_id: str
    ) -> None:
        assert (
            client.get(f"{API_PREFIX}/jobs/{job_id}/checkpoint", headers=_headers()).status_code
            == 404
        )
        slug = sorted(AVAILABLE_SERVICES)[0]
        response = client.post(f"{API_PREFIX}/jobs/{job_id}/masterfile/{slug}", headers=_headers())
        assert response.status_code == 409

    def test_reparse_stays_allowed(self, client: TestClient, job_id: str) -> None:
        response = client.post(f"{API_PREFIX}/jobs/{job_id}/reparse", headers=_headers())
        assert response.status_code == 200, response.text
        assert response.json()["provenance"] is None
        assert response.json()["id"] != job_id


class TestPostgresBacked:
    def _app(self, store: PostgresJobStore, tmp_path) -> Any:
        return create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda _host: [PUBLIC_IP]),
            deliverable_jobs_root=tmp_path / "deliverable_jobs",
            rulebooks_root=tmp_path / "rulebooks",
            session_secret=TEST_SESSION_SECRET,
        )

    def test_an_import_writes_no_ledger_row(self, tmp_path) -> None:
        db = _FakeDB(budgets={"org-a": 5.0})
        store = PostgresJobStore(fallback_store=MagicMock(), connection_factory=_factory(db))
        with TestClient(self._app(store, tmp_path)) as client:
            response = _import(client)
        assert response.status_code == 201, response.text
        assert db.cost_ledger == []
        assert db.jobs[response.json()["id"]]["status"] == "succeeded"

    def test_an_open_circuit_is_503_with_nothing_on_disk(self, tmp_path) -> None:
        breaker = CircuitBreaker()
        fallback = MagicMock()
        fallback.recover_orphans.return_value = []
        store = PostgresJobStore(
            circuit_breaker=breaker, fallback_store=fallback, connection_factory=_factory(_FakeDB())
        )
        with TestClient(self._app(store, tmp_path)) as client:
            for _ in range(breaker.failure_threshold):
                breaker.record_failure(psycopg.OperationalError("down"))
            response = _import(client)
        assert response.status_code == 503
        assert not fallback.import_terminal.called

    def test_an_unprovisioned_org_is_409(self, tmp_path) -> None:
        store = PostgresJobStore(
            fallback_store=MagicMock(), connection_factory=_factory(_FakeDB(budgets={}))
        )
        with TestClient(self._app(store, tmp_path)) as client:
            response = _import(client)
        assert response.status_code == 409
        assert "not provisioned" in response.json()["detail"]
