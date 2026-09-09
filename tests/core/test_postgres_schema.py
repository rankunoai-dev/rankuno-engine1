"""Tests for PostgreSQL schema migrations.

These tests verify that the Alembic migrations create the correct schema
with all required tables, columns, indexes, and constraints.
"""

from __future__ import annotations

import os


class TestInitialSchemaMigration:
    """Tests for the initial schema migration (0001_initial_schema.py)."""

    def test_migration_file_exists(self) -> None:
        """Migration file should exist."""
        assert os.path.exists("alembic/versions/0001_initial_schema.py")

    def test_migration_has_docstring(self) -> None:
        """Migration file should have a docstring."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert '"""' in content
        assert "Initial database schema" in content

    def test_migration_has_correct_revision_id(self) -> None:
        """Migration should declare revision ID."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'revision: str = "001"' in content

    def test_migration_has_down_revision_none(self) -> None:
        """Migration should have down_revision = None."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert "down_revision" in content

    def test_migration_creates_org_configs_table(self) -> None:
        """Migration should define org_configs table creation."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'op.create_table(\n        "org_configs"' in content
        assert "org_id" in content
        assert "display_name" in content
        assert "allowed_facets" in content
        assert "max_concurrent_crawls" in content
        assert "llm_credit_limit_usd" in content
        assert "is_active" in content

    def test_migration_creates_jobs_table(self) -> None:
        """Migration should define jobs table creation."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'op.create_table(\n        "jobs"' in content
        assert "tool_name" in content
        assert "facet_id" in content
        assert "request" in content
        assert "status" in content
        assert "idx_jobs_org_id" in content
        assert "idx_jobs_status" in content
        assert "idx_jobs_created_at" in content

    def test_migration_creates_cost_ledger_table(self) -> None:
        """Migration should define cost_ledger table creation."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'op.create_table(\n        "cost_ledger"' in content
        assert "amount_usd" in content
        assert "idx_cost_ledger_org_id" in content

    def test_migration_creates_idempotency_keys_table(self) -> None:
        """Migration should define idempotency_keys table creation."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'op.create_table(\n        "idempotency_keys"' in content
        assert "idempotency_key" in content

    def test_migration_creates_fallback_queue_table(self) -> None:
        """Migration should define fallback_queue table creation."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert 'op.create_table(\n        "fallback_queue"' in content
        assert "payload" in content

    def test_migration_has_foreign_keys(self) -> None:
        """Migration should define foreign key constraints."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert "ForeignKeyConstraint" in content
        assert 'org_configs.org_id' in content
        assert 'jobs.id' in content

    def test_migration_has_constraints(self) -> None:
        """Migration should define check constraints."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert "CheckConstraint" in content
        assert "queued" in content
        assert "running" in content
        assert "succeeded" in content

    def test_downgrade_drops_all_tables(self) -> None:
        """Downgrade should drop all created tables."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        # Check that downgrade function drops tables
        assert "def downgrade()" in content
        assert 'op.drop_table("fallback_queue")' in content
        assert 'op.drop_table("idempotency_keys")' in content
        assert 'op.drop_table("cost_ledger")' in content
        assert 'op.drop_table("jobs")' in content
        assert 'op.drop_table("org_configs")' in content


class TestAlembicEnvironment:
    """Tests for Alembic environment configuration."""

    def test_alembic_ini_exists(self) -> None:
        """alembic.ini should exist."""
        assert os.path.exists("alembic.ini")

    def test_alembic_ini_has_script_location(self) -> None:
        """alembic.ini should specify script_location."""
        with open("alembic.ini", encoding="utf-8") as f:
            content = f.read()

        assert "script_location = alembic" in content

    def test_alembic_env_py_exists(self) -> None:
        """alembic/env.py should exist."""
        assert os.path.exists("alembic/env.py")

    def test_alembic_env_py_has_upgrade_and_downgrade(self) -> None:
        """alembic/env.py should handle both modes."""
        with open("alembic/env.py", encoding="utf-8") as f:
            content = f.read()

        assert "run_migrations_online" in content
        assert "run_migrations_offline" in content

    def test_alembic_script_template_exists(self) -> None:
        """alembic/script.py.mako should exist."""
        assert os.path.exists("alembic/script.py.mako")

    def test_migration_file_has_upgrade_function(self) -> None:
        """Migration file should have upgrade function."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert "def upgrade() -> None:" in content

    def test_migration_file_has_downgrade_function(self) -> None:
        """Migration file should have downgrade function."""
        with open("alembic/versions/0001_initial_schema.py", encoding="utf-8") as f:
            content = f.read()

        assert "def downgrade() -> None:" in content
