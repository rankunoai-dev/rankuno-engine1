"""Operator identity and session-token issuance (ADR 0016).

Domain-agnostic, deliberately — no FastAPI, no `src/api` import, so this
module is unit-testable without an HTTP layer and stays on the `core` side of
CLAUDE.md's inward-only boundary. `src/api/auth.py` is the thin HTTP glue that
turns the exceptions raised here into responses.

No caller identity concept existed anywhere in this codebase before this ADR
(build-log for ADR 0016, Context item 5): `OrgConfig.org_id` names a *tenant*,
not a person who can log in. `Operator` is that first identity, and
`Principal` is what a verified request carries once a token has been checked
— the two are kept separate on purpose, because a `Principal` must never be
constructed from anything except a verified signature (ADR 0016 condition 4),
while an `Operator` is a stored record a login looks up.

Token format
------------
A self-contained, HMAC-SHA256-signed, JWT-shaped bearer token
(`header.payload.signature`, base64url, `HS256`) built from the standard
library rather than a JWT dependency. ADR 0016 condition 6 prefers a format
that costs nothing but a local signature check to verify — no per-request
network call, and therefore no new circuit-breaker surface this codebase does
not already have. Building it by hand keeps that preference from being
undercut by a dependency added for one HMAC compare; any standard JWT library
can still decode a token this module issues, because the wire shape is the
same one that library expects.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import Field, SecretStr, ValidationError

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.schemas import StrictModel

__all__ = [
    "AuthenticationError",
    "DiskOperatorStore",
    "Operator",
    "OperatorNotFoundError",
    "OperatorStore",
    "Principal",
    "SessionToken",
    "hash_password",
    "issue_session_token",
    "verify_password",
    "verify_session_token",
]

_logger = get_logger("core.auth")

_IDENTIFIER_PATTERN = r"^[a-z0-9_-]{1,64}$"
"""Shared by `operator_id` and `org_id`: the same rule `OrgConfig.org_id` and
the GSC account-name fields already use, so nothing new to remember."""

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 210_000
"""OWASP's 2023 minimum for PBKDF2-HMAC-SHA256. A one-time cost at login, not
a per-request one (unlike the token check below), so this is a security
choice, not a latency budget."""

_SALT_BYTES = 16

_TOKEN_ALG = "HS256"  # noqa: S105 - a JWT header algorithm name, not a credential
_TOKEN_TYP = "RANKUNO-SESSION"  # noqa: S105 - a JWT header type label, not a credential


class AuthenticationError(RankunoError):
    """A credential or session token failed verification.

    One exception for every failure mode — unknown operator, wrong password,
    malformed token, bad signature, expired token — on purpose: the HTTP layer
    answers all of them with the same generic 401. A distinct exception per
    cause is exactly the detail an attacker would use to tell "no such
    operator" from "wrong password" apart, which is a username-enumeration
    oracle by another name.
    """


class OperatorNotFoundError(KeyError):
    """No such operator exists in the store.

    A `KeyError` subclass, matching `OrgConfigStore.get`'s own contract
    (`src/core/state_store.py`) rather than inventing a second shape for the
    same kind of lookup failure.
    """


class Principal(StrictModel):
    """The verified identity behind one authenticated request.

    Built only by `verify_session_token`. Never accept one from a request
    body or query string — that would recreate exactly the "client asserts
    its own identity" hole ADR 0016 exists to close. `org_id` here is what
    condition 4 calls "a value derived from the verified principal": every
    route that used to trust an `X-Org-Id` header reads this instead.
    """

    operator_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)


class Operator(StrictModel):
    """One human who may log in to this server.

    One operator belongs to exactly one org. Phase 1 has no notion of an
    operator acting for several organizations — ADR 0016's Open Questions
    leave the exact `org_id`-derivation shape to implementation, and a single
    claim is the simplest one that satisfies condition 4; widening it to a
    set is a schema change if it is ever needed, not a migration.
    """

    operator_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    display_name: str = Field(min_length=1, max_length=200)
    password_hash: str = Field(min_length=1)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionToken(StrictModel):
    """What `issue_session_token` returns: a bearer token and its expiry."""

    token: str
    expires_at: datetime


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 a password behind a fresh random salt.

    Returns:
        `pbkdf2_sha256$<iterations>$<salt-hex>$<digest-hex>` — the iteration
        count travels with the hash so a future increase does not invalidate
        every stored password, matching how Django and passlib both do this.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_{_PBKDF2_ALGORITHM}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-compare a password against a stored hash.

    Never raises on a malformed hash. A corrupt store entry must fail closed
    — return `False` — rather than crash the login route and turn one bad
    record into an outage for every operator.
    """
    try:
        algorithm_part, iterations_s, salt_hex, digest_hex = password_hash.split("$")
        iterations = int(iterations_s)
        algorithm = algorithm_part.removeprefix("pbkdf2_")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def _b64url_encode(payload: bytes) -> str:
    return urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def issue_session_token(operator: Operator, *, secret: SecretStr, ttl_s: int) -> SessionToken:
    """Mint a signed, self-contained bearer token for one operator's session.

    Args:
        operator: Whose session this is. `org_id` becomes the claim every
            downstream route will trust.
        secret: Signing key. Never logged, never echoed back.
        ttl_s: Seconds until the token expires. Short-lived by ADR 0016
            condition 5(a) — the server's caller sets this from
            `Settings.auth_session_ttl_s`.

    Returns:
        The bearer token and its absolute expiry.
    """
    issued_at = time.time()
    expires_at = issued_at + ttl_s
    header = {"alg": _TOKEN_ALG, "typ": _TOKEN_TYP}
    payload = {
        "sub": operator.operator_id,
        "org_id": operator.org_id,
        "iat": int(issued_at),
        "exp": int(expires_at),
    }
    signing_input = (
        f"{_b64url_encode(json.dumps(header).encode())}."
        f"{_b64url_encode(json.dumps(payload).encode())}"
    )
    signature = hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    token = f"{signing_input}.{_b64url_encode(signature)}"
    return SessionToken(token=token, expires_at=datetime.fromtimestamp(expires_at, tz=UTC))


