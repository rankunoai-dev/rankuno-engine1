"""Tests for the worker daemon's single-use/idempotency ledger (ADR 0015)."""

from __future__ import annotations

from src.core.worker_consumed_ledger import ConsumedJobLedger


def test_has_run_is_false_for_an_unseen_job(tmp_path):
    ledger = ConsumedJobLedger(tmp_path / "consumed.json")
    assert ledger.has_run("job-1") is False


def test_try_consume_succeeds_exactly_once(tmp_path):
    ledger = ConsumedJobLedger(tmp_path / "consumed.json")
    assert ledger.try_consume("job-1") is True
    assert ledger.try_consume("job-1") is False


def test_has_run_reflects_a_consumed_job(tmp_path):
    ledger = ConsumedJobLedger(tmp_path / "consumed.json")
    ledger.try_consume("job-1")
    assert ledger.has_run("job-1") is True


def test_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "consumed.json"
    ConsumedJobLedger(path).try_consume("job-1")

    reopened = ConsumedJobLedger(path)
    assert reopened.has_run("job-1") is True
    assert reopened.try_consume("job-1") is False


def test_ledger_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "consumed.json"
    path.write_text("not valid json{{{", encoding="utf-8")

    ledger = ConsumedJobLedger(path)
    assert ledger.has_run("job-1") is False
    assert ledger.try_consume("job-1") is True


def test_distinct_jobs_are_tracked_independently(tmp_path):
    ledger = ConsumedJobLedger(tmp_path / "consumed.json")
    assert ledger.try_consume("job-1") is True
    assert ledger.try_consume("job-2") is True
    assert ledger.has_run("job-1") is True
    assert ledger.has_run("job-2") is True
