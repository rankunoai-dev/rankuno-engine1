"""Pick a finished local crawl and package it as a job bundle (ADR 0034).

The CLI half of the import contract. `scripts/push_job_to_cloud.py` is a thin
shell around this module: argument parsing and prompts there, decisions here,
so every decision is testable without a terminal.

Reads `.jobs/` through `DiskJobStore` only, never through the server's store
factory. The server's factory picks Postgres whenever a database URL is
configured, and a CLI on a workstation must never be one setting away from
reading, or worse writing, a shared database (ADR 0032).

The bundle bytes are deterministic: the same local job always encodes to the
same bytes (gzip `mtime=0`, a fixed serialisation). That is what lets the
server tell an honest retry, answered as a duplicate, from a changed job,
answered with 409.
"""

from __future__ import annotations

import gzip
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from src.core.errors import RankunoError
from src.core.job_provenance import INSTANCE_ID_PATTERN
from src.core.state_store import DiskJobStore, JobRecord, JobStatus
from src.modules.seo.page_classifier.job_bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    MAX_BUNDLE_HOMEPAGE_BYTES,
    BundleSource,
    JobImportBundle,
    audit_url_schemes,
)
from src.modules.seo.page_classifier.job_import import TOOL_NAME
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationOutput

__all__ = [
    "INSTANCE_ID_FILENAME",
    "BuiltBundle",
    "ExportRefusedError",
    "build_bundle",
    "encode_bundle",
    "exportable_jobs",
    "job_host",
    "load_or_create_instance_id",
    "normalise_host",
    "read_instance_id",
]

INSTANCE_ID_FILENAME = ".instance-id"
"""Inside `.jobs/`: already gitignored, and it travels with the jobs it names."""

_EXPORTABLE = frozenset({JobStatus.SUCCEEDED, JobStatus.PARTIAL})


class ExportRefusedError(RankunoError):
    """This local job cannot be exported, and the message says why."""


def normalise_host(text: str) -> str:
    """Host of a URL or bare domain, lowercased, without a leading `www.`."""
    candidate = text.strip()
    host = urlsplit(candidate if "//" in candidate else f"//{candidate}").hostname or ""
    return host.removeprefix("www.")


def job_host(record: JobRecord) -> str:
    """The normalised host a job crawled, from its stored request."""
    base = record.request.get("base_url")
    return normalise_host(base) if isinstance(base, str) else ""


def exportable_jobs(store: DiskJobStore, target: str | None = None) -> list[JobRecord]:
    """Finished page-classifier jobs with a result, newest first, optionally for one host.

    Args:
        store: The local job store.
        target: A domain or URL. Matches the crawled host, ignoring `www.`.
    """
    wanted = normalise_host(target) if target else None
    return [
        record
        for record in store.list_jobs()
        if record.tool_name == TOOL_NAME
        and record.status in _EXPORTABLE
        and record.has_result
        and record.provenance is None
        and (wanted is None or job_host(record) == wanted)
    ]


def read_instance_id(jobs_root: Path) -> str | None:
    """This `.jobs/` directory's instance id, or `None` if none was ever made.

    Raises:
        ExportRefusedError: The file exists but does not hold a valid id.
    """
    path = jobs_root / INSTANCE_ID_FILENAME
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(INSTANCE_ID_PATTERN, value):
        msg = f"{path.name} in the jobs directory is not a valid instance id; fix or delete it"
        raise ExportRefusedError(msg)
    return value


def load_or_create_instance_id(jobs_root: Path) -> str:
    """Read the instance id, creating it on first use.

    Random, never derived from the machine: the cloud only needs to tell one
    `.jobs/` directory from another, and a hostname or username would publish
    something about the workstation for no benefit. Created with `O_EXCL`, so
    two CLIs starting at once cannot each write a different id.
    """
    existing = read_instance_id(jobs_root)
    if existing is not None:
        return existing
    value = f"li-{secrets.token_hex(12)}"
    try:
        handle = os.open(jobs_root / INSTANCE_ID_FILENAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return read_instance_id(jobs_root) or value
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(value)
    return value


class BuiltBundle:
    """A bundle plus what the CLI tells the operator about it."""

    __slots__ = ("bundle", "homepage_dropped")

    def __init__(self, bundle: JobImportBundle, *, homepage_dropped: bool) -> None:
        """Hold the bundle.

        Args:
            bundle: The validated bundle.
            homepage_dropped: True when the homepage was over the size limit.
        """
        self.bundle = bundle
        self.homepage_dropped = homepage_dropped


def build_bundle(store: DiskJobStore, record: JobRecord, source: BundleSource) -> BuiltBundle:
    """Package one local job, applying every check the server will apply.

    Failing here, before anything is sent, is the point: an operator learns
    that a crawl cannot be imported, and which fields are why, without
    spending an upload and a rate-limit token to find out.

    Raises:
        ExportRefusedError: The job is not finished, has no result, does not
            match today's contract, or carries a URL the server would refuse.
    """
    if record.status not in _EXPORTABLE or not record.has_result:
        msg = (
            f"job {record.id} is {record.status.value} with no result; only finished crawls export"
        )
        raise ExportRefusedError(msg)
    if record.tool_name != TOOL_NAME:
        msg = f"job {record.id} ran {record.tool_name}, not {TOOL_NAME}"
        raise ExportRefusedError(msg)
    if record.provenance is not None:
        msg = f"job {record.id} was itself imported; export the original instead"
        raise ExportRefusedError(msg)

    homepage = store.read_homepage(record.id)
    dropped = homepage is not None and (
        len(homepage.encode("utf-8", "ignore")) > MAX_BUNDLE_HOMEPAGE_BYTES
    )
    try:
        bundle = JobImportBundle(
            format=BUNDLE_FORMAT,
            version=BUNDLE_VERSION,
            source=source,
            status="partial" if record.status is JobStatus.PARTIAL else "succeeded",
            label=record.label[:200],
            error=None if record.error is None else record.error[:2000],
            started_at=_aware(record.started_at or record.created_at),
            finished_at=_aware(record.finished_at or record.updated_at),
            request=PageClassificationInput.model_validate(record.request),
            result=PageClassificationOutput.model_validate(store.read_result(record.id)),
            homepage_html=None if dropped else homepage,
        )
    except ValueError as exc:
        msg = f"job {record.id} does not match the current contract ({type(exc).__name__})"
        raise ExportRefusedError(msg) from None

    failures = audit_url_schemes(bundle)
    if failures:
        shown = ", ".join(failures[:5])
        msg = f"job {record.id} has {len(failures)} URL(s) the cloud will refuse: {shown}"
        raise ExportRefusedError(msg)
    return BuiltBundle(bundle, homepage_dropped=dropped)


def encode_bundle(bundle: JobImportBundle) -> bytes:
    """Deterministic gzip of the bundle's JSON: same job, same bytes."""
    return gzip.compress(bundle.model_dump_json().encode("utf-8"), compresslevel=6, mtime=0)


def _aware(moment: datetime) -> datetime:
    """Records are written timezone-aware; refuse rather than guess if one is not."""
    if moment.tzinfo is None:
        msg = "a local job timestamp has no timezone"
        raise ExportRefusedError(msg)
    return moment
