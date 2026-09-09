"""Initial database schema for Rankuno Phase 2a multi-tenant architecture.

Revision ID: 001
Revises:
Create Date: 2026-09-09

Tables:
- org_configs: Organization metadata and rate limits
- jobs: Crawl job records with status and telemetry
- cost_ledger: Financial tracking (one row per job)
- idempotency_keys: Request deduplication by org + key
- fallback_queue: Temporary queue when PostgreSQL is unavailable
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial schema with 5 core tables."""
    # --- org_configs -------------------------------------------------------
    # Organization metadata and settings
    op.create_table(
        "org_configs",
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("allowed_facets", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "max_concurrent_crawls",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "llm_credit_limit_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="100.00",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("org_id"),
    )

    # --- jobs --------------------------------------------------------------
    # Crawl job records with detailed tracking
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("facet_id", sa.Text(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("telemetry", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("has_result", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_jobs_status",
        ),
    )
    op.create_index("idx_jobs_org_id", "jobs", ["org_id"])
    op.create_index("idx_jobs_status", "jobs", ["status"])
    op.create_index("idx_jobs_created_at", "jobs", ["created_at"], postgresql_using="DESC")

    # --- cost_ledger -------------------------------------------------------
    # Financial tracking: one row per job
    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="charged"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_cost_ledger_job_id"),
        sa.CheckConstraint(
            "status IN ('charged', 'refunded', 'pending')",
            name="ck_cost_ledger_status",
        ),
    )
    op.create_index("idx_cost_ledger_org_id", "cost_ledger", ["org_id"])

    # --- idempotency_keys --------------------------------------------------
    # Request deduplication by org + idempotency key
    op.create_table(
        "idempotency_keys",
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id"], ["org_configs.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_idempotency_keys_job_id"),
    )

    # --- fallback_queue ----------------------------------------------------
    # Temporary queue for jobs created when PostgreSQL is unavailable
    op.create_table(
        "fallback_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_fallback_queue_job_id"),
    )
    op.create_index("idx_fallback_queue_org_id", "fallback_queue", ["org_id"])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index("idx_fallback_queue_org_id", table_name="fallback_queue")
    op.drop_table("fallback_queue")
    op.drop_table("idempotency_keys")
    op.drop_index("idx_cost_ledger_org_id", table_name="cost_ledger")
    op.drop_table("cost_ledger")
    op.drop_index("idx_jobs_created_at", table_name="jobs")
    op.drop_index("idx_jobs_status", table_name="jobs")
    op.drop_index("idx_jobs_org_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("org_configs")
