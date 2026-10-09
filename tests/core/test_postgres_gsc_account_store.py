"""`PostgresGscAccountStore`: org-scoped, encrypted, and fail-closed (ADR 0036).

No live database. `_FakeDB` interprets exactly the statements the store issues
and records every `(sql, params)` pair, so the org-scoping test can inspect all
of them rather than trusting the ones it happens to look at.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr
from src.core.circuit_breaker import CircuitBreaker
from src.core.errors import GscAccountStoreUnavailableError, GscCredentialDecryptionError
from src.core.gsc_credential_crypto import GscCredentialCipher
from src.core.postgres_gsc_account_store import PostgresGscAccountStore
from src.core.schemas import GscAccountCredential

KEY = bytes(range(32))
CANARY_TOKEN = "1//0gCANARY-token-in-postgres"  # noqa: S105 - fake canary
CANARY_SECRET = "GOCSPX-CANARY-secret"  # noqa: S105 - fake canary


class _FakeDB:
    """In-memory `org_configs` + `org_gsc_accounts`, keyed like the real table."""

    def __init__(self) -> None:
        self.orgs: dict[str, float] = {}
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
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

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        db = self._db
        db.statements.append((sql, params))
        if db.fail_with is not None:
            raise db.fail_with
        if sql.startswith("INSERT INTO org_configs"):
            org_id, _display = params
            db.orgs.setdefault(org_id, 0.0)
        elif sql.startswith("INSERT INTO org_gsc_accounts"):
            (org_id, name, client_id, secret_ct, token_ct, key_id, created_by, updated_by, _o) = (
                params
            )
            key = (org_id, name)
            existed = key in db.rows
            row = db.rows.get(key, {"created_by": created_by})
            row.update(
                client_id=client_id,
                client_secret_ct=secret_ct,
                refresh_token_ct=token_ct,
                key_id=key_id,
                updated_by=updated_by,
            )
            db.rows[key] = row
            self._result = [(not existed,)]
        elif sql.startswith("SELECT account_name, client_id"):
            (org_id,) = params
            self._result = [
                (name, row["client_id"], row["client_secret_ct"] is not None)
                for (org, name), row in sorted(db.rows.items())
                if org == org_id
            ]
        elif sql.startswith("SELECT account_name FROM"):
            (org_id,) = params
            self._result = [(name,) for (org, name) in db.rows if org == org_id]
        elif sql.startswith("SELECT client_id, client_secret_ct"):
            row = db.rows.get(params)
            self._result = (
                []
                if row is None
                else [
                    (
                        row["client_id"],
                        row["client_secret_ct"],
                        row["refresh_token_ct"],
                        row["key_id"],
                    )
                ]
            )
        elif sql.startswith("DELETE FROM org_gsc_accounts"):
            self.rowcount = 1 if db.rows.pop(params, None) is not None else 0
        else:  # pragma: no cover - a new statement must be taught to the fake
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result[0] if self._result else None


class _FakeConnection:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db
        self.closed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def db() -> _FakeDB:
    return _FakeDB()


@pytest.fixture
def store(db: _FakeDB) -> PostgresGscAccountStore:
    return PostgresGscAccountStore(
        GscCredentialCipher(KEY),
        connection_factory=lambda: _FakeConnection(db),  # type: ignore[arg-type, return-value]
    )


def _cred(**overrides: Any) -> GscAccountCredential:
    values: dict[str, Any] = {"refresh_token": SecretStr(CANARY_TOKEN)}
    values.update(overrides)
    return GscAccountCredential(**values)


class TestRoundTrip:
    def test_upsert_then_get(self, store: PostgresGscAccountStore) -> None:
        outcome = store.upsert(
            "org-a",
            "acme",
            _cred(client_id="cid", client_secret=SecretStr(CANARY_SECRET)),
            operator_id="op-1",
        )
        assert outcome == "created"
        cred = store.get_credential("org-a", "acme")
        assert cred is not None
        assert cred.refresh_token.get_secret_value() == CANARY_TOKEN
        assert cred.client_secret is not None
        assert cred.client_secret.get_secret_value() == CANARY_SECRET
        assert cred.client_id == "cid"

    def test_stored_bytes_are_ciphertext(self, store: PostgresGscAccountStore, db: _FakeDB) -> None:
        store.upsert(
            "org-a", "acme", _cred(client_secret=SecretStr(CANARY_SECRET)), operator_id="op"
        )
        row = db.rows[("org-a", "acme")]
        assert CANARY_TOKEN.encode() not in row["refresh_token_ct"]
        assert CANARY_SECRET.encode() not in row["client_secret_ct"]
        assert row["key_id"] == GscCredentialCipher(KEY).key_id

    def test_second_upsert_is_replaced_and_records_who(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op-1")
        assert store.upsert("org-a", "acme", _cred(), operator_id="op-2") == "replaced"
        row = db.rows[("org-a", "acme")]
        assert (row["created_by"], row["updated_by"]) == ("op-1", "op-2")

    def test_parent_org_row_is_created_with_zero_budget(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        store.upsert("org-new", "acme", _cred(), operator_id="op")
        parent_sql = db.statements[0][0]
        assert "ON CONFLICT (org_id) DO NOTHING" in parent_sql
        assert "VALUES (%s, %s, 0)" in parent_sql
        assert db.orgs == {"org-new": 0.0}

    def test_unknown_account_is_none(self, store: PostgresGscAccountStore) -> None:
        assert store.get_credential("org-a", "nobody") is None

    def test_delete(self, store: PostgresGscAccountStore) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op")
        assert store.delete("org-a", "acme") is True
        assert store.delete("org-a", "acme") is False
        assert store.get_credential("org-a", "acme") is None


class TestListingNeverDecrypts:
    def test_list_and_names_work_with_no_usable_key(self, db: _FakeDB) -> None:
        writer = PostgresGscAccountStore(
            GscCredentialCipher(KEY),
            connection_factory=lambda: _FakeConnection(db),  # type: ignore[arg-type, return-value]
        )
        writer.upsert(
            "org-a", "acme", _cred(client_secret=SecretStr(CANARY_SECRET)), operator_id="op"
        )
        writer.upsert("org-a", "beta", _cred(client_id="cid"), operator_id="op")
        # A server holding a different key: listing still works.
        reader = PostgresGscAccountStore(
            GscCredentialCipher(bytes(range(32, 64))),
            connection_factory=lambda: _FakeConnection(db),  # type: ignore[arg-type, return-value]
        )
        summaries = reader.list_accounts("org-a")
        assert [(s.account_name, s.client_id, s.has_secret_override) for s in summaries] == [
            ("acme", None, True),
            ("beta", "cid", False),
        ]
        assert reader.account_names("org-a") == frozenset({"acme", "beta"})
        with pytest.raises(GscCredentialDecryptionError, match="re-add"):
            reader.get_credential("org-a", "acme")

    def test_list_sql_selects_no_ciphertext(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        store.list_accounts("org-a")
        store.account_names("org-a")
        for sql, _params in db.statements:
            select_list = sql.split("FROM")[0]
            assert "refresh_token_ct" not in select_list
            assert "client_secret_ct," not in select_list


class TestCorruptedRow:
    def test_one_bad_row_fails_alone(self, store: PostgresGscAccountStore, db: _FakeDB) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op")
        store.upsert("org-a", "good", _cred(), operator_id="op")
        corrupted = bytearray(db.rows[("org-a", "acme")]["refresh_token_ct"])
        corrupted[-1] ^= 0x01
        db.rows[("org-a", "acme")]["refresh_token_ct"] = bytes(corrupted)

        with pytest.raises(GscCredentialDecryptionError) as info:
            store.get_credential("org-a", "acme")
        assert CANARY_TOKEN not in str(info.value)
        assert store.get_credential("org-a", "good") is not None
        assert {s.account_name for s in store.list_accounts("org-a")} == {"acme", "good"}

    def test_a_row_copied_to_another_org_does_not_decrypt(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op")
        db.rows[("org-b", "acme")] = dict(db.rows[("org-a", "acme")])
        with pytest.raises(GscCredentialDecryptionError):
            store.get_credential("org-b", "acme")


class TestOrgScoping:
    """C3: every statement binds the caller's org; single-row ones add the name."""

    def test_every_statement_is_parameterised_and_org_scoped(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op")
        store.list_accounts("org-a")
        store.account_names("org-a")
        store.get_credential("org-a", "acme")
        store.delete("org-a", "acme")

        assert len(db.statements) == 6
        for sql, params in db.statements:
            assert "org-a" not in sql and "acme" not in sql, sql
            assert params[0] == "org-a"
            if sql.startswith(("SELECT", "DELETE")):
                assert "WHERE org_id = %s" in sql
            if sql.startswith(("SELECT client_id", "DELETE")):
                assert "AND account_name = %s" in sql
                assert params == ("org-a", "acme")
            if sql.startswith("INSERT INTO org_gsc_accounts"):
                assert "WHERE org_gsc_accounts.org_id = %s" in sql
                assert params[-1] == "org-a"

    def test_another_org_sees_nothing(self, store: PostgresGscAccountStore) -> None:
        store.upsert("org-a", "acme", _cred(), operator_id="op")
        assert store.list_accounts("org-b") == []
        assert store.account_names("org-b") == frozenset()
        assert store.get_credential("org-b", "acme") is None
        assert store.delete("org-b", "acme") is False


class TestFailClosed:
    def test_database_error_is_unavailable_and_never_logs_detail(
        self, store: PostgresGscAccountStore, db: _FakeDB, caplog: pytest.LogCaptureFixture
    ) -> None:
        db.fail_with = psycopg.OperationalError(f"DETAIL: row contains {CANARY_TOKEN}")
        with caplog.at_level(logging.DEBUG), pytest.raises(GscAccountStoreUnavailableError) as info:
            store.get_credential("org-a", "acme")
        assert info.value.__cause__ is None
        assert info.value.__suppress_context__ is True
        assert CANARY_TOKEN not in str(info.value)
        records = [r for r in caplog.records if r.getMessage() == "gsc_account_store_db_error"]
        assert [getattr(r, "error_class", None) for r in records] == ["OperationalError"]
        for record in caplog.records:
            assert CANARY_TOKEN not in str(record.__dict__)

    @pytest.mark.parametrize("method", ["list_accounts", "account_names", "upsert", "delete"])
    def test_every_operation_fails_closed(
        self, store: PostgresGscAccountStore, db: _FakeDB, method: str
    ) -> None:
        db.fail_with = psycopg.DatabaseError("boom")
        calls = {
            "list_accounts": lambda: store.list_accounts("org-a"),
            "account_names": lambda: store.account_names("org-a"),
            "upsert": lambda: store.upsert("org-a", "acme", _cred(), operator_id="op"),
            "delete": lambda: store.delete("org-a", "acme"),
        }
        with pytest.raises(GscAccountStoreUnavailableError):
            calls[method]()

    def test_connect_failure_is_unavailable(self) -> None:
        def refuse() -> Any:
            raise psycopg.OperationalError("connection refused")

        store = PostgresGscAccountStore(GscCredentialCipher(KEY), connection_factory=refuse)
        with pytest.raises(GscAccountStoreUnavailableError):
            store.account_names("org-a")

    def test_open_breaker_fails_fast_without_connecting(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("down"))
        connected: list[bool] = []

        def factory() -> Any:
            connected.append(True)
            raise AssertionError("must not connect while the breaker is open")

        store = PostgresGscAccountStore(
            GscCredentialCipher(KEY), circuit_breaker=breaker, connection_factory=factory
        )
        with pytest.raises(GscAccountStoreUnavailableError):
            store.get_credential("org-a", "acme")
        assert connected == []

    def test_repeated_failures_open_the_breaker(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        db.fail_with = psycopg.OperationalError("down")
        for _ in range(store.circuit_breaker.failure_threshold):
            with pytest.raises(GscAccountStoreUnavailableError):
                store.account_names("org-a")
        assert store.circuit_breaker.is_open()

    def test_integrity_error_does_not_open_the_breaker(
        self, store: PostgresGscAccountStore, db: _FakeDB
    ) -> None:
        db.fail_with = psycopg.IntegrityError("check violation")
        for _ in range(10):
            with pytest.raises(GscAccountStoreUnavailableError):
                store.upsert("org-a", "acme", _cred(), operator_id="op")
        assert not store.circuit_breaker.is_open()

    def test_success_closes_a_half_open_breaker(self, store: PostgresGscAccountStore) -> None:
        store.circuit_breaker.record_failure(RuntimeError("x"))
        assert store.account_names("org-a") == frozenset()
