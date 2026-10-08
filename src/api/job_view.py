"""The client-facing shape of a job.

`JobRecord` is the persistence model: `DiskJobStore` and the Postgres store
serialise it whole, so it must keep `password_hash`. Returning it from a route
would hand every authenticated caller in the org the PBKDF2 hash of the delete
password, enough to mount an offline guess. Routes therefore return `JobView`,
which carries every public field and replaces the hash with a boolean the UI
can act on ("this job needs a password to delete").

A separate model rather than `Field(exclude=True)` on `JobRecord`: exclusion
would also drop the hash from `model_dump`, silently un-persisting it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from pydantic import Field

from src.core.job_provenance import JobProvenance
from src.core.schemas import StrictModel
from src.core.state_store import JobRecord, JobStatus, JobTelemetry

__all__ = ["JobView", "job_views"]


class JobView(StrictModel):
    """A `JobRecord` without its secrets.

    Attributes mirror `JobRecord` (see its docstring) except `password_hash`,
    which is replaced by `has_delete_password`.
    """

    id: str
    tool_name: str
    label: str = ""
    org_id: str
    facet_id: str
    request: Mapping[str, object] = Field(default_factory=dict)
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    has_result: bool = False
    has_checkpoint: bool = False
    telemetry: JobTelemetry = JobTelemetry()
    provenance: JobProvenance | None = None
    has_delete_password: bool = Field(
        default=False,
        description="Whether deleting this job requires the password set at creation.",
    )

    @classmethod
    def from_record(cls, record: JobRecord) -> JobView:
        """Project a stored record, dropping the hash."""
        # Field-by-field from the live objects, not model_dump: nested models
        # and enums stay typed, and a field added to JobView but missing on
        # JobRecord fails loudly here rather than defaulting silently.
        data = {
            name: getattr(record, name)
            for name in cls.model_fields
            if name != "has_delete_password"
        }
        return cls(**data, has_delete_password=record.password_hash is not None)


def job_views(records: Iterable[JobRecord]) -> list[JobView]:
    """Project many records, preserving order."""
    return [JobView.from_record(record) for record in records]
