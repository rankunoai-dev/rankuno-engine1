"""Where a job came from, when it did not start on this server (ADR 0034).

A crawl run on a workstation can be copied to the cloud as a finished job. The
copy must say so: an analyst comparing two crawls needs to know that one of
them was run from a home broadband line on a different day, and the server
must be able to refuse things that only make sense for its own jobs (re-running
one, resuming one).

Domain-agnostic, like `state_store`: nothing here knows what a crawl is. The
fields name a *source instance* and a *source job* only.

No path, hostname or username appears anywhere. `source_instance_id` is a
random value generated once per local `.jobs/` directory, precisely so that
identifying the machine is never required to de-duplicate its uploads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from src.core.schemas import StrictModel

__all__ = [
    "INSTANCE_ID_PATTERN",
    "SOURCE_JOB_ID_PATTERN",
    "SOURCE_LABEL_PATTERN",
    "JobProvenance",
]

INSTANCE_ID_PATTERN = r"^[a-z0-9-]{8,64}$"
"""A random local-instance id. Lowercase, so it can never smuggle a path."""

SOURCE_LABEL_PATTERN = r"^[a-z0-9-]{1,64}$"
"""An operator-chosen name for the source machine. Same character class as the id."""

SOURCE_JOB_ID_PATTERN = r"^[0-9a-f]{32}$"
"""A `DiskJobStore` id: `uuid4().hex`. Never a cloud id, which carries hyphens."""


class JobProvenance(StrictModel):
    """How an imported job reached this server.

    `origin`, the source fields and the crawl times come from the bundle; the
    server sets `imported_by`, `imported_at` and `bundle_sha256` itself and
    accepts none of them from the client.
    """

    origin: Literal["local_import"] = Field(
        description="How the job arrived. Only local imports exist today."
    )
    source_instance_id: str = Field(
        pattern=INSTANCE_ID_PATTERN,
        description="Random id of the local job directory the crawl ran in.",
    )
    source_label: str | None = Field(
        default=None,
        pattern=SOURCE_LABEL_PATTERN,
        description="Optional operator-chosen name for the source machine.",
    )
    source_job_id: str = Field(
        pattern=SOURCE_JOB_ID_PATTERN,
        description="The job's id on the source instance. Never a cloud job id.",
    )
    crawl_started_at: datetime = Field(description="When the crawl started on the source.")
    crawl_finished_at: datetime = Field(description="When the crawl finished on the source.")
    imported_by: str = Field(
        min_length=1, description="Operator id that imported it, from the verified session."
    )
    imported_at: datetime = Field(description="When this server accepted the import.")
    bundle_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the decompressed bundle, used to tell a replay from a change.",
    )
