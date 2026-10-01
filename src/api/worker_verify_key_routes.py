"""Publish the cloud's Ed25519 dispatch *verify* key to worker installers (ADR 0028).

A worker needs the cloud's public key to verify gate (b) assignments, and
before ADR 0028 the equivalent value — a shared HMAC secret — was pasted by
hand from the Railway dashboard into every desktop's `.env.local`. Publishing
the public key over the API removes that copy step and, with it, any reason
for an operator to handle a signing secret on a worker machine at all.

Why authenticated when the key is public
----------------------------------------
Nothing here is secret: a public key grants no authority. The route still
sits behind `require_principal` (operator session, ADR 0016) because its only
legitimate caller is `scripts/register_worker.py`, which has just logged in,
and because an anonymous endpoint would let anyone fingerprint which signing
key — and therefore which rotation generation — a deployment runs.

A separate module from `worker_dashboard_routes.py` purely to keep that file's
history independent of this change; it is the same human-authenticated half
of the worker surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, status

from src.api.auth import require_principal
from src.api.worker_schemas import DispatchVerifyKeyView

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_dispatch_verify_key_router"]

_NOT_CONFIGURED = (
    "This deployment does not sign dispatch assignments with Ed25519 yet: "
    "WORKER_DISPATCH_SIGNING_PRIVATE_KEY is not set on the cloud API (ADR 0028)."
)


def build_dispatch_verify_key_router(state: ApiState) -> APIRouter:
    """Build `GET /workers/dispatch-verify-key` over `state`."""
    router = APIRouter()

    @router.get("/workers/dispatch-verify-key", response_model=DispatchVerifyKeyView)
    def get_dispatch_verify_key(
        authorization: str | None = Header(default=None),
    ) -> DispatchVerifyKeyView:
        """Return the public half of the cloud's dispatch signing key.

        Raises:
            HTTPException: `401` without a valid operator session; `503`
                when the deployment still signs with the legacy HMAC key
                only, so an installer stops instead of writing a key that
                could never verify anything.
        """
        require_principal(authorization, session_secret=state.session_secret)
        key = state.dispatch_signing_key
        if key is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED)
        return DispatchVerifyKeyView(kid=key.kid, public_key=key.public_key_b64)

    return router
