"""The PID + process-start-time ledger `process_supervisor.py` reads and writes.

Independent of `DiskJobStore` (`state_store.py`) by design, per ADR 0013
condition 2: that store answers "which job *record* was left `RUNNING`" and
has no concept of an OS process; this ledger answers "which OS *process* is
still alive" and has no concept of a `JobRecord`. One JSON file, one entry per
supervised launch, written atomically like every other durable file in
`core/` — a crash mid-write must leave the old ledger or the new one, never a
half-written file that fails to parse and hides every entry in it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel

__all__ = ["LedgerEntry", "read_ledger", "remove_entry", "upsert_entry", "write_ledger"]

_logger = get_logger("core.process_supervisor.ledger")

_lock = threading.Lock()
"""Guards the ledger file against concurrent launches in this process.
Single-process only, like `DiskJobStore` (CLAUDE.md §8)."""


class LedgerEntry(StrictModel):
    """One supervised process's identity, recorded before Job Object assignment.

    Attributes:
        pid: OS process id. Meaningful only paired with `process_start_time`:
            Windows reuses a PID the instant its holder exits.
        process_start_time: `GetProcessTimes` creation time as a POSIX
            timestamp. Fixed at process creation; never changes.
        job_object_name: The Job Object this process was assigned to, or
            `None` if written before assignment completed — the narrow window
            `launch_supervised` covers by writing the PID first. `None` tells
            `reconcile_orphans` there is no job to reopen, only a process tree
            to walk.
    """

    pid: int = Field(gt=0)
    process_start_time: float
    job_object_name: str | None = None


def read_ledger(path: Path) -> dict[str, LedgerEntry]:
    """Read every entry, dropping (and logging) any that fail to parse."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _logger.warning("ledger_unreadable", extra={"path": str(path), "error": str(exc)})
        return {}

    entries: dict[str, LedgerEntry] = {}
    for job_id, payload in raw.items():
        try:
            entries[job_id] = LedgerEntry.model_validate(payload)
        except ValueError as exc:
            _logger.warning("ledger_entry_invalid", extra={"job_id": job_id, "error": str(exc)})
    return entries


def write_ledger(path: Path, entries: Mapping[str, LedgerEntry]) -> None:
    """Replace the whole ledger file atomically (`tempfile` + `os.replace`).

    Exposed (not just used internally by `upsert_entry`/`remove_entry`) so
    `reconcile_orphans` can persist the surviving-entries set it computes in
    one write, rather than one `remove_entry` call per entry it cleaned up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({job_id: entry.model_dump() for job_id, entry in entries.items()})
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def upsert_entry(
    path: Path,
    job_id: str,
    pid: int,
    process_start_time: float,
    *,
    job_object_name: str | None,
) -> None:
    """Write or replace one entry, under the intra-process lock."""
    with _lock:
        entries = read_ledger(path)
        entries[job_id] = LedgerEntry(
            pid=pid, process_start_time=process_start_time, job_object_name=job_object_name
        )
        write_ledger(path, entries)


def remove_entry(path: Path, job_id: str) -> None:
    """Drop one entry, under the intra-process lock. A no-op if already gone."""
    with _lock:
        entries = read_ledger(path)
        if job_id in entries:
            del entries[job_id]
            write_ledger(path, entries)
