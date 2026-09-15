"""Tests for the deferred pywin32 import shared across process-supervisor modules."""

from __future__ import annotations

import sys

import pytest
from src.core._win32_bindings import ProcessSupervisorUnavailableError, Win32Handles, load_win32


class TestLoadWin32:
    def test_returns_bound_submodules_when_pywin32_is_installed(self) -> None:
        """On this test machine pywin32 is genuinely installed; no mocking here."""
        handles = load_win32()
        assert isinstance(handles, Win32Handles)
        assert handles.job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        assert handles.types.error is not None

    def test_raises_a_clear_error_when_pywin32_cannot_be_imported(self, monkeypatch) -> None:
        """`sys.modules[name] = None` is the documented way to force an `ImportError`.

        Simulates both "not Windows" and "Windows without the `pywin32` extra
        installed" — `load_win32` cannot tell those apart, and does not need to.
        """
        for name in (
            "pywintypes",
            "win32api",
            "win32con",
            "win32event",
            "win32job",
            "win32process",
        ):
            monkeypatch.setitem(sys.modules, name, None)

        with pytest.raises(ProcessSupervisorUnavailableError, match="pywin32"):
            load_win32()