def verify_session_token(token: str, *, secret: SecretStr) -> Principal:
    """Verify a bearer token's signature and expiry, and return its principal.

    Self-contained by design (ADR 0016 condition 6): this touches only the
    signing key already held in this process, never the operator store and
    never the network, so authenticating a request adds no I/O to it.

    Raises:
        AuthenticationError: If the token is malformed, the signature does
            not match, it has expired, or its claims fail `Principal`'s own
            validation.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError("malformed session token")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected_signature = hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        actual_signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise AuthenticationError("malformed session token signature") from exc
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise AuthenticationError("session token signature does not match")

    try:
        claims = json.loads(_b64url_decode(parts[1]))
    except Exception as exc:
        raise AuthenticationError("malformed session token payload") from exc
    if not isinstance(claims, dict):
        raise AuthenticationError("malformed session token payload")

    expiry = claims.get("exp")
    if not isinstance(expiry, int | float) or expiry < time.time():
        raise AuthenticationError("session token expired")

    try:
        return Principal(
            operator_id=str(claims.get("sub", "")), org_id=str(claims.get("org_id", ""))
        )
    except ValidationError as exc:
        raise AuthenticationError("session token claims are invalid") from exc


class OperatorStore(Protocol):
    """The persistence seam for operator identity.

    A Protocol, matching `OrgConfigStore` and `JobStore`
    (`src/core/state_store.py`), so a hosted deployment can swap in a shared
    implementation without the API layer changing.
    """

    def create(self, operator: Operator) -> Operator:
        """Persist a new operator.

        Raises:
            ValueError: If the operator id is already taken.
        """
        ...

    def get(self, operator_id: str) -> Operator:
        """Read one operator.

        Raises:
            OperatorNotFoundError: If no such operator exists.
        """
        ...

    def list_operators(self) -> list[Operator]:
        """Every operator, sorted by id."""
        ...


def _atomic_write(path: Path, payload: str) -> None:
    """Write `payload` to `path` so a crash cannot leave it half-written.

    The same pattern `state_store.py`'s `_atomic_write` uses, duplicated
    rather than imported: that function is module-private there, and this
    module must stay importable without dragging in the job-store machinery
    for one helper.
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


class DiskOperatorStore:
    """An `OperatorStore` backed by a single JSON file.

    Single-process only, the same limitation `DiskOrgConfigStore` and
    `DiskJobStore` carry (ADR 0004): writes go through `os.replace` for
    atomicity, but two servers sharing a directory would interleave them.
    Never seeds a default operator the way `DiskOrgConfigStore` seeds a
    default org — there is no safe default password, so an empty store stays
    empty until `create()` is called (see `scripts/create_operator.py`).
    """

    def __init__(self, root: Path | str) -> None:
        """Create the store, making its directory if absent.

        Args:
            root: Directory to hold `operators.json`.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "operators.json"
        self._lock = threading.Lock()
        self._operators: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _logger.warning("operator_store_load_failed", extra={"error": str(exc)})
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _save(self) -> None:
        payload = json.dumps(self._operators, indent=2, sort_keys=True)
        _atomic_write(self._path, payload)

    def create(self, operator: Operator) -> Operator:
        """Persist a new operator.

        Raises:
            ValueError: If the operator id is already taken.
        """
        with self._lock:
            if operator.operator_id in self._operators:
                msg = f"Operator '{operator.operator_id}' already exists"
                raise ValueError(msg)
            self._operators[operator.operator_id] = json.loads(operator.model_dump_json())
            self._save()
        _logger.info(
            "operator_created",
            extra={"operator_id": operator.operator_id, "org": operator.org_id},
        )
        return operator

    def get(self, operator_id: str) -> Operator:
        """Read one operator.

        Raises:
            OperatorNotFoundError: If no such operator exists.
        """
        with self._lock:
            data = self._operators.get(operator_id)
        if data is None:
            msg = f"Operator '{operator_id}' not found"
            raise OperatorNotFoundError(msg)
        return Operator.model_validate(data)

    def list_operators(self) -> list[Operator]:
        """Every operator, sorted by id."""
        with self._lock:
            values = list(self._operators.values())
        return sorted((Operator.model_validate(v) for v in values), key=lambda o: o.operator_id)
