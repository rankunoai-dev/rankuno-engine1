r"""The process an operator actually starts on the Screaming Frog machine.

`run_worker_daemon` shipped with no caller: no console script, no entry in
`scripts/`, nothing outside its own module and its tests. The loop was
correct and unreachable. This module is the missing front door, exposed as
the `rankuno-worker` console script (`pyproject.toml`) and as
`scripts/run_worker_daemon.py` for a checkout that has not been pip
installed.

Configuration, never arguments
------------------------------
The cloud URL, worker id and worker secret are read through
`get_settings()` — `WORKER_CLOUD_API_BASE_URL`, `WORKER_ID`,
`WORKER_ORG_ID`, `WORKER_CREDENTIAL`, normally in `.env.local`. There is
deliberately **no `--worker-secret` flag**, for the same reason
`scripts/create_operator.py` refuses to take a password as an argument: a
secret passed positionally lands in shell history and in every process
listing on the machine. `--check` prints which settings are missing, by
name, and never prints a value.

The packaged worker (ADR 0030)
------------------------------
Frozen into `rankuno-worker.exe`, the same entry point reads a non-secret
`worker.env` from `%LOCALAPPDATA%\Rankuno\Worker` and its credential from
Windows Credential Manager (`src.core.credential_vault`). `rankuno-worker
setup` writes both, and runs by itself on a first interactive launch with no
configuration. In a checkout `setup` is refused and nothing else changes:
`.env.local` and `scripts/register_worker.py` work exactly as before.

Shutdown
--------
`SIGINT`/`SIGTERM` set a flag; `run_worker_daemon` reads it between jobs.
That is what makes Ctrl+C safe here: the default handler would raise
`KeyboardInterrupt` wherever the interpreter happened to be — quite
possibly inside the upload — and leave the cloud holding a partial bundle.
Installing a handler replaces that with "finish this job, then exit". A
second Ctrl+C is left to the operating system, so an operator who genuinely
wants to abandon a running crawl still can.
"""

from __future__ import annotations

import argparse
import signal
import sys
from types import FrameType

from src.core.app_paths import WORKER_CONFIG_FILENAME, ensure_private_dir, is_frozen
from src.core.config import (
    Settings,
    WorkerCredentialStore,
    get_settings,
    reset_settings_cache,
    user_data_root,
)
from src.core.credential_vault import (
    default_vault,
    effective_credential_store,
    resolve_worker_credential,
)
from src.core.errors import ConfigurationError, WorkerCredentialRejectedError
from src.core.logger import get_logger
from src.modules.seo.screaming_frog_control.worker_daemon import run_worker_daemon
from src.modules.seo.screaming_frog_control.worker_setup import SetupConsole, run_setup

__all__ = ["build_parser", "main", "missing_settings"]

_logger = get_logger(__name__)

_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("worker_cloud_api_base_url", "WORKER_CLOUD_API_BASE_URL"),
    ("worker_id", "WORKER_ID"),
    ("worker_org_id", "WORKER_ORG_ID"),
    ("worker_credential", "WORKER_CREDENTIAL"),
)
"""Every setting without which this daemon cannot do its job, and the
environment variable name an operator would actually edit."""

_VERIFY_KEY_ENV = "WORKER_DISPATCH_VERIFY_KEY"
"""Required unless the legacy `WORKER_DISPATCH_SIGNING_SECRET` is set (ADR
0028). Reported by *this* name when both are missing, because a new install
needs only the public verify key and must never be told to obtain the shared
secret. Checked here even though `Settings` generates a random HMAC key
outside production: a *generated* key can never verify an artifact the cloud
signed, so every dispatch would be rejected with nothing pointing at the
cause. Naming it here turns that into one line at startup."""

EXIT_OK = 0
EXIT_CONFIGURATION = 2
EXIT_CREDENTIAL_REJECTED = 3


