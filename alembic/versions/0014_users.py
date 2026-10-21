"""Users table: persisted identities, with at most one admin row.

Revision ID: 014
Revises: 013
Create Date: 2026-10-20

Phase 1 of the multi-user auth plan (ADR 0040, ADR 0041). This migration adds
the table only. Nothing reads it from a request path yet, so no existing
operator login changes.

* `session_version` is the revocation counter. A user session carries the
  version it was issued under and is refused once the row's counter moves on
  (ADR 0040). Starts at 0.
* `email` is stored lower-cased, and the CHECK enforces it, so the UNIQUE
  constraint is case-insensitive without a functional index.
* `google_sub` and `password_hash` are NULLABLE. A user signs in by one or the
  other, so neither is required.
* `ux_users_single_admin` is a partial unique index: at most one row may have
  `role = 'admin'`. This is the database-level guarantee behind the atomic
  bootstrap. The application's "no admin yet" check is only a fast path.

Downgrade drops the table and DESTROYS every user account. Re-running the
bootstrap recreates the first admin only if `ADMIN_EMAIL` and
`ADMIN_INITIAL_PASSWORD` are still set.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "users"
ADMIN_INDEX = "ux_users_single_admin"


def upgrade() -> None:
    """Create `users` and its single-admin partial unique index."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("google_sub", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
        sa.CheckConstraint(
            "length(email) BETWEEN 3 AND 254",
            name="ck_users_email_length",
        ),
        sa.CheckConstraint("session_version >= 0", name="ck_users_session_version"),
    )
    op.create_index(
        ADMIN_INDEX,
        TABLE,
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'admin'"),
    )


def downgrade() -> None:
    """Drop `users`. Destroys every user account."""
    op.drop_index(ADMIN_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
