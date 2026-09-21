"""Tests for the durable worker identity store (`PostgresWorkerStore`).

**Read this before trusting these tests.** No PostgreSQL server is available
in this environment — `psycopg` is not even installed in the local venv —
so every assertion below runs against an in-memory fake connection/cursor,
exactly as `test_postgres_worker_dispatch_store.py` already does. That fake
proves the *business logic* around the SQL: which parameters are bound, that
a duplicate id raises `ValueError`, that a poll does not wipe the template
set, that every failure becomes `WorkerStoreUnavailableError` rather than
something a caller would read as "no such worker".

It cannot prove the SQL is valid PostgreSQL, that `COALESCE(%s,
template_names)` behaves as intended against a real planner, or that
`ON CONFLICT (worker_id) DO NOTHING` reports `rowcount == 0` on conflict the
way psycopg does. Those are asserted by construction and remain unverified
until this runs against a real database. Said plainly here rather than left
for a reader to discover.

The fake understands exactly the four queries this store issues; an
unrecognised query is a hard failure, so a change to the SQL that this suite
does not know about fails loudly rather than silently passing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from src.core.auth import hash_password, verify_password
from src.core.postgres_worker_store import PostgresWorkerStore
from src.core.worker_auth import (
    TEMPLATE_NAME_PATTERN,
    Worker,
    WorkerNotFoundError,
    WorkerStoreUnavailableError,
    verify_worker_credential,
)

_COLUMNS = (
    "worker_id",
    "org_id",
    "secret_hash",
    "display_name",
    "is_active",
    "created_at",
    "last_seen_at",
    "template_names",
)


class _FakeCursor:
    """Understands exactly the SQL `PostgresWorkerStore` issues."""

    def __init__(self, db: dict[str, dict[str, object]]) -> None:
        self._db = db
        self._result: object = None
        self.rowcount = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        q = " ".join(query.split())
        if q.startswith("INSERT INTO workers"):
            self._insert(params)
        elif q.startswith("UPDATE workers SET last_seen_at"):
            self._touch(params)
        elif "FROM workers WHERE worker_id = %s" in q:
            self._get(params)
        elif "FROM workers" in q and "ORDER BY worker_id" in q:
            self._list(params)
        else:  # pragma: no cover - defensive: an unmodelled query fails loudly
            raise AssertionError(f"fake cursor does not understand query: {q!r}")

    def _row(self, record: dict[str, object]) -> tuple[object, ...]:
        return tuple(record[name] for name in _COLUMNS)

    def _insert(self, params: tuple[object, ...]) -> None:
        record = dict(zip(_COLUMNS, params, strict=True))
        worker_id = str(record["worker_id"])
        if worker_id in self._db:
            self.rowcount = 0
            return
        self._db[worker_id] = record
        self.rowcount = 1

    def _get(self, params: tuple[object, ...]) -> None:
        record = self._db.get(str(params[0]))
        self._result = None if record is None else self._row(record)

    def _list(self, params: tuple[object, ...]) -> None:
        records = sorted(self._db.values(), key=lambda r: str(r["worker_id"]))
        if params:
            records = [r for r in records if r["org_id"] == params[0]]
        self._result = [self._row(r) for r in records]

    def _touch(self, params: tuple[object, ...]) -> None:
        seen_at, template_names, worker_id = params
        record = self._db.get(str(worker_id))
        if record is None:
            self._result = None
            return
        record["last_seen_at"] = seen_at
        if template_names is not None:  # the COALESCE
            record["template_names"] = template_names
        self._result = self._row(record)

    def fetchone(self) -> object:
        return self._result

    def fetchall(self) -> list[object]:
        return list(self._result) if isinstance(self._result, list) else []


class _FakeConnection:
    def __init__(self, db: dict[str, dict[str, object]]) -> None:
        self._db = db
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def db() -> dict[str, dict[str, object]]:
    return {}


@pytest.fixture
def store(db) -> PostgresWorkerStore:
    return PostgresWorkerStore(connection_factory=lambda: _FakeConnection(db))


def _worker(
    worker_id: str = "wkr-alice",
    org_id: str = "acme",
    secret: str = "s3cret",  # noqa: S107 - a test fixture value, never a real credential
) -> Worker:
    return Worker(
        worker_id=worker_id,
        org_id=org_id,
        secret_hash=hash_password(secret),
        display_name="Alice's desktop",
    )


# --- create / get ---------------------------------------------------------------


def test_create_then_get_round_trips_a_worker(store):
    created = store.create(_worker())
    read = store.get("wkr-alice")
    assert read.worker_id == created.worker_id
    assert read.org_id == "acme"
    assert read.last_seen_at is None
    assert read.template_names == ()


def test_create_preserves_the_pbkdf2_hash_untouched(store, db):
    """This module must never re-hash, downgrade, or invent a scheme."""
    worker = _worker(secret="the-real-secret")  # noqa: S106 - a test fixture value
    store.create(worker)
    assert db["wkr-alice"]["secret_hash"] == worker.secret_hash
    assert str(db["wkr-alice"]["secret_hash"]).startswith("pbkdf2_")
    assert verify_password("the-real-secret", store.get("wkr-alice").secret_hash)


def test_create_never_stores_the_plaintext_secret_anywhere(store, db):
    store.create(_worker(secret="the-real-secret"))  # noqa: S106 - a test fixture value
    assert "the-real-secret" not in json.dumps(db, default=str)


def test_create_rejects_a_duplicate_worker_id(store):
    store.create(_worker())
    with pytest.raises(ValueError, match="already exists"):
        store.create(_worker())


def test_get_of_an_unknown_worker_raises_not_found(store):
    with pytest.raises(WorkerNotFoundError):
        store.get("wkr-ghost")


# --- list -----------------------------------------------------------------------


def test_list_workers_filters_by_org(store):
    store.create(_worker("wkr-alice", org_id="acme"))
    store.create(_worker("wkr-bob", org_id="globex"))
    assert [w.worker_id for w in store.list_workers("acme")] == ["wkr-alice"]
    assert [w.worker_id for w in store.list_workers()] == ["wkr-alice", "wkr-bob"]


# --- touch ----------------------------------------------------------------------


def test_touch_records_last_seen(store):
    store.create(_worker())
    seen = datetime.now(UTC)
    updated = store.touch("wkr-alice", seen_at=seen)
    assert updated.last_seen_at == seen
    assert store.get("wkr-alice").last_seen_at == seen


def test_touch_with_templates_replaces_the_stored_set(store):
    store.create(_worker())
    store.touch("wkr-alice", seen_at=datetime.now(UTC), template_names=("a", "b"))
    store.touch("wkr-alice", seen_at=datetime.now(UTC), template_names=("c",))
    assert store.get("wkr-alice").template_names == ("c",)


def test_touch_without_templates_leaves_the_stored_set_alone(store):
    """A poll reports no templates and must not wipe what a heartbeat sent."""
    store.create(_worker())
    store.touch("wkr-alice", seen_at=datetime.now(UTC), template_names=("default-crawl",))
    store.touch("wkr-alice", seen_at=datetime.now(UTC) + timedelta(seconds=1))
    assert store.get("wkr-alice").template_names == ("default-crawl",)


def test_touch_of_an_unknown_worker_raises_not_found(store):
    with pytest.raises(WorkerNotFoundError):
        store.touch("wkr-ghost", seen_at=datetime.now(UTC))


def test_a_stored_template_name_that_could_become_a_path_is_refused_on_read(store, db):
    """Defense in depth: even a row written past the HTTP layer is re-checked."""
    store.create(_worker())
    db["wkr-alice"]["template_names"] = json.dumps(["../../etc/passwd"])
    with pytest.raises(ValueError, match="template_names"):
        store.get("wkr-alice")


# --- unavailability: never mistaken for "no such worker" ------------------------


def _explode() -> NoReturn:
    raise ConnectionError("postgres is down")


def test_every_method_fails_closed_when_postgres_is_unreachable():
    store = PostgresWorkerStore(connection_factory=_explode)
    with pytest.raises(WorkerStoreUnavailableError):
        store.create(_worker())
    with pytest.raises(WorkerStoreUnavailableError):
        store.get("wkr-alice")
    with pytest.raises(WorkerStoreUnavailableError):
        store.list_workers("acme")
    with pytest.raises(WorkerStoreUnavailableError):
        store.touch("wkr-alice", seen_at=datetime.now(UTC))


def test_an_outage_is_not_reported_as_an_authentication_failure():
    """The distinction a daemon acts on: stop forever, or back off and return."""
    from src.core.worker_auth import WorkerAuthenticationError

    store = PostgresWorkerStore(connection_factory=_explode)
    with pytest.raises(WorkerStoreUnavailableError):
        verify_worker_credential("wkr-alice", "s3cret", store=store)  # noqa: S106
    # And specifically not the error that tells a daemon to give up.
    try:
        verify_worker_credential("wkr-alice", "s3cret", store=store)  # noqa: S106
    except WorkerStoreUnavailableError as exc:
        assert not isinstance(exc, WorkerAuthenticationError)


# --- the pattern this store and the template registry must agree on -------------


def test_the_core_template_pattern_matches_the_registry_that_enforces_it():
    """`core` cannot import `modules`, so the literal is restated. Verify it."""
    from src.modules.seo.screaming_frog_control.template_registry import (
        TEMPLATE_NAME_PATTERN as REGISTRY_PATTERN,
    )

    assert REGISTRY_PATTERN.pattern == TEMPLATE_NAME_PATTERN
