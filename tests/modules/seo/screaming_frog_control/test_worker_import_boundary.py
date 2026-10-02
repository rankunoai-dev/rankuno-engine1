"""The standalone worker executable must contain no engine code (ADR 0030).

PyInstaller bundles exactly the import closure of its entry point, so "what
does importing the worker CLI load" *is* "what ships inside rankuno-worker.exe".
Before ADR 0030 that closure held 11 engine modules (`page_classifier.*`,
`contracts.*`) reached through two incidental imports; a decompiled executable
would have handed out the classification cascade and the issue catalogue.

A subprocess is required: `sys.modules` is shared by the whole pytest session,
so in-process every engine module some earlier test imported would already be
"loaded" and the check would mean nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

WORKER_ENTRY_POINTS = (
    "src.modules.seo.screaming_frog_control.worker_daemon_cli",
    "src.modules.seo.screaming_frog_control.worker_setup",
)

ALLOWED_PREFIXES = (
    "src.core",
    "src.integrations.base_client",
    "src.integrations.worker_cloud_client",
    "src.integrations.worker_registration_client",
    "src.modules.seo.screaming_frog_control",
)
"""Everything a worker may load. An allowlist, not a denylist, so a new
engine package is refused without anyone remembering to name it here."""

ALLOWED_EXACT = frozenset({"src", "src.integrations", "src.modules", "src.modules.seo"})
"""Package `__init__` modules on the way to the allowed ones."""

_PROBE = """
import json, sys
for name in sys.argv[1:]:
    __import__(name)
print(json.dumps(sorted(m for m in sys.modules if m == "src" or m.startswith("src."))))
"""


def _loaded_src_modules() -> list[str]:
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, no shell
        [sys.executable, "-c", _PROBE, *WORKER_ENTRY_POINTS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    loaded: list[str] = json.loads(result.stdout.strip().splitlines()[-1])
    return loaded


def _is_allowed(module: str) -> bool:
    if module in ALLOWED_EXACT:
        return True
    return any(module == prefix or module.startswith(prefix + ".") for prefix in ALLOWED_PREFIXES)


def test_the_worker_loads_no_engine_or_server_module() -> None:
    loaded = _loaded_src_modules()
    forbidden = [module for module in loaded if not _is_allowed(module)]
    assert forbidden == [], (
        f"The worker CLI's import closure reaches {len(forbidden)} engine/server "
        f"module(s); they would ship inside rankuno-worker.exe: {forbidden}"
    )


def test_the_probe_actually_sees_the_worker() -> None:
    """Guard against a vacuous pass: the closure must contain the entry points."""
    loaded = _loaded_src_modules()
    assert set(WORKER_ENTRY_POINTS) <= set(loaded)
    assert "src.modules.seo.screaming_frog_control.worker_daemon" in loaded
