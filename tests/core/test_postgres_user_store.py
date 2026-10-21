"""`PostgresUserStore` and the admin bootstrap (ADR 0040). No live database.

`_FakeDB` models the partial unique index `ux_users_single_admin` and the email
UNIQUE constraint, so a clash inserts nothing. It does not prove Postgres
itself: the migration SQL is checked offline in `test_postgres_schema.py`.
`race_past_exists_check` ignores the `NOT EXISTS` fast path, so the race tests
prove the index alone stops a second admin.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from src.core.auth import verify_password
from src.core.circuit_breaker import CircuitBreaker
from src.core.config import Settings
from src.core.errors import ConfigurationError, UserStoreUnavailableError
from src.core.postgres_user_store import (
    _INSERT_ADMIN_SQL,
    _SELECT_BY_EMAIL_SQL,
    PostgresUserStore,
)
from src.core.user_store import (
    MIN_ADMIN_PASSWORD_LENGTH,
    AdminBootstrapOutcome,
    UserRecord,
    bootstrap_admin_from_settings,
)

ADMIN_EMAIL = "Owner.Admin@Example.COM"
ADMIN_PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test fixture, not a secret
CANARY_DETAIL = "DETAIL: Key (email)=(canary-owner@example.com) CANARY-row-detail"
_COLUMNS = (
    "id",
    "role",
    "is_active",
    "session_version",
    "email",
    "google_sub",
    "password_hash",
    "must_change_password",
    "created_at",
)


class _FakeDB:
    """In-memory `users` table with the constraints the store relies on."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rows: list[dict[str, Any]] = []
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.race_past_exists_check = False
        self.barrier: threading.Barrier | None = None
        self.fail_with: BaseException | None = None

    def add_row(self, **overrides: Any) -> dict[str, Any]:
        """Seed a row directly, as an earlier process would have left it."""
        row: dict[str, Any] = {
            "id": "seeded-1",
            "role": "user",
            "is_active": True,
            "session_version": 0,
            "email": "seeded@example.com",
            "google_sub": None,
            "password_hash": None,
            "must_change_password": False,
            "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        }
        row.update(overrides)
        self.rows.append(row)
        return row

    def admins(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["role"] == "admin"]


class _FakeCursor:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db
        self._result: list[tuple[Any, ...]] = []

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
        if sql == _INSERT_ADMIN_SQL:
            self._insert_admin(params)
        elif sql == _SELECT_BY_EMAIL_SQL:
            row = next((r for r in db.rows if r["email"] == params[0]), None)
            if row is not None:
                self._result = [tuple(row[column] for column in _COLUMNS)]
        else:
            msg = f"fake DB does not understand: {sql!r}"
            raise AssertionError(msg)

    def _insert_admin(self, params: tuple[Any, ...]) -> None:
        """Mirror `INSERT ... WHERE NOT EXISTS ... ON CONFLICT DO NOTHING RETURNING id`."""
        db = self._db
        new_id, email, password_hash = params
        if db.barrier is not None:
            # Both racers have read the table before either one writes.
            db.barrier.wait(timeout=5)
        with db.lock:
            admin_exists = bool(db.admins())
            if admin_exists and not db.race_past_exists_check:
                return  # WHERE NOT EXISTS is false: no row is produced at all.
            # ON CONFLICT DO NOTHING (no target) absorbs a clash on the partial
            # unique index for role='admin' and on the UNIQUE email, inserting nothing.
            if admin_exists or any(r["email"] == email for r in db.rows):
                return
            db.rows.append(
                {
                    "id": new_id,
                    "role": "admin",
                    "is_active": True,
                    "session_version": 0,
                    "email": email,
                    "google_sub": None,
                    "password_hash": password_hash,
                    "must_change_password": True,
                    "created_at": datetime.now(UTC),
                }
            )
            self._result = [(new_id,)]

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


def _store(db: _FakeDB, *, breaker: CircuitBreaker | None = None) -> PostgresUserStore:
    return PostgresUserStore(
        circuit_breaker=breaker,
        connection_factory=lambda: _FakeConnection(db),  # type: ignore[arg-type,return-value]
    )


def _settings(
    *, email: str | None = ADMIN_EMAIL, password: str | None = ADMIN_PASSWORD
) -> Settings:
    """Hermetic settings: no `.env` file, so the developer's machine cannot leak in."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        admin_email=email,
        admin_initial_password=None if password is None else SecretStr(password),
    )


def test_bootstrap_creates_exactly_one_admin_on_an_empty_table() -> None:
    db = _FakeDB()
    outcome = _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    assert outcome is AdminBootstrapOutcome.CREATED
    assert len(db.rows) == 1
    assert len(db.admins()) == 1


def test_a_second_bootstrap_is_a_no_op() -> None:
    db = _FakeDB()
    store = _store(db)
    store.bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    before = dict(db.admins()[0])
    outcome = store.bootstrap_admin("second@example.com", SecretStr(ADMIN_PASSWORD))
    assert outcome is AdminBootstrapOutcome.NOT_CREATED
    assert len(db.admins()) == 1
    assert db.admins()[0] == before


def test_an_existing_admin_row_is_never_overwritten() -> None:
    db = _FakeDB()
    existing = db.add_row(
        id="owner-1",
        role="admin",
        email="owner@example.com",
        password_hash="pbkdf2_sha256$1$aa$bb",
        must_change_password=False,
    )
    before = dict(existing)
    outcome = _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    assert outcome is AdminBootstrapOutcome.NOT_CREATED
    assert existing == before
    # No statement issued by the bootstrap is an UPDATE or a DELETE.
    assert all(sql.lstrip().startswith("INSERT") for sql, _ in db.statements)


def test_a_non_admin_row_with_the_same_email_blocks_the_bootstrap_without_error() -> None:
    db = _FakeDB()
    db.add_row(id="u-1", role="user", email=ADMIN_EMAIL.lower())
    outcome = _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    assert outcome is AdminBootstrapOutcome.NOT_CREATED
    assert db.rows[0]["role"] == "user"
    assert db.admins() == []


def test_racing_bootstraps_yield_exactly_one_admin_row() -> None:
    """Two processes both pass the `NOT EXISTS` check, then both insert."""
    db = _FakeDB()
    db.race_past_exists_check = True
    db.barrier = threading.Barrier(2)
    outcomes: list[AdminBootstrapOutcome] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def racer(email: str) -> None:
        try:
            outcome = _store(db).bootstrap_admin(email, SecretStr(ADMIN_PASSWORD))
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            with results_lock:
                errors.append(exc)
            return
        with results_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=racer, args=("racer-a@example.com",)),
        threading.Thread(target=racer, args=("racer-b@example.com",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert sorted(o.value for o in outcomes) == ["created", "not_created"]
    assert len(db.admins()) == 1


def test_the_partial_unique_index_alone_stops_a_second_admin() -> None:
    """With the fast path bypassed, only the index can refuse the second admin."""
    db = _FakeDB()
    db.race_past_exists_check = True
    store = _store(db)
    assert store.bootstrap_admin("first@example.com", SecretStr(ADMIN_PASSWORD)) is (
        AdminBootstrapOutcome.CREATED
    )
    assert store.bootstrap_admin("second@example.com", SecretStr(ADMIN_PASSWORD)) is (
        AdminBootstrapOutcome.NOT_CREATED
    )
    assert [r["email"] for r in db.admins()] == ["first@example.com"]


@pytest.mark.parametrize(
    "weak",
    [
        "",
        "short",
        "x" * (MIN_ADMIN_PASSWORD_LENGTH - 1),
        "password",
        "Changeme",
        "Administrator",  # long enough to pass the length floor: the weak list must catch it
        "ADMINISTRATOR",
    ],
)
def test_a_short_or_known_weak_password_is_refused_before_any_statement(weak: str) -> None:
    db = _FakeDB()
    with pytest.raises(ConfigurationError) as info:
        _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(weak))
    assert db.statements == []
    assert db.rows == []
    if weak:
        assert weak not in str(info.value)


def test_the_minimum_length_is_accepted() -> None:
    db = _FakeDB()
    password = "a" * MIN_ADMIN_PASSWORD_LENGTH
    outcome = _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(password))
    assert outcome is AdminBootstrapOutcome.CREATED


@pytest.mark.parametrize("bad", ["", "not-an-email", "a@b", " @example.com", "x" * 250 + "@a.co"])
def test_a_malformed_email_is_refused_without_echoing_it(bad: str) -> None:
    db = _FakeDB()
    with pytest.raises(ConfigurationError) as info:
        _store(db).bootstrap_admin(bad, SecretStr(ADMIN_PASSWORD))
    assert db.statements == []
    if bad.strip():
        assert bad.strip() not in str(info.value)


def test_bootstrapped_admin_must_change_password_and_stores_only_a_hash() -> None:
    db = _FakeDB()
    _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    row = db.admins()[0]
    assert row["must_change_password"] is True
    assert row["email"] == ADMIN_EMAIL.lower()
    assert ADMIN_PASSWORD not in row["password_hash"]
    assert verify_password(ADMIN_PASSWORD, row["password_hash"]) is True


def test_get_by_email_is_case_insensitive_and_misses_return_none() -> None:
    db = _FakeDB()
    store = _store(db)
    store.bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    record = store.get_by_email("  OWNER.ADMIN@example.com ")
    assert isinstance(record, UserRecord)
    assert record.role == "admin"
    assert record.must_change_password is True
    assert record.password_hash is not None
    assert store.get_by_email("nobody@example.com") is None


def test_the_warning_is_logged_and_neither_address_nor_password_appears(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _FakeDB()
    caplog.set_level(logging.DEBUG)
    outcome = bootstrap_admin_from_settings(_store(db), _settings())
    assert outcome is AdminBootstrapOutcome.CREATED
    warnings = [r for r in caplog.records if r.getMessage() == "admin_initial_password_still_set"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        assert ADMIN_PASSWORD not in rendered
        assert "owner.admin@example.com" not in rendered.lower()
    assert ADMIN_PASSWORD not in caplog.text
    assert "owner.admin@example.com" not in caplog.text.lower()


@pytest.mark.parametrize(
    ("email", "password", "warns"),
    [(None, None, False), (None, ADMIN_PASSWORD, True)],
)
def test_missing_email_or_password_is_not_configured(
    caplog: pytest.LogCaptureFixture, email: str | None, password: str | None, warns: bool
) -> None:
    db = _FakeDB()
    caplog.set_level(logging.DEBUG)
    outcome = bootstrap_admin_from_settings(_store(db), _settings(email=email, password=password))
    assert outcome is AdminBootstrapOutcome.NOT_CONFIGURED
    assert db.statements == []
    assert ("admin_initial_password_still_set" in caplog.text) is warns
    assert ADMIN_PASSWORD not in caplog.text


def test_db_error_fails_closed_and_logs_sqlstate_only(caplog: pytest.LogCaptureFixture) -> None:
    db = _FakeDB()
    db.fail_with = psycopg.OperationalError(f"connection refused {CANARY_DETAIL}")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(UserStoreUnavailableError) as info:
        _store(db).bootstrap_admin(ADMIN_EMAIL, SecretStr(ADMIN_PASSWORD))
    assert "canary" not in str(info.value)
    assert info.value.__cause__ is None  # raised `from None`
    assert "canary" not in caplog.text.lower()
    assert "user_store_db_error" in caplog.text


def test_open_breaker_fails_fast_without_connecting() -> None:
    db = _FakeDB()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=3600.0)
    breaker.record_failure(RuntimeError("boom"))
    with pytest.raises(UserStoreUnavailableError):
        _store(db, breaker=breaker).get_by_email(ADMIN_EMAIL)
    assert db.statements == []


def test_migration_head_is_014_and_follows_013() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["014"]
    assert script.get_revision("014").down_revision == "013"
