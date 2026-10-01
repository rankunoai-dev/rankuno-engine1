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

Ed25519, and the HMAC transition (ADR 0028)
-------------------------------------------
A shared HMAC key made every *verifier* a potential *signer*: anyone holding
one worker's configuration could forge claims for every worker. The cloud now
signs with an Ed25519 private key (`worker_dispatch_keys`) and a worker holds
only the public key. The token keeps its three-segment `header.payload.hmac`
shape because deployed workers parse the poll response with `extra="forbid"`
and verify the HMAC over `header.payload` — a new envelope field, or a fourth
segment, would make every existing worker reject every job. So the Ed25519
signature rides **inside the header segment** as a JWS-style detached
signature::

    header = {"alg": ..., "typ": "RANKUNO-DISPATCH",
              "ed25519": {"protected": b64url({"alg": "EdDSA",
                                               "typ": "RANKUNO-DISPATCH",
                                               "kid": <kid>}),
                          "signature": b64url(Ed25519(protected + "." + payload))}}
    token  = b64url(header) "." b64url(claims) "." b64url(HMAC(header "." payload)) | ""

The Ed25519 signing input is the same `<b64url header>.<b64url claims>` shape
HMAC signs, over the protected header rather than the outer one, and over the
byte-identical claims segment — the claims canonicalisation is unchanged. The
legacy HMAC covers the whole outer header, so an old worker verifies a
dual-signed token exactly as before. With no signing key configured the header
is the original `{"alg": "HS256", "typ": ...}` and the token is byte-for-byte
what this module always produced.

The verifier picks the algorithm from its **own** configuration, never from
the token: given a verify key it demands a valid Ed25519 signature under a
matching `kid` and never looks at the HMAC segment. An HMAC fallback there
would leave the original forgery open, so there is none.

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
from typing import Any

from pydantic import SecretStr, ValidationError

from src.core.errors import ConfigurationError, RankunoError
from src.core.worker_dispatch_keys import DispatchSigningKey, DispatchVerifyKey
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
_ED_ALG = "EdDSA"
_TYP = "RANKUNO-DISPATCH"  # noqa: S105 - a JWT header type label, not a credential
_ED_FIELD = "ed25519"


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


def _hmac_segment(signing_input: str, secret: SecretStr) -> bytes:
    return hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()


def _header_segment(
    payload_segment: str, *, signing_key: DispatchSigningKey | None, hmac_on: bool
) -> str:
    """Build the outer header, embedding the Ed25519 signature when there is a key.

    With no key the header is exactly the legacy `{"alg": "HS256", ...}`, so
    an HMAC-only deployment keeps producing byte-identical tokens.
    """
    if signing_key is None:
        return _b64url_encode(json.dumps({"alg": _ALG, "typ": _TYP}).encode())
    protected = _b64url_encode(
        json.dumps({"alg": _ED_ALG, "typ": _TYP, "kid": signing_key.kid}).encode()
    )
    signature = signing_key.sign(f"{protected}.{payload_segment}".encode("ascii"))
    header = {
        "alg": _ALG if hmac_on else _ED_ALG,
        "typ": _TYP,
        _ED_FIELD: {"protected": protected, "signature": _b64url_encode(signature)},
    }
    return _b64url_encode(json.dumps(header).encode())


