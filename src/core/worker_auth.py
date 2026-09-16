"""Worker daemon identity and credential verification (ADR 0015 condition 2).

ADR 0015 layers a *second* credential type on top of ADR 0016's mechanism
(`src/core/auth.py`), for a principal ADR 0016 never designed for: an
unattended desktop daemon polling the cloud API, not a human operator's
browser session. The two must stay distinct (ADR 0016 condition 5, ADR 0015
condition 2) — a worker credential is long-lived (no login exchange, no
short-TTL session) and identifies one specific machine holding the Screaming
Frog licence seat, never a platform-wide shared secret.

`Worker`/`WorkerPrincipal` mirror `Operator`/`Principal` deliberately, and
`DiskWorkerStore` mirrors `DiskOperatorStore` byte-for-byte in its storage
model: ADR 0016 already shipped `DiskOperatorStore` as production storage for
human identity despite the same multi-cloud-replica caveat this module
carries (a worker registered against one replica's disk file is invisible to
another). That is a known, accepted limitation this module inherits rather
than re-litigates — condition 5's *binding* Postgres requirement names the
preview/confirm dispatch gate and the job queue specifically, not worker
identity storage, and this module does not expand that scope.

Password hashing is reused verbatim from `src/core/auth.py`: a worker secret
is verified exactly like an operator password (PBKDF2-HMAC-SHA256 behind a
salt), because the security property required — "prove knowledge of a secret
without the verifier being able to leak the plaintext" — is identical.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import Field

from src.core.auth import hash_password, verify_password
from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.schemas import StrictModel

__all__ = [
    "DiskWorkerStore",
    "Worker",
    "WorkerAuthenticationError",
    "WorkerNotFoundError",
    "WorkerPrincipal",
    "WorkerStore",
    "mint_worker_secret",
    "verify_worker_credential",
]

_logger = get_logger("core.worker_auth")

_IDENTIFIER_PATTERN = r"^[a-z0-9_-]{1,64}$"
"""Same rule `Operator.operator_id`/`OrgConfig.org_id` already use."""

_SECRET_BYTES = 32
"""256 bits of entropy for a long-lived, network-facing bearer credential —
generous relative to a human password, because this secret is never typed
and never expires on a human-forgettable schedule."""

# A precomputed, valid-shaped hash with no real worker behind it, so a
# worker-id-not-found rejection costs the same as a wrong-secret rejection —
# the same timing-oracle defense `src/api/auth.py`'s login route already
# applies to operator ids.
_DUMMY_SECRET_HASH = hash_password("no-worker-has-this-secret")


class WorkerAuthenticationError(RankunoError):
    """A worker credential failed verification.

    One exception for "unknown worker_id" and "wrong secret" alike, for the
    same reason `src.core.auth.AuthenticationError` collapses its own cases:
    a distinct error per cause is a worker-id-enumeration oracle.
    """


class WorkerNotFoundError(KeyError):
    """No such worker is registered.

    A `KeyError` subclass, matching `OperatorNotFoundError`'s own contract.
    """


class Worker(StrictModel):
    """One registered desktop worker daemon.

    Attributes:
        worker_id: Stable identifier the daemon presents on every request.
        org_id: The organization this worker's Screaming Frog seat belongs
            to. A job is only ever dispatched to a worker inside its own
            org — this is not itself the IDOR check (routes must still
            compare against the authenticated principal), but no worker
            row exists outside an org to accidentally match against.
        secret_hash: PBKDF2 hash of the worker's long-lived credential.
            Never the recoverable secret (ADR 0015 condition 2, ADR 0016
            condition 5(b), ADR 0010's posture toward GSC OAuth secrets).
        display_name: Operator-facing label (e.g. the desktop's hostname).
        is_active: Whether this worker may currently be dispatched to.
        created_at: When the worker was registered.
    """

    worker_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    secret_hash: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=200)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkerPrincipal(StrictModel):
    """The verified identity behind one authenticated worker request.

    Built only by `verify_worker_credential`. Every worker-facing dispatch
    route filters strictly by this — never by a `worker_id` the request body
    or a path parameter merely claims (ADR 0015 condition 2's IDOR
    requirement, the same pattern `src.core.auth.Principal` already
    establishes for human callers).
    """

    worker_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)


def mint_worker_secret() -> str:
    """Generate a fresh, high-entropy worker credential.

    Returned exactly once, by the registration route, to the operator
    provisioning a new desktop — the same "shown once" posture an API-key
    creation flow uses, because this module stores only `hash_password`'s
    output afterward.
    """
    return secrets.token_urlsafe(_SECRET_BYTES)


def verify_worker_credential(worker_id: str, secret: str, *, store: WorkerStore) -> WorkerPrincipal:
    """Verify a worker's long-lived credential and return its principal.

    Args:
        worker_id: The id the request claims.
        secret: The bearer credential presented alongside it.
        store: Where registered workers live.

    Returns:
        The verified principal — `org_id` here is ground truth for the rest
        of the request, the same role `Principal.org_id` plays for a human
        session.

    Raises:
        WorkerAuthenticationError: The worker is unknown, inactive, or the
            secret does not match. One message for all three (see module
            docstring).
    """
    try:
        worker = store.get(worker_id)
    except WorkerNotFoundError:
        # Spend the same PBKDF2 cost on an unknown id as on a real one, so a
        # timing measurement cannot distinguish the two cases.
        verify_password(secret, _DUMMY_SECRET_HASH)
        raise WorkerAuthenticationError("unknown worker or invalid credential") from None

    if not worker.is_active or not verify_password(secret, worker.secret_hash):
        raise WorkerAuthenticationError("unknown worker or invalid credential")

    return WorkerPrincipal(worker_id=worker.worker_id, org_id=worker.org_id)


class WorkerStore(Protocol):
    """The persistence seam for worker identity.

    A Protocol, matching `OperatorStore`/`OrgConfigStore`/`JobStore`, so a
    future shared implementation can replace `DiskWorkerStore` without the
    API layer changing.
    """

    def create(self, worker: Worker) -> Worker:
        """Persist a new worker.

        Raises:
            ValueError: If the worker id is already taken.
        """
        ...

    def get(self, worker_id: str) -> Worker:
        """Read one worker.

        Raises:
            WorkerNotFoundError: If no such worker exists.
        """
        ...

    def list_workers(self, org_id: str | None = None) -> list[Worker]:
        """Every worker, sorted by id. Filtered to `org_id` when given."""
        ...


def _atomic_write(path: Path, payload: str) -> None:
    """Write `payload` to `path` so a crash cannot leave it half-written.

    Duplicated from `src.core.auth`'s own private helper rather than
    imported, matching that module's precedent: it is private there, and
    this module should stay importable without depending on `auth.py`'s
    internals for one function.
    """
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class DiskWorkerStore:
    """A `WorkerStore` backed by a single JSON file.

    Single-process only, the same limitation `DiskOperatorStore` carries and
    the same reason it is nonetheless the shipped implementation: worker
    *identity* is not the piece ADR 0015 condition 5 requires on Postgres —
    the dispatch preview/confirm gate and the job queue are (see
    `src.core.postgres_worker_dispatch_store`). A worker registered on one
    cloud replica being invisible to another is a real limitation of this
    class; it is inherited from `DiskOperatorStore`'s already-accepted
    posture, not introduced fresh here.
    """

    def __init__(self, root: Path | str) -> None:
        """Create the store, making its directory if absent.

        Args:
            root: Directory to hold `workers.json`.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "workers.json"
        self._lock = threading.Lock()
        self._workers: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _logger.warning("worker_store_load_failed", extra={"error": str(exc)})
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _save(self) -> None:
        payload = json.dumps(self._workers, indent=2, sort_keys=True)
        _atomic_write(self._path, payload)

    def create(self, worker: Worker) -> Worker:
        """Persist a new worker.

        Raises:
            ValueError: If the worker id is already taken.
        """
        with self._lock:
            if worker.worker_id in self._workers:
                msg = f"Worker '{worker.worker_id}' already exists"
                raise ValueError(msg)
            self._workers[worker.worker_id] = json.loads(worker.model_dump_json())
            self._save()
        _logger.info(
            "worker_registered", extra={"worker_id": worker.worker_id, "org": worker.org_id}
        )
        return worker

    def get(self, worker_id: str) -> Worker:
        """Read one worker.

        Raises:
            WorkerNotFoundError: If no such worker exists.
        """
        with self._lock:
            data = self._workers.get(worker_id)
        if data is None:
            msg = f"Worker '{worker_id}' not found"
            raise WorkerNotFoundError(msg)
        return Worker.model_validate(data)

    def list_workers(self, org_id: str | None = None) -> list[Worker]:
        """Every worker, sorted by id. Filtered to `org_id` when given."""
        with self._lock:
            values = list(self._workers.values())
        workers = sorted((Worker.model_validate(v) for v in values), key=lambda w: w.worker_id)
        if org_id is not None:
            workers = [w for w in workers if w.org_id == org_id]
        return workers
