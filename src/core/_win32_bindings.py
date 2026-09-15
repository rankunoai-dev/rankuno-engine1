"""Deferred pywin32 import, shared by every `process_supervisor` submodule.

`core/` has no platform-detection convention to lean on, and pytest imports
every test module at collection time regardless of `-m` filters. An
unconditional `import win32job` at module scope would turn "pywin32 is a
Windows-only extra" (`pyproject.toml`) into a collection error for the whole
suite on `ci.yml`'s `ubuntu-latest` runners, not a scoped test failure. Every
caller in `process_supervisor.py`, `_process_ledger.py` and
`_process_orphans.py` goes through `load_win32()` instead of importing
`win32*` directly, so importing any of those modules never requires Windows —
only calling into them does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.errors import RankunoError

__all__ = ["ProcessSupervisorError", "ProcessSupervisorUnavailableError", "load_win32"]


class ProcessSupervisorError(RankunoError):
    """A supervised launch or reconciliation failed against a real Windows API.

    Distinct from `ProcessSupervisorUnavailableError`: pywin32 *was* available
    and the OS itself refused the call.
    """


class ProcessSupervisorUnavailableError(ProcessSupervisorError):
    """`pywin32` is not importable, or this is not Windows.

    Raised at first use, not import time — see the module docstring.
    """


@dataclass(frozen=True)
class Win32Handles:
    """The pywin32 submodules process supervision depends on, bound once per call.

    `Any`-typed: pywin32 ships no inline types, and the `win32*`/`pywintypes`
    mypy override (`pyproject.toml`) already treats every symbol as `Any`.
    """

    api: Any
    con: Any
    event: Any
    job: Any
    process: Any
    types: Any


def load_win32() -> Win32Handles:
    """Import pywin32, on the first call that actually needs the OS.

    Raises:
        ProcessSupervisorUnavailableError: pywin32 is not importable — normal
            off Windows, or on Windows without the `pywin32` extra installed.
    """
    try:
        import pywintypes
        import win32api
        import win32con
        import win32event
        import win32job
        import win32process
    except ImportError as exc:  # pragma: no cover - exercised only where pywin32 is absent
        msg = (
            "pywin32 is required for process supervision and is not installed. "
            "This is a Windows-only capability (ADR 0004); install with "
            '`pip install -e ".[pywin32]"` on a Windows workstation.'
        )
        raise ProcessSupervisorUnavailableError(msg) from exc
    return Win32Handles(
        api=win32api,
        con=win32con,
        event=win32event,
        job=win32job,
        process=win32process,
        types=pywintypes,
    )
