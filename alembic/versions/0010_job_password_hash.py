"""Persist the per-job deletion password hash on Postgres.

Revision ID: 010
Revises: 009
Create Date: 2026-10-08

`JobRecord.password_hash` (the Argon/PBKDF hash a crawl's creator sets so only
they can delete it) lived only on `DiskJobStore`. `PostgresJobStore` neither
wrote nor read it, so `create()` echoed the hash in its response and the next
`get()` returned `None`: every `DELETE /jobs/{id}` on Postgres answered 403
"deletion requires a password". One nullable `TEXT` column fixes it.

`ADD COLUMN IF NOT EXISTS` keeps a half-applied or hand-patched database from
failing the migration. No backfill: a plaintext password was never stored, so
the hash of an existing job cannot be reconstructed. Existing rows stay `NULL`,
which still means "not deletable through the API", the pre-fix behaviour.

Deploy order: run this BEFORE the code that reads or writes the column ships.
The new INSERT and SELECT name `password_hash` and fail on a database without it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable `password_hash` column to `jobs`."""
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS password_hash TEXT")


def downgrade() -> None:
    """Drop `password_hash`; hashes written since the upgrade are lost."""
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS password_hash")
