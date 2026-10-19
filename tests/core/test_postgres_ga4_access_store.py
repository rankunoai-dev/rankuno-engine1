"""`PostgresGa4AccessStore`: org-scoped, encrypted, fail-closed (ADR 0038).

No live database. `_FakeDB` interprets exactly the statements the store issues
and records every `(sql, params)` pair, so the org-scoping test inspects all of
them rather than trusting the ones it happens to look at.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr
from src.core.circuit_breaker import CircuitBreaker
from src.core.errors import Ga4AccessStoreUnavailableError, Ga4CredentialDecryptionError
from src.core.gsc_credential_crypto import GscCredentialCipher
from src.core.postgres_ga4_access_store import PostgresGa4AccessStore

KEY = bytes(range(32))
CANARY_TOKEN = "1//0gCANARY-ga4-token-in-postgres"  # noqa: S105 - fake canary
CANARY_DETAIL = "DETAIL: Key (org_id)=(acme) CANARY-row-detail"


class _FakeDB:
    """In-memory `org_configs` + `org_ga4_access`, keyed like the real tables."""

    def __init__(self) -> None:
        self.orgs: dict[str, float] = {}
        self.rows: dict[str, dict[str, Any]] = {}
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_with: BaseException | None = None


class _FakeCursor:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db
        self._result: list[tuple[Any, ...]] = []
        self.rowcount = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        db = self._db
        db.statements.append((sql, params))
        if db.fail_with is not None:
            raise db.fail_with
        self._result = []
        self.rowcount = 0
        if sql.startswith("INSERT INTO org_configs"):
            db.orgs.setdefault(params[0], 0.0)
        elif sql.startswith("INSERT INTO org_ga4_access"):
            org_id, token_ct, key_id, created_by, updated_by, _org = params
            db.rows[org_id] = {
                "refresh_token_ct": token_ct,
                "key_id": key_id,
                "property_id": None,
                "updated_by": updated_by,
            }
            _ = created_by
        elif sql.startswith("SELECT property_id FROM org_ga4_access"):
            row = db.rows.get(params[0])
            self._result = [] if row is None else [(row["property_id"],)]
        elif sql.startswith("SELECT refresh_token_ct, key_id FROM org_ga4_access"):
            row = db.rows.get(params[0])
            self._result = [] if row is None else [(row["refresh_token_ct"], row["key_id"])]
        elif sql.startswith("UPDATE org_ga4_access SET property_id"):
            prop, _by, org_id = params
            if org_id in db.rows:
                db.rows[org_id]["property_id"] = prop
                self.rowcount = 1
        elif sql.startswith("DELETE FROM org_ga4_access") and params[0] in db.rows:
            del db.rows[params[0]]
            self.rowcount = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)


class _FakeConnection:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def close(self) -> None:
        return None


def _store(db: _FakeDB, *, breaker: CircuitBreaker | None = None) -> PostgresGa4AccessStore:
    return PostgresGa4AccessStore(
        GscCredentialCipher(KEY),
        circuit_breaker=breaker,
        connection_factory=lambda: _FakeConnection(db),  # type: ignore[arg-type,return-value]
    )


def test_set_then_read_round_trips_the_token_and_stores_only_ciphertext() -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    assert store.refresh_token("acme") == SecretStr(CANARY_TOKEN)
    stored = db.rows["acme"]["refresh_token_ct"]
    assert isinstance(stored, bytes)
    assert CANARY_TOKEN.encode() not in stored


def test_status_reports_credential_and_mapping_without_decrypting() -> None:
    db = _FakeDB()
    store = _store(db)
    assert store.status("acme").has_credential is False
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    assert store.status("acme").has_credential is True
    assert store.status("acme").property_id is None
    assert store.set_property("acme", "123456", operator_id="op-1") is True
    assert store.status("acme").property_id == "123456"
    # `status` must not touch the ciphertext column at all.
    status_sql = [sql for sql, _ in db.statements if sql.startswith("SELECT property_id")]
    assert status_sql
    assert all("refresh_token_ct" not in sql for sql in status_sql)


def test_replacing_the_credential_clears_the_mapped_property() -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    store.set_property("acme", "123456", operator_id="op-1")
    store.set_credential("acme", SecretStr("1//0gSECOND"), operator_id="op-2")
    assert store.status("acme").property_id is None


def test_every_statement_binds_the_callers_org() -> None:
    """Inspect every statement issued, not only the ones the test happens to read."""
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    store.status("acme")
    store.refresh_token("acme")
    store.set_property("acme", "123456", operator_id="op-1")
    store.delete("acme", operator_id="op-1")
    scoped = [(sql, params) for sql, params in db.statements if "org_ga4_access" in sql]
    assert scoped
    for sql, params in scoped:
        assert "org_id" in sql, sql
        assert "acme" in params, (sql, params)


def test_another_org_sees_nothing_and_can_change_nothing() -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    store.set_property("acme", "123456", operator_id="op-1")
    assert store.status("globex").has_credential is False
    assert store.status("globex").property_id is None
    assert store.refresh_token("globex") is None
    assert store.set_property("globex", "999", operator_id="op-2") is False
    assert store.delete("globex", operator_id="op-2") is False
    # Acme is untouched by every attempt above.
    assert store.status("acme").property_id == "123456"
    assert store.refresh_token("acme") == SecretStr(CANARY_TOKEN)


def test_set_property_without_a_credential_is_refused() -> None:
    store = _store(_FakeDB())
    assert store.set_property("acme", "123456", operator_id="op-1") is False


@pytest.mark.parametrize("bad", ["", "0", "12 3", "123\n", "properties/1"])
def test_malformed_property_id_never_reaches_a_statement(bad: str) -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    statements_before = len(db.statements)
    with pytest.raises(ValueError, match="numeric form"):
        store.set_property("acme", bad, operator_id="op-1")
    assert len(db.statements) == statements_before


def test_delete_reports_whether_anything_was_removed() -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    assert store.delete("acme", operator_id="op-1") is True
    assert store.delete("acme", operator_id="op-1") is False
    assert store.status("acme").has_credential is False


def test_database_error_fails_closed_and_leaks_neither_message_nor_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _FakeDB()
    store = _store(db)
    db.fail_with = psycopg.OperationalError(f"connection refused {CANARY_DETAIL} {CANARY_TOKEN}")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Ga4AccessStoreUnavailableError) as info:
        store.status("acme")
    assert CANARY_DETAIL not in str(info.value)
    assert CANARY_TOKEN not in str(info.value)
    assert info.value.__cause__ is None  # raised `from None`
    assert CANARY_DETAIL not in caplog.text
    assert CANARY_TOKEN not in caplog.text
    assert "ga4_access_store_db_error" in caplog.text


def test_open_breaker_fails_fast_without_connecting() -> None:
    db = _FakeDB()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=3600.0)
    breaker.record_failure(RuntimeError("boom"))
    store = _store(db, breaker=breaker)
    with pytest.raises(Ga4AccessStoreUnavailableError):
        store.status("acme")
    assert db.statements == []


def test_tampered_row_raises_decryption_error_with_no_token() -> None:
    db = _FakeDB()
    store = _store(db)
    store.set_credential("acme", SecretStr(CANARY_TOKEN), operator_id="op-1")
    blob = bytearray(db.rows["acme"]["refresh_token_ct"])
    blob[-1] ^= 0x01
    db.rows["acme"]["refresh_token_ct"] = bytes(blob)
    with pytest.raises(Ga4CredentialDecryptionError) as info:
        store.refresh_token("acme")
    assert CANARY_TOKEN not in str(info.value)
