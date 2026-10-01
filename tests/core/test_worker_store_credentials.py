"""Revoke and rotate, as a contract both `WorkerStore` implementations must meet.

Parametrised over `DiskWorkerStore` and `PostgresWorkerStore` (the latter
on the in-memory fake connection from `test_postgres_worker_store.py`, with
that file's stated limit: the fake proves which parameters are bound and
what the store does with the row, not that the SQL is valid PostgreSQL).

"Rejected" is always asserted through `verify_worker_credential`, the one
function every worker request is authenticated by, rather than by reading
`is_active` back: a flag nothing acts on is the defect being closed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from src.core.auth import hash_password
from src.core.postgres_worker_store import PostgresWorkerStore
from src.core.worker_auth import (
    DiskWorkerStore,
    Worker,
    WorkerAuthenticationError,
    WorkerNotFoundError,
    WorkerStore,
    WorkerStoreUnavailableError,
    verify_worker_credential,
)

from tests.core.test_postgres_worker_store import _FakeConnection

OLD = "old-secret-value"
NEW = "new-secret-value"


@pytest.fixture(params=["disk", "postgres"])
def store(request, tmp_path) -> WorkerStore:
    if request.param == "disk":
        return DiskWorkerStore(tmp_path / "workers")
    db: dict[str, dict[str, object]] = {}
    return PostgresWorkerStore(connection_factory=lambda: _FakeConnection(db))


def _seed(store: WorkerStore, *, org_id: str = "acme") -> Worker:
    worker = Worker(
        worker_id="wkr-alice",
        org_id=org_id,
        secret_hash=hash_password(OLD),
        display_name="Alice",
    )
    store.create(worker)
    store.touch("wkr-alice", seen_at=datetime.now(UTC))
    return worker


def test_set_active_false_makes_the_credential_fail_verification(store):
    _seed(store)
    assert verify_worker_credential("wkr-alice", OLD, store=store).org_id == "acme"

    revoked = store.set_active("wkr-alice", "acme", active=False)

    assert revoked.is_active is False
    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-alice", OLD, store=store)


def test_set_active_is_idempotent_and_reversible(store):
    _seed(store)
    store.set_active("wkr-alice", "acme", active=False)
    assert store.set_active("wkr-alice", "acme", active=False).is_active is False
    assert store.set_active("wkr-alice", "acme", active=True).is_active is True
    assert verify_worker_credential("wkr-alice", OLD, store=store).worker_id == "wkr-alice"


def test_replace_credential_swaps_the_secret_and_keeps_the_id(store):
    _seed(store)

    rotated = store.replace_credential("wkr-alice", "acme", new_credential_hash=hash_password(NEW))

    assert rotated.worker_id == "wkr-alice"
    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-alice", OLD, store=store)
    assert verify_worker_credential("wkr-alice", NEW, store=store).worker_id == "wkr-alice"


def test_replace_credential_reactivates_and_clears_liveness(store):
    _seed(store)
    store.set_active("wkr-alice", "acme", active=False)

    rotated = store.replace_credential("wkr-alice", "acme", new_credential_hash=hash_password(NEW))

    assert rotated.is_active is True
    assert rotated.last_seen_at is None
    assert store.get("wkr-alice").last_seen_at is None


@pytest.mark.parametrize("org_id", ["globex", "acme-not"])
def test_another_orgs_worker_is_indistinguishable_from_unknown(store, org_id):
    _seed(store)

    with pytest.raises(WorkerNotFoundError) as cross_set:
        store.set_active("wkr-alice", org_id, active=False)
    with pytest.raises(WorkerNotFoundError) as cross_rotate:
        store.replace_credential("wkr-alice", org_id, new_credential_hash=hash_password(NEW))
    with pytest.raises(WorkerNotFoundError) as unknown:
        store.set_active("wkr-ghost", org_id, active=False)

    assert str(cross_set.value) == str(unknown.value).replace("wkr-ghost", "wkr-alice")
    assert str(cross_rotate.value) == str(cross_set.value)
    # Nothing changed for the real owner.
    assert verify_worker_credential("wkr-alice", OLD, store=store).org_id == "acme"


def test_unknown_worker_raises_not_found_on_rotate(store):
    with pytest.raises(WorkerNotFoundError):
        store.replace_credential("wkr-ghost", "acme", new_credential_hash="pbkdf2_x")


# --- backend-specific -----------------------------------------------------------


def test_disk_rotation_persists_across_instances_and_holds_no_plaintext(tmp_path):
    first = DiskWorkerStore(tmp_path)
    _seed(first)
    first.replace_credential("wkr-alice", "acme", new_credential_hash=hash_password(NEW))

    reopened = DiskWorkerStore(tmp_path)

    assert verify_worker_credential("wkr-alice", NEW, store=reopened).worker_id == "wkr-alice"
    assert NEW not in (tmp_path / "workers.json").read_text(encoding="utf-8")


def test_disk_revoke_persists_across_instances(tmp_path):
    first = DiskWorkerStore(tmp_path)
    _seed(first)
    first.set_active("wkr-alice", "acme", active=False)

    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-alice", OLD, store=DiskWorkerStore(tmp_path))


def test_disk_failed_save_leaves_memory_matching_disk(tmp_path, monkeypatch):
    """A revoke that did not reach disk must not look applied in memory either."""
    store = DiskWorkerStore(tmp_path)
    _seed(store)

    def _disk_full() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", _disk_full)
    with pytest.raises(OSError, match="disk full"):
        store.set_active("wkr-alice", "acme", active=False)

    assert store.get("wkr-alice").is_active is True
    on_disk = json.loads((tmp_path / "workers.json").read_text(encoding="utf-8"))
    assert on_disk["wkr-alice"]["is_active"] is True


class _ExplodingCursor:
    def __enter__(self) -> _ExplodingCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        # Mimics a driver error whose text echoes bound parameters.
        raise RuntimeError(f"statement failed with params {params!r}")


class _ExplodingConnection(_FakeConnection):
    def cursor(self) -> _ExplodingCursor:  # type: ignore[override]
        return _ExplodingCursor()


def test_postgres_failure_message_never_echoes_the_credential_hash():
    store = PostgresWorkerStore(connection_factory=lambda: _ExplodingConnection({}))
    new_hash = hash_password(NEW)

    with pytest.raises(WorkerStoreUnavailableError) as excinfo:
        store.replace_credential("wkr-alice", "acme", new_credential_hash=new_hash)

    assert new_hash not in str(excinfo.value)
    assert "RuntimeError" in str(excinfo.value)
