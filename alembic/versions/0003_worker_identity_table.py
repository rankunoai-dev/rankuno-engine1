"""Durable worker identity, plus liveness and worker-reported templates.

Revision ID: 003
Revises: 002
Create Date: 2026-09-21

Migration 0002 left worker *identity* on disk (`workers.json`), on the
reasoning that ADR 0015 condition 5's binding Postgres requirement named the
dispatch gate and the job queue, not identity. That reasoning was correct
about the ADR and wrong about the deployment: on a container host the
filesystem is rebuilt on every deploy, so every registered worker was being
destroyed on every redeploy and every desktop silently needed a new secret.
This revision adds the `workers` table `PostgresWorkerStore` reads and
writes.

**There is no data migration, and none is possible.** The rows this table
would have inherited lived in a container-local `workers.json` that no
longer exists by the time this migration runs — that is the whole defect.
Switching a deployment to `WORKER_STORE_BACKEND=postgres` therefore requires
**re-registering each desktop worker once** (`POST /api/v1/workers`) and
re-provisioning `WORKER_CREDENTIAL` on that machine. It is a one-time cost,
and it is the last time it will be paid.

`org_id` deliberately carries no foreign key to `org_configs`, unlike
`worker_jobs.org_id`: registering a desktop must not require an org row to
exist first, and the constraint that matters is already enforced one step
later, where `worker_jobs` refuses to queue work for an unknown org.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the `workers` table."""
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        # PBKDF2-HMAC-SHA256 output from `src.core.auth.hash_password`. Never
        # a recoverable secret, and never read by anything but
        # `verify_worker_credential`.
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # NULL means "registered but its daemon has never checked in once".
        # Distinct from "checked in long ago", which is what liveness reads.
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        # A JSON array of `.seospiderconfig` names the worker reported about
        # itself. Read and written whole, never queried element-wise, so a
        # JSON string in TEXT is simpler than TEXT[] and maps identically
        # through psycopg and through the test double.
        sa.Column("template_names", sa.Text(), nullable=False, server_default="[]"),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    # `list_workers(org_id)` — every dashboard read of this table.
    op.create_index("idx_workers_org_id", "workers", ["org_id"])


def downgrade() -> None:
    """Drop the `workers` table."""
    op.drop_index("idx_workers_org_id", table_name="workers")
    op.drop_table("workers")
