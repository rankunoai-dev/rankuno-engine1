"""Tests for ADR 0015's worker identity and credential primitives.

Mirrors `tests/core/test_auth.py`'s structure closely — `Worker`/
`WorkerPrincipal`/`DiskWorkerStore` are the worker-daemon analogues of
`Operator`/`Principal`/`DiskOperatorStore`, and the same properties matter:
password/secret hashing round-trips, a corrupt store fails closed, an
unknown worker id and a wrong secret are indistinguishable to the caller.
"""

from __future__ import annotations

import pytest
from src.core.worker_auth import (
    DiskWorkerStore,
    Worker,
    WorkerAuthenticationError,
    WorkerNotFoundError,
    mint_worker_secret,
    verify_worker_credential,
)


def _worker(**overrides: object) -> Worker:
    from src.core.auth import hash_password

    base: dict[str, object] = {
        "worker_id": "wkr-alice-desktop",
        "org_id": "acme",
        "secret_hash": hash_password("a-real-worker-secret"),
        "display_name": "Alice's desktop",
    }
    base.update(overrides)
    return Worker(**base)


# --- mint_worker_secret -------------------------------------------------------


def test_mint_worker_secret_is_high_entropy_and_unique():
    a = mint_worker_secret()
    b = mint_worker_secret()
    assert a != b
    assert len(a) >= 32


# --- verify_worker_credential --------------------------------------------------


class _InMemoryWorkerStore:
    """A minimal `WorkerStore` for tests that do not need disk I/O."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def create(self, worker: Worker) -> Worker:
        if worker.worker_id in self._workers:
            raise ValueError(f"Worker '{worker.worker_id}' already exists")
        self._workers[worker.worker_id] = worker
        return worker

    def get(self, worker_id: str) -> Worker:
        try:
            return self._workers[worker_id]
        except KeyError:
            raise WorkerNotFoundError(worker_id) from None

    def list_workers(self, org_id: str | None = None) -> list[Worker]:
        values = sorted(self._workers.values(), key=lambda w: w.worker_id)
        if org_id is not None:
            values = [w for w in values if w.org_id == org_id]
        return values


def test_verify_worker_credential_round_trips():
    store = _InMemoryWorkerStore()
    store.create(_worker())
    principal = verify_worker_credential("wkr-alice-desktop", "a-real-worker-secret", store=store)
    assert principal.worker_id == "wkr-alice-desktop"
    assert principal.org_id == "acme"


def test_verify_worker_credential_rejects_wrong_secret():
    store = _InMemoryWorkerStore()
    store.create(_worker())
    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-alice-desktop", "wrong-secret", store=store)


def test_verify_worker_credential_rejects_unknown_worker():
    store = _InMemoryWorkerStore()
    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-nobody", "anything", store=store)


def test_verify_worker_credential_rejects_inactive_worker():
    store = _InMemoryWorkerStore()
    store.create(_worker(is_active=False))
    with pytest.raises(WorkerAuthenticationError):
        verify_worker_credential("wkr-alice-desktop", "a-real-worker-secret", store=store)


def test_verify_worker_credential_unknown_vs_wrong_secret_raise_the_same_error_type():
    """A distinct exception per cause would be a worker-id-enumeration oracle."""
    store = _InMemoryWorkerStore()
    store.create(_worker())

    with pytest.raises(WorkerAuthenticationError) as unknown_exc:
        verify_worker_credential("wkr-nobody", "anything", store=store)
    with pytest.raises(WorkerAuthenticationError) as wrong_exc:
        verify_worker_credential("wkr-alice-desktop", "wrong-secret", store=store)

    assert str(unknown_exc.value) == str(wrong_exc.value)


# --- DiskWorkerStore ------------------------------------------------------------


def test_disk_worker_store_round_trips(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    worker = _worker()
    store.create(worker)

    fetched = store.get("wkr-alice-desktop")
    assert fetched.org_id == "acme"
    assert fetched.secret_hash == worker.secret_hash


def test_disk_worker_store_get_unknown_raises(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    with pytest.raises(WorkerNotFoundError):
        store.get("wkr-nobody")


def test_disk_worker_store_create_duplicate_raises(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker())
    with pytest.raises(ValueError, match="already exists"):
        store.create(_worker())


def test_disk_worker_store_list_workers_is_sorted_and_org_filterable(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker(worker_id="wkr-zeta", org_id="acme"))
    store.create(_worker(worker_id="wkr-alpha", org_id="acme"))
    store.create(_worker(worker_id="wkr-other-org", org_id="globex"))

    ids = [w.worker_id for w in store.list_workers()]
    assert ids == ["wkr-alpha", "wkr-other-org", "wkr-zeta"]

    acme_only = [w.worker_id for w in store.list_workers("acme")]
    assert acme_only == ["wkr-alpha", "wkr-zeta"]


def test_disk_worker_store_persists_across_instances(tmp_path):
    root = tmp_path / "workers"
    DiskWorkerStore(root).create(_worker())

    reopened = DiskWorkerStore(root)
    assert reopened.get("wkr-alice-desktop").org_id == "acme"


def test_disk_worker_store_survives_a_corrupt_file(tmp_path):
    root = tmp_path / "workers"
    root.mkdir()
    (root / "workers.json").write_text("not valid json{{{", encoding="utf-8")

    store = DiskWorkerStore(root)
    assert store.list_workers() == []


def test_disk_worker_store_never_writes_a_plaintext_secret(tmp_path):
    root = tmp_path / "workers"
    store = DiskWorkerStore(root)
    store.create(_worker())

    raw = (root / "workers.json").read_text(encoding="utf-8")
    assert "a-real-worker-secret" not in raw
    assert "pbkdf2_sha256$" in raw


def test_verify_worker_credential_against_disk_store(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker())
    principal = verify_worker_credential("wkr-alice-desktop", "a-real-worker-secret", store=store)
    assert principal.org_id == "acme"
