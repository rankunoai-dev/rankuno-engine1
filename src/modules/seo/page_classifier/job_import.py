"""Turn an uploaded bundle into something the job store can write (ADR 0034).

The route reads a capped body and hands it here; everything between "these are
bytes" and "this is a terminal job record" is in this module, so the route
holds no business logic and this logic is testable without HTTP.

Order matters, and each step exists because the one before it cannot be
trusted:

1. Inflate under a hard cap (`gunzip_capped`). The compressed size says
   nothing about the inflated size.
2. Validate with `model_validate_json` on the bytes. No `json.loads` first: a
   dict of the whole document is a second full copy in memory, and the parser
   inside pydantic enforces a nesting limit that `json.loads` does not.
3. Walk every URL field (`audit_url_schemes`). The schema says "a string"; the
   UI needs "an http(s) URL".
4. Re-serialise from the validated model. What is stored is what this build
   produced from validated data, never the client's bytes.

Errors are reported by location only. A `ValidationError`'s message and its
`input` are attacker-controlled text, so neither leaves this module.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from src.core.bounded_gzip import gunzip_capped
from src.core.errors import RankunoError
from src.core.job_provenance import JobProvenance
from src.core.state_store import ImportedJob, JobStatus, JobTelemetry
from src.modules.seo.page_classifier.job_bundle import JobImportBundle, audit_url_schemes

__all__ = [
    "MAX_REPORTED_LOCATIONS",
    "TOOL_NAME",
    "BundleInvalidError",
    "PreparedImport",
    "prepare_import",
]

TOOL_NAME = "seo.page_classifier"
"""The only tool and facet an import may claim. Fixed here, never read from the bundle."""

MAX_REPORTED_LOCATIONS = 10
"""How many failing locations a 422 lists. Enough to fix the cause, bounded per response."""


class BundleInvalidError(RankunoError):
    """The bundle failed the contract or the URL audit.

    Attributes:
        error_count: How many problems there were in total.
        locations: The first `MAX_REPORTED_LOCATIONS` of them, as dotted paths.
    """

    def __init__(self, error_count: int, locations: list[str]) -> None:
        """Hold a sanitised summary.

        Args:
            error_count: Total problems found.
            locations: Paths of the first few, with no values.
        """
        super().__init__(f"bundle failed validation at {error_count} location(s)")
        self.error_count = error_count
        self.locations = locations[:MAX_REPORTED_LOCATIONS]


class PreparedImport:
    """A validated import, ready for `JobStore.import_terminal`."""

    __slots__ = ("decompressed_bytes", "job", "page_count", "result_json")

    def __init__(
        self, job: ImportedJob, result_json: str, page_count: int, decompressed_bytes: int
    ) -> None:
        """Hold the pieces the route needs.

        Args:
            job: Metadata for the store.
            result_json: The re-serialised, validated result.
            page_count: Pages in the result, for the response and the log.
            decompressed_bytes: Inflated bundle size, for the log.
        """
        self.job = job
        self.result_json = result_json
        self.page_count = page_count
        self.decompressed_bytes = decompressed_bytes


def prepare_import(
    body: bytes, *, max_decompressed: int, org_id: str, operator_id: str, now: datetime
) -> PreparedImport:
    """Inflate, validate and audit an uploaded bundle.

    Args:
        body: The gzip body, already capped by the route.
        max_decompressed: Most bytes the bundle may inflate to.
        org_id: The verified session's org. The only org the job can land in.
        operator_id: The verified session's operator, recorded as `imported_by`.
        now: The import time, recorded as `imported_at`.

    Returns:
        A `PreparedImport`.

    Raises:
        DecompressedTooLargeError: Inflates past `max_decompressed`.
        InvalidGzipError: Not one complete gzip member.
        BundleInvalidError: Fails the bundle contract or the URL audit.
    """
    inflated = gunzip_capped(body, max_output=max_decompressed)
    try:
        bundle = JobImportBundle.model_validate_json(inflated.data)
    except ValidationError as exc:
        details = exc.errors(include_url=False, include_context=False, include_input=False)
        raise BundleInvalidError(
            exc.error_count(),
            [_dotted(detail["loc"]) for detail in details[:MAX_REPORTED_LOCATIONS]],
        ) from None
    decompressed_bytes = len(inflated.data)
    bundle_sha256 = inflated.sha256
    del inflated  # The model now holds everything; drop the raw copy before re-serialising.

    failures = audit_url_schemes(bundle)
    if failures:
        raise BundleInvalidError(len(failures), failures)

    discovery = bundle.result.discovery
    job = ImportedJob(
        org_id=org_id,
        tool_name=TOOL_NAME,
        facet_id=TOOL_NAME,
        label=bundle.label or bundle.result.base_url[:200],
        request=bundle.request.model_dump(mode="json"),
        status=JobStatus(bundle.status),
        started_at=bundle.started_at,
        finished_at=bundle.finished_at,
        error=bundle.error,
        telemetry=JobTelemetry(
            completed=discovery.pages_fetched,
            discovered=discovery.total_urls,
            updated_at=bundle.finished_at,
        ),
        homepage_html=bundle.homepage_html,
        provenance=JobProvenance(
            origin="local_import",
            source_instance_id=bundle.source.source_instance_id,
            source_label=bundle.source.source_label,
            source_job_id=bundle.source.source_job_id,
            crawl_started_at=bundle.started_at,
            crawl_finished_at=bundle.finished_at,
            imported_by=operator_id,
            imported_at=now,
            bundle_sha256=bundle_sha256,
        ),
    )
    return PreparedImport(
        job, bundle.result.model_dump_json(), len(bundle.result.pages), decompressed_bytes
    )


def _dotted(loc: tuple[int | str, ...]) -> str:
    """`("result", "pages", 3, "url")` -> `result.pages[3].url`."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "(root)"
