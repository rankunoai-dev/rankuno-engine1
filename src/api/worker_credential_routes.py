"""Operator routes that revoke or rotate a desktop worker's credential.

Before these existed an ADR 0015 worker credential could never be withdrawn:
`verify_worker_credential` checked `Worker.is_active`, but nothing anywhere
set it, so a leaked `WORKER_CREDENTIAL` stayed valid for the life of the
worker row. That matters more once credentials are handed to non-technical
operators inside a downloadable worker build.

Two actions, deliberately not three:

* **Revoke** sets `is_active = False`. The worker's very next request fails
  `require_worker_principal` with the same `401` an unknown worker gets, and
  the daemon treats a `401` as "credential rejected" and exits (exit code 3,
  `worker_daemon_cli.EXIT_CREDENTIAL_REJECTED`). Idempotent.
* **Rotate** stores the hash of a freshly minted secret, reactivates the
  worker and clears `last_seen_at`, in one store write. The old secret stops
  verifying immediately; the new one is in this response and nowhere else.

There is no "reactivate" route. Re-trusting the *old* secret after a revoke
would undo the revoke for exactly the case it exists for — a credential that
may have been copied — so rotation is the only way back.

Approval model: these follow `POST /workers` (registration) and the GSC
account routes in `server.py`, the existing precedent for operator-initiated
credential changes — an authenticated, org-scoped session is the
authorization, and the UI's confirmation dialog is the human confirmation.
No `GuardrailEngine` is involved: that engine governs `BaseTool.run()`
executions with a `RiskClass`, and no dashboard credential route goes
through it. Revoke only ever *reduces* what a credential can do.

In-flight jobs are not touched here. A job already `DISPATCHED` to a revoked
worker can no longer be progressed, uploaded or failed (all three routes
authenticate the worker), and `expire_stale_dispatched` moves it to `FAILED`
after `Settings.worker_dispatch_timeout_s`. A job still `QUEUED` for that
worker waits: a rotated worker claims it under its new credential on its
next poll; a revoked-and-never-rotated worker never does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, status

from src.api.auth import require_principal
from src.api.worker_route_helpers import summarise_worker, worker_store_unavailable
from src.api.worker_schemas import WorkerCredentialRotateResponse, WorkerSummary
from src.core.auth import hash_password
from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.worker_auth import (
    WorkerNotFoundError,
    WorkerStoreUnavailableError,
    mint_worker_secret,
)

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_worker_credential_router"]

_logger = get_logger("api.worker_credential_routes")


def _not_found(worker_id: str) -> HTTPException:
    """The single answer for "unknown" and "another org's" worker alike.

    The store already refuses to distinguish the two; a `403` here (the
    convention `owned_worker` uses for reads) would hand back the difference
    on the one route family where confirming that a worker id exists is
    most useful to someone holding a stolen credential.
    """
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no worker {worker_id}")


def build_worker_credential_router(state: ApiState) -> APIRouter:
    """Build the revoke and rotate routes over `state`."""
    router = APIRouter()

    @router.post("/workers/{worker_id}/revoke", response_model=WorkerSummary)
    def revoke_worker(
        worker_id: str, authorization: str | None = Header(default=None)
    ) -> WorkerSummary:
        """Refuse this worker's credential from now on.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown worker or
                another org's; `503` the worker store is unreachable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        try:
            worker = state.worker_store.set_active(worker_id, principal.org_id, active=False)
        except WorkerNotFoundError as exc:
            raise _not_found(worker_id) from exc
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        _logger.info(
            "worker_credential_revoked",
            extra={
                "worker_id": worker.worker_id,
                "org": principal.org_id,
                "operator_id": principal.operator_id,
            },
        )
        return summarise_worker(worker, offline_after_s=get_settings().worker_offline_after_s)

    @router.post(
        "/workers/{worker_id}/rotate-credential", response_model=WorkerCredentialRotateResponse
    )
    def rotate_worker_credential(
        worker_id: str, authorization: str | None = Header(default=None)
    ) -> WorkerCredentialRotateResponse:
        """Issue a new secret for this worker; the old one is refused at once.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown worker or
                another org's; `503` the worker store is unreachable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        secret = mint_worker_secret()
        try:
            worker = state.worker_store.replace_credential(
                worker_id, principal.org_id, new_credential_hash=hash_password(secret)
            )
        except WorkerNotFoundError as exc:
            raise _not_found(worker_id) from exc
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        _logger.info(
            "worker_credential_rotated",
            extra={
                "worker_id": worker.worker_id,
                "org": principal.org_id,
                "operator_id": principal.operator_id,
            },
        )
        return WorkerCredentialRotateResponse(
            worker_id=worker.worker_id, worker_secret=secret, org_id=worker.org_id
        )

    return router
