"""The deletion password gates every write to an existing job (ADR 0042).

What these pin down, each of which a regression would break silently:

* Creation stores only a PBKDF2 hash. The plaintext never reaches the stored
  request, the job file, the response or the log.
* A protected job refuses every gated write without the right
  `X-Deletion-Password`, and a job with no hash is not gated at all (D1).
* Retry, reparse and reconciliation hand the hash to the job they create, so
  a derived job stays deletable with the same password (D3).
* Ordering: `401` before any bucket, `404` before the password, `403 access
  denied` for another org before the password is looked at.
* The PBKDF2 check runs in a worker thread, not on the event loop (F6).

Crawls are never started: `_dispatch` is replaced, so a POST that admits a
crawl only records it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from src.api import job_password_gate
from src.api import server as server_module
from src.api.job_password_gate import header_password
from src.api.server import API_PREFIX, create_app
from src.core.auth import hash_password, verify_password
from src.core.job_password import MAX_DELETION_PASSWORD_LENGTH
from src.core.state_store import DiskJobStore, JobRecord
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.api.test_job_view import _output

PUBLIC_IP = "93.184.216.34"
BASE = "https://a.test"
PASSWORD = "correct-horse-1"  # noqa: S105 - a test fixture password, not a credential
WRONG = "wrong-horse-22"  # noqa: S105 - a wrong guess for the fixture job
HEADER = "X-Deletion-Password"


def _make_client(tmp_path: Path, store: DiskJobStore) -> TestClient:
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda _host: [PUBLIC_IP]),
        deliverable_jobs_root=tmp_path / "deliverable_jobs",
        rulebooks_root=tmp_path / "rulebooks",
        session_secret=TEST_SESSION_SECRET,
    )
    return TestClient(app)


@pytest.fixture
def store(tmp_path: Path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(
    tmp_path: Path, store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    async def no_crawl(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(server_module, "_dispatch", no_crawl)
    with _make_client(tmp_path, store) as test_client:
        yield test_client


def _job(
    store: DiskJobStore,
    *,
    protected: bool = True,
    org: str = "org-a",
    finished: bool = False,
) -> JobRecord:
    record = store.create(
        server_module.TOOL_NAME,
        {"base_url": BASE},
        org_id=org,
        password_hash=hash_password(PASSWORD) if protected else None,
    )
    if finished:
        store.finish(record.id, _output())
        return store.get(record.id)
    return record


def _headers(
    password: str | None, *, org: str = "org-a", operator: str = "alice"
) -> dict[str, str]:
    headers = dict(auth_headers(org, operator))
    if password is not None:
        headers[HEADER] = password
    return headers


def _limiter_reset(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.api.principal_rate_limiter.reset()


def _post(client: TestClient, path: str, headers: dict[str, str]) -> httpx.Response:
    response: httpx.Response = client.post(f"{API_PREFIX}{path}", headers=headers)
    return response


def test_create_keeps_only_a_hash_and_never_the_plaintext(
    client: TestClient, store: DiskJobStore, capfd: pytest.CaptureFixture[str]
) -> None:
    response = client.post(
        f"{API_PREFIX}/jobs",
        json={"base_url": BASE, "max_pages": 5, "crawl_dom": False, "deletion_password": PASSWORD},
        headers=auth_headers(),
    )
    assert response.status_code == 202, response.text

    record = store.get(response.json()["id"])
    assert record.password_hash is not None
    assert verify_password(PASSWORD, record.password_hash)
    assert "deletion_password" not in record.request

    assert PASSWORD not in response.text
    for path in store.root.rglob("*"):
        if path.is_file():
            assert PASSWORD not in path.read_text(encoding="utf-8", errors="ignore"), path
    captured = capfd.readouterr()
    assert PASSWORD not in captured.out + captured.err


@pytest.mark.parametrize("bad", ["x" * 11, "pässwörd-long-1", "tab\tseparated-pw"])
def test_creation_password_under_twelve_or_not_printable_ascii_is_422(
    client: TestClient, bad: str
) -> None:
    response = client.post(
        f"{API_PREFIX}/jobs",
        json={"base_url": BASE, "max_pages": 5, "crawl_dom": False, "deletion_password": bad},
        headers=auth_headers(),
    )
    assert response.status_code == 422


def test_twelve_character_creation_password_is_accepted(client: TestClient) -> None:
    response = client.post(
        f"{API_PREFIX}/jobs",
        json={"base_url": BASE, "max_pages": 5, "crawl_dom": False, "deletion_password": "x" * 12},
        headers=auth_headers(),
    )
    assert response.status_code == 202, response.text


def test_a_job_created_with_a_short_password_is_still_deletable(
    client: TestClient, store: DiskJobStore
) -> None:
    """Decision A (ADR 0042): the 12-character floor is for creation only.

    A job created before the floor existed holds an 11-character password. It
    must still be deletable with that password, or it is undeletable forever.
    """
    record = store.create(
        server_module.TOOL_NAME,
        {"base_url": BASE},
        org_id="org-a",
        password_hash=hash_password("x" * 11),
    )
    response = client.request(
        "DELETE",
        f"{API_PREFIX}/jobs/{record.id}",
        json={"password": "x" * 11},
        headers=auth_headers("org-a", "alice"),
    )
    assert response.status_code == 204, response.text


def test_delete_with_an_empty_password_is_422(client: TestClient, store: DiskJobStore) -> None:
    job = _job(store)
    response = client.request(
        "DELETE",
        f"{API_PREFIX}/jobs/{job.id}",
        json={"password": ""},
        headers=auth_headers("org-a", "alice"),
    )
    assert response.status_code == 422


def test_unprotected_job_takes_cancel_without_a_password(
    client: TestClient, store: DiskJobStore
) -> None:
    job = _job(store, protected=False)
    response = _post(client, f"/jobs/{job.id}/cancel", _headers(None))
    assert response.status_code == 200, response.text


def test_protected_cancel_needs_the_right_header(client: TestClient, store: DiskJobStore) -> None:
    job = _job(store)
    missing = _post(client, f"/jobs/{job.id}/cancel", _headers(None))
    assert missing.status_code == 403
    assert missing.json()["detail"] == "job password required"

    _limiter_reset(client)
    wrong = _post(client, f"/jobs/{job.id}/cancel", _headers(WRONG))
    assert wrong.status_code == 403
    assert wrong.json()["detail"] == "incorrect password"

    _limiter_reset(client)
    right = _post(client, f"/jobs/{job.id}/cancel", _headers(PASSWORD))
    assert right.status_code == 200, right.text


def test_five_wrong_header_passwords_lock_every_gated_write(
    client: TestClient, store: DiskJobStore
) -> None:
    job = _job(store)
    for _ in range(4):
        _limiter_reset(client)
        assert _post(client, f"/jobs/{job.id}/cancel", _headers(WRONG)).status_code == 403
    _limiter_reset(client)
    fifth = _post(client, f"/jobs/{job.id}/cancel", _headers(WRONG))
    assert fifth.status_code == 429
    assert int(fifth.headers["retry-after"]) >= 1

    # The lock is on the job, so a different write route is refused too, and the
    # right password does not get through while the window is open.
    _limiter_reset(client)
    assert _post(client, f"/jobs/{job.id}/retry", _headers(PASSWORD)).status_code == 429
    _limiter_reset(client)
    assert _post(client, f"/jobs/{job.id}/cancel", _headers(PASSWORD)).status_code == 429


def test_retry_refused_without_password_and_inherits_the_hash_with_it(
    client: TestClient, store: DiskJobStore
) -> None:
    job = _job(store, finished=True)
    assert _post(client, f"/jobs/{job.id}/retry", _headers(None)).status_code == 403

    _limiter_reset(client)
    response = _post(client, f"/jobs/{job.id}/retry", _headers(PASSWORD))
    assert response.status_code == 202, response.text
    derived = store.get(response.json()["id"])
    assert derived.password_hash == job.password_hash


def test_reparse_inherits_the_hash(client: TestClient, store: DiskJobStore) -> None:
    job = _job(store, finished=True)
    assert _post(client, f"/jobs/{job.id}/reparse", _headers(None)).status_code == 403

    _limiter_reset(client)
    response = _post(client, f"/jobs/{job.id}/reparse", _headers(PASSWORD))
    assert response.status_code == 200, response.text
    assert store.get(response.json()["id"]).password_hash == job.password_hash


def test_deliverable_build_is_gated_before_its_own_conflict(
    client: TestClient, store: DiskJobStore
) -> None:
    # A queued job has no result, so without the gate this would be a 409. The
    # gate runs first, so a missing password is a 403 and the right one reaches 409.
    job = _job(store)
    path = f"{API_PREFIX}/jobs/{job.id}/deliverable"
    assert client.post(path, json={}, headers=_headers(None)).status_code == 403

    _limiter_reset(client)
    assert client.post(path, json={}, headers=_headers(PASSWORD)).status_code == 409


def test_wrong_org_is_403_before_the_password_is_checked(
    client: TestClient, store: DiskJobStore
) -> None:
    job = _job(store)
    response = _post(
        client, f"/jobs/{job.id}/cancel", _headers(PASSWORD, org="org-b", operator="mallory")
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "access denied"
    assert list(store.root.glob("*.delete_lockout.json")) == []


def test_unknown_job_is_404_whatever_the_header_says(client: TestClient) -> None:
    assert _post(client, "/jobs/does-not-exist/cancel", _headers(None)).status_code == 404


def test_gate_runs_in_a_worker_thread(
    client: TestClient, store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(store)
    real_to_thread = asyncio.to_thread
    called: list[str] = []

    async def spy(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        called.append(func.__name__)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    _post(client, f"/jobs/{job.id}/cancel", _headers(PASSWORD))
    assert "_require_job_password" in called


def test_an_oversize_header_password_is_refused_before_any_hash(
    client: TestClient, store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A value longer than any stored password is refused before PBKDF2 or a bucket.

    Without the bound, every attempt hashes the whole header, and the attempt
    costs no more than the header itself.
    """
    job = _job(store)
    checked: list[str] = []

    def spy(raw: str, hashed: str) -> bool:
        checked.append(raw)
        return verify_password(raw, hashed)

    monkeypatch.setattr(job_password_gate, "verify_password", spy)
    too_long = "x" * (MAX_DELETION_PASSWORD_LENGTH + 1)
    refused = _post(client, f"/jobs/{job.id}/cancel", _headers(too_long))
    assert refused.status_code == 422
    assert checked == []
    assert list(store.root.glob("*.delete_lockout.json")) == []

    # The bound is inclusive: the maximum itself reaches the gate and is judged as a guess.
    _limiter_reset(client)
    at_max = _post(client, f"/jobs/{job.id}/cancel", _headers("x" * MAX_DELETION_PASSWORD_LENGTH))
    assert at_max.status_code == 403
    assert at_max.json()["detail"] == "incorrect password"
    assert len(checked) == 1


def test_header_password_bound_is_inclusive_at_the_maximum() -> None:
    assert header_password("x" * MAX_DELETION_PASSWORD_LENGTH) is not None
    with pytest.raises(HTTPException) as caught:
        header_password("x" * (MAX_DELETION_PASSWORD_LENGTH + 1))
    assert caught.value.status_code == 422