def missing_settings(settings: Settings) -> list[str]:
    """Environment variable names this daemon needs and does not have.

    Returns names only. A value is never read into the return type, so no
    caller of this function can accidentally log a secret.
    """
    missing = [env_name for attr, env_name in _REQUIRED_SETTINGS if getattr(settings, attr) is None]
    if (
        settings.worker_dispatch_verify_key is None
        and settings.worker_dispatch_signing_secret is None
    ):
        missing.append(_VERIFY_KEY_ENV)
    return missing


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. No option here accepts a secret."""
    parser = argparse.ArgumentParser(
        prog="rankuno-worker",
        description=(
            "Run the Rankuno desktop worker daemon: poll the cloud API for "
            "approved Screaming Frog crawls, run them locally, upload the "
            "results. Configuration comes from .env.local (or, for the packaged "
            "worker, from `rankuno-worker setup`); no secret is ever accepted as "
            "a command-line argument."
        ),
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "setup",
        help="Packaged worker only: sign in once and register this PC as a worker.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report whether this machine is configured, then exit without polling.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Stop after this many poll cycles. Omit to run until stopped.",
    )
    return parser


def _install_signal_handlers(stop: list[bool]) -> None:
    """Route SIGINT/SIGTERM into a flag the poll loop reads between jobs.

    A list rather than a `threading.Event` because a signal handler runs on
    the main thread between bytecodes and needs no synchronisation here —
    and because `run_worker_daemon` takes a plain predicate, not an event,
    so it stays testable without threads.
    """

    def _handle(signum: int, _frame: FrameType | None) -> None:
        _logger.info("worker_daemon_shutdown_requested", extra={"signal": signum})
        stop[0] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle)


def _with_resolved_credential(settings: Settings) -> Settings:
    """Apply `credential_vault`'s precedence to `settings.worker_credential`.

    Returns `settings` itself on a checkout's default path, so nothing about
    that path changes; otherwise a copy carrying the credential the vault
    resolved (or `None`, which `missing_settings` then names).
    """
    frozen = is_frozen()
    if effective_credential_store(settings, frozen=frozen) is WorkerCredentialStore.ENV:
        return settings
    credential = resolve_worker_credential(settings, vault_factory=default_vault, frozen=frozen)
    return settings.model_copy(update={"worker_credential": credential})


def _setup(console: SetupConsole | None = None) -> int:
    """Run interactive setup for the packaged worker, or refuse in a checkout."""
    if not is_frozen():
        print(  # noqa: T201
            "`rankuno-worker setup` configures the packaged worker. In a checkout, "
            "run `python scripts/register_worker.py` instead.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION
    root = ensure_private_dir(user_data_root())
    configured = run_setup(root, console=console or SetupConsole(), vault_factory=default_vault)
    reset_settings_cache()
    return EXIT_OK if configured else EXIT_CONFIGURATION


def _needs_first_run_setup() -> bool:
    """A packaged worker with no `worker.env` yet: the very first launch."""
    return is_frozen() and not (user_data_root() / WORKER_CONFIG_FILENAME).is_file()


def main(argv: list[str] | None = None) -> int:
    """Start the worker daemon, or explain why it cannot start.

    Returns:
        `0` on a clean shutdown, `2` when configuration is incomplete, `3`
        when the cloud refused this worker's credential. Distinct codes so a
        service supervisor can tell "restart me" from "a human must fix
        something" — restarting on a rejected credential is the hot loop
        this whole path exists to avoid.
    """
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        return _setup()
    if not args.check and _needs_first_run_setup():
        if not sys.stdin.isatty():
            print("This worker is not set up. Run: rankuno-worker setup", file=sys.stderr)  # noqa: T201
            return EXIT_CONFIGURATION
        if _setup() != EXIT_OK:
            return EXIT_CONFIGURATION

    try:
        settings = _with_resolved_credential(get_settings())
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)  # noqa: T201
        return EXIT_CONFIGURATION

    missing = missing_settings(settings)
    if missing:
        where = "Run `rankuno-worker setup`" if is_frozen() else "Set these in .env.local first"
        print(  # noqa: T201 - a CLI's own stderr, the same posture scripts/ already takes
            f"Cannot start the worker daemon. {where}:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION

    if args.check:
        print(  # noqa: T201
            f"Worker '{settings.worker_id}' (org '{settings.worker_org_id}') is configured "
            f"for {settings.worker_cloud_api_base_url}."
        )
        return EXIT_OK

    stop = [False]
    _install_signal_handlers(stop)
    _logger.info(
        "worker_daemon_starting",
        extra={"worker_id": settings.worker_id, "org": settings.worker_org_id},
    )
    try:
        run_worker_daemon(
            settings=settings,
            max_iterations=args.max_iterations,
            should_stop=lambda: stop[0],
        )
    except WorkerCredentialRejectedError as exc:
        print(f"Worker credential rejected: {exc}", file=sys.stderr)  # noqa: T201
        return EXIT_CREDENTIAL_REJECTED
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)  # noqa: T201
        return EXIT_CONFIGURATION
    _logger.info("worker_daemon_stopped")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via `main()` in tests
    raise SystemExit(main())
