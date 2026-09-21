"""Durable worker identity for a container host (ADR 0015 condition 2).

`DiskWorkerStore` writes `workers.json` under `Settings.worker_store_path`.
On a workstation that is a real file on a real disk. On Railway it is
container-local scratch space: **every redeploy rebuilds the filesystem, so
every registered worker disappears and every desktop has to be re-registered
with a brand-new secret.** It also cannot work above one replica, because
each replica would hold a different file. Neither failure is visible as an
error — the API simply answers `401 invalid worker credential` to a daemon
whose credential was fine yesterday.

This module is the durable implementation of the same `WorkerStore`
Protocol. `Settings.worker_store_backend` selects between the two; nothing
in `src/api` knows which one it is holding.

Design choices worth stating, because they differ from
`postgres_worker_dispatch_store`:

* **Secret hashing is unchanged.** `create()` stores whatever
  `src.core.auth.hash_password` produced (PBKDF2-HMAC-SHA256, the iteration
  count that module already sets) and this module never hashes, re-hashes,
  compares, logs, or returns a secret or a hash. Verification stays in
  `worker_auth.verify_worker_credential`, one implementation for both
  backends.
* **No foreign key from `workers.org_id` to `org_configs.org_id`**, unlike
  `worker_jobs`. Registering a desktop must not require an org to have an
  `org_configs` row first; the constraint that actually matters is already
  enforced one step later, where `worker_jobs` refuses to queue a job for an
  unknown org.
* **`template_names` is a JSON array in a `TEXT` column**, not `TEXT[]`. The
  column is read and written whole, never queried element-wise, and a JSON
  string maps identically through psycopg and through the in-memory fake the
  tests use.

Every failure is raised as `WorkerStoreUnavailableError`, never swallowed:
an unreachable identity store must produce a `503`, not an implicit "no such
worker" that a daemon would read as a revoked credential.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, cast

from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.worker_auth import Worker, WorkerNotFoundError, WorkerStoreUnavailableError

if TYPE_CHECKING:
    from psycopg import Connection

__all__ = ["PostgresWorkerStore"]

_logger = get_logger("core.postgres_worker_store")

_COLUMNS = (
    "worker_id, org_id, secret_hash, display_name, is_active, created_at, "
    "last_seen_at, template_names"
)
"""Column list every read uses, in the order `_row_to_worker` expects."""


def _row_to_worker(row: tuple[object, ...]) -> Worker:
    """Map one `_COLUMNS`-shaped row onto a `Worker`.

    `template_names` is re-validated by `Worker`'s own field pattern on the
    way through, so even a row written by some other process cannot
    reintroduce a name that fails `TEMPLATE_NAME_PATTERN`.
    """
    (
        worker_id,
        org_id,
        secret_hash,
        display_name,
        is_active,
        created_at,
        last_seen_at,
        template_names,
    ) = row
    return Worker(
        worker_id=str(worker_id),
        org_id=str(org_id),
        secret_hash=str(secret_hash),
        display_name=str(display_name),
        is_active=bool(is_active),
        created_at=cast("datetime", created_at),
        last_seen_at=None if last_seen_at is None else cast("datetime", last_seen_at),
        template_names=tuple(json.loads(str(template_names or "[]"))),
    )


class PostgresWorkerStore:
    """Postgres-backed implementation of `WorkerStore`.

    A `connection_factory` is accepted so tests can inject a psycopg-shaped
    fake without a live database; production callers leave it `None` and get
    a fresh connection per call from `get_postgres_settings()`, matching
    `PostgresWorkerDispatchStore`'s posture on credential rotation.
    """

    def __init__(self, connection_factory: Callable[[], Connection] | None = None) -> None:
        """Build the store.

        Args:
            connection_factory: Returns a new `psycopg.Connection`. Defaults
                to a real connection built from `get_postgres_settings()`.
        """
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        import psycopg

        return psycopg.connect(get_postgres_settings().get_connection_string())

    def _connect(self) -> Connection:
        try:
            return self._connection_factory()
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed, fail-closed error
            raise WorkerStoreUnavailableError(f"cannot reach the worker store: {exc}") from exc

    def create(self, worker: Worker) -> Worker:
        """Persist a new worker.

        `ON CONFLICT DO NOTHING` plus a row-count check rather than catching
        a `UniqueViolation`: the duplicate case must raise `ValueError` to
        satisfy the Protocol, and distinguishing a unique-violation from a
        connection failure by exception type would couple this module to
        psycopg's error classes for no benefit.

        Raises:
            ValueError: If the worker id is already taken.
            WorkerStoreUnavailableError: If Postgres is unreachable.
        """
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO workers "
                    "(worker_id, org_id, secret_hash, display_name, is_active, created_at, "
                    "last_seen_at, template_names) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (worker_id) DO NOTHING",
                    (
                        worker.worker_id,
                        worker.org_id,
                        worker.secret_hash,
                        worker.display_name,
                        worker.is_active,
                        worker.created_at,
                        worker.last_seen_at,
                        json.dumps(list(worker.template_names)),
                    ),
                )
                inserted = cur.rowcount
        except WorkerStoreUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WorkerStoreUnavailableError(f"cannot register worker: {exc}") from exc
        finally:
            conn.close()

        if not inserted:
            msg = f"Worker '{worker.worker_id}' already exists"
            raise ValueError(msg)
        _logger.info(
            "worker_registered", extra={"worker_id": worker.worker_id, "org": worker.org_id}
        )
        return worker

    def get(self, worker_id: str) -> Worker:
        """Read one worker.

        Raises:
            WorkerNotFoundError: If no such worker exists.
            WorkerStoreUnavailableError: If Postgres is unreachable.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # `_COLUMNS` is a fixed module constant, never caller input;
                # `worker_id` is still bound via a `%s` placeholder.
                cur.execute(
                    f"SELECT {_COLUMNS} FROM workers WHERE worker_id = %s",  # noqa: S608
                    (worker_id,),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            raise WorkerStoreUnavailableError(f"cannot read worker {worker_id}: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            msg = f"Worker '{worker_id}' not found"
            raise WorkerNotFoundError(msg)
        return _row_to_worker(row)

    def list_workers(self, org_id: str | None = None) -> list[Worker]:
        """Every worker, sorted by id. Filtered to `org_id` when given.

        Raises:
            WorkerStoreUnavailableError: If Postgres is unreachable.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if org_id is None:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM workers ORDER BY worker_id ASC"  # noqa: S608
                    )
                else:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM workers "  # noqa: S608
                        "WHERE org_id = %s ORDER BY worker_id ASC",
                        (org_id,),
                    )
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise WorkerStoreUnavailableError(f"cannot list workers: {exc}") from exc
        finally:
            conn.close()
        return [_row_to_worker(row) for row in rows]

    def touch(
        self,
        worker_id: str,
        *,
        seen_at: datetime,
        template_names: tuple[str, ...] | None = None,
    ) -> Worker:
        """Record a check-in in one statement, returning the updated row.

        `COALESCE(%s, template_names)` keeps a poll (which reports no
        templates) from wiping the set a heartbeat reported earlier, without
        a read-modify-write that two replicas could interleave.

        Raises:
            WorkerNotFoundError: If no such worker exists.
            WorkerStoreUnavailableError: If Postgres is unreachable.
        """
        payload = None if template_names is None else json.dumps(list(template_names))
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                # `_COLUMNS` is a fixed module constant; both values below
                # are bound via `%s` placeholders.
                cur.execute(
                    "UPDATE workers SET last_seen_at = %s, "  # noqa: S608
                    "template_names = COALESCE(%s, template_names) "
                    f"WHERE worker_id = %s RETURNING {_COLUMNS}",
                    (seen_at, payload, worker_id),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            raise WorkerStoreUnavailableError(f"cannot record check-in: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            msg = f"Worker '{worker_id}' not found"
            raise WorkerNotFoundError(msg)
        return _row_to_worker(row)
