"""Tests for `launch_supervised` / `SupervisedProcess`.

Two layers:

* Orchestration unit tests, using the `fake_win32` fixture (`conftest.py`) so
  call order, ledger writes and error-path cleanup are verified without
  touching a real OS process, on any platform.
* `@pytest.mark.integration` tests (Windows-only, `skipif` elsewhere) that
  prove the real Job Object mechanism: `terminate()` actually kills a real
  child, and — the guarantee the whole ADR exists for — a supervisor that
  crashes without running one line of cleanup code still cannot leave its
  child running, because the OS closes the Job Object handle for it.
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404 - only `list2cmdline` and a controlled, argv-list `subprocess.run`
import sys
import time
from unittest.mock import MagicMock

import pytest
from src.core import process_supervisor
from src.core._process_ledger import read_ledger, upsert_entry
from src.core.process_supervisor import (
    ProcessSupervisorError,
    SupervisedProcess,
    launch_supervised,
)


class TestLaunchSupervisedValidation:
    """Guard clauses that run before `load_win32()` — no fixture needed."""

    def test_argv_must_not_be_empty(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="argv must not be empty"):
            launch_supervised([], ledger_path=tmp_path / "ledger.json")

    def test_job_id_must_match_the_safe_token_pattern(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="must match"):
            launch_supervised(["fake.exe"], ledger_path=tmp_path / "ledger.json", job_id="not/safe")


class TestLaunchSupervisedOrchestration:
    """Mocked pywin32 — proves the sequencing and cleanup contract, not the OS."""

    def test_pid_is_recorded_before_job_object_assignment_completes(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        """The load-bearing ordering guarantee.

        `upsert_entry` runs with `job_object_name=None` strictly before
        `AssignProcessToJobObject`.
        """
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        upsert_spy = MagicMock(wraps=upsert_entry)
        monkeypatch.setattr(process_supervisor, "upsert_entry", upsert_spy)

        def _assert_pid_already_ledgered(job_handle: object, process_handle: object) -> None:
            assert upsert_spy.call_count == 1
            assert upsert_spy.mock_calls[0].kwargs["job_object_name"] is None

        fake_win32.job.AssignProcessToJobObject.side_effect = _assert_pid_already_ledgered

        launch_supervised(["fake.exe"], ledger_path=tmp_path / "ledger.json", job_id="job-1")

        assert upsert_spy.call_count == 2
        assert upsert_spy.mock_calls[1].kwargs["job_object_name"] is not None

    def test_returns_a_supervised_process_with_the_launched_pid(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)

        result = launch_supervised(
            ["fake.exe"], ledger_path=tmp_path / "ledger.json", job_id="job-1"
        )

        assert isinstance(result, SupervisedProcess)
        assert result.job_id == "job-1"
        assert result.pid == 4242
        fake_win32.process.ResumeThread.assert_called_once()
        fake_win32.api.CloseHandle.assert_called_once()  # only the thread handle, on success

    def test_a_job_id_is_generated_when_omitted(self, monkeypatch, fake_win32, tmp_path) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)

        result = launch_supervised(["fake.exe"], ledger_path=tmp_path / "ledger.json")

        assert re.fullmatch(r"[0-9a-f]{32}", result.job_id)

    def test_the_job_object_name_is_derived_from_the_job_id(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)

        launch_supervised(["fake.exe"], ledger_path=tmp_path / "ledger.json", job_id="my-job")

        _name, name_arg = fake_win32.job.CreateJobObject.call_args.args
        assert name_arg == "Local\\rankuno-process-supervisor-my-job"

    def test_argv_is_quoted_into_a_windows_command_line(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        argv = ["C:\\Program Files\\x\\y.exe", "--flag", "value with spaces"]

        launch_supervised(argv, ledger_path=tmp_path / "ledger.json")

        command_line = fake_win32.process.CreateProcess.call_args.args[1]
        assert command_line == subprocess.list2cmdline(argv)

    def test_create_process_failure_raises_and_writes_no_ledger_entry(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.process.CreateProcess.side_effect = fake_win32.types.error("boom")
        ledger_path = tmp_path / "ledger.json"

        with pytest.raises(ProcessSupervisorError, match="boom"):
            launch_supervised(["fake.exe"], ledger_path=ledger_path)

        assert read_ledger(ledger_path) == {}

    def test_job_object_assignment_failure_kills_the_suspended_child(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        """Still `CREATE_SUSPENDED`.

        Killing it here loses no work, only closes the governance gap a
        partially-assigned process would otherwise leave.
        """
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.job.AssignProcessToJobObject.side_effect = fake_win32.types.error("denied")
        ledger_path = tmp_path / "ledger.json"

        with pytest.raises(ProcessSupervisorError, match="denied"):
            launch_supervised(["fake.exe"], ledger_path=ledger_path, job_id="job-x")

        fake_win32.process.TerminateProcess.assert_called_once()
        assert read_ledger(ledger_path) == {}

    def test_create_job_object_failure_also_kills_the_suspended_child(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.job.CreateJobObject.side_effect = fake_win32.types.error("denied")
        ledger_path = tmp_path / "ledger.json"

        with pytest.raises(ProcessSupervisorError):
            launch_supervised(["fake.exe"], ledger_path=ledger_path, job_id="job-x")

        fake_win32.process.TerminateProcess.assert_called_once()
        assert read_ledger(ledger_path) == {}


class TestSupervisedProcessUnit:
    """Mocked pywin32 — proves `SupervisedProcess`'s own contract."""

    @staticmethod
    def _make(fake_win32, ledger_path, job_id: str = "job-1") -> SupervisedProcess:
        return SupervisedProcess(
            job_id=job_id,
            pid=4242,
            ledger_path=ledger_path,
            job_object_name="Local\\rankuno-process-supervisor-job-1",
            process_handle=MagicMock(name="process_handle"),
            job_handle=MagicMock(name="job_handle"),
        )

    def test_pid_property_reports_the_launched_pid(self, fake_win32, tmp_path) -> None:
        supervised = self._make(fake_win32, tmp_path / "ledger.json")
        assert supervised.pid == 4242

    def test_is_running_true_when_the_wait_times_out(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.event.WaitForSingleObject.return_value = fake_win32.event.WAIT_TIMEOUT
        supervised = self._make(fake_win32, tmp_path / "ledger.json")

        assert supervised.is_running() is True

    def test_is_running_false_when_the_wait_is_signalled(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.event.WaitForSingleObject.return_value = fake_win32.event.WAIT_OBJECT_0
        supervised = self._make(fake_win32, tmp_path / "ledger.json")

        assert supervised.is_running() is False

    def test_terminate_calls_terminate_job_object_and_closes_both_handles(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        supervised = self._make(fake_win32, tmp_path / "ledger.json")

        supervised.terminate()

        fake_win32.job.TerminateJobObject.assert_called_once()
        assert fake_win32.api.CloseHandle.call_count == 2

    def test_terminate_is_idempotent(self, monkeypatch, fake_win32, tmp_path) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        supervised = self._make(fake_win32, tmp_path / "ledger.json")

        supervised.terminate()
        fake_win32.job.TerminateJobObject.reset_mock()
        supervised.terminate()

        fake_win32.job.TerminateJobObject.assert_not_called()

    def test_terminate_removes_the_ledger_entry(self, monkeypatch, fake_win32, tmp_path) -> None:
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        ledger_path = tmp_path / "ledger.json"
        upsert_entry(
            ledger_path,
            "job-1",
            pid=4242,
            process_start_time=1.0,
            job_object_name="Local\\rankuno-process-supervisor-job-1",
        )
        supervised = self._make(fake_win32, ledger_path)

        supervised.terminate()

        assert read_ledger(ledger_path) == {}

    def test_terminate_still_cleans_up_when_terminate_job_object_raises(
        self, monkeypatch, fake_win32, tmp_path
    ) -> None:
        """A `TerminateJobObject` failure is logged and swallowed, not raised.

        Most commonly: the process already exited on its own — a no-op, not a
        failure.
        """
        monkeypatch.setattr(process_supervisor, "load_win32", lambda: fake_win32)
        fake_win32.job.TerminateJobObject.side_effect = fake_win32.types.error("already gone")
        supervised = self._make(fake_win32, tmp_path / "ledger.json")

        supervised.terminate()  # must not raise

        assert fake_win32.api.CloseHandle.call_count == 2
        assert supervised.is_running() is False


def _pid_is_alive(pid: int) -> bool:
    """Windows-only liveness probe, used only by the real integration tests below.

    Checks the signaled state via `WaitForSingleObject`, not merely whether
    `OpenProcess` succeeds: a PID stays "reserved" — `OpenProcess` keeps
    succeeding — for as long as *any* handle to it remains open anywhere,
    even after the process has actually exited.
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
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
class TestRealWindowsKillOnJobClose:
    """Proof against a real OS process, not just that mocked code ran without error."""

    def test_terminate_kills_the_real_child_process(self, tmp_path) -> None:
        ledger_path = tmp_path / "ledger.json"
        supervised = launch_supervised(["ping", "-t", "127.0.0.1"], ledger_path=ledger_path)
        pid = supervised.pid
        assert _pid_is_alive(pid)
        assert supervised.is_running() is True

        supervised.terminate()
        time.sleep(0.3)

        assert supervised.is_running() is False
        assert not _pid_is_alive(pid), f"pid {pid} is still alive after terminate()"
        assert read_ledger(ledger_path) == {}

    def test_kill_on_job_close_survives_an_unclean_supervisor_exit(self, tmp_path) -> None:
        """The regression ADR 0013 exists to prevent.

        RAE's Screaming Frog launch left the JVM running when its own cancel
        path never ran. `os._exit()` in the child interpreter skips every
        `atexit` hook and every `finally` block this module has — including
        `terminate()`. If the ping process dies anyway, it is the OS closing
        the Job Object handle on process teardown that did it, not any Python
        code of ours.
        """
        ledger_path = tmp_path / "ledger.json"
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "from src.core.process_supervisor import launch_supervised\n"
            "sp = launch_supervised(['ping', '-t', '127.0.0.1'], "
            f"ledger_path=Path(r'{ledger_path}'))\n"
            "print(sp.pid, flush=True)\n"
            "os._exit(1)\n"
        )

        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, test-only child
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        assert result.returncode == 1, result.stderr
        pid = int(result.stdout.strip())

        time.sleep(0.5)  # let the kernel finish tearing the job down
        assert not _pid_is_alive(pid), f"pid {pid} survived an unclean supervisor exit"
