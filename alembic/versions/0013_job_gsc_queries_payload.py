"""Query-by-page Search Console fetches move into `job_payloads`.

Revision ID: 013
Revises: 012
Create Date: 2026-10-19

The top-queries-per-URL fetch is a sidecar on a finished job, like the
performance report before it. Migration 0008 is the precedent and the reason:
`PostgresJobStore` writes a Postgres-backed job's sidecar to Postgres only, and
the disk store refuses a sidecar for a job whose record it does not hold, so a
disk-only home would silently discard the fetch for every Postgres job.

One nullable JSON column on the existing 1:1 `job_payloads` companion, not a new
table, for the same reason 0006 and 0008 gave. No data migration: every existing
row gets `NULL`, which is the value a job with no saved query fetch already reads
as.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `job_payloads.gsc_queries`."""
    op.add_column("job_payloads", sa.Column("gsc_queries", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop `job_payloads.gsc_queries`."""
    op.drop_column("job_payloads", "gsc_queries")
