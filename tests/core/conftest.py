"""Shared fixtures for `process_supervisor` and its sibling submodules.

`fake_win32` stands in for a real Windows OS whenever a test is exercising
*orchestration* (call order, ledger writes, error-path cleanup) rather than
the OS mechanism itself — the mechanism itself is proven by the
`@pytest.mark.integration` tests, which run against a real `pywin32` and a
real child process.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from src.core._win32_bindings import Win32Handles


class FakeWin32Error(Exception):
    """Stand-in for `pywintypes.error` in every mocked `except win32.types.error:`."""


@pytest.fixture
def fake_win32() -> Win32Handles:
    """A `Win32Handles` bundle of `MagicMock`s, for OS-free orchestration tests.

    A handful of attributes are pinned to real pywin32 constant values rather
    than left as auto-generated `MagicMock` children, because the code under
    test compares against them directly (e.g. `result == win32.event.WAIT_TIMEOUT`).
    """
    event = MagicMock(name="win32event")
    event.WAIT_TIMEOUT = 258
    event.WAIT_OBJECT_0 = 0

    job = MagicMock(name="win32job")
    job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    job.JobObjectExtendedLimitInformation = 9
    job.JOB_OBJECT_TERMINATE = 0x1
    job.QueryInformationJobObject.return_value = {"BasicLimitInformation": {"LimitFlags": 0}}

    con = MagicMock(name="win32con")
    con.CREATE_SUSPENDED = 0x4
    con.PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    con.PROCESS_TERMINATE = 0x1

    process = MagicMock(name="win32process")
    process.CreateProcess.return_value = (
        MagicMock(name="process_handle"),
        MagicMock(name="thread_handle"),
        4242,
        99,
    )
    process.GetProcessTimes.return_value = {
        "CreationTime": SimpleNamespace(timestamp=lambda: 1_700_000_000.0)
    }

    return Win32Handles(
        api=MagicMock(name="win32api"),
        con=con,
        event=event,
        job=job,
        process=process,
        types=SimpleNamespace(error=FakeWin32Error),
    )
