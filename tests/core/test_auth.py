"""Tests for ADR 0016's identity and session-token primitives.

Deliberately no FastAPI here — `src/core/auth.py` has none either, so these
tests exercise the token and password machinery entirely on its own terms:
signature verification, expiry, malformed input, and the disk-backed
operator store. `tests/api/test_auth.py` covers the HTTP-layer glue that
turns these into `401`s.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64encode

import pytest
from pydantic import SecretStr, ValidationError
from src.core.auth import (
    AuthenticationError,
    DiskOperatorStore,
    Operator,
    OperatorNotFoundError,
    Principal,
    _b64url_encode,
    hash_password,
    issue_session_token,
    verify_password,
    verify_session_token,
)

SECRET = SecretStr("unit-test-signing-key")
OTHER_SECRET = SecretStr("a-different-signing-key")


def _operator(**overrides: object) -> Operator:
    base: dict[str, object] = {
        "operator_id": "alice",
        "org_id": "acme",
        "display_name": "Alice",
        "password_hash": hash_password("correct horse battery staple"),
    }
    base.update(overrides)
    return Operator(**base)


# --- Password hashing --------------------------------------------------------


def test_hash_password_accepts_the_correct_password():
    digest = hash_password("s3cret!")
    assert verify_password("s3cret!", digest) is True


def test_hash_password_rejects_the_wrong_password():
    digest = hash_password("s3cret!")
    assert verify_password("wrong", digest) is False


def test_hash_password_uses_a_fresh_salt_each_time():
    """Two hashes of the same password must not be byte-identical."""
    assert hash_password("s3cret!") != hash_password("s3cret!")


def test_verify_password_fails_closed_on_a_corrupt_hash():
    """A malformed stored hash must refuse, never raise."""
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "pbkdf2_sha256$not-an-int$ab$cd") is False


# --- Session tokens -----------------------------------------------------------


def test_issue_and_verify_round_trips():
    operator = _operator()
    session = issue_session_token(operator, secret=SECRET, ttl_s=3600)
    principal = verify_session_token(session.token, secret=SECRET)
    assert principal == Principal(operator_id="alice", org_id="acme")


def test_verify_rejects_a_token_signed_with_a_different_secret():
    operator = _operator()
    session = issue_session_token(operator, secret=SECRET, ttl_s=3600)
    with pytest.raises(AuthenticationError):
        verify_session_token(session.token, secret=OTHER_SECRET)


def test_verify_rejects_an_expired_token():
    operator = _operator()
    session = issue_session_token(operator, secret=SECRET, ttl_s=-1)
    with pytest.raises(AuthenticationError):
        verify_session_token(session.token, secret=SECRET)


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "not.a.token.at.all",
        "onlyonepart",
        "two.parts",
        "not-base64.also-not-base64.still-not",
    ],
)
def test_verify_rejects_malformed_tokens(malformed: str):
    with pytest.raises(AuthenticationError):
        verify_session_token(malformed, secret=SECRET)


def test_verify_rejects_a_tampered_payload():
    """Flipping the org_id claim without re-signing must fail the signature check.

    The exploit this closes: without this, a caller could self-escalate to
    another organization by editing a token's claims client-side.
    """
    operator = _operator()
    session = issue_session_token(operator, secret=SECRET, ttl_s=3600)
    header_b64, payload_b64, signature_b64 = session.token.split(".")

    tampered_payload = json.dumps(
        {"sub": "alice", "org_id": "someone-elses-org", "exp": 9999999999}
    )
    tampered_b64 = urlsafe_b64encode(tampered_payload.encode()).rstrip(b"=").decode("ascii")

    forged_token = f"{header_b64}.{tampered_b64}.{signature_b64}"
    with pytest.raises(AuthenticationError):
        verify_session_token(forged_token, secret=SECRET)


def test_verify_rejects_a_syntactically_invalid_org_id_claim():
    """A forged token naming an org_id `Principal` itself would reject.

    Signed with the real secret via the private encoding this module uses
    internally, so the *signature* passes — only the claim's shape is bad.
    This is the negative case `tests/api/test_multi_org.py`'s
    `test_malformed_org_ids_cannot_even_authenticate` defers to this file.
    """
    header = {"alg": "HS256", "typ": "RANKUNO-SESSION"}
    payload = {
        "sub": "alice",
        "org_id": "Not Valid!",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    signing_input = (
        f"{_b64url_encode(json.dumps(header).encode())}."
        f"{_b64url_encode(json.dumps(payload).encode())}"
    )
    signature = hmac.new(
        SECRET.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    token = f"{signing_input}.{_b64url_encode(signature)}"

    with pytest.raises(AuthenticationError):
        verify_session_token(token, secret=SECRET)


def _sign(header_bytes: bytes, payload_bytes: bytes) -> str:
    """A correctly-signed token around arbitrary header/payload bytes.

    Lets a test put something genuinely malformed (not valid JSON, or valid
    JSON that is not an object) behind a signature that passes, so the test
    reaches `verify_session_token`'s payload-parsing branches rather than
    failing earlier at the signature check.
    """
    signing_input = f"{_b64url_encode(header_bytes)}.{_b64url_encode(payload_bytes)}"
    signature = hmac.new(
        SECRET.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def test_verify_rejects_a_payload_that_is_not_valid_json():
    header = json.dumps({"alg": "HS256", "typ": "RANKUNO-SESSION"}).encode()
    token = _sign(header, b"not valid json at all{{{")
    with pytest.raises(AuthenticationError):
        verify_session_token(token, secret=SECRET)


def test_verify_rejects_a_payload_that_is_valid_json_but_not_an_object():
    header = json.dumps({"alg": "HS256", "typ": "RANKUNO-SESSION"}).encode()
    token = _sign(header, json.dumps(["not", "an", "object"]).encode())
    with pytest.raises(AuthenticationError):
        verify_session_token(token, secret=SECRET)


def test_operator_and_principal_share_the_same_org_id_pattern():
    """Both reject the same shapes `OrgConfig.org_id` already refuses."""
    for bad in ("Org_A", "org a", "org@a", "a" * 65, ""):
        with pytest.raises(ValidationError):
            Principal(operator_id="alice", org_id=bad)


# --- DiskOperatorStore --------------------------------------------------------


def test_disk_operator_store_round_trips(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    operator = _operator()
    store.create(operator)

    fetched = store.get("alice")
    assert fetched.org_id == "acme"
    assert fetched.password_hash == operator.password_hash


def test_disk_operator_store_get_unknown_raises(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    with pytest.raises(OperatorNotFoundError):
        store.get("nobody")


def test_disk_operator_store_create_duplicate_raises(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(_operator())
    with pytest.raises(ValueError, match="already exists"):
        store.create(_operator())


def test_disk_operator_store_list_operators_is_sorted(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(_operator(operator_id="zeta", org_id="acme"))
    store.create(_operator(operator_id="alpha", org_id="acme"))

    ids = [op.operator_id for op in store.list_operators()]
    assert ids == ["alpha", "zeta"]


def test_disk_operator_store_persists_across_instances(tmp_path):
    """A second store over the same directory must see what the first wrote."""
    root = tmp_path / "operators"
    DiskOperatorStore(root).create(_operator())

    reopened = DiskOperatorStore(root)
    assert reopened.get("alice").org_id == "acme"


def test_disk_operator_store_survives_a_corrupt_file(tmp_path):
    """A malformed operators.json degrades to empty, never crashes the server."""
    root = tmp_path / "operators"
    root.mkdir()
    (root / "operators.json").write_text("not valid json{{{", encoding="utf-8")

    store = DiskOperatorStore(root)
    assert store.list_operators() == []


def test_disk_operator_store_never_writes_a_plaintext_password(tmp_path):
    """The stored file must hold a hash, never anything resembling the input."""
    root = tmp_path / "operators"
    store = DiskOperatorStore(root)
    store.create(_operator(password_hash=hash_password("correct horse battery staple")))

    raw = (root / "operators.json").read_text(encoding="utf-8")
    assert "correct horse battery staple" not in raw
    assert "pbkdf2_sha256$" in raw
