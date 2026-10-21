"""DELETE /jobs/{id}: auth before the limiter, per-operator limits, password lockout.

Three guarantees, each with its own failure mode on the old route:

* An unauthenticated caller is refused with 401 before any limiter bucket
  exists, so it cannot spend the owner's per-job budget (the old route
  consumed the bucket before checking the token).
* A wrong password is counted on the job itself, so a brute-force attacker is
  stopped by a time-bounded lock that survives the 1-minute bucket refill.
* The lock is disk-only (see `DiskJobStore.record_failed_delete`). These tests
  use `DiskJobStore` directly; there is no Postgres column behind the counter.

The limiter is reset between requests in the lockout tests, so a 429 there
can only come from the lock, not from the per-minute bucket.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import job_password_gate
from src.api.server import API_PREFIX, create_app
from src.core import state_store
from src.core.auth import hash_password, verify_password
from src.core.postgres_store import PostgresJobStore
from src.core.rate_limiter import RateLimiterRegistry
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
RIGHT = "right-password"
WRONG = "wrong-password"
RATE_LIMITED_DETAIL = "too many delete attempts; wait a moment and try again"
MAX_LOCK_S = 86_400


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
def client(tmp_path: Path, store: DiskJobStore) -> Iterator[TestClient]:
    with _make_client(tmp_path, store) as test_client:
        yield test_client


def _job(store: DiskJobStore, *, org: str = "org-a") -> str:
    return store.create(
        "seo_crawl", {"url": "https://a.test"}, org_id=org, password_hash=hash_password(RIGHT)
    ).id


def _delete(
    client: TestClient,
    job_id: str,
    password: str,
    *,
    org: str = "org-a",
    operator: str = "alice",
) -> httpx.Response:
    response: httpx.Response = client.request(
        "DELETE",
        f"{API_PREFIX}/jobs/{job_id}",
        json={"password": password},
        headers=auth_headers(org, operator),
    )
    return response


def _limiter(client: TestClient) -> RateLimiterRegistry:
    app = cast(FastAPI, client.app)
    registry: RateLimiterRegistry = app.state.api.principal_rate_limiter
    return registry


def _reset_limiter(client: TestClient) -> None:
    """Drop every bucket so only the password lock can answer 429."""
    _limiter(client).reset()


def _limiter_keys(client: TestClient) -> set[str]:
    return set(_limiter(client)._buckets)


def _lock_files(store: DiskJobStore) -> list[Path]:
    return list(store.root.glob("*.delete_lockout.json"))


def test_unauthenticated_deletes_are_401_and_do_not_spend_the_owners_budget(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store)
    url = f"{API_PREFIX}/jobs/{job_id}"
    for _ in range(6):
        response = client.request("DELETE", url, json={"password": WRONG})
        assert response.status_code == 401
    assert _limiter_keys(client) == set()
    assert _delete(client, job_id, RIGHT).status_code == 204


def test_no_password_on_the_job_is_403_and_leaves_no_lock_state(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = store.create("seo_crawl", {"url": "https://a.test"}, org_id="org-a").id
    assert _delete(client, job_id, "anything-long-enough").status_code == 403
    assert _lock_files(store) == []


def test_unknown_job_is_404_for_the_owning_org(client: TestClient) -> None:
    assert _delete(client, "does-not-exist", RIGHT).status_code == 404


def test_cross_org_wrong_password_is_403_and_moves_no_counter(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store, org="org-a")
    for _ in range(5):
        response = _delete(client, job_id, WRONG, org="org-b", operator="mallory")
        assert response.status_code == 403
        assert response.json()["detail"] == "access denied"
    assert _lock_files(store) == []


def test_fifth_wrong_password_locks_the_job_and_the_correct_one_is_refused(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store)
    for _ in range(4):
        _reset_limiter(client)
        assert _delete(client, job_id, WRONG).status_code == 403

    _reset_limiter(client)
    fifth = _delete(client, job_id, WRONG)
    assert fifth.status_code == 429
    assert fifth.json()["detail"] == RATE_LIMITED_DETAIL
    assert int(fifth.headers["retry-after"]) >= 1

    _reset_limiter(client)
    locked = _delete(client, job_id, RIGHT)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) >= 1
    assert store.get(job_id).id == job_id


def test_locked_path_runs_a_dummy_verify_not_the_real_hash(
    client: TestClient, store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _job(store)
    record_hash = store.get(job_id).password_hash
    assert record_hash is not None
    store.record_failed_delete(job_id)
    for _ in range(4):
        store.record_failed_delete(job_id)

    checked: list[str] = []

    def spy(_password: str, password_hash: str) -> bool:
        checked.append(password_hash)
        return False

    monkeypatch.setattr(job_password_gate, "verify_password", spy)
    _reset_limiter(client)
    assert _delete(client, job_id, RIGHT).status_code == 429
    assert len(checked) == 1
    assert checked[0] != record_hash


def test_correct_password_clears_the_counter_before_deleting(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store)
    for _ in range(4):
        _reset_limiter(client)
        assert _delete(client, job_id, WRONG).status_code == 403
    assert len(_lock_files(store)) == 1

    _reset_limiter(client)
    assert _delete(client, job_id, RIGHT).status_code == 204
    assert _lock_files(store) == []


def test_counter_persists_across_a_reload_of_the_disk_store(
    tmp_path: Path, store: DiskJobStore
) -> None:
    job_id = _job(store)
    with _make_client(tmp_path, store) as first:
        for _ in range(4):
            assert _delete(first, job_id, WRONG).status_code == 403

    reloaded = DiskJobStore(store.root)
    with _make_client(tmp_path, reloaded) as second:
        response = _delete(second, job_id, WRONG)
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1


def test_running_job_delete_with_the_right_password_still_succeeds(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store)
    store.mark_running(job_id)
    assert _delete(client, job_id, RIGHT).status_code == 204
    with pytest.raises(state_store.JobNotFoundError):
        store.get(job_id)


def test_lock_window_doubles_from_fifteen_minutes_and_is_capped_at_a_day(
    store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_000_000.0]
    monkeypatch.setattr(state_store, "_now", lambda: datetime.fromtimestamp(now[0], UTC))
    job_id = "job-lock-ladder"
    windows: list[float] = []
    for _ in range(12):
        windows.append(max(store.record_failed_delete(job_id) for _ in range(5)))
        now[0] += MAX_LOCK_S + 1
    # Doubling from 15 minutes; the lifetime soft cap (50 wrong passwords) pins the
    # window at the 24 h ceiling from the tenth lock onward. Never permanent.
    assert windows == [
        900,
        1800,
        3600,
        7200,
        14400,
        28800,
        57600,
        MAX_LOCK_S,
        MAX_LOCK_S,
        MAX_LOCK_S,
        MAX_LOCK_S,
        MAX_LOCK_S,
    ]
    assert all(window <= MAX_LOCK_S for window in windows)
    assert store.delete_lockout_remaining_s(job_id) == 0.0


def test_lock_expires_so_the_owner_can_delete_after_the_window(
    client: TestClient, store: DiskJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _job(store)
    now = [1_000_000.0]
    monkeypatch.setattr(state_store, "_now", lambda: datetime.fromtimestamp(now[0], UTC))
    for _ in range(5):
        store.record_failed_delete(job_id)
    now[0] += 901
    _reset_limiter(client)
    assert _delete(client, job_id, RIGHT).status_code == 204


def test_lockout_429_uses_the_rate_limit_detail_string(
    client: TestClient, store: DiskJobStore
) -> None:
    job_id = _job(store)
    for _ in range(5):
        store.record_failed_delete(job_id)
    _reset_limiter(client)
    response = _delete(client, job_id, RIGHT)
    assert response.status_code == 429
    assert response.json() == {"detail": RATE_LIMITED_DETAIL}


def test_limiter_keys_are_per_operator_and_job(client: TestClient, store: DiskJobStore) -> None:
    job_id = _job(store)
    _delete(client, job_id, RIGHT, operator="alice")
    keys = _limiter_keys(client)
    assert f"delete:alice:{job_id}" in keys
    assert "delete-op:alice" in keys


class _NoSidecarStore:
    """A job store with no disk sidecar: it cannot hold a lock counter."""


def _unused_connection() -> Any:
    raise AssertionError("the store must not open a connection in these tests")


def test_a_store_that_cannot_hold_the_lock_refuses_every_guess_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown store types must refuse the write, not run it with no lock.

    Covers both shapes: a store that is not disk-backed, and a Postgres store
    whose fallback is not disk-backed. Neither has a counter, so the right
    password is refused as well as the wrong ones, and no guess is checked.
    """
    checked: list[str] = []

    def spy(raw: str, hashed: str) -> bool:
        checked.append(raw)
        return verify_password(raw, hashed)

    monkeypatch.setattr(job_password_gate, "verify_password", spy)
    stores: list[Any] = [
        _NoSidecarStore(),
        PostgresJobStore(fallback_store=_NoSidecarStore(), connection_factory=_unused_connection),
    ]
    for store in stores:
        for password in (WRONG, RIGHT):
            with pytest.raises(HTTPException) as refused:
                job_password_gate.enforce_job_password(
                    limiter=RateLimiterRegistry(),
                    store=store,
                    job_id="job-no-sidecar",
                    operator_id="alice",
                    password_hash=hash_password(RIGHT),
                    password=SecretStr(password),
                    action="cancel",
                )
            assert refused.value.status_code == 503
    assert checked == [], "no password was checked, so no guess was spent on an unlocked job"