def issue_dispatch_assignment(
    *,
    job_id: str,
    worker_id: str,
    org_id: str,
    kind: WorkerJobKind,
    seed_url: str,
    template_name: str | None,
    correlation_id: str,
    ttl_s: float,
    secret: SecretStr | None = None,
    signing_key: DispatchSigningKey | None = None,
    url_list_sha256: str | None = None,
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
        ttl_s: Seconds until the artifact expires. Short — long enough for
            the worker to receive the poll response and start the tool,
            short enough that an intercepted artifact has a narrow replay
            window (mirrors `preview_tokens.DEFAULT_TOKEN_TTL_S`'s stance).
        secret: The legacy shared HMAC key, or `None` to emit no HMAC
            signature. Kept only for the ADR 0028 transition, so workers
            not yet holding a verify key keep working.
        signing_key: The cloud's Ed25519 private key, or `None` while a
            deployment has not configured one yet.
        url_list_sha256: Digest of the approved `--crawl-list` file, or
            `None` for an ordinary `--crawl` job (ADR 0023). Carried inside
            the same claims for the same reason as `seed_url`: swapping it
            in transit for a digest naming a different stored list
            invalidates every signature over the claims, so no separate
            signing step was needed to cover it.

    Returns:
        The signed token and its absolute expiry.

    Raises:
        ConfigurationError: Neither `secret` nor `signing_key` was given.
            An unsigned artifact is refused rather than minted — fail closed.
    """
    if secret is None and signing_key is None:
        msg = (
            "No dispatch signing method is configured: set "
            "WORKER_DISPATCH_SIGNING_PRIVATE_KEY (ADR 0028). Refusing to mint an "
            "unsigned dispatch assignment."
        )
        raise ConfigurationError(msg)
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
        url_list_sha256=url_list_sha256,
        jti=secrets.token_urlsafe(16),
        issued_at=datetime.fromtimestamp(issued_at, tz=UTC),
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
    )
    payload_segment = _b64url_encode(claims.model_dump_json().encode())
    header_segment = _header_segment(
        payload_segment, signing_key=signing_key, hmac_on=secret is not None
    )
    signing_input = f"{header_segment}.{payload_segment}"
    hmac_segment = "" if secret is None else _b64url_encode(_hmac_segment(signing_input, secret))
    token = f"{signing_input}.{hmac_segment}"
    return SignedDispatchAssignment(token=token, expires_at=claims.expires_at)


def _verify_hmac(parts: list[str], secret: SecretStr) -> None:
    """The legacy check, unchanged: HMAC-SHA256 over `header.payload`."""
    expected_signature = _hmac_segment(f"{parts[0]}.{parts[1]}", secret)
    try:
        actual_signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise DispatchAssignmentError("malformed dispatch assignment signature") from exc
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise DispatchAssignmentError("dispatch assignment signature does not match")


def _decode_json_object(segment: str) -> dict[str, Any]:
    """Decode one b64url JSON object, or raise — every failure looks the same."""
    try:
        value = json.loads(_b64url_decode(segment))
    except Exception as exc:
        raise DispatchAssignmentError("malformed dispatch assignment header") from exc
    if not isinstance(value, dict):
        raise DispatchAssignmentError("malformed dispatch assignment header")
    return value


def _verify_ed25519(parts: list[str], verify_key: DispatchVerifyKey) -> None:
    """Demand a valid Ed25519 signature under this worker's own `kid`.

    `parts[2]` (the HMAC segment) is never read here: a token whose only
    valid signature is the HMAC one is rejected, which is the property that
    closes the shared-key forgery.
    """
    embedded = _decode_json_object(parts[0]).get(_ED_FIELD)
    if not isinstance(embedded, dict):
        raise DispatchAssignmentError("dispatch assignment carries no Ed25519 signature")
    protected = embedded.get("protected")
    signature_b64 = embedded.get("signature")
    if not isinstance(protected, str) or not isinstance(signature_b64, str):
        raise DispatchAssignmentError("dispatch assignment carries no Ed25519 signature")

    protected_header = _decode_json_object(protected)
    if protected_header.get("alg") != _ED_ALG or protected_header.get("typ") != _TYP:
        raise DispatchAssignmentError("dispatch assignment has an unexpected protected header")
    if protected_header.get("kid") != verify_key.kid:
        raise DispatchAssignmentError("dispatch assignment is signed by an unknown key id")

    try:
        signature = _b64url_decode(signature_b64)
        signing_input = f"{protected}.{parts[1]}".encode("ascii")
    except Exception as exc:
        raise DispatchAssignmentError("malformed dispatch assignment signature") from exc
    if not verify_key.verify(signature, signing_input):
        raise DispatchAssignmentError("dispatch assignment signature does not match")


def verify_dispatch_assignment(
    token: str,
    *,
    worker_id: str,
    org_id: str,
    secret: SecretStr | None = None,
    verify_key: DispatchVerifyKey | None = None,
) -> DispatchAssignmentClaims:
    """Verify a dispatch assignment's signature, expiry, and identity binding.

    This is gate (b): the worker daemon's `CallbackApprovalProvider` calls
    this, never trusting the poll response's mere presence as approval.

    Args:
        token: The signed artifact from the poll response.
        worker_id: This worker's own configured id. The claims must name
            exactly this worker — an artifact minted for another worker_id
            is refused even though the signature is otherwise valid,
            because a compromised cloud process could otherwise hand one
            worker a job meant for another's licence seat.
        org_id: This worker's own configured org. Same binding reasoning.
        secret: The legacy shared HMAC key — this worker's own
            `get_settings()` value, never one the request supplied.
            Consulted **only** when `verify_key` is `None`.
        verify_key: This worker's Ed25519 public key. When given, only an
            Ed25519 signature under its `kid` is accepted and `secret` is
            ignored entirely, so there is no downgrade path to HMAC.

    Returns:
        The verified claims.

    Raises:
        DispatchAssignmentError: The token is malformed, the signature does
            not match or names an unknown `kid`, it has expired, its claims
            are invalid, it is bound to a different worker or org than the
            one verifying it, or no verification key was supplied at all.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise DispatchAssignmentError("malformed dispatch assignment token")

    if verify_key is not None:
        _verify_ed25519(parts, verify_key)
    elif secret is not None:
        _verify_hmac(parts, secret)
    else:
        raise DispatchAssignmentError("no dispatch verification key is configured")

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
