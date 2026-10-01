"""ADR 0028: gate (b) assignments signed with Ed25519, with an HMAC transition.

The property this file exists for: a worker holding a verify key accepts
**only** a valid Ed25519 signature under its own `kid`. Holding the legacy
shared HMAC secret — which every pre-ADR-0028 worker's `.env.local` contained
— must no longer be enough to forge a dispatch. Every test that names "no
fallback" is a variant of that one claim.

The other half is compatibility: a dual-signed token must still verify on a
worker that has not been upgraded, and an HMAC-only mint must stay
byte-shape-identical to what this module produced before ADR 0028.
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64decode, urlsafe_b64decode, urlsafe_b64encode

import pytest
from pydantic import SecretStr
from src.core.errors import ConfigurationError
from src.core.worker_dispatch_keys import DispatchSigningKey, DispatchVerifyKey, compute_kid
from src.core.worker_dispatch_schemas import SignedDispatchAssignment, WorkerJobKind
from src.core.worker_dispatch_signing import (
    DispatchAssignmentError,
    issue_dispatch_assignment,
    verify_dispatch_assignment,
)

SECRET = SecretStr("legacy-shared-hmac-key")
SIGNING_KEY = DispatchSigningKey.generate()
VERIFY_KEY = SIGNING_KEY.verify_key
WORKER = {"worker_id": "wkr-alice-desktop", "org_id": "acme"}

_CLAIMS: dict[str, object] = {
    "job_id": "job-123",
    "worker_id": "wkr-alice-desktop",
    "org_id": "acme",
    "kind": WorkerJobKind.SCREAMING_FROG_CRAWL,
    "seed_url": "https://example.com/",
    "template_name": "standard-audit",
    "correlation_id": "corr-1",
}


def _issue(**overrides: object) -> str:
    kwargs: dict[str, object] = {**_CLAIMS, "ttl_s": 300.0, **overrides}
    return issue_dispatch_assignment(**kwargs).token  # type: ignore[arg-type]


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json(segment: str) -> dict[str, object]:
    decoded: dict[str, object] = json.loads(urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    return decoded


def _resign_hmac(header: dict[str, object], payload_segment: str, secret: SecretStr) -> str:
    """What an attacker holding the shared HMAC secret can produce."""
    import hmac as _hmac

    header_segment = _b64(json.dumps(header).encode())
    signing_input = f"{header_segment}.{payload_segment}"
    signature = _hmac.new(
        secret.get_secret_value().encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64(signature)}"


# --- Ed25519 round trip ---------------------------------------------------------


def test_ed25519_only_round_trip():
    token = _issue(signing_key=SIGNING_KEY)
    claims = verify_dispatch_assignment(token, verify_key=VERIFY_KEY, **WORKER)
    assert claims.job_id == "job-123"
    assert claims.seed_url == "https://example.com/"
    assert token.endswith("."), "no HMAC segment when no legacy secret is given"


def test_dual_signed_round_trip_on_both_kinds_of_worker():
    token = _issue(signing_key=SIGNING_KEY, secret=SECRET)
    assert verify_dispatch_assignment(token, verify_key=VERIFY_KEY, **WORKER).job_id == "job-123"
    # A legacy (pre-ADR-0028) worker: HMAC secret only.
    assert verify_dispatch_assignment(token, secret=SECRET, **WORKER).job_id == "job-123"


def test_the_protected_header_carries_the_kid_derived_from_the_public_key():
    token = _issue(signing_key=SIGNING_KEY, secret=SECRET)
    header = _json(token.split(".")[0])
    embedded = header["ed25519"]
    assert isinstance(embedded, dict)
    protected = _json(embedded["protected"])
    raw_public = b64decode(VERIFY_KEY.public_key_b64)
    assert protected == {
        "alg": "EdDSA",
        "typ": "RANKUNO-DISPATCH",
        "kid": hashlib.sha256(raw_public).hexdigest()[:16],
    }


# --- Tampering and key identity -------------------------------------------------


def test_a_tampered_payload_is_rejected():
    header_segment, payload_segment, hmac_segment = _issue(signing_key=SIGNING_KEY).split(".")
    payload = _json(payload_segment)
    payload["seed_url"] = "https://attacker.example/"
    forged = f"{header_segment}.{_b64(json.dumps(payload).encode())}.{hmac_segment}"
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(forged, verify_key=VERIFY_KEY, **WORKER)


def test_a_token_signed_by_a_different_key_is_rejected_by_kid():
    other = DispatchSigningKey.generate()
    token = _issue(signing_key=other)
    with pytest.raises(DispatchAssignmentError, match="unknown key id"):
        verify_dispatch_assignment(token, verify_key=VERIFY_KEY, **WORKER)


def test_relabelling_a_foreign_signature_with_our_kid_is_rejected():
    """The kid selects the key; it is not itself evidence of anything."""
    other = DispatchSigningKey.generate()
    header_segment, payload_segment, _ = _issue(signing_key=other).split(".")
    header = _json(header_segment)
    embedded = header["ed25519"]
    assert isinstance(embedded, dict)
    relabelled = _b64(
        json.dumps({"alg": "EdDSA", "typ": "RANKUNO-DISPATCH", "kid": VERIFY_KEY.kid}).encode()
    )
    header["ed25519"] = {"protected": relabelled, "signature": embedded["signature"]}
    forged = f"{_b64(json.dumps(header).encode())}.{payload_segment}."
    with pytest.raises(DispatchAssignmentError, match="does not match"):
        verify_dispatch_assignment(forged, verify_key=VERIFY_KEY, **WORKER)


def test_identity_binding_and_expiry_still_apply_on_the_ed25519_path():
    with pytest.raises(DispatchAssignmentError, match="different worker"):
        verify_dispatch_assignment(
            _issue(signing_key=SIGNING_KEY, worker_id="wkr-bob"), verify_key=VERIFY_KEY, **WORKER
        )
    with pytest.raises(DispatchAssignmentError, match="expired"):
        verify_dispatch_assignment(
            _issue(signing_key=SIGNING_KEY, ttl_s=-1.0), verify_key=VERIFY_KEY, **WORKER
        )


@pytest.mark.parametrize(
    "header",
    [
        "not-json",
        _b64(b"[1, 2]"),
        _b64(json.dumps({"alg": "HS256", "typ": "RANKUNO-DISPATCH"}).encode()),
        _b64(json.dumps({"ed25519": "a-string"}).encode()),
        _b64(json.dumps({"ed25519": {"protected": 1, "signature": "x"}}).encode()),
        _b64(
            json.dumps(
                {"ed25519": {"protected": _b64(b'{"alg": "HS256"}'), "signature": "x"}}
            ).encode()
        ),
    ],
)
def test_malformed_or_missing_ed25519_headers_are_rejected(header: str):
    payload_segment = _issue(signing_key=SIGNING_KEY).split(".")[1]
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(f"{header}.{payload_segment}.", verify_key=VERIFY_KEY, **WORKER)


# --- No fallback: the security property of ADR 0028 -----------------------------


def test_a_verify_key_worker_rejects_a_claim_carrying_only_a_valid_hmac_signature():
    """The original forgery: anyone with the shared secret mints a claim.

    The worker is handed the secret too, to prove it is not merely absent
    but ignored — a fallback anywhere would accept this token.
    """
    hmac_only = _issue(secret=SECRET)
    assert verify_dispatch_assignment(hmac_only, secret=SECRET, **WORKER)  # genuinely valid HMAC
    with pytest.raises(DispatchAssignmentError, match="no Ed25519 signature"):
        verify_dispatch_assignment(hmac_only, verify_key=VERIFY_KEY, secret=SECRET, **WORKER)


def test_a_forged_claim_with_a_valid_hmac_and_a_broken_ed25519_signature_is_rejected():
    """Strip-and-resign: keep the real header shape, alter claims, re-HMAC."""
    header_segment, payload_segment, _ = _issue(signing_key=SIGNING_KEY, secret=SECRET).split(".")
    payload = _json(payload_segment)
    payload["seed_url"] = "https://attacker.example/"
    forged = _resign_hmac(_json(header_segment), _b64(json.dumps(payload).encode()), SECRET)
    # The forged token is a perfectly good legacy token...
    assert verify_dispatch_assignment(forged, secret=SECRET, **WORKER).seed_url == (
        "https://attacker.example/"
    )
    # ...and an upgraded worker refuses it.
    with pytest.raises(DispatchAssignmentError, match="does not match"):
        verify_dispatch_assignment(forged, verify_key=VERIFY_KEY, secret=SECRET, **WORKER)


# --- Transition compatibility ---------------------------------------------------


def test_an_hmac_only_mint_keeps_the_pre_adr_0028_header_exactly():
    header = _json(_issue(secret=SECRET).split(".")[0])
    assert header == {"alg": "HS256", "typ": "RANKUNO-DISPATCH"}


def test_an_ed25519_only_token_is_refused_by_a_legacy_worker():
    """Expected once WORKER_DISPATCH_LEGACY_HMAC_ENABLED=false: upgrade first."""
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(_issue(signing_key=SIGNING_KEY), secret=SECRET, **WORKER)


def test_the_wire_envelope_shape_is_unchanged():
    """Deployed workers parse the poll response with `extra="forbid"`.

    Any new field on `SignedDispatchAssignment` would make every un-upgraded
    worker reject every job, which is why the Ed25519 signature rides inside
    the token instead.
    """
    assert set(SignedDispatchAssignment.model_fields) == {"token", "expires_at"}


def test_minting_with_no_signing_method_fails_closed():
    with pytest.raises(ConfigurationError):
        _issue()


def test_verifying_with_no_key_fails_closed():
    with pytest.raises(DispatchAssignmentError, match="no dispatch verification key"):
        verify_dispatch_assignment(_issue(secret=SECRET), **WORKER)


# --- Key encoding ---------------------------------------------------------------


def test_private_key_round_trips_through_its_settings_format():
    secret = SIGNING_KEY.private_key_secret()
    restored = DispatchSigningKey.from_secret(secret)
    assert restored.kid == SIGNING_KEY.kid
    assert DispatchVerifyKey.from_base64(SIGNING_KEY.public_key_b64).kid == SIGNING_KEY.kid
    assert compute_kid(b64decode(SIGNING_KEY.public_key_b64)) == SIGNING_KEY.kid


@pytest.mark.parametrize("value", ["!!!not-base64!!!", "AAAA", "A" * 60])
def test_malformed_keys_are_refused_without_echoing_the_value(value: str):
    with pytest.raises(ConfigurationError) as private_error:
        DispatchSigningKey.from_secret(SecretStr(value))
    with pytest.raises(ConfigurationError) as public_error:
        DispatchVerifyKey.from_base64(value)
    assert value not in str(private_error.value)
    assert "WORKER_DISPATCH_SIGNING_PRIVATE_KEY" in str(private_error.value)
    assert "WORKER_DISPATCH_VERIFY_KEY" in str(public_error.value)


def test_reprs_never_render_key_material():
    private_b64 = SIGNING_KEY.private_key_secret().get_secret_value()
    assert private_b64 not in repr(SIGNING_KEY)
    assert SIGNING_KEY.kid in repr(SIGNING_KEY)
    assert VERIFY_KEY.kid in repr(VERIFY_KEY)
