"""The worker daemon's own record of job ids it has already run.

Two things this closes, both named in ADR 0015:

* **Step 5 answer 4's idempotency requirement**, restated for the worker
  side: "the worker must treat re-dispatch of an already-ledgered job_id as
  a no-op rather than launching a second Screaming Frog process." The
  cloud's own atomic `QUEUED -> DISPATCHED` transition
  (`PostgresWorkerDispatchStore.claim_next_job`) already prevents a normal
  re-poll from handing this worker the same job twice; this ledger is what
  survives a **daemon restart**, which that transition alone does not cover.
* **Condition 3(b)'s "single-use" requirement** for the signed dispatch
  assignment artifact, for the same reason: `worker_dispatch_signing`'s own
  module docstring explains why no separate server-side "consumed jti"
  table exists — this ledger is the other half of that design, checked
  before a claimed assignment is ever acted on.

One JSON file, atomic writes, the same shape `_process_ledger.py` already
uses for a different ledger — duplicated rather than imported, matching
that module's own precedent of not sharing private helpers across a
package boundary that does not need them.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.core.logger import get_logger

__all__ = ["ConsumedJobLedger"]

_logger = get_logger("core.worker_consumed_ledger")


class ConsumedJobLedger:
    """Disk-backed set of job ids this worker daemon has already executed."""

    def __init__(self, path: Path) -> None:
        """Build the ledger over `path`, creating its parent directory if absent.

        Args:
            path: JSON file to persist consumed job ids in. Typically
                `Settings.worker_consumed_jobs_path`.
        """
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _logger.warning("consumed_ledger_unreadable", extra={"error": str(exc)})
            return {}
        return raw if isinstance(raw, dict) else {}

    def has_run(self, job_id: str) -> bool:
        """Whether this worker has already executed `job_id`.

        Non-mutating — a fast admission-time check, mirroring
        `preview_tokens.PreviewTokenStore.peek`. Never the authoritative
        single-use decision; `try_consume` is.
        """
        with self._lock:
            return job_id in self._read()

    def try_consume(self, job_id: str) -> bool:
        """Atomically check-and-mark `job_id` as run. The real single-use decision.

        Returns:
            `True` the first time this is called for a given `job_id`;
            `False` on every call after — including a concurrent one, since
            both the check and the write happen under one lock.
        """
        with self._lock:
            entries = self._read()
            if job_id in entries:
                return False
            entries[job_id] = datetime.now(UTC).isoformat()
            self._write(entries)
        _logger.info("worker_job_marked_consumed", extra={"job_id": job_id})
        return True

    def _write(self, entries: dict[str, str]) -> None:
        payload = json.dumps(entries, indent=2, sort_keys=True)
        handle, temp_name = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self._path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
