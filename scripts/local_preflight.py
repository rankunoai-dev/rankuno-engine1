"""Pre-flight guards for `scripts/run_local.ps1`, the local full-site launcher.

The launcher runs the API and the built React UI on this workstation so long
crawls are not bound by the Railway container. The danger in doing that is not
the crawl. It is a workstation process that quietly reaches the *production*
database: `PostgresJobStore` is chosen whenever Postgres looks configured, and
startup orphan recovery would then mark every job running on Railway as
"interrupted by a server restart". So the guard logic lives here, in Python,
where the quality gate tests it. The PowerShell script only orchestrates.

Four subcommands, run by the launcher in this order:

* `scan` refuses a `.env` / `.env.local` that names any production-reaching key,
  or the per-run sign-in token. It matches key NAMES only and never prints a
  value.
* `budget` turns physical RAM into `CRAWL_MEMORY_BUDGET_MIB` (40%, clamped to the
  `Settings` bounds), or validates an explicit override.
* `verify` runs inside the exact child environment the server will get, and
  proves the guard took effect rather than assuming it: Postgres is not
  configured, the environment is development, the worker store is disk, and the
  budget Settings resolved is the one the launcher exported.
* `ui-deps` decides whether the UI's `node_modules` needs `npm ci` before a
  build, and refuses when it would need one but is a link to another folder.

Output from every subcommand is safe to show: key names, file names and
numbers. A `verify` failure reports an exception's type, never its message,
because a pydantic validation error echoes the offending input value.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

# Make `src` importable when this script is run from repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

FORBIDDEN_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_PRIVATE_URL",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "ENVIRONMENT",
)
"""Keys whose mere presence in a dotenv file refuses the launch.

Matched by name, whatever the value: an empty `DATABASE_URL=` is harmless today
but is one paste away from production, and the launcher cannot tell a local URL
from a Railway one without reading the value, which it must not do.
"""

AUTOSIGNIN_TOKEN_KEY = "AUTH_LOCAL_AUTOSIGNIN_TOKEN"  # noqa: S105 - a key name, not a value
"""Refused in a dotenv file whatever its value (ADR 0033).

The launcher generates this token fresh on every start and hands it only to the
server process. One written to disk would be a standing password-free sign-in,
reusable on every launch that forgot to override it.
"""

DOTENV_FILES: tuple[str, ...] = (".env", ".env.local")
BUDGET_KEY = "CRAWL_MEMORY_BUDGET_MIB"
BUDGET_FRACTION = 0.40
BUDGET_MIN_MIB = 256
BUDGET_MAX_MIB = 65536
MIB = 1024 * 1024

# `case_sensitive=False` in both settings classes, and python-dotenv accepts an
# `export ` prefix, so `export database_url = x` configures Postgres just as
# surely as `DATABASE_URL=x`. A bare `^KEY=` check would let both through.
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class ScanResult:
    """What a dotenv scan found: refusals stop the launch, notices do not."""

    refusals: list[str]
    notices: list[str]


def _dotenv_entries(path: Path) -> list[tuple[str, str]]:
    """Return `(KEY, raw_value)` for every assignment line in `path`."""
    if not path.is_file():
        return []
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = _LINE.match(line)
        if match:
            entries.append((match.group(1).upper(), match.group(2)))
    return entries


def _is_postgres(raw_value: str) -> bool:
    """Whether a raw dotenv value selects the postgres worker store."""
    value = raw_value.split(" #", 1)[0].strip().strip("'\"").strip()
    return value.lower() == "postgres"


def scan_dotenv(root: Path) -> ScanResult:
    """Check the dotenv files next to the repo root for production-reaching keys.

    Args:
        root: Repository root the server will run from.

    Returns:
        Refusal and notice messages. Every message names a key and a file,
        never a value.
    """
    refusals: list[str] = []
    notices: list[str] = []
    for name in DOTENV_FILES:
        path = root / name
        for key, raw_value in _dotenv_entries(path):
            if key == "ENVIRONMENT":
                refusals.append(
                    f"{path} defines ENVIRONMENT: comment out or delete the ENVIRONMENT "
                    f"line in {path} (the launcher always runs development)."
                )
            elif key == AUTOSIGNIN_TOKEN_KEY:
                refusals.append(
                    f"{path} defines {key}: the launcher generates a fresh sign-in token "
                    f"on every start, and one stored on disk would never expire. Delete "
                    f"the {key} line in {path}."
                )
            elif key in FORBIDDEN_KEYS:
                refusals.append(
                    f"{path} defines {key}: a local server must never reach a shared "
                    f"database or cache. Comment out or delete the {key} line in {path}."
                )
            elif key == "WORKER_STORE_BACKEND" and _is_postgres(raw_value):
                refusals.append(
                    f"{path} sets WORKER_STORE_BACKEND to postgres: the local server uses "
                    f"the disk worker store. Comment out or delete that line in {path}."
                )
            elif key == BUDGET_KEY:
                notices.append(f"{path} defines {BUDGET_KEY}; the launcher's value overrides it.")
    return ScanResult(refusals=refusals, notices=notices)


def compute_budget_mib(total_bytes: int, override: str | None = None) -> int:
    """Size the crawl memory budget from physical RAM, or validate an override.

    40% leaves the rest for what the budget does not count (graph objects,
    sitemaps, result reads, workbook builds) and for the operating system and
    the operator's browser. It is a share of RAM, not an OOM guarantee (ADR 0031).

    Args:
        total_bytes: Physical RAM in bytes.
        override: An explicit budget in MiB, as typed by the operator.

    Returns:
        The budget in MiB, within the `Settings.crawl_memory_budget_mib` bounds.

    Raises:
        ValueError: The override is not an integer or is out of bounds, or the
            RAM figure is not positive.
    """
    if override is not None:
        if not re.fullmatch(r"\s*\d+\s*", override):
            msg = f"memory budget override must be a whole number of MiB, got {override!r}"
            raise ValueError(msg)
        value = int(override)
        if not BUDGET_MIN_MIB <= value <= BUDGET_MAX_MIB:
            msg = f"memory budget override must be {BUDGET_MIN_MIB}-{BUDGET_MAX_MIB} MiB"
            raise ValueError(msg)
        return value
    if total_bytes <= 0:
        msg = "physical RAM must be a positive number of bytes"
        raise ValueError(msg)
    derived = int((total_bytes / MIB) * BUDGET_FRACTION)
    return max(BUDGET_MIN_MIB, min(BUDGET_MAX_MIB, derived))


UI_DEPS_CURRENT = "current"
UI_DEPS_INSTALL = "install"
LINKED_NODE_MODULES_MESSAGE = (
    "node_modules is a link to another folder; refusing to reinstall through it. "
    "Run npm ci in the link target, or remove the link."
)


class LinkedNodeModulesError(RuntimeError):
    """`node_modules` needs reinstalling but is a junction or symlink."""


def _is_link(path: Path) -> bool:
    """Whether `path` is a symlink or a Windows junction (any reparse point)."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def ui_dependency_action(ui_dir: Path) -> str:
    """Decide whether the UI build first needs `npm ci`.

    Stale means `node_modules/.package-lock.json` is missing or older than
    `package-lock.json`, the same rule the launcher always used. A stale
    `node_modules` that is a link is refused rather than reinstalled: `npm ci`
    deletes `node_modules` first, and through a junction that deletion lands
    in the folder the link points at, which is how one launch emptied another
    checkout's dependencies. A link that is current is fine: a build only
    reads it.

    Args:
        ui_dir: The `rankuno-ui` directory.

    Returns:
        `UI_DEPS_CURRENT` or `UI_DEPS_INSTALL`.

    Raises:
        LinkedNodeModulesError: Stale, and `node_modules` is a link.
    """
    modules = ui_dir / "node_modules"
    lock = ui_dir / "package-lock.json"
    installed = modules / ".package-lock.json"
    try:
        stale = not installed.is_file() or (
            lock.is_file() and lock.stat().st_mtime > installed.stat().st_mtime
        )
    except OSError:
        stale = True
    if not stale:
        return UI_DEPS_CURRENT
    if _is_link(modules):
        raise LinkedNodeModulesError(LINKED_NODE_MODULES_MESSAGE)
    return UI_DEPS_INSTALL


