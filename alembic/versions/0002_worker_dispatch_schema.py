"""Worker dispatch schema for ADR 0015 (Cloud + Local Desktop Worker Architecture).

Revision ID: 002
Revises: 001
Create Date: 2026-09-16

Tables (ADR 0015 condition 5 — the persistent, multi-replica-safe half of
the dual approval gate; worker *identity* remains disk-backed per
`src.core.worker_auth`'s own module docstring, matching `DiskOperatorStore`'s
already-accepted posture):

- worker_dispatch_previews: gate (a)'s preview/confirm tokens, bound to a
  target worker_id.
- worker_jobs: the job queue itself, pinned one worker per job (condition
  6) — never round-robined.
- worker_job_uploads: encrypted-at-rest bundle blobs (condition 11), with a
  retention `expires_at` for automatic-expiry cleanup.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the three ADR 0015 dispatch tables."""
    # --- worker_dispatch_previews -------------------------------------------
    op.create_table(
        "worker_dispatch_previews",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("token"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_worker_dispatch_previews_org_worker",
        "worker_dispatch_previews",
        ["org_id", "worker_id"],
    )

    # --- worker_jobs ---------------------------------------------------------
    op.create_table(
        "worker_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("bundle_size_bytes", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatched', 'succeeded', 'partial', 'failed')",
            name="ck_worker_jobs_status",
        ),
        sa.CheckConstraint("kind IN ('screaming_frog_crawl')", name="ck_worker_jobs_kind"),
    )
    op.create_index("idx_worker_jobs_org_id", "worker_jobs", ["org_id"])
    # The `claim_next_job` dequeue (`WHERE worker_id = ? AND org_id = ? AND
    # status = 'queued' ORDER BY created_at ASC ... FOR UPDATE SKIP LOCKED`)
    # is this route's exact access pattern.
    op.create_index(
        "idx_worker_jobs_worker_org_status", "worker_jobs", ["worker_id", "org_id", "status"]
    )

    # --- worker_job_uploads ---------------------------------------------------
    op.create_table(
        "worker_job_uploads",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("encrypted_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
        sa.ForeignKeyConstraint(["job_id"], ["worker_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="CASCADE"),
    )
    op.create_index("idx_worker_job_uploads_expires_at", "worker_job_uploads", ["expires_at"])


def downgrade() -> None:
    """Drop the three ADR 0015 dispatch tables."""
    op.drop_index("idx_worker_job_uploads_expires_at", table_name="worker_job_uploads")
    op.drop_table("worker_job_uploads")
    op.drop_index("idx_worker_jobs_worker_org_status", table_name="worker_jobs")
    op.drop_index("idx_worker_jobs_org_id", table_name="worker_jobs")
    op.drop_table("worker_jobs")
    op.drop_index("idx_worker_dispatch_previews_org_worker", table_name="worker_dispatch_previews")
    op.drop_table("worker_dispatch_previews")
