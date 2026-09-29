"""Reconciliation and performance payloads move into `job_payloads`.

Revision ID: 008
Revises: 007
Create Date: 2026-09-29

Migration 0006 gave `result`/`checkpoint`/`homepage_html` a durable Postgres
home and, per its own docstring and `docs/adr/0022-postgres-backed-job-store.md`
decision 5, left `reconciliation` and `performance` disk-only "as a
documented follow-up, not an oversight." That follow-up turned out to be
load-bearing rather than optional: `PostgresJobStore.write_reconciliation`/
`read_reconciliation`/`write_performance`/`read_performance` delegated straight
to `fallback_store` (disk) *unconditionally* — not only once the circuit
breaker opened, the way every other method behaves — while `create()` writes
a Postgres-backed job's row to Postgres only. `DiskJobStore.write_reconciliation`
then requires the job to exist on disk before it will write the sidecar file,
which a Postgres-backed job never does, so the write silently no-oped and
every subsequent read 404'd. A user could never download a Screaming Frog
reconciliation report once Postgres became the default job store
(build-log 0118).

Two more JSON columns on the same table, not a new one, for the identical
reason 0006 gave for `result`/`checkpoint`/`homepage_html`: `job_payloads` is
already the 1:1, nullable-by-column companion table that keeps `jobs.get()`/
`list_jobs()` cheap, and a reconciliation or performance report is exactly
the same shape of thing — an occasional, potentially large blob most jobs
never carry.

No data migration. Every existing `job_payloads` row gets `NULL` in both new
columns, which is the correct answer for a job that has no saved
reconciliation or performance report today — the same value `DiskJobStore`
implicitly returns for such a job now (`read_reconciliation`/
`read_performance` return `None` when no sidecar file exists).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `job_payloads.reconciliation` and `job_payloads.performance`."""
    op.add_column("job_payloads", sa.Column("reconciliation", sa.JSON(), nullable=True))
    op.add_column("job_payloads", sa.Column("performance", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop `job_payloads.reconciliation` and `job_payloads.performance`."""
    op.drop_column("job_payloads", "performance")
    op.drop_column("job_payloads", "reconciliation")