def verify_environment(expect_budget_mib: int) -> dict[str, object]:
    """Prove, inside the server's environment, that the guard took effect.

    Builds the same settings objects `create_app()` will build, from the same
    cwd and environment, so a passing check is a statement about the server
    and not about the launcher.

    Args:
        expect_budget_mib: The budget the launcher exported.

    Returns:
        Non-secret facts about the configuration in force.

    Raises:
        RuntimeError: A guard did not hold.
    """
    from src.core.config import Environment, WorkerStoreBackend, get_settings
    from src.core.postgres_config import get_postgres_settings

    if get_postgres_settings().is_configured():
        msg = "Postgres is still configured after the guard; refusing to start."
        raise RuntimeError(msg)
    settings = get_settings()
    if settings.environment is not Environment.DEVELOPMENT:
        msg = "ENVIRONMENT did not resolve to development; refusing to start."
        raise RuntimeError(msg)
    if settings.worker_store_backend is not WorkerStoreBackend.DISK:
        msg = "WORKER_STORE_BACKEND did not resolve to disk; refusing to start."
        raise RuntimeError(msg)
    if settings.crawl_memory_budget_mib != expect_budget_mib:
        msg = (
            f"Settings resolved a memory budget of {settings.crawl_memory_budget_mib} MiB, "
            f"not the {expect_budget_mib} MiB the launcher exported; refusing to start."
        )
        raise RuntimeError(msg)
    return {
        "postgres_configured": False,
        "environment": settings.environment.value,
        "worker_store_backend": settings.worker_store_backend.value,
        "crawl_memory_budget_mib": settings.crawl_memory_budget_mib,
        "max_concurrent_crawls": settings.max_concurrent_crawls,
        "fair_share_mib": settings.crawl_memory_budget_mib // settings.max_concurrent_crawls,
        "operator_store_empty": not settings.operator_store.list_operators(),
        "job_store": str(Path.cwd() / ".jobs"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local_preflight", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Refuse dotenv files that reach production.")
    scan.add_argument("--root", type=Path, default=REPO_ROOT)
    budget = sub.add_parser("budget", help="Compute or validate the memory budget.")
    budget.add_argument("--total-bytes", type=int, required=True)
    budget.add_argument("--override", default=None)
    verify = sub.add_parser("verify", help="Prove the guard inside the server env.")
    verify.add_argument("--expect-budget", type=int, required=True)
    deps = sub.add_parser("ui-deps", help="Decide whether the UI needs npm ci.")
    deps.add_argument("--ui-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        result = scan_dotenv(args.root)
        for notice in result.notices:
            print(f"notice: {notice}")
        for refusal in result.refusals:
            print(f"REFUSED: {refusal}", file=sys.stderr)
        return 1 if result.refusals else 0
    if args.command == "ui-deps":
        try:
            print(ui_dependency_action(args.ui_dir))
        except LinkedNodeModulesError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "budget":
        try:
            print(compute_budget_mib(args.total_bytes, args.override))
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        facts = verify_environment(args.expect_budget)
    except RuntimeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - type only; the message may echo a value
        print(f"REFUSED: settings failed to load ({type(exc).__name__}).", file=sys.stderr)
        return 1
    print(json.dumps(facts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
