"""Copy one finished local crawl into the cloud, as a job in your cloud org (ADR 0034).

Usage:
    python scripts/push_job_to_cloud.py --list [--target groundsguys.com]
    python scripts/push_job_to_cloud.py --latest --target groundsguys.com
    python scripts/push_job_to_cloud.py --job 42de4ed7b5ff44e8a592922aa99dfaeb
        [--operator alice] [--source-label office-desktop] [--cloud-url https://...]
        [--dry-run] [--yes]

How it behaves:

* It reads `.jobs/` through `DiskJobStore` directly and never through the
  server's store factory, so no database setting can redirect it (ADR 0032).
  The server is not involved; it does not need to be running.
* `--dry-run` and `--list` write nothing at all, not even the instance id.
* The password is read only from a masked prompt. It is never an argument, an
  environment variable or a file, and it is never stored. The session token
  is held in memory for this run and dropped at exit. That token is valid for
  12 hours, so treat a terminal it ran in accordingly.
* The cloud URL comes from `--cloud-url` or `CLOUD_IMPORT_BASE_URL`, and must
  be https (plain http only to localhost). Redirects are refused.
* Pushing the same job twice is safe: the cloud answers "already imported".

Exit codes: 0 imported or already there; 2 local problem or bad usage; 3 sign-in
refused; 4 the cloud refused the bundle; 5 the cloud could not be reached.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from getpass import getpass
from pathlib import Path
from typing import TextIO

# Make `src` importable when this is run directly from the repository root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.config import get_settings  # noqa: E402
from src.core.errors import ConfigurationError, IntegrationError  # noqa: E402
from src.core.job_provenance import SOURCE_JOB_ID_PATTERN  # noqa: E402
from src.core.state_store import DiskJobStore, JobRecord  # noqa: E402
from src.integrations.rankuno_cloud_client import (  # noqa: E402
    CloudImportRejectedError,
    RankunoCloudClient,
)
from src.integrations.worker_cloud_client import require_secure_base_url  # noqa: E402
from src.modules.seo.page_classifier.job_bundle import BundleSource  # noqa: E402
from src.modules.seo.page_classifier.local_job_export import (  # noqa: E402
    ExportRefusedError,
    build_bundle,
    encode_bundle,
    exportable_jobs,
    load_or_create_instance_id,
    read_instance_id,
)

EXIT_OK, EXIT_LOCAL, EXIT_AUTH, EXIT_REFUSED, EXIT_NETWORK = 0, 2, 3, 4, 5

_DRY_RUN_INSTANCE = "dry-run-not-saved"
"""Stands in for the instance id on a dry run, which must not create the file."""

ClientFactory = Callable[[str], RankunoCloudClient]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="push_job_to_cloud",
        description="Copy a finished local crawl into your cloud org.",
    )
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument("--list", action="store_true", help="List local crawls that can be pushed")
    pick.add_argument("--job", help="Local job id (32 hex characters)")
    pick.add_argument("--latest", action="store_true", help="Newest finished crawl of --target")
    parser.add_argument("--target", help="Domain or URL, e.g. groundsguys.com (ignores www.)")
    parser.add_argument("--operator", help="Cloud operator id (prompted if omitted)")
    parser.add_argument("--source-label", help="Optional name for this machine, e.g. office-pc")
    parser.add_argument("--cloud-url", help="Cloud API root; overrides CLOUD_IMPORT_BASE_URL")
    parser.add_argument(
        "--jobs-dir", type=Path, default=REPO_ROOT / ".jobs", help=argparse.SUPPRESS
    )
    parser.add_argument("--dry-run", action="store_true", help="Build and check; send nothing")
    parser.add_argument("--yes", action="store_true", help="Do not ask before uploading")
    return parser


def _describe(record: JobRecord) -> str:
    finished = record.finished_at.strftime("%Y-%m-%d %H:%M UTC") if record.finished_at else "?"
    pages = record.telemetry.completed
    return f"{record.id}  {record.status.value:<9}  {finished}  {pages:>7,} fetched  {record.label}"


def _pick(store: DiskJobStore, args: argparse.Namespace, out: TextIO) -> JobRecord | None:
    if args.job:
        if not re.fullmatch(SOURCE_JOB_ID_PATTERN, args.job):
            # Checked before the id becomes part of a file path.
            print("--job must be a local job id: 32 lowercase hex characters.", file=out)
            return None
        try:
            return store.get(args.job)
        except (KeyError, ValueError):
            print(f"No local job {args.job} in {store.root}.", file=out)
            return None
    if not args.target:
        print("--latest needs --target, e.g. --target groundsguys.com", file=out)
        return None
    candidates = exportable_jobs(store, args.target)
    if not candidates:
        print(f"No finished local crawl of {args.target}.", file=out)
        return None
    return candidates[0]


def run(  # noqa: C901, PLR0911, PLR0912 - one linear CLI flow; splitting it hides the order
    argv: list[str] | None = None,
    *,
    out: TextIO = sys.stdout,
    read_password: Callable[[str], str] = getpass,
    read_line: Callable[[str], str] = input,
    is_interactive: Callable[[], bool] = sys.stdin.isatty,
    client_factory: ClientFactory = RankunoCloudClient,
) -> int:
    """The whole CLI, with its terminal and network injectable for tests."""
    args = build_parser().parse_args(argv)
    if not args.jobs_dir.is_dir():
        print(f"No jobs directory at {args.jobs_dir}.", file=out)
        return EXIT_LOCAL
    store = DiskJobStore(args.jobs_dir)

    if args.list:
        records = exportable_jobs(store, args.target)
        print(f"{len(records)} finished crawl(s) can be pushed (newest first):", file=out)
        for listed in records:
            print(f"  {_describe(listed)}", file=out)
        return EXIT_OK

    record = _pick(store, args, out)
    if record is None:
        return EXIT_LOCAL

    try:
        if args.dry_run:
            instance_id = read_instance_id(args.jobs_dir) or _DRY_RUN_INSTANCE
        else:
            instance_id = load_or_create_instance_id(args.jobs_dir)
        source = BundleSource(
            source_instance_id=instance_id,
            source_label=args.source_label,
            source_job_id=record.id,
        )
        built = build_bundle(store, record, source)
    except (ExportRefusedError, ValueError) as exc:
        print(f"Cannot push this job: {exc}", file=out)
        return EXIT_LOCAL

    payload = built.bundle.model_dump_json().encode("utf-8")
    body = encode_bundle(built.bundle)
    print(f"Local job   {record.id}  {built.bundle.result.base_url}", file=out)
    print(
        f"            {record.status.value}, finished "
        f"{built.bundle.finished_at:%Y-%m-%d %H:%M UTC}, {len(built.bundle.result.pages):,} pages",
        file=out,
    )
    print(
        f"Bundle      {len(payload) / 1e6:.1f} MB -> {len(body) / 1e6:.2f} MB gzip"
        f"{', homepage left out (over 5 MiB)' if built.homepage_dropped else ''}",
        file=out,
    )
    del payload
    if args.dry_run:
        print(
            "Dry run: the bundle passed every check the cloud applies. Nothing was sent.", file=out
        )
        return EXIT_OK

    try:
        base_url = require_secure_base_url(
            args.cloud_url or get_settings().require("cloud_import_base_url"),
            setting_name="--cloud-url" if args.cloud_url else "CLOUD_IMPORT_BASE_URL",
        )
    except ConfigurationError as exc:
        print(str(exc), file=out)
        return EXIT_LOCAL
    print(f"Cloud       {base_url}", file=out)

    if not is_interactive():
        print("The password prompt needs an interactive terminal; refusing to read it.", file=out)
        return EXIT_LOCAL
    operator = args.operator or read_line("Operator id: ").strip()
    password = read_password("Password: ")
    if not args.yes:
        answer = read_line(f"Upload this crawl to {base_url} as {operator}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Not uploaded.", file=out)
            return EXIT_OK

    client = client_factory(base_url)
    try:
        try:
            org_id = client.login(operator, password)
        except CloudImportRejectedError as exc:
            print(f"Sign-in refused: {exc.detail}", file=out)
            return EXIT_AUTH
        finally:
            del password
        print(f"Signed in (org: {org_id}). Uploading {len(body) / 1e6:.2f} MB...", file=out)
        result = client.import_bundle(body)
    except CloudImportRejectedError as exc:
        print(f"The cloud refused the bundle: {exc.detail}", file=out)
        return EXIT_REFUSED
    except IntegrationError as exc:
        print(f"Could not reach the cloud: {exc}", file=out)
        return EXIT_NETWORK
    finally:
        client.close()

    if result.duplicate:
        print(f"Already imported as cloud job {result.job_id}; nothing changed.", file=out)
    else:
        print(
            f"Imported as cloud job {result.job_id}  ({result.status}, {result.pages:,} pages)",
            file=out,
        )
    root = base_url.rstrip("/")
    print(f'Open {root}/ and pick "{result.label}" (Imported from local)', file=out)
    print(f"API  {root}/api/v1/jobs/{result.job_id}", file=out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(run())
