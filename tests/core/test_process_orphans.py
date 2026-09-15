"""Tests for startup orphan reconciliation.

Two layers, matching the acceptance criteria:

* Unit tests monkeypatch the individual kill-path functions, so the
  PID/start-time matching logic, path selection, and ledger bookkeeping are
  verified without touching a real OS process, on any platform.
* `@pytest.mark.integration` tests (Windows-only, `skipif` elsewhere) prove
  both real kill paths — named Job Object reopen, and the
  `CreateToolhelp32Snapshot` descendant-walk fallback — actually terminate a
  real child process, not just that mocked code ran without error.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from src.core import _process_orphans as orphans_mod
from src.core._process_ledger import read_ledger, upsert_entry
from src.core._process_orphans import reconcile_orphans
from src.core.process_supervisor import launch_supervised


class TestReconcileOrphansUnit:
    def test_an_empty_ledger_kills_nothing(self, tmp_path) -> None:
        assert reconcile_orphans(tmp_path / "ledger.json") == []

    def test_a_dead_pid_is_dropped_without_being_killed(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name=None)
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: False)

        killed = reconcile_orphans(path)

        assert killed == []
        assert read_ledger(path) == {}

    def test_a_reused_pid_is_never_touched(self, tmp_path, monkeypatch) -> None:
        """Start time mismatch means a different process now holds this PID."""
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name=None)
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 999.0)
        kill_spy = MagicMock()
        monkeypatch.setattr(orphans_mod, "_kill_via_named_job_object", kill_spy)
        monkeypatch.setattr(orphans_mod, "_kill_via_process_tree", kill_spy)

        killed = reconcile_orphans(path)

        assert killed == []
        kill_spy.assert_not_called()
        assert read_ledger(path) == {}

    def test_a_start_time_that_cannot_be_read_is_treated_as_vanished(
        self, tmp_path, monkeypatch
    ) -> None:
        """Alive at the liveness check, gone by the time start time is read."""
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name=None)
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: None)

        assert reconcile_orphans(path) == []
        assert read_ledger(path) == {}

    def test_a_confirmed_orphan_is_killed_via_its_named_job_object(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name="Local\\x")
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 1.0)
        monkeypatch.setattr(orphans_mod, "_kill_via_named_job_object", lambda name: True)

        def _fail_if_called(root_pid: int) -> list[int]:
            raise AssertionError("process-tree fallback must not run when the job path succeeds")

        monkeypatch.setattr(orphans_mod, "_kill_via_process_tree", _fail_if_called)

        killed = reconcile_orphans(path)

        assert killed == [111]
        assert read_ledger(path) == {}

    def test_no_job_object_name_goes_straight_to_the_process_tree_path(
        self, tmp_path, monkeypatch
    ) -> None:
        """`job_object_name is None` is exactly the narrow crash window."""
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name=None)
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 1.0)

        def _fail_if_called(name: str) -> bool:
            raise AssertionError("named job object path must not run without a name")

        monkeypatch.setattr(orphans_mod, "_kill_via_named_job_object", _fail_if_called)
        monkeypatch.setattr(orphans_mod, "_kill_via_process_tree", lambda root_pid: [111, 222])

        killed = reconcile_orphans(path)

        assert killed == [111, 222]
        assert read_ledger(path) == {}

    def test_a_failed_job_object_reopen_falls_back_to_the_process_tree(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name="Local\\x")
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 1.0)
        monkeypatch.setattr(orphans_mod, "_kill_via_named_job_object", lambda name: False)
        monkeypatch.setattr(orphans_mod, "_kill_via_process_tree", lambda root_pid: [111])

        assert reconcile_orphans(path) == [111]

    def test_an_entry_that_cannot_be_killed_by_either_path_survives_for_next_startup(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "job-1", pid=111, process_start_time=1.0, job_object_name=None)
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: True)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 1.0)
        monkeypatch.setattr(orphans_mod, "_kill_via_process_tree", lambda root_pid: [])

        killed = reconcile_orphans(path)

        assert killed == []
        assert "job-1" in read_ledger(path)

    def test_unrelated_entries_are_reconciled_independently(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "ledger.json"
        upsert_entry(path, "dead", pid=1, process_start_time=1.0, job_object_name=None)
        upsert_entry(path, "alive", pid=2, process_start_time=2.0, job_object_name="Local\\y")
        monkeypatch.setattr(orphans_mod, "_process_is_alive", lambda pid: pid == 2)
        monkeypatch.setattr(orphans_mod, "_process_start_time", lambda pid: 2.0)
        monkeypatch.setattr(orphans_mod, "_kill_via_named_job_object", lambda name: True)

        killed = reconcile_orphans(path)

        assert killed == [2]
        assert read_ledger(path) == {}


def _pid_is_alive(pid: int) -> bool:
    """Windows-only liveness probe, used only by the real integration tests below.

    Checks the signaled state via `WaitForSingleObject`, not merely whether
    `OpenProcess` succeeds: a PID stays "reserved" — `OpenProcess` keeps
    succeeding — for as long as *any* handle to it remains open anywhere,
    including a handle this same test process opened earlier and has not
    closed, even after the process has actually exited.
    """
    import pywintypes
    import win32api
    import win32con
    import win32event

    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE, False, pid
        )
    except pywintypes.error:
        return False
    try:
        return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_TIMEOUT
    finally:
        win32api.CloseHandle(handle)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects and Toolhelp32 are Windows-only")
class TestOrphanHelpersAgainstRealWindows:
    """The "not found" branches of the low-level win32 wrappers, against a real OS.

    No mocking: an implausibly large PID and a kernel object name that was
    never created are genuinely absent, so these exercise the real
    `except win32.types.error:` paths the mocked orchestration tests above
    cannot reach (they replace the whole function, not just the OS call).
    """

    def test_process_is_alive_is_false_for_a_pid_that_does_not_exist(self) -> None:
        assert orphans_mod._process_is_alive(999_999_999) is False

    def test_process_start_time_is_none_for_a_pid_that_does_not_exist(self) -> None:
        assert orphans_mod._process_start_time(999_999_999) is None

    def test_kill_via_named_job_object_is_false_for_an_unknown_name(self) -> None:
        name = "Local\\rankuno-process-supervisor-does-not-exist"
        assert orphans_mod._kill_via_named_job_object(name) is False


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects and Toolhelp32 are Windows-only")
class TestReconcileOrphansRealWindows:
    def test_kills_a_real_orphan_via_the_named_job_object_path(self, tmp_path) -> None:
        """A process launched normally, then reconciled as if this were a fresh startup."""
        import time

        ledger_path = tmp_path / "ledger.json"
        supervised = launch_supervised(
            ["ping", "-t", "127.0.0.1"], ledger_path=ledger_path, job_id="orphan-via-job"
        )
        pid = supervised.pid
        assert _pid_is_alive(pid)

        try:
            killed = reconcile_orphans(ledger_path)
            time.sleep(0.3)  # let the OS finish tearing the process down

            assert killed == [pid]
            assert not _pid_is_alive(pid), f"pid {pid} is still alive after reconcile_orphans"
            assert "orphan-via-job" not in read_ledger(ledger_path)
        finally:
            supervised.terminate()  # idempotent cleanup of our own handles

    def test_kills_a_real_orphan_via_the_process_tree_fallback(self, tmp_path) -> None:
        """No Job Object was ever assigned — the narrow crash window, simulated directly."""
        import time

        import win32api
        import win32process

        ledger_path = tmp_path / "ledger.json"
        startup_info = win32process.STARTUPINFO()
        process_handle, thread_handle, pid, _tid = win32process.CreateProcess(
            None, "ping -t 127.0.0.1", None, None, False, 0, None, None, startup_info
        )
        start_time = float(win32process.GetProcessTimes(process_handle)["CreationTime"].timestamp())
        upsert_entry(
            ledger_path,
            "orphan-via-tree",
            pid=pid,
            process_start_time=start_time,
            job_object_name=None,
        )
        win32api.CloseHandle(thread_handle)
        win32api.CloseHandle(process_handle)
        assert _pid_is_alive(pid)

        killed = reconcile_orphans(ledger_path)
        time.sleep(0.3)  # let the OS finish tearing the process down

        assert killed == [pid]
        assert not _pid_is_alive(pid), f"pid {pid} is still alive after reconcile_orphans"
        assert "orphan-via-tree" not in read_ledger(ledger_path)
