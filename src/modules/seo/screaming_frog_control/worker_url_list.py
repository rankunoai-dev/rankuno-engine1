"""Fetch, verify and lay down the approved `--crawl-list` file (ADR 0023).

The one place bytes travel cloud -> worker in this whole architecture, and
therefore the one place a worker must not take delivery on trust. The check
here is not a checksum of a file against a checksum that arrived with it: the
digest compared against is the one inside this worker's own HMAC-verified
`DispatchAssignmentClaims`, so a list substituted anywhere between the cloud's
storage and this process fails it.

Split out of `worker_daemon` because it is a distinct concern with its own
failure type, and because that module was already past this codebase's
400-line target.
"""

from __future__ import annotations

from pathlib import Path

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.worker_dispatch_schemas import DispatchAssignmentClaims
from src.integrations.worker_cloud_client import WorkerCloudClient
from src.modules.seo.screaming_frog_control.schemas import UrlListInvocation
from src.modules.seo.screaming_frog_control.url_list import (
    LIST_ENCODING,
    SAMPLE_SIZE,
    fingerprint,
    read_url_list_file,
    render_url_list,
)

__all__ = [
    "URL_LIST_FILENAME",
    "EmptyApprovedListError",
    "UrlListIntegrityError",
    "prepare_url_list",
]

_logger = get_logger(__name__)

URL_LIST_FILENAME = "url-list.txt"
"""Written inside `output_root / job_id`, the one directory a job may
write to (`tool.execute` creates it). Beside the export CSVs rather than in
a temp directory on purpose: when a run goes wrong, the exact list it was
given is then sitting next to the exact output it produced, and the
bundle's own allow-list means this file is never uploaded with them."""


class UrlListIntegrityError(RankunoError):
    """The fetched URL list does not hash to the digest that was approved.

    A distinct type, not a generic failure, because it means exactly one
    thing and it is not a transient: the bytes this worker received are not
    the bytes a human approved. Retrying fetches the same mismatch. The job
    is failed with this message verbatim so the cloud record says *which*
    check refused it, rather than "the tool returned no data".
    """

    def __init__(self, *, expected: str, actual: str, byte_count: int) -> None:
        """Record both digests; the message shows enough of each to compare."""
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"the URL list this worker downloaded does not match the approved "
            f"fingerprint: expected sha256:{expected}, got sha256:{actual} over "
            f"{byte_count:,} bytes. Nothing was crawled. This is not a transient "
            f"failure — the list that was approved and the list that arrived are "
            f"different files."
        )


class EmptyApprovedListError(RankunoError):
    """The digest matched, but the file holds no URLs.

    Separate from `UrlListIntegrityError` because the honest message is a
    different one: nothing was tampered with, the approved bytes really are
    empty. The cloud refuses to store an empty list at generation time
    (`url_list.EmptyUrlListError`), so reaching this means the stored blob
    itself is wrong — an engineering fault, not an operator one, and saying
    "fingerprint mismatch" here would send someone looking for an attacker
    who is not there.
    """

    def __init__(self, *, sha256: str) -> None:
        """Record the digest of the empty list, so the row can be found."""
        self.sha256 = sha256
        super().__init__(
            f"the approved URL list (sha256:{sha256}) contains no URLs, so there is "
            f"nothing to crawl. Its fingerprint is correct, which means the stored "
            f"list itself is empty — report this rather than retrying."
        )


def prepare_url_list(
    client: WorkerCloudClient,
    claims: DispatchAssignmentClaims,
    *,
    output_root: Path,
    seed_url: str,
) -> UrlListInvocation:
    """Fetch the approved list, verify its digest, and write it for the CLI.

    The digest compared against is `claims.url_list_sha256` — the copy
    inside this worker's own HMAC-verified assignment, never anything the
    download itself supplied. That is what makes this a real check rather
    than a checksum of a file against its own checksum.

    The file is then **re-rendered from the parsed URLs**, not written from
    the downloaded bytes. Two reasons, and the second is the operational
    one: a BOM or a bare-LF file that an intermediary re-encoded is
    normalised back to the CRLF UTF-8 Screaming Frog reads cleanly on
    Windows, and the count handed to the truncation check is then counted
    from exactly what the CLI will read. The verification happens on the
    downloaded bytes first, so normalising afterwards cannot launder a
    tampered list.

    `UrlListInvocation.source` is left empty: which subset an operator
    picked ("orphans"/"all") is a cloud-side label and is deliberately not
    carried in the signed claims — it would be one more signed field that
    exists only to be displayed. The confirmation modal that a human
    actually approves names it; this worker's own summary names the crawl,
    the count, a sample and the fingerprint, which is what identifies the
    list.

    Raises:
        UrlListIntegrityError: The download does not match the approval.
        EmptyApprovedListError: It matched, but holds no URLs.
        IntegrationError: The fetch itself failed.
        OSError: The list could not be written to the job directory.
    """
    expected = claims.url_list_sha256
    body = client.fetch_url_list(claims.job_id)
    actual = fingerprint(body)
    if expected is None or actual != expected:
        raise UrlListIntegrityError(
            expected=expected or "(none)", actual=actual, byte_count=len(body)
        )

    urls = read_url_list_file(body)
    if not urls:
        raise EmptyApprovedListError(sha256=expected)

    job_dir = output_root / claims.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / URL_LIST_FILENAME
    path.write_bytes(render_url_list(urls))
    _logger.info(
        "worker_url_list_written",
        extra={
            "job_id": claims.job_id,
            "urls": len(urls),
            "path": str(path),
            "encoding": LIST_ENCODING,
        },
    )
    return UrlListInvocation(
        path=path,
        url_count=len(urls),
        sha256=expected,
        source_label=f"Crawl: {seed_url}",
        source="",
        sample=urls[:SAMPLE_SIZE],
    )
