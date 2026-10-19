"""Migration 0012 (ADR 0038): the org GA4 access table, rendered offline.

No database is contacted. The offline SQL is the reviewable artefact, so these
tests pin the constraints a reviewer would check: the org FK cascades, the
property CHECK mirrors the API pattern, and no index exists on the ciphertext.
"""

from __future__ import annotations

import io

from alembic import command
from alembic.config import Config
from src.core.ga4_access_store import GA4_PROPERTY_ID_PATTERN

PATH = "alembic/versions/0012_org_ga4_access.py"


def _offline_sql(revisions: str, *, downgrade: bool = False) -> str:
    """Render a migration range as SQL, with no file logging and no connection."""
    buffer = io.StringIO()
    cfg = Config(output_buffer=buffer)
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", "postgresql://offline:offline@offline.invalid/x")
    if downgrade:
        command.downgrade(cfg, revisions, sql=True)
    else:
        command.upgrade(cfg, revisions, sql=True)
    return buffer.getvalue()


def test_file_follows_011_and_is_the_only_head() -> None:
    with open(PATH, encoding="utf-8") as handle:
        content = handle.read()
    assert 'revision: str = "012"' in content
    assert 'down_revision: str | None = "011"' in content


def test_upgrade_creates_the_table_with_its_constraints() -> None:
    sql = _offline_sql("011:012")
    assert "CREATE TABLE org_ga4_access" in sql
    assert "CONSTRAINT pk_org_ga4_access PRIMARY KEY (org_id)" in sql
    assert "FOREIGN KEY(org_id) REFERENCES org_configs (org_id) ON DELETE CASCADE" in sql
    assert "refresh_token_ct BYTEA NOT NULL" in sql
    assert "key_id TEXT NOT NULL" in sql
    assert "property_id TEXT," in sql


def test_property_check_mirrors_the_api_pattern() -> None:
    sql = _offline_sql("011:012")
    assert "CHECK (property_id IS NULL OR property_id ~ '^[1-9][0-9]{0,19}$')" in sql
    assert GA4_PROPERTY_ID_PATTERN in sql


def test_no_index_on_ciphertext_and_no_second_table() -> None:
    sql = _offline_sql("011:012")
    assert "CREATE INDEX" not in sql
    assert "CREATE UNIQUE INDEX" not in sql
    assert sql.count("CREATE TABLE") == 1
    assert "org_gsc_accounts" not in sql


def test_downgrade_drops_only_the_ga4_table() -> None:
    sql = _offline_sql("012:011", downgrade=True)
    assert "DROP TABLE org_ga4_access" in sql
    assert "org_gsc_accounts" not in sql
