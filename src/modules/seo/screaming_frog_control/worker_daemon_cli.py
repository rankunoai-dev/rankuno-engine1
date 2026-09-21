"""The process an operator actually starts on the Screaming Frog machine.

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

from src.core.config import Settings, get_settings
from src.core.errors import ConfigurationError, WorkerCredentialRejectedError
from src.core.logger import get_logger
from src.modules.seo.screaming_frog_control.worker_daemon import run_worker_daemon

__all__ = ["build_parser", "main", "missing_settings"]

_logger = get_logger(__name__)

_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("worker_cloud_api_base_url", "WORKER_CLOUD_API_BASE_URL"),
    ("worker_id", "WORKER_ID"),
    ("worker_org_id", "WORKER_ORG_ID"),
    ("worker_credential", "WORKER_CREDENTIAL"),
    ("worker_dispatch_signing_secret", "WORKER_DISPATCH_SIGNING_SECRET"),
)
"""Every setting without which this daemon cannot do its job, and the
environment variable name an operator would actually edit.

`WORKER_DISPATCH_SIGNING_SECRET` is in this list even though `Settings`
generates a random one outside production, because a *generated* key on the
worker side can never verify an artifact the cloud signed: every dispatch
would be rejected as a bad signature, with nothing in the message pointing
at the real cause. Naming it here turns that into one line at startup."""

EXIT_OK = 0
EXIT_CONFIGURATION = 2
EXIT_CREDENTIAL_REJECTED = 3


def missing_settings(settings: Settings) -> list[str]:
    """Environment variable names this daemon needs and does not have.

    Returns names only. A value is never read into the return type, so no
    caller of this function can accidentally log a secret.
    """
    return [env_name for attr, env_name in _REQUIRED_SETTINGS if getattr(settings, attr) is None]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. No option here accepts a secret."""
    parser = argparse.ArgumentParser(
        prog="rankuno-worker",
        description=(
            "Run the Rankuno desktop worker daemon: poll the cloud API for "
            "approved Screaming Frog crawls, run them locally, upload the "
            "results. Configuration comes from .env.local; no secret is ever "
            "accepted as a command-line argument."
        ),
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
    settings = get_settings()

    missing = missing_settings(settings)
    if missing:
        print(  # noqa: T201 - a CLI's own stderr, the same posture scripts/ already takes
            "Cannot start the worker daemon. Set these in .env.local first:\n  "
            + "\n  ".join(missing),
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
