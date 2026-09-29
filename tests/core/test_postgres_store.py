"""Tests for the PostgreSQL job store (`src.core.postgres_store`).

No live Postgres is available in this environment (matching
`test_postgres_worker_dispatch_store.py`'s own note), so the real-SQL paths
below run against `_FakeConnection`/`_FakeCursor` — a small in-memory double
that understands exactly the queries `PostgresJobStore` issues against
`jobs`/`job_payloads`/`org_configs`/`cost_ledger`. An unrecognised query is a
hard test failure, so a change to the store's SQL that this suite does not
know about fails loudly here rather than silently passing. Circuit-breaker
and fallback-store behaviour is exercised separately with plain `MagicMock`s,
since that boundary needs no SQL understanding at all.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from src.core.circuit_breaker import CircuitBreaker
from src.core.postgres_store import PostgresJobStore
from src.core.state_store import JobNotFoundError, JobRecord, JobTelemetry

# --------------------------------------------------------------------------
# Fake connection/cursor: understands exactly PostgresJobStore's SQL.
# --------------------------------------------------------------------------


class _FakeDB:
    """Shared, mutable state.

    Two stores pointed at the same `_FakeDB` simulate a redeploy: a new
    process, the same database.
    """

    def __init__(self, *, budgets: Mapping[str, float] | None = None) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self.payloads: dict[str, dict[str, object]] = {}
        self.org_budgets: dict[str, float] = dict(budgets or {"default": 5.0})
        self.cost_ledger: list[tuple[str, str, float, str]] = []

    def snapshot(self) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        return copy.deepcopy(self.jobs), copy.deepcopy(self.payloads)

    def restore(
        self, snap: tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]
    ) -> None:
        self.jobs, self.payloads = snap


_JOB_FIELD_ORDER = (
    "id",
    "org_id",
    "tool_name",
    "label",
    "facet_id",
    "request",
    "status",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "error",
    "has_result",
    "has_checkpoint",
    "telemetry",
)


def _job_row(job: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(job[field] for field in _JOB_FIELD_ORDER)


class _FakeCursor:
    """Understands exactly the SQL `PostgresJobStore` issues."""

    def __init__(self, db: _FakeDB) -> None:
        self._db = db
        self._one: object = None
        self._many: list[tuple[object, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:  # noqa: C901, PLR0912
        q = " ".join(query.split())
        if q == "SELECT llm_credit_limit_usd FROM org_configs WHERE org_id = %s FOR UPDATE":
            (org_id,) = params
            budget = self._db.org_budgets.get(org_id)
            self._one = (budget,) if budget is not None else None
        elif q.startswith("INSERT INTO jobs"):
            job_id, org_id, tool_name, label, facet_id, request_json, status, created, updated = (
                params
            )
            import json

            self._db.jobs[job_id] = {
                "id": job_id,
                "org_id": org_id,
                "tool_name": tool_name,
                "label": label,
                "facet_id": facet_id,
                "request": json.loads(request_json),
                "status": status,
                "created_at": created,
                "updated_at": updated,
                "started_at": None,
                "finished_at": None,
                "error": None,
                "has_result": False,
                "has_checkpoint": False,
                "telemetry": {},
            }
        elif q.startswith("INSERT INTO cost_ledger"):
            self._db.cost_ledger.append(params)  # type: ignore[arg-type]
        elif q.startswith("INSERT INTO job_payloads (job_id, result"):
            self._upsert_payload(params, "result")
        elif q.startswith("INSERT INTO job_payloads (job_id, checkpoint"):
            self._upsert_payload(params, "checkpoint")
        elif q.startswith("INSERT INTO job_payloads (job_id, homepage_html"):
            self._upsert_payload(params, "homepage_html")
        elif (
            q == "SELECT 1 FROM jobs WHERE id = %s FOR UPDATE"
            or q == "SELECT 1 FROM jobs WHERE id = %s"
        ):
            (job_id,) = params
            self._one = (1,) if job_id in self._db.jobs else None
        elif q.startswith("SELECT id, org_id, tool_name") and "ORDER BY created_at DESC" in q:
            rows = sorted(self._db.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            self._many = [_job_row(row) for row in rows]
        elif q.startswith("SELECT id, org_id, tool_name") and "WHERE id = %s" in q:
            (job_id,) = params
            job = self._db.jobs.get(job_id)
            self._one = _job_row(job) if job is not None else None
        elif q.startswith("UPDATE jobs SET status = %s, error = CASE WHEN has_checkpoint"):
            self._recover_orphans(params)
        elif q.startswith("UPDATE jobs SET has_checkpoint = true"):
            updated, job_id = params
            if job_id in self._db.jobs:
                self._db.jobs[job_id]["has_checkpoint"] = True
                self._db.jobs[job_id]["updated_at"] = updated
        elif q.startswith("UPDATE jobs SET") and "RETURNING id, org_id, tool_name" in q:
            self._transition(q, params)
        elif q.startswith("SELECT j.id, p.result FROM jobs j"):
            (job_id,) = params
            job = self._db.jobs.get(job_id)
            payload = self._db.payloads.get(job_id, {})
            self._one = (job_id, payload.get("result")) if job is not None else None
        elif q == "SELECT checkpoint FROM job_payloads WHERE job_id = %s":
            (job_id,) = params
            payload = self._db.payloads.get(job_id)
            self._one = (payload.get("checkpoint"),) if payload is not None else None
        elif q == "SELECT homepage_html FROM job_payloads WHERE job_id = %s":
            (job_id,) = params
            payload = self._db.payloads.get(job_id)
            self._one = (payload.get("homepage_html"),) if payload is not None else None
        else:  # pragma: no cover - defensive: an unmodelled query fails the test loudly
            raise AssertionError(f"fake cursor does not understand query: {q!r}")

    def _upsert_payload(self, params: tuple[object, ...], column: str) -> None:
        # JSON/JSONB columns (`result`, `checkpoint`) come back from a real
        # Postgres SELECT already deserialised into a Python object, not the
        # JSON-text `psycopg.execute` was given — this fake must do the same
        # deserialisation on write so a later read sees what Postgres would
        # actually hand back, not the raw string `finish`/`write_checkpoint`
        # sent in. `homepage_html` is plain TEXT and stays a string.
        import json

        job_id, value, updated_at = params
        if column in ("result", "checkpoint") and value is not None:
            value = json.loads(value)
        row = self._db.payloads.setdefault(
            job_id, {"result": None, "checkpoint": None, "homepage_html": None}
        )
        row[column] = value
        row["updated_at"] = updated_at

    def _transition(self, q: str, params: tuple[object, ...]) -> None:
        if "telemetry = %s" in q:
            telemetry_json, updated, job_id = params
            import json

            job = self._db.jobs[job_id]
            job["telemetry"] = json.loads(telemetry_json)
            job["updated_at"] = updated
        elif "has_result = true" in q:
            status, finished, updated, error, job_id = params
            job = self._db.jobs[job_id]
            job.update(
                status=status,
                has_result=True,
                finished_at=finished,
                updated_at=updated,
                error=error,
            )
        elif "started_at = %s" in q:
            status, started, updated, job_id = params
            job = self._db.jobs[job_id]
            job.update(status=status, started_at=started, updated_at=updated)
        elif "error = %s, finished_at = %s" in q:
            status, error, finished, updated, job_id = params
            job = self._db.jobs[job_id]
            job.update(status=status, error=error, finished_at=finished, updated_at=updated)
        else:  # pragma: no cover - defensive
            raise AssertionError(f"fake cursor does not understand transition: {q!r}")
        self._one = _job_row(self._db.jobs[job_id]) if job_id in self._db.jobs else None

    def _recover_orphans(self, params: tuple[object, ...]) -> None:
        failed_status, checkpoint_reason, base_reason, finished, updated, queued, running = params
        recovered = []
        for job_id, job in self._db.jobs.items():
            if job["status"] not in (queued, running):
                continue
            job["status"] = failed_status
            job["error"] = checkpoint_reason if job["has_checkpoint"] else base_reason
            job["finished_at"] = finished
            job["updated_at"] = updated
            recovered.append((job_id,))
        self._many = recovered

    def fetchone(self) -> object:
        return self._one

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._many


class _FakeConnection:
    """A `psycopg.Connection`-shaped double: `with conn:` commits or rolls back."""

    def __init__(self, db: _FakeDB) -> None:
        self._db = db
        self._snapshot: tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]] | None = (
            None
        )

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def __enter__(self) -> _FakeConnection:
        self._snapshot = self._db.snapshot()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is not None and self._snapshot is not None:
            self._db.restore(self._snapshot)
        return False

    def close(self) -> None:
        return None


def _factory(db: _FakeDB) -> Any:
    return lambda: _FakeConnection(db)


def _raising_factory(error: Exception) -> Any:
    def _raise() -> Any:
        raise error

    return _raise


def _make_store(
    db: _FakeDB, *, circuit_breaker: CircuitBreaker | None = None
) -> tuple[PostgresJobStore, MagicMock]:
    fallback = MagicMock()
    store = PostgresJobStore(
        circuit_breaker=circuit_breaker,
        fallback_store=fallback,
        connection_factory=_factory(db),
    )
    return store, fallback


# --------------------------------------------------------------------------
# Initialization
# --------------------------------------------------------------------------


class TestPostgresJobStoreInitialization:
    def test_initialization_with_defaults(self) -> None:
        store = PostgresJobStore()
        assert store.circuit_breaker is not None
        assert store.fallback_store is not None

    def test_initialization_with_custom_circuit_breaker(self) -> None:
        breaker = CircuitBreaker()
        store = PostgresJobStore(circuit_breaker=breaker)
        assert store.circuit_breaker is breaker

    def test_initialization_with_custom_fallback(self) -> None:
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        assert store.fallback_store is fallback


# --------------------------------------------------------------------------
# Real SQL, against the fake DB
# --------------------------------------------------------------------------


class TestPostgresJobStoreRealSql:
    def test_create_get_list_round_trip_including_label(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)

        created = store.create(
            tool_name="seo.page_classifier",
            request={"seed_url": "https://example.com"},
            label="Example crawl",
            facet_id="seo.page_classifier",
            org_id="default",
        )
        assert created.label == "Example crawl"

        fetched = store.get(created.id)
        assert fetched.label == "Example crawl"  # the bug this cycle fixes
        assert fetched.request == {"seed_url": "https://example.com"}
        assert fetched.has_checkpoint is False

        listed = store.list_jobs()
        assert [j.id for j in listed] == [created.id]
        assert listed[0].label == "Example crawl"

    def test_create_raises_value_error_on_missing_budget(self) -> None:
        db = _FakeDB(budgets={})
        store, _fallback = _make_store(db)
        with pytest.raises(ValueError, match="no budget"):
            store.create(tool_name="seo.page_classifier", request={}, org_id="ghost-org")

    def test_get_raises_job_not_found_error_not_bare_key_error(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        with pytest.raises(JobNotFoundError):
            store.get("does-not-exist")

    def test_mark_running_then_mark_failed(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        running = store.mark_running(job.id)
        assert running.status.value == "running"
        assert running.started_at is not None

        failed = store.mark_failed(job.id, "boom")
        assert failed.status.value == "failed"
        assert failed.error == "boom"
        assert failed.finished_at is not None

    def test_update_telemetry_round_trips(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        telemetry = JobTelemetry(completed=10, discovered=20, rate_per_sec=1.5)
        updated = store.update_telemetry(job.id, telemetry)
        assert updated.telemetry.completed == 10
        assert updated.telemetry.discovered == 20

        refetched = store.get(job.id)
        assert refetched.telemetry.completed == 10

    def test_finish_with_large_result_round_trips_exactly(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        # ~2000 synthetic page records — large enough to exercise a real
        # payload, small enough to keep the test fast.
        result = {
            "pages": [
                {"url": f"https://example.com/{i}", "title": f"Page {i}"} for i in range(2000)
            ]
        }
        finished = store.finish(job.id, result)
        assert finished.status.value == "succeeded"
        assert finished.has_result is True

        read_back = store.read_result(job.id)
        assert read_back == result

    def test_finish_partial_with_error_sets_both(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})
        finished = store.finish(job.id, {"pages": []}, partial=True, error="stalled crawl")
        assert finished.status.value == "partial"
        assert finished.error == "stalled crawl"

    def test_finish_raises_job_not_found_and_writes_nothing(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        with pytest.raises(JobNotFoundError):
            store.finish("ghost-job", {"pages": []})
        assert db.payloads == {}

    def test_read_result_raises_when_job_exists_but_has_no_result(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})
        with pytest.raises(JobNotFoundError, match="no result"):
            store.read_result(job.id)

    def test_checkpoint_write_and_read_round_trip(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        assert store.read_checkpoint(job.id) is None
        store.write_checkpoint(job.id, {"visited": ["https://example.com/a"]})
        assert store.read_checkpoint(job.id) == {"visited": ["https://example.com/a"]}
        assert store.get(job.id).has_checkpoint is True

    def test_write_checkpoint_raises_job_not_found(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        with pytest.raises(JobNotFoundError):
            store.write_checkpoint("ghost-job", {"visited": []})

    def test_homepage_write_and_read_round_trip(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        assert store.read_homepage(job.id) is None
        store.write_homepage(job.id, "<html>hello</html>")
        assert store.read_homepage(job.id) == "<html>hello</html>"

    def test_write_homepage_oversized_is_dropped_silently(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        job = store.create(tool_name="t", request={})

        oversized = "x" * (8 * 1024 * 1024 + 1)
        store.write_homepage(job.id, oversized)  # must not raise
        assert store.read_homepage(job.id) is None

    def test_write_homepage_never_raises_for_missing_job(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        store.write_homepage("ghost-job", "<html></html>")  # must not raise

    def test_recover_orphans_marks_queued_and_running_failed(self) -> None:
        db = _FakeDB()
        store, _fallback = _make_store(db)
        queued = store.create(tool_name="t", request={})
        running = store.create(tool_name="t", request={})
        store.mark_running(running.id)
        done = store.create(tool_name="t", request={})
        store.finish(done.id, {"pages": []})
        with_checkpoint = store.create(tool_name="t", request={})
        store.write_checkpoint(with_checkpoint.id, {"visited": []})

        recovered = store.recover_orphans()

        assert set(recovered) == {queued.id, running.id, with_checkpoint.id}
        assert store.get(queued.id).status.value == "failed"
        assert store.get(queued.id).error == "interrupted by a server restart"
        assert "partial results were saved" in (store.get(with_checkpoint.id).error or "")
        assert store.get(done.id).status.value == "succeeded"

    def test_redeploy_simulation_new_instance_same_db_sees_old_job(self) -> None:
        """A new store instance reads a job an earlier instance created.

        A new `PostgresJobStore` stands in for a new process after a
        redeploy — the whole point of moving off disk.
        """
        db = _FakeDB()
        first_store, _ = _make_store(db)
        job = first_store.create(
            tool_name="t", request={"seed_url": "https://example.com"}, label="pre-redeploy"
        )
        first_store.write_checkpoint(job.id, {"visited": ["a"]})

        second_store, _ = _make_store(db)
        reread = second_store.get(job.id)
        assert reread.label == "pre-redeploy"
        assert second_store.read_checkpoint(job.id) == {"visited": ["a"]}


# --------------------------------------------------------------------------
# Circuit breaker: closed circuit hits Postgres, open circuit falls back
# --------------------------------------------------------------------------


class TestPostgresJobStoreCircuitBreakerFallback:
    def test_create_uses_fallback_when_circuit_open(self) -> None:
        fallback = MagicMock()
        fallback.create.return_value = JobRecord(
            id="test-job",
            tool_name="test",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        result = store.create(tool_name="test_tool", request={"key": "value"})

        fallback.create.assert_called_once()
        assert result.id == "test-job"

    def test_get_uses_fallback_when_circuit_open(self) -> None:
        fallback = MagicMock()
        fallback.get.return_value = JobRecord(
            id="test-job",
            tool_name="test",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        result = store.get("test-job")
        fallback.get.assert_called_once_with("test-job")
        assert result.id == "test-job"

    def test_list_jobs_uses_fallback_when_circuit_open(self) -> None:
        fallback = MagicMock()
        fallback.list_jobs.return_value = []
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        assert store.list_jobs() == []
        fallback.list_jobs.assert_called_once()

    @pytest.mark.parametrize(
        ("method", "args", "kwargs"),
        [
            ("mark_running", ("job-id",), {}),
            ("mark_failed", ("job-id", "boom"), {}),
            ("read_result", ("job-id",), {}),
            ("write_checkpoint", ("job-id", {"a": 1}), {}),
            ("read_checkpoint", ("job-id",), {}),
            ("write_homepage", ("job-id", "<html></html>"), {}),
            ("read_homepage", ("job-id",), {}),
            ("recover_orphans", (), {}),
        ],
    )
    def test_method_uses_fallback_when_circuit_open(
        self, method: str, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> None:
        fallback = MagicMock()
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        getattr(store, method)(*args, **kwargs)
        getattr(fallback, method).assert_called_once_with(*args, **kwargs)

    def test_update_telemetry_uses_fallback_when_circuit_open(self) -> None:
        fallback = MagicMock()
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)
        telemetry = JobTelemetry()

        store.update_telemetry("job-id", telemetry)
        fallback.update_telemetry.assert_called_once_with("job-id", telemetry)

    def test_finish_uses_fallback_when_circuit_open(self) -> None:
        fallback = MagicMock()
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("test"))
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        store.finish("job-id", {"key": "value"})
        fallback.finish.assert_called_once_with(
            "job-id", {"key": "value"}, partial=False, error=None
        )

    def test_operational_error_below_threshold_raises_not_falls_back(self) -> None:
        """A single transient failure must not silently swap stores.

        Only an *open* circuit does. Below threshold, the caller sees the
        error.
        """
        breaker = CircuitBreaker(failure_threshold=5)
        fallback = MagicMock()
        store = PostgresJobStore(
            circuit_breaker=breaker,
            fallback_store=fallback,
            connection_factory=_raising_factory(psycopg.OperationalError("connection refused")),
        )

        with pytest.raises(psycopg.OperationalError):
            store.get("job-id")
        fallback.get.assert_not_called()
        assert breaker.state().value == "closed"  # one failure, threshold 5

    def test_operational_error_opens_circuit_then_falls_back(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1)
        fallback = MagicMock()
        fallback.get.return_value = JobRecord(
            id="job-id",
            tool_name="t",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        store = PostgresJobStore(
            circuit_breaker=breaker,
            fallback_store=fallback,
            connection_factory=_raising_factory(psycopg.OperationalError("connection refused")),
        )

        result = store.get("job-id")
        assert result.id == "job-id"
        fallback.get.assert_called_once_with("job-id")


# --------------------------------------------------------------------------
# Reconciliation / performance: always disk, never Postgres (out of scope)
# --------------------------------------------------------------------------


class TestPostgresJobStoreReconciliationAndPerformanceStayOnDisk:
    def test_write_reconciliation_delegates_unconditionally(self) -> None:
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        store.write_reconciliation("job-id", {"a": 1})
        fallback.write_reconciliation.assert_called_once_with("job-id", {"a": 1})

    def test_read_reconciliation_delegates_unconditionally(self) -> None:
        fallback = MagicMock()
        fallback.read_reconciliation.return_value = {"a": 1}
        store = PostgresJobStore(fallback_store=fallback)
        assert store.read_reconciliation("job-id") == {"a": 1}

    def test_write_performance_delegates_unconditionally(self) -> None:
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        store.write_performance("job-id", {"a": 1})
        fallback.write_performance.assert_called_once_with("job-id", {"a": 1})

    def test_read_performance_delegates_unconditionally(self) -> None:
        fallback = MagicMock()
        fallback.read_performance.return_value = {"a": 1}
        store = PostgresJobStore(fallback_store=fallback)
        assert store.read_performance("job-id") == {"a": 1}
