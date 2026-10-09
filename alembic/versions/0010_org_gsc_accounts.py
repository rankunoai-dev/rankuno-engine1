"""Org GSC accounts move to Postgres, encrypted, so they survive a redeploy.

Revision ID: 010
Revises: 009
Create Date: 2026-10-09

ADR 0036. The cloud kept each org's GSC accounts in `.orgs/org_configs.json`
on the Railway container disk, which every redeploy wipes. This table is the
durable home. `refresh_token_ct` and `client_secret_ct` hold AES-256-GCM
`nonce || ciphertext+tag` (`src/core/gsc_credential_crypto.py`), and `key_id`
names the key that wrote them so a rotation can decrypt old rows.

* `org_id` references `org_configs` with `ON DELETE CASCADE`: deleting an
  org deletes its credentials, never leaves them orphaned.
* The `account_name` CHECK mirrors the API's full-match rule, so a name the
  API would refuse cannot be written by any other path either.
* No index on either ciphertext column. Nothing looks a row up by its secret.

No data migration: the disk copies were already lost to redeploys, and the
operator re-adds each account once the key is set.

Downgrade drops the table and DESTROYS every stored GSC credential. There is
no way back except re-adding each account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "org_gsc_accounts"


def upgrade() -> None:
    """Create `org_gsc_accounts`."""
    op.create_table(
        TABLE,
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("account_name", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret_ct", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_ct", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("org_id", "account_name", name="pk_org_gsc_accounts"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org_configs.org_id"],
            name="fk_org_gsc_accounts_org",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "account_name ~ '^[a-z0-9_-]{1,64}$'",
            name="ck_org_gsc_accounts_name",
        ),
        sa.CheckConstraint(
            "client_id IS NULL OR length(client_id) <= 256",
            name="ck_org_gsc_accounts_client_id_len",
        ),
    )


def downgrade() -> None:
    """Drop `org_gsc_accounts`. Destroys every stored GSC credential."""
    op.drop_table(TABLE)
