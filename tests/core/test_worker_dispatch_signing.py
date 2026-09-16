"""Tests for ADR 0015's gate (b): the signed dispatch assignment artifact.

Mirrors `tests/core/test_auth.py`'s session-token tests closely — same HMAC
construction, same failure modes (tampering, wrong secret, expiry,
malformed input) — plus this artifact's own extra binding requirement:
`worker_id`/`org_id` must match the *verifying* worker exactly, which a
session token has no equivalent of.
"""

from __future__ import annotations

import time

import pytest
from pydantic import SecretStr
from src.core.worker_dispatch_schemas import WorkerJobKind
from src.core.worker_dispatch_signing import (
    DispatchAssignmentError,
    issue_dispatch_assignment,
    verify_dispatch_assignment,
)

SECRET = SecretStr("unit-test-dispatch-signing-key")
OTHER_SECRET = SecretStr("a-different-signing-key")

_BASE_KWARGS: dict[str, object] = {
    "job_id": "job-123",
    "worker_id": "wkr-alice-desktop",
    "org_id": "acme",
    "kind": WorkerJobKind.SCREAMING_FROG_CRAWL,
    "seed_url": "https://example.com/",
    "template_name": "standard-audit",
    "correlation_id": "corr-1",
}


def _issue(**overrides: object) -> str:
    kwargs = {**_BASE_KWARGS, **overrides}
    return issue_dispatch_assignment(secret=SECRET, ttl_s=300.0, **kwargs).token  # type: ignore[arg-type]


def test_issue_and_verify_round_trips():
    token = _issue()
    claims = verify_dispatch_assignment(
        token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
    )
    assert claims.job_id == "job-123"
    assert claims.worker_id == "wkr-alice-desktop"
    assert claims.org_id == "acme"
    assert claims.kind is WorkerJobKind.SCREAMING_FROG_CRAWL
    assert claims.seed_url == "https://example.com/"
    assert claims.template_name == "standard-audit"
    assert claims.correlation_id == "corr-1"


def test_verify_rejects_a_token_signed_with_a_different_secret():
    token = _issue()
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token, secret=OTHER_SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


def test_verify_rejects_an_expired_assignment():
    token = issue_dispatch_assignment(secret=SECRET, ttl_s=-1.0, **_BASE_KWARGS)  # type: ignore[arg-type]
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token.token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


@pytest.mark.parametrize(
    "malformed",
    ["", "not.a.token.at.all", "onlyonepart", "two.parts", "not-base64.also-not.still-not"],
)
def test_verify_rejects_malformed_tokens(malformed: str):
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            malformed, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


# --- Identity binding (ADR 0015 condition 3(b)) ---------------------------------


def test_verify_rejects_an_assignment_bound_to_a_different_worker():
    """A worker must not be able to act on a job dispatched to another worker."""
    token = _issue(worker_id="wkr-bob-desktop")
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


def test_verify_rejects_an_assignment_bound_to_a_different_org():
    token = _issue(org_id="globex")
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


def test_verify_rejects_a_tampered_seed_url():
    """A tampered envelope field must invalidate the same signature.

    Condition 4: the envelope is signed inside the same artifact as the
    approval — tampering `seed_url` in transit must invalidate the
    signature, not merely be caught by a separate integrity check.
    """
    import json
    from base64 import urlsafe_b64decode, urlsafe_b64encode

    token = _issue()
    header_b64, payload_b64, signature_b64 = token.split(".")
    payload = json.loads(urlsafe_b64decode(payload_b64 + "=="))
    payload["seed_url"] = "https://attacker.example/"
    tampered_payload_b64 = (
        urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode("ascii")
    )
    forged_token = f"{header_b64}.{tampered_payload_b64}.{signature_b64}"

    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            forged_token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
        )


def test_each_issued_assignment_has_a_unique_jti():
    """`jti` is the artifact's own nonce — two mints for the same job must differ."""
    first = issue_dispatch_assignment(secret=SECRET, ttl_s=300.0, **_BASE_KWARGS)  # type: ignore[arg-type]
    second = issue_dispatch_assignment(secret=SECRET, ttl_s=300.0, **_BASE_KWARGS)  # type: ignore[arg-type]
    claims_a = verify_dispatch_assignment(
        first.token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
    )
    claims_b = verify_dispatch_assignment(
        second.token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
    )
    assert claims_a.jti != claims_b.jti


def test_expires_at_reflects_the_requested_ttl():
    before = time.time()
    signed = issue_dispatch_assignment(secret=SECRET, ttl_s=60.0, **_BASE_KWARGS)  # type: ignore[arg-type]
    assert signed.expires_at.timestamp() >= before + 59
    assert signed.expires_at.timestamp() <= before + 61
