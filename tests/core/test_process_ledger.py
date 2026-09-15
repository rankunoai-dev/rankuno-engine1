"""Tests for the PID/start-time ledger `process_supervisor` reads and writes.

No Windows dependency at all — this is plain file I/O plus a `StrictModel` —
so every test here runs on any platform, including `ci.yml`'s `ubuntu-latest`.
"""

from __future__ import annotations

import json
import os

import pytest
from src.core._process_ledger import (
    LedgerEntry,
    read_ledger,
    remove_entry,
    upsert_entry,
    write_ledger,
)


class TestReadLedger:
    def test_a_missing_file_reads_as_empty(self, tmp_path) -> None:
        assert read_ledger(tmp_path / "does-not-exist.json") == {}

    def test_corrupt_json_reads_as_empty_rather_than_raising(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert read_ledger(path) == {}

    def test_an_invalid_entry_is_dropped_not_fatal(self, tmp_path) -> None:
        """One bad entry must not hide every other entry in the same file."""
        path = tmp_path / "ledger.json"
        path.write_text(
            json.dumps(
                {
                    "good": {"pid": 111, "process_start_time": 1.0, "job_object_name": None},
                    "bad": {"pid": "not-an-int", "process_start_time": 1.0},
                }
            ),
            encoding="utf-8",
        )
        entries = read_ledger(path)
        assert set(entries) == {"good"}
        assert entries["good"].pid == 111


class TestUpsertAndRemove:
    def test_upsert_then_read_round_trips(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=123, process_start_time=42.5, job_object_name=None)

        entries = read_ledger(path)
        assert entries["job-1"] == LedgerEntry(
            pid=123, process_start_time=42.5, job_object_name=None
        )

    def test_upsert_replaces_an_existing_entry_for_the_same_job_id(self, tmp_path) -> None:
        """The second write (job assigned) must supersede the first (PID only)."""
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=123, process_start_time=42.5, job_object_name=None)
        upsert_entry(path, "job-1", pid=123, process_start_time=42.5, job_object_name="Local\\x")

        entries = read_ledger(path)
        assert len(entries) == 1
        assert entries["job-1"].job_object_name == "Local\\x"

    def test_upsert_does_not_disturb_other_entries(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=1, process_start_time=1.0, job_object_name=None)
        upsert_entry(path, "job-2", pid=2, process_start_time=2.0, job_object_name=None)

        assert set(read_ledger(path)) == {"job-1", "job-2"}

    def test_remove_drops_only_the_named_entry(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=1, process_start_time=1.0, job_object_name=None)
        upsert_entry(path, "job-2", pid=2, process_start_time=2.0, job_object_name=None)

        remove_entry(path, "job-1")

        assert set(read_ledger(path)) == {"job-2"}

    def test_remove_of_an_unknown_job_id_is_a_no_op(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=1, process_start_time=1.0, job_object_name=None)

        remove_entry(path, "never-existed")  # must not raise

        assert set(read_ledger(path)) == {"job-1"}

    def test_the_parent_directory_is_created_if_absent(self, tmp_path) -> None:
        path = tmp_path / "does" / "not" / "exist" / "ledger.json"
        upsert_entry(path, "job-1", pid=1, process_start_time=1.0, job_object_name=None)
        assert path.exists()


class TestWriteLedger:
    def test_write_then_read_round_trips_every_entry(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        entries = {
            "a": LedgerEntry(pid=1, process_start_time=1.0, job_object_name=None),
            "b": LedgerEntry(pid=2, process_start_time=2.0, job_object_name="Local\\b"),
        }
        write_ledger(path, entries)
        assert read_ledger(path) == entries

    def test_an_empty_mapping_produces_a_readable_empty_ledger(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        write_ledger(path, {})
        assert read_ledger(path) == {}

    def test_a_failed_replace_cleans_up_its_temp_file_and_still_raises(
        self, tmp_path, monkeypatch
    ) -> None:
        """Same crash-safety contract as `state_store._atomic_write`.

        A write that cannot complete must not leave a stray `.tmp` file
        behind, and must not swallow the error that caused it.
        """
        path = tmp_path / "ledger.json"

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)

        with pytest.raises(OSError, match="disk full"):
            write_ledger(path, {"job-1": LedgerEntry(pid=1, process_start_time=1.0)})

        assert list(tmp_path.glob("*.tmp")) == []
        assert not path.exists()
