"""Sign and verify the dual-gate's second half: the worker-side artifact.

ADR 0015 condition 3 is a **dual** gate, and this module is only the second
half of it:

* Gate (a) — whether a job is ever queued at all — is the cloud-side
  preview/confirm exchange in `postgres_worker_dispatch_store`, structurally
  identical to `screaming_frog_control.preview_tokens`. Nothing here mints
  or consumes that.
* Gate (b) — what THIS module does — is what the worker daemon
  independently verifies before its own `GuardrailEngine.authorize()` call
  runs locally. `issue_dispatch_assignment` is called only once a job has
  already been claimed off the queue (`claim_next_job`'s atomic
  `QUEUED -> DISPATCHED` transition), so gate (a) has already passed by the
  time gate (b)'s artifact is ever minted.

Condition 3(b) is explicit: this must be "a falsifiable, single-use,
expiring, identity-bound approval artifact ... NEVER a bare boolean". This
module's `verify_dispatch_assignment` is what the worker calls from inside
a `CallbackApprovalProvider` — the same pattern
`screaming_frog_control.preview_tokens.make_approval_callback` already
uses locally, extended across the network hop. A worker that instead
trusted an unconditional `{"approved": true}` would be
`AutoApproveProvider` wired into production by another name (CLAUDE.md §3).

Why HMAC, self-contained, JWT-shaped
-------------------------------------
Same construction as `src.core.auth.issue_session_token`/
`verify_session_token`, duplicated rather than imported — that module's
helpers are private, and this one needs the identical "header.payload.
signature" b64url shape for the same reason: ADR 0016 condition 6 prefers a
format that costs nothing but a local HMAC compare to verify, so a worker
daemon polling every 10-15s never needs a network round-trip, and therefore
never needs circuit-breaker coverage this codebase does not have on any
HTTP path (ADR 0015's own correction re: `circuit_breaker.py`).

Condition 4's own limit
------------------------
Signing defends against network-path tampering and a third party spoofing
either side. It does **not** defend against a compromised cloud process,
because the signing key lives inside that trust boundary. Gate (a) — not
this module — is what limits the blast radius of a compromised cloud API;
nothing here should be read as sufficient approval on its own.

Single-use, without a third server-side store
-----------------------------------------------
`claim_next_job`'s atomic `UPDATE ... WHERE status = 'queued'` already
guarantees the cloud issues at most one assignment per `job_id` under
normal operation — a second poll for the same job finds it no longer
`QUEUED`. This module adds no separate "consumed jti" table for that
reason; a *replay* of an intercepted, still-unexpired token is a network-
tampering threat condition 4 already scopes to HMAC signing plus TLS in
production, not to server-side state this ADR would otherwise need to add.
The worker's own local idempotency ledger (see
`screaming_frog_control.worker_daemon`) is what defends against a replayed
artifact being *run twice* on the machine that actually executes it, which
is the outcome that matters operationally.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime

from pydantic import SecretStr, ValidationError

from src.core.errors import RankunoError
from src.core.worker_dispatch_schemas import (
    DispatchAssignmentClaims,
    SignedDispatchAssignment,
    WorkerJobKind,
)

__all__ = [
    "DispatchAssignmentError",
    "issue_dispatch_assignment",
    "verify_dispatch_assignment",
]

_ALG = "HS256"  # noqa: S105 - a JWT header algorithm name, not a credential
_TYP = "RANKUNO-DISPATCH"  # noqa: S105 - a JWT header type label, not a credential


class DispatchAssignmentError(RankunoError):
    """A dispatch assignment artifact failed verification.

    Raised for every failure mode alike (malformed, bad signature, expired,
    invalid claims) — the worker's only correct response to any of them is
    "do not run this job", so collapsing the cases costs nothing and avoids
    the same enumeration-oracle shape `AuthenticationError` avoids.
    """


def _b64url_encode(payload: bytes) -> str:
    return urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def issue_dispatch_assignment(
    *,
    job_id: str,
    worker_id: str,
    org_id: str,
    kind: WorkerJobKind,
    seed_url: str,
    template_name: str | None,
    correlation_id: str,
    secret: SecretStr,
    ttl_s: float,
) -> SignedDispatchAssignment:
    """Mint a signed, self-contained assignment for one claimed job.

    Called exactly once per successful `claim_next_job` — never speculatively,
    and never for a job that has not already passed gate (a).

    Args:
        job_id: The claimed job's id.
        worker_id: The worker that claimed it. Binds the artifact so a
            different worker's daemon (even a compromised one holding a
            valid *worker* credential) cannot use an artifact minted for
            someone else's job.
        org_id: The owning organization.
        kind: Closed-enum job kind (condition 7).
        seed_url: Carried inside the signed claims so tampering the
            envelope in transit invalidates the same signature (condition
            4) — not a second, separately-signed object.
        template_name: As above.
        correlation_id: As above.
        secret: The shared HMAC key both the cloud API and this worker's
            daemon hold via `get_settings()` (ADR 0016 condition 10's
            `SecretStr`/no-`os.environ` posture, extended to this secret).
        ttl_s: Seconds until the artifact expires. Short — long enough for
            the worker to receive the poll response and start the tool,
            short enough that an intercepted artifact has a narrow replay
            window (mirrors `preview_tokens.DEFAULT_TOKEN_TTL_S`'s stance).

    Returns:
        The signed token and its absolute expiry.
    """
    issued_at = time.time()
    expires_at = issued_at + ttl_s
    claims = DispatchAssignmentClaims(
        job_id=job_id,
        worker_id=worker_id,
        org_id=org_id,
        kind=kind,
        seed_url=seed_url,
        template_name=template_name,
        correlation_id=correlation_id,
        jti=secrets.token_urlsafe(16),
        issued_at=datetime.fromtimestamp(issued_at, tz=UTC),
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
    )
    header = {"alg": _ALG, "typ": _TYP}
    signing_input = (
        f"{_b64url_encode(json.dumps(header).encode())}."
        f"{_b64url_encode(claims.model_dump_json().encode())}"
    )
    signature = hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    token = f"{signing_input}.{_b64url_encode(signature)}"
    return SignedDispatchAssignment(token=token, expires_at=claims.expires_at)


def verify_dispatch_assignment(
    token: str, *, secret: SecretStr, worker_id: str, org_id: str
) -> DispatchAssignmentClaims:
    """Verify a dispatch assignment's signature, expiry, and identity binding.

    This is gate (b): the worker daemon's `CallbackApprovalProvider` calls
    this, never trusting the poll response's mere presence as approval.

    Args:
        token: The signed artifact from the poll response.
        secret: The same shared HMAC key `issue_dispatch_assignment` signed
            with — this worker's own `get_settings()` value, never a value
            the request itself supplied.
        worker_id: This worker's own configured id. The claims must name
            exactly this worker — an artifact minted for another worker_id
            is refused even though the signature is otherwise valid,
            because a compromised cloud process could otherwise hand one
            worker a job meant for another's licence seat.
        org_id: This worker's own configured org. Same binding reasoning.

    Returns:
        The verified claims.

    Raises:
        DispatchAssignmentError: The token is malformed, the signature does
            not match, it has expired, its claims are invalid, or it is
            bound to a different worker or org than the one verifying it.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise DispatchAssignmentError("malformed dispatch assignment token")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected_signature = hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        actual_signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise DispatchAssignmentError("malformed dispatch assignment signature") from exc
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise DispatchAssignmentError("dispatch assignment signature does not match")

    try:
        payload_bytes = _b64url_decode(parts[1])
    except Exception as exc:
        raise DispatchAssignmentError("malformed dispatch assignment payload") from exc

    try:
        claims = DispatchAssignmentClaims.model_validate_json(payload_bytes)
    except ValidationError as exc:
        raise DispatchAssignmentError("dispatch assignment claims are invalid") from exc

    if claims.expires_at.timestamp() < time.time():
        raise DispatchAssignmentError("dispatch assignment expired")

    if claims.worker_id != worker_id or claims.org_id != org_id:
        raise DispatchAssignmentError(
            "dispatch assignment is bound to a different worker or organization"
        )

    return claims
