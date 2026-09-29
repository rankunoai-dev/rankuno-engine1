"""Bind an approved `--crawl-list` URL list into the cloud dispatch gate.

Revision ID: 007
Revises: 006
Create Date: 2026-09-29

ADR 0023. Screaming Frog's `--crawl` mode can only audit what the site links
to; `--crawl-list` audits a supplied set. The set this engine supplies is
generated from a finished Rankuno crawl, frozen at preview time, and
identified everywhere afterwards by its SHA-256.

Three changes, and the reason each one is here rather than somewhere cheaper:

* `worker_dispatch_previews.url_list_sha256` — the digest joins gate (a)'s
  `WHERE` clause. Without a column there is nothing for the confirm statement
  to compare against, and "preview a three-URL list, confirm a
  hundred-thousand-URL one" is accepted silently. Nullable, because an
  ordinary `--crawl` dispatch has no list and `IS NOT DISTINCT FROM` is what
  makes `NULL` match `NULL` on both sides.

* `worker_jobs.url_list_sha256` / `worker_jobs.url_list_url_count` — what the
  claimed job is actually for. The digest is what the signed assignment
  carries to the worker; the count is the denominator of the finished job's
  truncation check (list length versus pages actually crawled — the first
  time Screaming Frog's silent free-tier cap can be detected as something
  other than "exactly 500 URLs"). The count is stored beside the job rather
  than read back from the list, so it outlives the list's own retention.

* `worker_dispatch_url_lists` — the bytes. Content-addressed on
  `(sha256, org_id)`: the digest is already the identity every gate compares,
  so it is the natural key, and including `org_id` in it means one
  organization cannot fetch another's list even holding the right digest.
  `expires_at` mirrors `worker_job_uploads`' retention posture; the list is an
  input fetched once, minutes after approval, so its default window
  (`WORKER_URL_LIST_RETENTION_DAYS`, 7 days) is much shorter than a bundle's.

**No data migration, and none is needed.** Every existing `worker_jobs` and
`worker_dispatch_previews` row is a `--crawl` dispatch, and `NULL` is exactly
what those rows mean: no list. An old row read after this migration produces
`url_list_sha256=None`, which is the same envelope it produced before.

**Rollback is lossy, and deliberately so.** `downgrade()` drops the stored
lists outright. A list that cannot be fetched must not leave a job behind
claiming to have been approved against it, and the job rows lose their digest
in the same statement, so the two stay consistent: after a downgrade every
job is a `--crawl` job again, which is the only thing the older code can run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the digest columns and create the URL-list table."""
    op.add_column(
        "worker_dispatch_previews", sa.Column("url_list_sha256", sa.Text(), nullable=True)
    )
    op.add_column("worker_jobs", sa.Column("url_list_sha256", sa.Text(), nullable=True))
    op.add_column("worker_jobs", sa.Column("url_list_url_count", sa.Integer(), nullable=True))

    op.create_table(
        "worker_dispatch_url_lists",
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        # The rendered file exactly as Screaming Frog will read it: CRLF
        # separated UTF-8, no BOM. Stored as bytes rather than TEXT because
        # the digest is taken over bytes, and a TEXT column would invite a
        # round trip through a client encoding that changes them.
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("url_count", sa.Integer(), nullable=False),
        # Audit only. No foreign key to any job table: the source crawl lives
        # in the local `DiskJobStore`, not in Postgres at all, and deleting it
        # must not invalidate a list an operator has already approved.
        sa.Column("source_job_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sha256", "org_id"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="CASCADE"),
    )
    # The retention sweep's access pattern, matching `worker_job_uploads`'.
    op.create_index(
        "idx_worker_dispatch_url_lists_expires_at", "worker_dispatch_url_lists", ["expires_at"]
    )


def downgrade() -> None:
    """Drop the URL-list table and both digest columns. Lossy — see module docs."""
    op.drop_index(
        "idx_worker_dispatch_url_lists_expires_at", table_name="worker_dispatch_url_lists"
    )
    op.drop_table("worker_dispatch_url_lists")
    op.drop_column("worker_jobs", "url_list_url_count")
    op.drop_column("worker_jobs", "url_list_sha256")
    op.drop_column("worker_dispatch_previews", "url_list_sha256")
