r"""Where this process keeps its own files: the repository, or the user's profile.

Every durable path `Settings` names used to be `REPO_ROOT`-relative, which is
right for a checkout and wrong for the packaged worker (ADR 0030). Inside a
PyInstaller build `REPO_ROOT` resolves into the bundle — read-only under
Program Files, or a temp directory deleted on exit for a one-file build — so
the consumed-jobs ledger and the orphan-process ledger would silently reset on
every restart. The first breaks ADR 0015's single-use guarantee across a
restart; the second leaves a crashed crawl's Screaming Frog running forever.

The rule is one switch, read once per call, never guessed:

* **Not frozen** (a checkout, the test suite, the cloud server): `REPO_ROOT`,
  exactly as before. The cloud server must never write into a user profile,
  and nothing here can make it.
* **Frozen** (`sys.frozen`, set by PyInstaller before any import runs):
  `%LOCALAPPDATA%\Rankuno\Worker`, or `RANKUNO_WORKER_HOME` when set — the
  override exists for support and for tests, and is honoured only when frozen
  so it cannot redirect a server.

This module takes the environment as an argument instead of reading
`os.environ`: `config.py` is the one module allowed to read the environment
(CLAUDE.md §1.3), and it passes `os.environ` in. The read has to happen
*before* `Settings` exists, because it decides which file `Settings` loads.

Permissions: `ensure_private_dir` asks for mode `0o700`, which POSIX enforces
and Windows ignores. On Windows the directory inherits `%LOCALAPPDATA%`'s ACL
(the user, SYSTEM and Administrators), which is the same protection every other
per-user application relies on; no explicit DACL is written. Nothing secret is
stored here regardless — the worker credential lives in Windows Credential
Manager (`credential_vault.py`), and these files hold ids, a public key, URLs
and ledgers.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "WORKER_CONFIG_FILENAME",
    "WORKER_HOME_ENV",
    "ensure_private_dir",
    "env_files",
    "is_frozen",
    "resolve_user_data_root",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKER_HOME_ENV = "RANKUNO_WORKER_HOME"
"""Override for the packaged worker's data directory. Ignored unless frozen."""

WORKER_CONFIG_FILENAME = "worker.env"
"""The packaged worker's one, non-secret configuration file. `rankuno-worker
setup` writes it; `Settings` reads it. A single name rather than the
checkout's `.env` / `.env.local` pair, because an operator who never cloned
the repository has no reason to know that convention."""

_APP_SUBDIR = ("Rankuno", "Worker")


def is_frozen() -> bool:
    """Whether this interpreter is running from a packaged executable.

    PyInstaller sets `sys.frozen`; a normal interpreter never has it. Read on
    every call, not cached, so a test can simulate a frozen build.
    """
    return bool(getattr(sys, "frozen", False))


def resolve_user_data_root(environ: Mapping[str, str], *, frozen: bool) -> Path:
    r"""The directory this process keeps its durable files under.

    Args:
        environ: The process environment, passed in by `config.py`.
        frozen: Usually `is_frozen()`.

    Returns:
        `REPO_ROOT` when not frozen — unconditionally, so a server or a
        checkout is unaffected by anything set in its environment. When
        frozen, `RANKUNO_WORKER_HOME` if set, else
        `%LOCALAPPDATA%\Rankuno\Worker`.
    """
    if not frozen:
        return REPO_ROOT
    override = environ.get(WORKER_HOME_ENV, "").strip()
    if override:
        return Path(override)
    local_app_data = environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base.joinpath(*_APP_SUBDIR)


def env_files(root: Path, *, frozen: bool) -> tuple[Path, ...]:
    """The dotenv files `Settings` reads, in increasing precedence.

    A checkout keeps its `.env` / `.env.local` pair byte-for-byte; the
    packaged worker reads only its own `worker.env`.
    """
    if frozen:
        return (root / WORKER_CONFIG_FILENAME,)
    return (root / ".env", root / ".env.local")


def ensure_private_dir(path: Path) -> Path:
    """Create `path` (and parents) for this user only, where the OS lets us.

    Returns:
        `path`, so a caller can create and use it in one expression.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path
