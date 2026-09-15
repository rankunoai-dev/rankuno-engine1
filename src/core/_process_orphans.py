"""Startup reconciliation: kill anything `launch_supervised` left running.

Two termination paths, tried in order, and why both exist:

* **Named Job Object reopen** — the normal case. Every `launch_supervised`
  call assigns its child to a Job Object created with a name derived from the
  job id, so a *new* process (this reconciliation routine, running after a
  restart) can reopen it with `OpenJobObject` and terminate the whole tree
  through it — tree-safe, exactly like `SupervisedProcess.terminate()`.
* **`CreateToolhelp32Snapshot` descendant walk** — the fallback, reached only
  for the narrow crash window `launch_supervised` documents: a process was
  created and ledgered, but the crash happened before Job Object assignment
  completed, so there is no job to reopen. pywin32 does not wrap Toolhelp32
  (confirmed by inspection of `win32process`/`win32api`), so this is the one
  place process supervision uses `ctypes` directly rather than pywin32.

Every entry is matched on PID **and** process start time before either path
runs — a bare PID match is not enough, because Windows reuses a PID the
instant its previous holder exits, and killing whatever now holds a recycled
PID would kill a process this engine never launched.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

from src.core._process_ledger import LedgerEntry, read_ledger, write_ledger
from src.core._win32_bindings import load_win32
from src.core.logger import get_logger

__all__ = ["reconcile_orphans"]

_logger = get_logger("core.process_supervisor.orphans")

_START_TIME_TOLERANCE_S = 0.001
"""Looser than a JSON float round-trip needs (that is exact), tight enough
that only the *same* process's creation time can match, not a coincidence."""

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = -1


def _process_is_alive(pid: int) -> bool:
    win32 = load_win32()
    try:
        handle = win32.api.OpenProcess(win32.con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except win32.types.error:
        return False
    win32.api.CloseHandle(handle)
    return True


def _process_start_time(pid: int) -> float | None:
    """The live process's creation time, or `None` if it cannot be opened."""
    win32 = load_win32()
    try:
        handle = win32.api.OpenProcess(win32.con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except win32.types.error:
        return None
    try:
        creation_time = win32.process.GetProcessTimes(handle)["CreationTime"]
    finally:
        win32.api.CloseHandle(handle)
    return float(creation_time.timestamp())


def _kill_via_named_job_object(name: str) -> bool:
    """Reopen a named Job Object from this (new) process and terminate it.

    Returns `False` rather than raising when the name cannot be reopened —
    most commonly because the owning process already exited cleanly and the
    job, with nothing assigned and no other handle open, no longer exists.
    """
    win32 = load_win32()
    try:
        handle = win32.job.OpenJobObject(win32.job.JOB_OBJECT_TERMINATE, False, name)
    except win32.types.error:
        return False
    try:
        win32.job.TerminateJobObject(handle, 1)
    finally:
        win32.api.CloseHandle(handle)
    return True


def _snapshot_parent_pids() -> dict[int, int]:
    """PID -> parent PID for every running process, from one Toolhelp32 snapshot."""
    from ctypes import wintypes

    class _ProcessEntry32(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        )

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:  # pragma: no cover - OS-level failure
        raise ctypes.WinError()

    parents: dict[int, int] = {}
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        found = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _descendant_pids(root_pid: int) -> list[int]:
    """Every process descended from `root_pid`, per one point-in-time snapshot."""
    parents = _snapshot_parent_pids()
    children: dict[int, list[int]] = {}
    for pid, parent_pid in parents.items():
        children.setdefault(parent_pid, []).append(pid)

    descendants: list[int] = []
    frontier = [root_pid]
    while frontier:
        current = frontier.pop()
        kids = children.get(current, [])
        descendants.extend(kids)
        frontier.extend(kids)
    return descendants


def _kill_via_process_tree(root_pid: int) -> list[int]:
    """Best-effort tree termination for a process that was never in a Job Object.

    Each PID is terminated individually; one failing to open does not stop
    the rest.

    Returns:
        PIDs actually terminated, root included when it succeeded.
    """
    win32 = load_win32()
    killed: list[int] = []
    for pid in (root_pid, *_descendant_pids(root_pid)):
        try:
            handle = win32.api.OpenProcess(win32.con.PROCESS_TERMINATE, False, pid)
        except win32.types.error:
            continue
        try:
            win32.api.TerminateProcess(handle, 1)
        except win32.types.error:
            continue
        finally:
            win32.api.CloseHandle(handle)
        killed.append(pid)
    return killed


def reconcile_orphans(ledger_path: Path) -> list[int]:
    """Kill any process this engine launched whose supervisor never cleaned it up.

    Call once at startup. Deliberately independent of
    `DiskJobStore.recover_orphans()` (`state_store.py`, ADR 0013 condition 2):
    that store answers "which job *record* was left `RUNNING`" and has no
    concept of an OS process; this ledger answers "which OS *process* is
    still alive" and has no concept of a `JobRecord`. Neither can be extended
    to answer the other's question without breaking the separation the ADR
    requires.

    Args:
        ledger_path: Same path passed to every `launch_supervised` call whose
            orphans this should catch.

    Returns:
        PIDs actually terminated. An empty ledger, or one whose every entry
        is already gone or belongs to a reused PID, returns `[]`.
    """
    entries = read_ledger(ledger_path)
    killed: list[int] = []
    surviving: dict[str, LedgerEntry] = {}

    for job_id, entry in entries.items():
        if not _process_is_alive(entry.pid):
            _logger.info(
                "orphan_ledger_entry_already_gone", extra={"job_id": job_id, "pid": entry.pid}
            )
            continue

        observed_start = _process_start_time(entry.pid)
        if (
            observed_start is None
            or abs(observed_start - entry.process_start_time) > _START_TIME_TOLERANCE_S
        ):
            # Vanished between the two checks, or a different process now
            # holds this PID. Either way, not ours to kill.
            _logger.warning(
                "orphan_pid_reused_or_vanished", extra={"job_id": job_id, "pid": entry.pid}
            )
            continue

        if entry.job_object_name is not None and _kill_via_named_job_object(entry.job_object_name):
            _logger.warning(
                "orphan_killed_via_job_object",
                extra={"job_id": job_id, "pid": entry.pid, "path": "job_object"},
            )
            killed.append(entry.pid)
            continue

        tree_killed = _kill_via_process_tree(entry.pid)
        if tree_killed:
            _logger.warning(
                "orphan_killed_via_process_tree",
                extra={"job_id": job_id, "pid": entry.pid, "path": "process_tree"},
            )
            killed.extend(tree_killed)
        else:
            _logger.warning("orphan_kill_failed", extra={"job_id": job_id, "pid": entry.pid})
            surviving[job_id] = entry

    write_ledger(ledger_path, surviving)
    return killed
