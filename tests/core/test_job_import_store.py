"""`JobStore.import_terminal` on both stores (ADR 0034, audit conditions 4, 5 and 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from src.core.circuit_breaker import CircuitBreaker
from src.core.job_provenance import JobProvenance
from src.core.postgres_store import PostgresJobStore
from src.core.state_store import (
    DiskJobStore,
    ImportConflictError,
    ImportedJob,
    JobRecord,
    JobStatus,
    JobStoreUnavailableError,
    JobTelemetry,
)

from tests.core.test_postgres_store import _FakeDB, _make_store, _raising_factory

STARTED = datetime(2026, 10, 6, 17, 34, tzinfo=UTC)
FINISHED = STARTED + timedelta(minutes=38)
RESULT_JSON = '{"base_url": "https://example.com/", "pages": [{"url": "https://example.com/a"}]}'


def imported(
    org_id: str = "default", sha: str = "a" * 64, source_job_id: str = "0" * 32, **extra: Any
) -> ImportedJob:
    return ImportedJob(
        org_id=org_id,
        tool_name="seo.page_classifier",
        facet_id="seo.page_classifier",
        label="https://example.com/",
        request={"base_url": "https://example.com/"},
        status=extra.pop("status", JobStatus.SUCCEEDED),
        started_at=STARTED,
        finished_at=FINISHED,
        telemetry=JobTelemetry(completed=1, discovered=1, updated_at=FINISHED),
        homepage_html=extra.pop("homepage_html", "<html></html>"),
        provenance=JobProvenance(
            origin="local_import",
            source_instance_id="li-test-instance",
            source_job_id=source_job_id,
            crawl_started_at=STARTED,
            crawl_finished_at=FINISHED,
            imported_by="alice",
            imported_at=FINISHED + timedelta(days=1),
            bundle_sha256=sha,
        ),
        **extra,
    )


def _assert_terminal(record: JobRecord) -> None:
    assert record.status is JobStatus.SUCCEEDED
    assert record.is_terminal
    assert record.has_result is True
    assert record.has_checkpoint is False
    assert record.started_at == STARTED
    assert record.finished_at == FINISHED
    assert record.provenance is not None
    assert record.provenance.imported_by == "alice"


class TestDiskImport:
    def test_lands_terminal_with_result_and_homepage(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        outcome = store.import_terminal(imported(), RESULT_JSON)

        assert outcome.duplicate is False
        _assert_terminal(outcome.record)
        assert store.get(outcome.record.id) == outcome.record
        assert store.read_result(outcome.record.id)["base_url"] == "https://example.com/"
        assert store.read_homepage(outcome.record.id) == "<html></html>"
        assert list(store.iter_result_page_urls(outcome.record.id)) == ["https://example.com/a"]

    def test_an_identical_replay_is_a_duplicate(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        first = store.import_terminal(imported(), RESULT_JSON)
        second = store.import_terminal(imported(), RESULT_JSON)
        assert second.duplicate is True
        assert second.record.id == first.record.id
        assert len(store.list_jobs()) == 1

    def test_same_source_with_different_content_conflicts(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        first = store.import_terminal(imported(), RESULT_JSON)
        with pytest.raises(ImportConflictError) as caught:
            store.import_terminal(imported(sha="b" * 64), RESULT_JSON)
        assert caught.value.existing_id == first.record.id

    def test_dedupe_is_per_org(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        a = store.import_terminal(imported(org_id="org-a"), RESULT_JSON)
        b = store.import_terminal(imported(org_id="org-b", sha="b" * 64), RESULT_JSON)
        assert not b.duplicate
        assert a.record.id != b.record.id

    def test_recover_orphans_never_touches_an_import(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = store.import_terminal(imported(), RESULT_JSON).record
        assert store.recover_orphans() == []
        assert store.get(record.id).status is JobStatus.SUCCEEDED

    def test_a_record_written_before_provenance_existed_still_loads(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        legacy = store.create("seo.page_classifier", {"base_url": "https://example.com/"})
        raw = (tmp_path / f"{legacy.id}.json").read_text(encoding="utf-8")
        assert '"provenance":null' in raw.replace(" ", "")
        stripped = raw.replace(',"provenance":null', "")
        (tmp_path / f"{legacy.id}.json").write_text(stripped, encoding="utf-8")
        assert store.get(legacy.id).provenance is None


class TestPostgresImport:
    def test_one_transaction_terminal_row_and_payload_no_ledger_no_budget_lock(self) -> None:
        db = _FakeDB()
        store, fallback = _make_store(db)
        outcome = store.import_terminal(imported(), RESULT_JSON)

        _assert_terminal(outcome.record)
        assert outcome.duplicate is False
        assert db.cost_ledger == []  # condition 5: no charge
        row = db.jobs[outcome.record.id]
        assert row["import_origin"] == "local_import"
        assert row["bundle_sha256"] == "a" * 64
        assert db.payloads[outcome.record.id]["result"]["base_url"] == "https://example.com/"
        assert db.payloads[outcome.record.id]["homepage_html"] == "<html></html>"
        assert store.get(outcome.record.id).provenance == outcome.record.provenance
        assert fallback.method_calls == []

    def test_replay_conflict_and_per_org_isolation(self) -> None:
        db = _FakeDB(budgets={"org-a": 5.0, "org-b": 5.0})
        store, _ = _make_store(db)
        first = store.import_terminal(imported(org_id="org-a"), RESULT_JSON)

        replay = store.import_terminal(imported(org_id="org-a"), RESULT_JSON)
        assert replay.duplicate and replay.record.id == first.record.id

        with pytest.raises(ImportConflictError):
            store.import_terminal(imported(org_id="org-a", sha="b" * 64), RESULT_JSON)

        other = store.import_terminal(imported(org_id="org-b", sha="b" * 64), RESULT_JSON)
        assert not other.duplicate and other.record.id != first.record.id

    def test_a_lost_race_is_answered_from_the_winner_without_tripping_the_breaker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = _FakeDB()
        breaker = CircuitBreaker()
        store, _ = _make_store(db, circuit_breaker=breaker)
        winner = store.import_terminal(imported(), RESULT_JSON).record

        # The loser's lookup ran before the winner committed: hide the row once.
        real = PostgresJobStore._import_once
        calls = {"n": 0}

        def racing(self: PostgresJobStore, job: ImportedJob, result_json: str) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise psycopg.errors.UniqueViolation("uq_jobs_import_source")
            return real(self, job, result_json)

        monkeypatch.setattr(PostgresJobStore, "_import_once", racing)
        outcome = store.import_terminal(imported(), RESULT_JSON)
        assert outcome.duplicate and outcome.record.id == winner.id
        assert breaker._failure_count == 0

    def test_an_unprovisioned_org_is_a_value_error_not_a_breaker_failure(self) -> None:
        breaker = CircuitBreaker()
        store, _ = _make_store(_FakeDB(budgets={"default": 5.0}), circuit_breaker=breaker)
        with pytest.raises(ValueError, match="not provisioned"):
            store.import_terminal(imported(org_id="ghost-org"), RESULT_JSON)
        assert breaker._failure_count == 0

    def test_circuit_open_refuses_with_no_disk_fallback(self) -> None:
        breaker = CircuitBreaker()
        for _ in range(breaker.failure_threshold):
            breaker.record_failure(psycopg.OperationalError("down"))
        assert breaker.is_open()
        store, fallback = _make_store(_FakeDB(), circuit_breaker=breaker)
        with pytest.raises(JobStoreUnavailableError):
            store.import_terminal(imported(), RESULT_JSON)
        assert fallback.method_calls == []

    def test_a_database_error_refuses_and_counts_toward_the_breaker(self) -> None:
        breaker = CircuitBreaker()
        fallback = MagicMock()
        store = PostgresJobStore(
            circuit_breaker=breaker,
            fallback_store=fallback,
            connection_factory=_raising_factory(psycopg.OperationalError("down")),
        )
        with pytest.raises(JobStoreUnavailableError):
            store.import_terminal(imported(), RESULT_JSON)
        assert breaker._failure_count == 1
        assert fallback.method_calls == []

    def test_recover_orphans_leaves_imports_alone(self) -> None:
        db = _FakeDB()
        store, _ = _make_store(db)
        record = store.import_terminal(imported(), RESULT_JSON).record
        assert store.recover_orphans() == []
        assert store.get(record.id).status is JobStatus.SUCCEEDED

    def test_rows_without_provenance_map_to_none(self) -> None:
        db = _FakeDB()
        store, _ = _make_store(db)
        created = store.create("seo.page_classifier", {"base_url": "https://example.com/"})
        assert store.get(created.id).provenance is None
