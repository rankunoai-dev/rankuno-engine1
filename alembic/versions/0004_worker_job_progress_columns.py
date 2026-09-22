"""Live progress columns on worker_jobs.

Revision ID: 004
Revises: 003
Create Date: 2026-09-22

Adds `pages_crawled`, `progress_pct`, `current_phase` to `worker_jobs`
(migration 0002) — additive to ADR 0015's dispatch schema, not a revision of
it. A worker daemon's background progress thread reports these periodically
while a job is still `DISPATCHED`; the job's own lifecycle `status` column
is untouched by any of the three (see `WorkerDispatchStore.
update_job_progress`'s docstring for why that separation matters).

All three columns are nullable with no `server_default`: `NULL` means "no
progress report has arrived yet", not zero — true for every job that
predates this migration, and true for a fresh job until its worker's first
report. Nothing reading `WorkerJob` may assume these are always present
(CLAUDE.md's optional-everywhere-read discipline, restated in this cycle's
build-log).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the three progress columns and a closed-enum check on the phase."""
    op.add_column("worker_jobs", sa.Column("pages_crawled", sa.Integer(), nullable=True))
    op.add_column("worker_jobs", sa.Column("progress_pct", sa.Float(), nullable=True))
    op.add_column("worker_jobs", sa.Column("current_phase", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_worker_jobs_current_phase",
        "worker_jobs",
        "current_phase IN ('crawling', 'exporting')",
    )


def downgrade() -> None:
    """Drop the check constraint and the three progress columns."""
    op.drop_constraint("ck_worker_jobs_current_phase", "worker_jobs", type_="check")
    op.drop_column("worker_jobs", "current_phase")
    op.drop_column("worker_jobs", "progress_pct")
    op.drop_column("worker_jobs", "pages_crawled")
