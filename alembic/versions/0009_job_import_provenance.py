"""Imported jobs carry their provenance, and one source imports once per org.

Revision ID: 009
Revises: 008
Create Date: 2026-10-07

ADR 0034 lets an operator copy a finished local crawl into the cloud through
`POST /api/v1/jobs/import`. The cloud row must say where it came from, and the
same local job pushed twice must land once. Nine nullable columns on `jobs`,
mirroring `src.core.job_provenance.JobProvenance` field for field, rather than
one JSON column: the de-duplication key has to be indexable, and a typed
column is what a later query by source will want anyway.

The unique index is partial (`WHERE source_job_id IS NOT NULL`) so every row
this server ran itself, all `NULL` here, stays out of it. `org_id`
leads the key: the same local job imported into two orgs is two jobs, and the
lookup can never answer one org with another org's row.

No data migration. Every existing row gets `NULL` in all nine, which reads back
as `provenance=None`, the correct answer for a job this server ran itself.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_jobs_import_source"


def upgrade() -> None:
    """Add the provenance columns to `jobs` and the per-org source unique index."""
    op.add_column("jobs", sa.Column("import_origin", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("source_instance_id", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("source_label", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("source_job_id", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("crawl_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("crawl_finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("imported_by", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("bundle_sha256", sa.Text(), nullable=True))
    op.create_index(
        _INDEX,
        "jobs",
        ["org_id", "source_instance_id", "source_job_id"],
        unique=True,
        postgresql_where=sa.text("source_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the index, then the nine provenance columns."""
    op.drop_index(_INDEX, table_name="jobs")
    for column in (
        "bundle_sha256",
        "imported_at",
        "imported_by",
        "crawl_finished_at",
        "crawl_started_at",
        "source_job_id",
        "source_label",
        "source_instance_id",
        "import_origin",
    ):
        op.drop_column("jobs", column)
