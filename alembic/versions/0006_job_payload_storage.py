"""Job result/checkpoint/homepage payloads move into Postgres.

Revision ID: 006
Revises: 005
Create Date: 2026-09-29

Railway wipes the container's own disk on every redeploy, and the live job
store (`DiskJobStore`) writes to that disk — every crawl job vanishes on
redeploy, not merely its result (`docs/adr/0022-postgres-backed-job-store.md`).
`jobs` (migration 0001) already holds job metadata; this migration adds the
one column metadata was missing (`has_checkpoint`, mirroring `has_result`)
and a companion table for the three payloads a job can carry:

- `result`: the tool's output blob (`DiskJobStore.finish`/`read_result`).
- `checkpoint`: partial work saved before an interruption
  (`write_checkpoint`/`read_checkpoint`).
- `homepage_html`: one page's body, kept so the header-menu parser can be
  re-run against a finished crawl without the network
  (`write_homepage`/`read_homepage`).

A companion table, not three new columns on `jobs` directly, for the same
reason `DiskJobStore` used sidecar files rather than one fat record:
`list_jobs()`/`get()` must stay cheap, and a query that never selects
`job_payloads` never has to skip past a 16 MB result the way a `SELECT *`
would. `job_payloads` is 1:1 with `jobs` (`job_id` is both primary key and
foreign key) and nullable in all three payload columns, because most jobs
carry only a subset — a `FAILED` job before its first checkpoint has none of
them.

`ON DELETE CASCADE` matches the existing `jobs` foreign keys (`cost_ledger`,
`idempotency_keys`): deleting a job takes its payloads with it, there being
nothing to reconcile independently of the job it describes.

Deliberately not covered here (see the ADR): `reconciliation` and
`performance` sidecars stay disk-only, and so do the unrelated `.orgs`/
`.operators` stores. Both are documented follow-ups, not oversights.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `jobs.has_checkpoint` and create `job_payloads`."""
    op.add_column(
        "jobs",
        sa.Column("has_checkpoint", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "job_payloads",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("homepage_html", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    """Drop `job_payloads` and `jobs.has_checkpoint`."""
    op.drop_table("job_payloads")
    op.drop_column("jobs", "has_checkpoint")
