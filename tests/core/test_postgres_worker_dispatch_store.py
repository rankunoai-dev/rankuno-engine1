"""Tests for ADR 0015 condition 5's persistent dispatch store.

No live Postgres is available in this environment, so these tests exercise
`PostgresWorkerDispatchStore`'s real SQL and real business logic (atomic
consume, atomic claim, org/worker scoping, the fail-closed error path)
against a small in-memory fake connection/cursor — a test double for the
database, not a second production storage mechanism (ADR 0015 condition 5
is about what *ships*; this is what proves the shipped SQL does what its
docstring claims). The fake understands exactly the eight queries this
store issues; an unrecognised query is a hard test failure, so a change to
the store's SQL that this suite does not know about fails loudly here
rather than silently passing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from src.core.postgres_worker_dispatch_store import PostgresWorkerDispatchStore
from src.core.worker_dispatch_schemas import WorkerJobKind, WorkerJobStatus
from src.core.worker_dispatch_store import (
    DispatchStoreUnavailableError,
    WorkerJobNotFoundError,
)

_COLUMNS = (
    "id",
    "org_id",
    "worker_id",
    "kind",
    "seed_url",
    "template_name",
    "correlation_id",
    "status",
    "created_at",
    "updated_at",
    "dispatched_at",
    "finished_at",
    "error",
    "bundle_size_bytes",
)


class _FakeCursor:
    """Understands exactly the SQL `PostgresWorkerDispatchStore` issues."""

    def __init__(self, db: dict[str, dict[str, dict[str, object]]]) -> None:
        self._db = db
        self._result: object = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        q = " ".join(query.split())
        if "WITH next_job AS" in q:
            self._claim_next_job(params)
        elif q.startswith("INSERT INTO worker_dispatch_previews"):
            self._insert_preview(params)
        elif q.startswith("UPDATE worker_dispatch_previews SET consumed_at"):
            self._consume_preview(params)
        elif q.startswith("INSERT INTO worker_jobs"):
            self._insert_job(params)
        elif q.startswith("INSERT INTO worker_job_uploads"):
            self._store_upload(params)
        elif q.startswith("SELECT encrypted_bytes FROM worker_job_uploads"):
            self._read_upload(params)
        elif q.startswith("UPDATE worker_jobs SET"):
            self._transition(q, params)
        elif q.startswith("SELECT") and "FROM worker_jobs WHERE id = %s" in q:
            self._get_job(params)
        elif q.startswith("SELECT") and "ORDER BY created_at DESC" in q:
            self._list_jobs(params)
        else:  # pragma: no cover - defensive: an unmodelled query fails the test loudly
            raise AssertionError(f"fake cursor does not understand query: {q!r}")

    def fetchone(self) -> object:
        return self._result

    def fetchall(self) -> list[object]:
        return list(self._result or [])

    # -- query handlers ----------------------------------------------------

    def _insert_preview(self, params: tuple[object, ...]) -> None:
        token, org_id, worker_id, seed_url, template_name, correlation_id, expires_at = params
        self._db["worker_dispatch_previews"][str(token)] = {
            "org_id": org_id,
            "worker_id": worker_id,
            "seed_url": seed_url,
            "template_name": template_name,
            "correlation_id": correlation_id,
            "expires_at": expires_at,
            "consumed_at": None,
        }
        self._result = None

    def _consume_preview(self, params: tuple[object, ...]) -> None:
        now, token, org_id, worker_id, seed_url, template_name, correlation_id, cutoff = params
        row = self._db["worker_dispatch_previews"].get(str(token))
        matches = (
            row is not None
            and row["consumed_at"] is None
            and row["org_id"] == org_id
            and row["worker_id"] == worker_id
            and row["seed_url"] == seed_url
            and row["template_name"] == template_name
            and row["correlation_id"] == correlation_id
            and row["expires_at"] > cutoff
        )
        if matches:
            row["consumed_at"] = now  # type: ignore[index]
            self._result = (token,)
        else:
            self._result = None

    def _insert_job(self, params: tuple[object, ...]) -> None:
        (
            job_id,
            org_id,
            worker_id,
            kind,
            seed_url,
            template_name,
            correlation_id,
            status,
            created_at,
            updated_at,
        ) = params
        self._db["worker_jobs"][str(job_id)] = {
            "id": job_id,
            "org_id": org_id,
            "worker_id": worker_id,
            "kind": kind,
            "seed_url": seed_url,
            "template_name": template_name,
            "correlation_id": correlation_id,
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
            "dispatched_at": None,
            "finished_at": None,
            "error": None,
            "bundle_size_bytes": None,
        }
        self._result = None

    def _claim_next_job(self, params: tuple[object, ...]) -> None:
        worker_id, org_id, queued, dispatched, dispatched_at, updated_at = params
        candidates = sorted(
            (
                row
                for row in self._db["worker_jobs"].values()
                if row["worker_id"] == worker_id
                and row["org_id"] == org_id
                and row["status"] == queued
            ),
            key=lambda row: row["created_at"],  # type: ignore[arg-type,return-value]
        )
        if not candidates:
            self._result = None
            return
        row = candidates[0]
        row["status"] = dispatched
        row["dispatched_at"] = dispatched_at
        row["updated_at"] = updated_at
        self._result = tuple(row[c] for c in _COLUMNS)

    def _get_job(self, params: tuple[object, ...]) -> None:
        (job_id,) = params
        row = self._db["worker_jobs"].get(str(job_id))
        self._result = None if row is None else tuple(row[c] for c in _COLUMNS)

    def _list_jobs(self, params: tuple[object, ...]) -> None:
        (org_id,) = params
        rows = sorted(
            (row for row in self._db["worker_jobs"].values() if row["org_id"] == org_id),
            key=lambda row: row["created_at"],  # type: ignore[arg-type,return-value]
            reverse=True,
        )
        self._result = [tuple(row[c] for c in _COLUMNS) for row in rows]

    def _transition(self, q: str, params: tuple[object, ...]) -> None:
        *values, job_id = params
        status, updated_at, finished_at, *extra = values
        row = self._db["worker_jobs"].get(str(job_id))
        if row is None:
            self._result = None
            return
        row["status"] = status
        row["updated_at"] = updated_at
        row["finished_at"] = finished_at
        if "bundle_size_bytes = %s" in q:
            row["bundle_size_bytes"] = extra[0]
        elif "error = %s" in q:
            row["error"] = extra[0]
        self._result = tuple(row[c] for c in _COLUMNS)

    def _store_upload(self, params: tuple[object, ...]) -> None:
        job_id, org_id, worker_id, encrypted_bytes, size_bytes, expires_at = params
        self._db["worker_job_uploads"][str(job_id)] = {
            "org_id": org_id,
            "worker_id": worker_id,
            "encrypted_bytes": encrypted_bytes,
            "size_bytes": size_bytes,
            "expires_at": expires_at,
        }
        self._result = None

    def _read_upload(self, params: tuple[object, ...]) -> None:
        job_id, org_id, now = params
        row = self._db["worker_job_uploads"].get(str(job_id))
        if row is not None and row["org_id"] == org_id and row["expires_at"] > now:
            self._result = (row["encrypted_bytes"],)
        else:
            self._result = None


class _FakeConnection:
    """A `with conn, conn.cursor() as cur:`-shaped fake over a shared dict."""

    def __init__(self, db: dict[str, dict[str, dict[str, object]]]) -> None:
        self._db = db

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def db() -> dict[str, dict[str, dict[str, object]]]:
    return {"worker_dispatch_previews": {}, "worker_jobs": {}, "worker_job_uploads": {}}


@pytest.fixture
def store(db: dict[str, dict[str, dict[str, object]]]) -> PostgresWorkerDispatchStore:
    return PostgresWorkerDispatchStore(connection_factory=lambda: _FakeConnection(db))


# --- mint_dispatch_preview / confirm_dispatch (gate a) -------------------------


def test_confirm_dispatch_queues_a_job_given_a_valid_token(store):
    preview = store.mint_dispatch_preview(
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://example.com/",
        template_name="standard",
        correlation_id="corr-1",
    )
    job = store.confirm_dispatch(
        preview.token,
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://example.com/",
        template_name="standard",
        correlation_id="corr-1",
    )
    assert job is not None
    assert job.status is WorkerJobStatus.QUEUED
    assert job.worker_id == "wkr-1"
    assert job.org_id == "acme"


def test_confirm_dispatch_rejects_an_unknown_token(store):
    job = store.confirm_dispatch(
        "not-a-real-token",
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://example.com/",
        template_name=None,
        correlation_id="corr-1",
    )
    assert job is None


def test_confirm_dispatch_is_single_use(store):
    """The safe failure (ADR 0015 condition 5): a second confirm never re-queues."""
    preview = store.mint_dispatch_preview(
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    first = store.confirm_dispatch(
        preview.token,
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    second = store.confirm_dispatch(
        preview.token,
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    assert first is not None
    assert second is None


def test_confirm_dispatch_rejects_a_token_bound_to_a_different_worker(store):
    preview = store.mint_dispatch_preview(
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    job = store.confirm_dispatch(
        preview.token,
        org_id="acme",
        worker_id="wkr-OTHER",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    assert job is None


def test_confirm_dispatch_rejects_an_expired_token(store, db):
    preview = store.mint_dispatch_preview(
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
        ttl_s=1.0,
    )
    db["worker_dispatch_previews"][preview.token]["expires_at"] = datetime.now(UTC) - timedelta(
        seconds=1
    )
    job = store.confirm_dispatch(
        preview.token,
        org_id="acme",
        worker_id="wkr-1",
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    assert job is None


# --- claim_next_job (condition 6: pinned to one worker) -------------------------


def _queue_job(store: PostgresWorkerDispatchStore, *, worker_id: str, org_id: str = "acme") -> None:
    preview = store.mint_dispatch_preview(
        org_id=org_id,
        worker_id=worker_id,
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )
    store.confirm_dispatch(
        preview.token,
        org_id=org_id,
        worker_id=worker_id,
        seed_url="https://x/",
        template_name=None,
        correlation_id="c1",
    )


def test_claim_next_job_returns_the_queued_job_for_this_worker(store):
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    assert job is not None
    assert job.status is WorkerJobStatus.DISPATCHED
    assert job.kind is WorkerJobKind.SCREAMING_FROG_CRAWL


def test_claim_next_job_never_returns_another_workers_job(store):
    """ADR 0015 condition 6: pinned to one worker, never round-robined."""
    _queue_job(store, worker_id="wkr-1")
    claimed = store.claim_next_job(worker_id="wkr-2", org_id="acme")
    assert claimed is None


def test_claim_next_job_does_not_reclaim_an_already_dispatched_job(store):
    _queue_job(store, worker_id="wkr-1")
    first = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    second = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    assert first is not None
    assert second is None


def test_claim_next_job_returns_none_when_the_queue_is_empty(store):
    assert store.claim_next_job(worker_id="wkr-1", org_id="acme") is None


# --- get_job / list_jobs_for_org -------------------------------------------------


def test_get_job_raises_for_an_unknown_job(store):
    with pytest.raises(WorkerJobNotFoundError):
        store.get_job("no-such-job")


def test_list_jobs_for_org_only_returns_that_orgs_jobs(store):
    _queue_job(store, worker_id="wkr-1", org_id="acme")
    _queue_job(store, worker_id="wkr-2", org_id="globex")
    jobs = store.list_jobs_for_org("acme")
    assert len(jobs) == 1
    assert jobs[0].org_id == "acme"


# --- mark_uploaded / mark_failed -------------------------------------------------


def test_mark_uploaded_transitions_to_succeeded(store):
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    updated = store.mark_uploaded(job.id, bundle_size_bytes=1234)
    assert updated.status is WorkerJobStatus.SUCCEEDED
    assert updated.bundle_size_bytes == 1234


def test_mark_failed_transitions_to_failed_with_a_reason(store):
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    updated = store.mark_failed(job.id, "screaming frog crashed")
    assert updated.status is WorkerJobStatus.FAILED
    assert updated.error == "screaming frog crashed"


def test_transition_raises_for_an_unknown_job(store):
    with pytest.raises(WorkerJobNotFoundError):
        store.mark_failed("no-such-job", "irrelevant")


# --- store_upload / read_upload (condition 11) ----------------------------------


def test_store_and_read_upload_round_trips(store):
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    store.store_upload(
        job.id, org_id="acme", worker_id="wkr-1", encrypted_bytes=b"ciphertext", retention_days=30
    )
    read_back = store.read_upload(job.id, org_id="acme")
    assert read_back == b"ciphertext"


def test_read_upload_scoped_to_the_owning_org(store):
    """Access is org-scoped the same way job records already are (condition 11)."""
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    store.store_upload(
        job.id, org_id="acme", worker_id="wkr-1", encrypted_bytes=b"secret", retention_days=30
    )
    assert store.read_upload(job.id, org_id="someone-elses-org") is None


def test_read_upload_respects_the_retention_expiry(store, db):
    _queue_job(store, worker_id="wkr-1")
    job = store.claim_next_job(worker_id="wkr-1", org_id="acme")
    store.store_upload(
        job.id, org_id="acme", worker_id="wkr-1", encrypted_bytes=b"secret", retention_days=30
    )
    db["worker_job_uploads"][job.id]["expires_at"] = datetime.now(UTC) - timedelta(days=1)
    assert store.read_upload(job.id, org_id="acme") is None


def test_read_upload_returns_none_for_an_unknown_job(store):
    assert store.read_upload("no-such-job", org_id="acme") is None


# --- fail-closed on a store outage (condition 5) --------------------------------


def test_a_connection_failure_raises_a_typed_error_never_a_silent_approval():
    def _broken_factory() -> NoReturn:
        raise ConnectionError("database unreachable")

    broken_store = PostgresWorkerDispatchStore(connection_factory=_broken_factory)
    with pytest.raises(DispatchStoreUnavailableError):
        broken_store.mint_dispatch_preview(
            org_id="acme",
            worker_id="wkr-1",
            seed_url="https://x/",
            template_name=None,
            correlation_id="c1",
        )


def test_claim_next_job_fails_closed_on_a_store_outage():
    def _broken_factory() -> NoReturn:
        raise ConnectionError("database unreachable")

    broken_store = PostgresWorkerDispatchStore(connection_factory=_broken_factory)
    with pytest.raises(DispatchStoreUnavailableError):
        broken_store.claim_next_job(worker_id="wkr-1", org_id="acme")
