"""Org GA4 access moves to Postgres: one encrypted credential and one property per org.

Revision ID: 012
Revises: 011
Create Date: 2026-10-19

GA4 is a separate Google API from Search Console and its credential is a
separate credential (ADR 0038). This table holds, per organisation, the GA4
refresh token encrypted under its own AAD label (`rankuno-ga4-cred-v1`, so a
GSC ciphertext copied here fails authentication) and the one GA4 property the
organisation has mapped for crawls. Keyed by `org_id` alone: a GA4 property is
an organisation's, not a Search Console account's.

* `org_id` references `org_configs` with `ON DELETE CASCADE`.
* `property_id` is NULL until an operator maps one, and the CHECK mirrors the
  API's full-match rule `^[1-9][0-9]{0,19}$`, so no other path can store a
  property id the API would refuse.
* No index on the ciphertext. Nothing looks a row up by its token.

Downgrade drops the table and DESTROYS every stored GA4 credential. There is
no way back except re-authorising each organisation.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "org_ga4_access"


def upgrade() -> None:
    """Create `org_ga4_access`."""
    op.create_table(
        TABLE,
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("refresh_token_ct", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("org_id", name="pk_org_ga4_access"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org_configs.org_id"],
            name="fk_org_ga4_access_org",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "property_id IS NULL OR property_id ~ '^[1-9][0-9]{0,19}$'",
            name="ck_org_ga4_access_property_id",
        ),
    )


def downgrade() -> None:
    """Drop `org_ga4_access`. Destroys every stored GA4 credential."""
    op.drop_table(TABLE)
