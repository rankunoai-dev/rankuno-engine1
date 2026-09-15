"""Windows Job Object process supervision — governs OS processes this engine launches.

ADR 0013 records why this exists: driving a licensed desktop tool (Screaming
Frog) from this engine means this process can now *cause* another OS process
to run, and a cancel path or crash that leaves it running is not
hypothetical — it is the documented failure mode of the code this replaces
(RAE's `--pool=solo` Screaming Frog launch, which orphaned the JVM on
cancel). Three pieces close that gap, split across sibling modules so each
stays small and independently testable:

* **A real Job Object** (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), not
  `subprocess.terminate()`/`kill()` and not `CREATE_NEW_PROCESS_GROUP` (only
  `CTRL_BREAK_EVENT`, no guaranteed descendant termination). The OS kills
  every process in the job the instant its handle closes — including when it
  closes because *this* process crashed and the kernel force-closed every
  handle it held, without one line of our own cleanup code running. That is
  the guarantee `subprocess` alone cannot make, and it is also why this runs
  in the API server process rather than a separate watchdog (ADR 0013
  condition 3): the guarantee does not depend on our process staying alive.
  Built here, in `launch_supervised` and `SupervisedProcess`.
* **An independent PID + process-start-time ledger** (`_process_ledger.py`),
  written the instant a PID exists — before the Job Object is even created —
  so a crash in that narrow enrollment window is still discoverable at next
  startup. `DiskJobStore.recover_orphans()` (`state_store.py`) answers a
  different question ("which job *record* was left RUNNING") and has no
  concept of an OS process; conflating the two was named explicitly as a
  defect to avoid (ADR 0013 condition 2).
* **`reconcile_orphans()`** (`_process_orphans.py`), a startup routine
  reading that ledger, matching PID *and* start time before killing anything.

Importable without Windows
---------------------------
Every `pywin32` import is deferred (`_win32_bindings.load_win32`), called
only when a function needs the OS. pytest imports every test module at
collection regardless of `-m` filters, so an unconditional `import win32job`
would turn a missing Windows-only extra into a collection error for the whole
suite on `ci.yml`'s `ubuntu-latest` runners. Calling any function here
without pywin32 raises `ProcessSupervisorUnavailableError` cleanly instead.

Scope: this is the primitive only — launch, supervise, terminate, reconcile.
Screaming Frog CLI flags, license detection and the `UrlSafetyPolicy` seed-URL
gate are later ADR 0013 conditions, built against a governed `RiskClass.WRITE`
tool that calls this module.
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404 - `list2cmdline` only; no process is spawned via `subprocess`
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.core._process_ledger import remove_entry, upsert_entry
from src.core._process_orphans import reconcile_orphans
from src.core._win32_bindings import (
    ProcessSupervisorError,
    ProcessSupervisorUnavailableError,
    load_win32,
)
from src.core.logger import get_logger

__all__ = [
    "ProcessSupervisorError",
    "ProcessSupervisorUnavailableError",
    "SupervisedProcess",
    "launch_supervised",
    "reconcile_orphans",
]

_logger = get_logger("core.process_supervisor")

_JOB_NAME_PREFIX = "Local\\rankuno-process-supervisor-"
"""Session-local (`Local\\`) so no `SeCreateGlobalPrivilege` is needed for a
per-user desktop tool (ADR 0004) that never needs cross-session visibility."""

_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
"""A job id becomes both a ledger key and a Windows kernel object name
(appended to `_JOB_NAME_PREFIX`); restricting the charset is what stops a
caller-supplied id from injecting a `\\` namespace separator."""


class SupervisedProcess:
    """A child process running inside a Windows Job Object this engine controls.

    Never construct directly — `launch_supervised` is the only sanctioned way
    to obtain one, since it guarantees the ledger entry and Job Object
    assignment both exist before this object is handed back.
    """

    def __init__(
        self,
        *,
        job_id: str,
        pid: int,
        ledger_path: Path,
        job_object_name: str,
        process_handle: Any,  # noqa: ANN401 - opaque pywin32 HANDLE, see `Win32Handles`
        job_handle: Any,  # noqa: ANN401 - opaque pywin32 HANDLE, see `Win32Handles`
    ) -> None:
        """Wrap an already-launched, already-supervised process."""
        self.job_id = job_id
        self._pid = pid
        self._ledger_path = ledger_path
        self._job_object_name = job_object_name
        self._process_handle = process_handle
        self._job_handle = job_handle
        self._closed = False

    @property
    def pid(self) -> int:
        """OS process id of the supervised child."""
        return self._pid

    def is_running(self) -> bool:
        """Whether the OS process is still alive.

        A zero-timeout `WaitForSingleObject`, not `GetExitCodeProcess`: the
        documented idiom for a non-blocking check, and it needs no
        `STILL_ACTIVE` sentinel comparison — 259 is also a value a process can
        legitimately exit with, which makes that comparison a false negative
        waiting to happen.
        """
        if self._closed:
            return False
        win32 = load_win32()
        result = win32.event.WaitForSingleObject(self._process_handle, 0)
        return bool(result == win32.event.WAIT_TIMEOUT)

    def terminate(self, *, timeout_s: float = 5.0) -> None:
        """Kill this process and everything it spawned, via its Job Object.

        `TerminateJobObject` is called explicitly rather than relying only on
        closing the handle: both trigger `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
        but calling it explicitly makes an intentional cancel synchronous and
        loggable instead of depending on when the garbage collector runs.
        Idempotent: a second call is a no-op.

        Args:
            timeout_s: How long to wait for the OS to confirm the process is
                gone before logging (not raising) that it did not confirm in
                time. Termination was already requested either way.
        """
        if self._closed:
            return
        win32 = load_win32()
        try:
            win32.job.TerminateJobObject(self._job_handle, 1)
        except win32.types.error as exc:
            # Most commonly: the process had already exited on its own, and
            # the job has nothing left to terminate — the goal state is
            # already reached.
            _logger.debug(
                "terminate_job_object_noop", extra={"job_id": self.job_id, "error": str(exc)}
            )
        else:
            result = win32.event.WaitForSingleObject(
                self._process_handle, max(0, int(timeout_s * 1000))
            )
            if result != win32.event.WAIT_OBJECT_0:
                _logger.warning(
                    "process_terminate_unconfirmed",
                    extra={"job_id": self.job_id, "pid": self._pid, "wait_result": result},
                )

        win32.api.CloseHandle(self._job_handle)
        win32.api.CloseHandle(self._process_handle)
        self._closed = True
        remove_entry(self._ledger_path, self.job_id)
        _logger.info("process_terminated", extra={"job_id": self.job_id, "pid": self._pid})


def launch_supervised(
    argv: Sequence[str],
    *,
    ledger_path: Path,
    job_id: str | None = None,
) -> SupervisedProcess:
    """Launch a child process inside a Job Object this engine can always kill.

    Sequence, and why the order is load-bearing (ADR 0013's approved design):

    1. `CreateProcess(..., CREATE_SUSPENDED, ...)` — the child exists but has
       not run one instruction of its own code yet.
    2. PID and process-start-time go to the ledger immediately — before the
       Job Object exists. This closes the enrollment-race window: a crash
       between here and step 3 still leaves the PID discoverable by
       `reconcile_orphans`, whose `None` `job_object_name` tells it there is
       no job to reopen, only a process tree to walk.
    3. `CreateJobObject` + `SetInformationJobObject(...,
       JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)` + `AssignProcessToJobObject`, then
       the ledger entry is updated with the job's name.
    4. `ResumeThread` — only now does the child's own code run.

    If steps 2-3 fail, the child is terminated while still suspended (safe: no
    instruction of its own has executed) and the ledger entry is removed, so a
    failed launch never leaves a governance gap behind.

    Args:
        argv: Executable and arguments. Quoted into a Windows command line
            with `subprocess.list2cmdline` — no process is spawned via
            `subprocess`.
        ledger_path: File the PID/start-time ledger lives in. Pass the same
            path to `reconcile_orphans` to find this entry later.
        job_id: Ledger key and Job Object name suffix. Generated if omitted;
            pass a `JobRecord.id` (ADR 0003) when one exists, to correlate.

    Returns:
        A `SupervisedProcess` wrapping the running (resumed) child.

    Raises:
        ValueError: `argv` is empty, or `job_id` is not a safe token
            (`_JOB_ID_PATTERN`) — it becomes a Windows kernel object name.
        ProcessSupervisorUnavailableError: pywin32 is unavailable.
        ProcessSupervisorError: the OS refused process creation or Job Object
            assignment.
    """
    if not argv:
        msg = "argv must not be empty"
        raise ValueError(msg)

    resolved_job_id = job_id if job_id is not None else uuid.uuid4().hex
    if not _JOB_ID_PATTERN.fullmatch(resolved_job_id):
        msg = f"job_id {resolved_job_id!r} must match {_JOB_ID_PATTERN.pattern!r}"
        raise ValueError(msg)

    win32 = load_win32()
    command_line = subprocess.list2cmdline(list(argv))
    startup_info = win32.process.STARTUPINFO()

    try:
        process_handle, thread_handle, pid, _tid = win32.process.CreateProcess(
            None,
            command_line,
            None,
            None,
            False,
            win32.con.CREATE_SUSPENDED,
            None,
            None,
            startup_info,
        )
    except win32.types.error as exc:
        msg = f"failed to launch {argv[0]!r}: {exc}"
        raise ProcessSupervisorError(msg) from exc

    # The PID is real; record it (and its creation time, only readable now)
    # before anything else that could fail.
    start_time = float(win32.process.GetProcessTimes(process_handle)["CreationTime"].timestamp())
    upsert_entry(ledger_path, resolved_job_id, pid, start_time, job_object_name=None)

    job_object_name = f"{_JOB_NAME_PREFIX}{resolved_job_id}"
    try:
        job_handle = win32.job.CreateJobObject(None, job_object_name)
        limits = win32.job.QueryInformationJobObject(
            job_handle, win32.job.JobObjectExtendedLimitInformation
        )
        limits["BasicLimitInformation"]["LimitFlags"] |= (
            win32.job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32.job.SetInformationJobObject(
            job_handle, win32.job.JobObjectExtendedLimitInformation, limits
        )
        win32.job.AssignProcessToJobObject(job_handle, process_handle)
    except win32.types.error as exc:
        # Still CREATE_SUSPENDED: killing it here loses no work, only the
        # governance gap a partially-assigned process would otherwise leave.
        win32.process.TerminateProcess(process_handle, 1)
        remove_entry(ledger_path, resolved_job_id)
        win32.api.CloseHandle(thread_handle)
        win32.api.CloseHandle(process_handle)
        msg = f"failed to assign {argv[0]!r} (pid {pid}) to a Job Object: {exc}"
        raise ProcessSupervisorError(msg) from exc

    upsert_entry(ledger_path, resolved_job_id, pid, start_time, job_object_name=job_object_name)

    win32.process.ResumeThread(thread_handle)
    win32.api.CloseHandle(thread_handle)

    _logger.info(
        "process_launched", extra={"job_id": resolved_job_id, "pid": pid, "argv0": argv[0]}
    )
    return SupervisedProcess(
        job_id=resolved_job_id,
        pid=pid,
        ledger_path=ledger_path,
        job_object_name=job_object_name,
        process_handle=process_handle,
        job_handle=job_handle,
    )
