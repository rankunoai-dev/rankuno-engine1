"""Tests for ADR 0015's worker identity and credential primitives.

Mirrors `tests/core/test_auth.py`'s structure closely — `Worker`/
`WorkerPrincipal`/`DiskWorkerStore` are the worker-daemon analogues of
`Operator`/`Principal`/`DiskOperatorStore`, and the same properties matter:
password/secret hashing round-trips, a corrupt store fails closed, an
unknown worker id and a wrong secret are indistinguishable to the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from src.core.config import Settings
from src.core.worker_auth import (
    MAX_REPORTED_TEMPLATES,
    DiskWorkerStore,
    Worker,
    WorkerAuthenticationError,
    WorkerNotFoundError,
    mint_worker_secret,
    verify_worker_credential,
    worker_is_online,
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


# --- Liveness (the rule the dashboard is served rather than re-inventing) -------


def test_a_worker_that_never_checked_in_is_offline():
    """Registered is not running: `last_seen_at is None` is not "just now"."""
    assert worker_is_online(_worker(), offline_after_s=60.0) is False


def test_a_worker_seen_within_the_threshold_is_online():
    worker = _worker().model_copy(update={"last_seen_at": datetime.now(UTC)})
    assert worker_is_online(worker, offline_after_s=60.0) is True


def test_a_worker_seen_longer_ago_than_the_threshold_is_offline():
    worker = _worker().model_copy(
        update={"last_seen_at": datetime.now(UTC) - timedelta(seconds=61)}
    )
    assert worker_is_online(worker, offline_after_s=60.0) is False


def test_exactly_at_the_threshold_is_still_online():
    """The boundary is inclusive, so a poll landing on the tick is not a flap."""
    now = datetime.now(UTC)
    worker = _worker().model_copy(update={"last_seen_at": now - timedelta(seconds=60)})
    assert worker_is_online(worker, offline_after_s=60.0, now=now) is True


def test_a_deactivated_worker_is_never_online_however_recently_it_polled():
    worker = _worker().model_copy(update={"last_seen_at": datetime.now(UTC), "is_active": False})
    assert worker_is_online(worker, offline_after_s=60.0) is False


def test_the_default_offline_threshold_is_four_poll_intervals():
    """Documented relationship, asserted so it cannot drift silently."""
    settings = Settings(_env_file=None)
    assert settings.worker_offline_after_s == 4 * settings.worker_poll_interval_s


# --- DiskWorkerStore.touch ------------------------------------------------------


def test_touch_records_last_seen_and_persists_it(tmp_path):
    root = tmp_path / "workers"
    store = DiskWorkerStore(root)
    store.create(_worker())
    seen = datetime.now(UTC)
    store.touch("wkr-alice-desktop", seen_at=seen)

    reopened = DiskWorkerStore(root)
    assert reopened.get("wkr-alice-desktop").last_seen_at == seen


def test_touch_replaces_templates_when_given_and_leaves_them_otherwise(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker())
    store.touch("wkr-alice-desktop", seen_at=datetime.now(UTC), template_names=("a-b", "c_d"))
    store.touch("wkr-alice-desktop", seen_at=datetime.now(UTC))
    assert store.get("wkr-alice-desktop").template_names == ("a-b", "c_d")


def test_touch_refuses_a_template_name_that_could_become_a_path(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker())
    with pytest.raises(ValidationError):
        store.touch(
            "wkr-alice-desktop", seen_at=datetime.now(UTC), template_names=("../../etc/passwd",)
        )


def test_touch_refuses_more_templates_than_the_cap(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    store.create(_worker())
    with pytest.raises(ValidationError):
        store.touch(
            "wkr-alice-desktop",
            seen_at=datetime.now(UTC),
            template_names=tuple(f"t{i}" for i in range(MAX_REPORTED_TEMPLATES + 1)),
        )


def test_touch_of_an_unknown_worker_raises_not_found(tmp_path):
    store = DiskWorkerStore(tmp_path / "workers")
    with pytest.raises(WorkerNotFoundError):
        store.touch("wkr-ghost", seen_at=datetime.now(UTC))


def test_the_selected_backend_follows_configuration(tmp_path):
    """One setting decides; there is no try-postgres-then-fall-back path."""
    from src.core.postgres_worker_store import PostgresWorkerStore

    disk = Settings(_env_file=None, worker_store_backend="disk", worker_store_path=tmp_path / "w")
    assert isinstance(disk.worker_store, DiskWorkerStore)

    postgres = Settings(_env_file=None, worker_store_backend="postgres")
    assert isinstance(postgres.worker_store, PostgresWorkerStore)


def test_an_unknown_backend_name_is_refused_at_boot():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, worker_store_backend="sqlite")
