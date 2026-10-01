"""Tests for ADR 0015's gate (b): the signed dispatch assignment artifact.

Mirrors `tests/core/test_auth.py`'s session-token tests closely — same HMAC
construction, same failure modes (tampering, wrong secret, expiry,
malformed input) — plus this artifact's own extra binding requirement:
`worker_id`/`org_id` must match the *verifying* worker exactly, which a
session token has no equivalent of.
"""

from __future__ import annotations

import inspect
import time

import pytest
from pydantic import SecretStr
from src.core.worker_dispatch_schemas import DispatchAssignmentClaims, WorkerJobKind
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


# --- Every declared claim must actually be minted -------------------------------
#
# Cycle 0119. `url_list_sha256` was added to `DispatchAssignmentClaims` and
# threaded through every model in the dispatch chain, but
# `issue_dispatch_assignment` — the only code that mints claims — was never
# changed, so the field took its `None` default on every single mint. Nothing
# failed: the worker's `if claims.url_list_sha256 is not None:` was simply
# always False, `prepare_url_list` never ran, and an approved `--crawl-list`
# dispatch silently ran as an ordinary link-following crawl of the seed URL.
#
# The three tests below are deliberately about the *shape* of the minting
# function rather than about that one field, because the defect was not really
# about that one field: it was that a claim can be declared on the model and
# forgotten in the mint with nothing anywhere noticing. A test written only for
# `url_list_sha256` would leave the next field just as exposed.

_DERIVED_CLAIM_FIELDS = frozenset({"jti", "issued_at", "expires_at"})
"""Claims `issue_dispatch_assignment` mints for itself.

`jti` is a fresh nonce and the two timestamps come from the clock and `ttl_s`,
so these three are the only claims that legitimately have no caller-supplied
parameter behind them. Anything else appearing here later would mean a field
the cloud cannot bind — which is the question this allow-list exists to force
someone to answer rather than to silence.
"""

_NON_CLAIM_PARAMS = frozenset({"secret", "signing_key", "ttl_s"})
"""Mint parameters that configure the signing rather than land in the claims."""

_PROBE: dict[str, object] = {
    "job_id": "job-probe",
    "worker_id": "wkr-probe-desktop",
    "org_id": "probe-org",
    "kind": WorkerJobKind.SCREAMING_FROG_CRAWL,
    "seed_url": "https://probe.example/start",
    "template_name": "probe-template",
    "correlation_id": "corr-probe",
    "url_list_sha256": "b" * 64,
}
"""One distinctive, non-default value per bindable claim.

Every value has to differ from the field's own declared default, or a claim
that was never populated would still compare equal to what we passed and the
round-trip test below would pass while proving nothing. That is exactly the
trap the original defect sat in, so it is asserted rather than assumed.
"""


def _mint_parameters() -> set[str]:
    return set(inspect.signature(issue_dispatch_assignment).parameters)


def test_every_claim_the_model_declares_is_a_parameter_of_the_mint():
    """The check that would have caught cycle 0119's defect at its source.

    A field added to `DispatchAssignmentClaims` that the minting function
    cannot be told about can only ever hold its default, however correctly
    every other layer carries it.
    """
    bindable = set(DispatchAssignmentClaims.model_fields) - _DERIVED_CLAIM_FIELDS
    missing = sorted(bindable - _mint_parameters())
    assert missing == [], (
        f"{missing} are claims on DispatchAssignmentClaims that "
        f"issue_dispatch_assignment has no parameter for, so they can only ever "
        f"be minted at their default value"
    )


def test_the_probe_covers_every_mint_parameter_with_a_non_default_value():
    """Guards the two tests either side of it from going quietly vacuous.

    If a new parameter is added and this probe is not extended, the round-trip
    test would never pass a value for it and its silence would mean nothing.
    """
    expected = _mint_parameters() - _NON_CLAIM_PARAMS
    assert set(_PROBE) == expected, (
        "add the new mint parameter to _PROBE with a value that is not its default"
    )
    for name, value in _PROBE.items():
        assert value != DispatchAssignmentClaims.model_fields[name].get_default(), (
            f"_PROBE[{name!r}] is the field's own default, so it cannot distinguish "
            f"a populated claim from a forgotten one"
        )


def test_minting_populates_every_bindable_claim_verbatim():
    """Mint through the real function, verify through the real one, field by field.

    Deliberately not a hand-built `DispatchAssignmentClaims`: constructing the
    claims in the test would test the consumer and silently assume the producer,
    which is precisely how the `url_list_sha256` defect survived a suite that
    already covered both ends of the path around it.
    """
    signed = issue_dispatch_assignment(secret=SECRET, ttl_s=300.0, **_PROBE)  # type: ignore[arg-type]

    claims = verify_dispatch_assignment(
        signed.token, secret=SECRET, worker_id="wkr-probe-desktop", org_id="probe-org"
    )

    dropped = {
        name: getattr(claims, name)
        for name, value in _PROBE.items()
        if getattr(claims, name) != value
    }
    assert dropped == {}, f"issue_dispatch_assignment did not carry these claims through: {dropped}"
