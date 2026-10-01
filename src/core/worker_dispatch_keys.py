"""Ed25519 keys that sign and verify ADR 0015 gate (b) dispatch claims (ADR 0028).

Why asymmetric
--------------
Gate (b) originally used one HMAC key held by the cloud *and* by every worker.
Verifying with a shared symmetric key means every verifier can also sign, so
anyone holding any worker's `.env.local` could mint a valid claim for any
worker, org, seed URL or template — gate (b) collapsed to "whoever has a copy
of the config". With Ed25519 the cloud alone holds the private key; a worker
holds only the public key, which can verify a claim and can never produce one.
Leaking a worker's configuration therefore no longer leaks signing authority.

Key encoding
------------
Both keys travel as **standard base64 of the 32 raw key bytes** (RFC 8032
encoding, no PEM/DER wrapper): short enough to paste into a Railway variable
or a `.env.local` line, and unambiguous to validate — anything that does not
decode to exactly 32 bytes is refused at boot.

Key id (`kid`)
--------------
The first 16 hex characters of the SHA-256 of the raw public key. Derived,
not configured, so it cannot drift from the key it names. It travels inside
the *signed* protected header, which is what lets a later rotation run two
keys side by side: a worker rejects any `kid` it does not hold rather than
trying keys until one fits.

Error messages here name the setting, never its value — a malformed private
key must not end up in a log line or a pydantic error repr.
"""

from __future__ import annotations

import binascii
import hashlib
from base64 import b64decode, b64encode

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from pydantic import SecretStr

from src.core.errors import ConfigurationError

__all__ = [
    "ED25519_RAW_KEY_BYTES",
    "PRIVATE_KEY_ENV",
    "VERIFY_KEY_ENV",
    "DispatchSigningKey",
    "DispatchVerifyKey",
    "compute_kid",
]

ED25519_RAW_KEY_BYTES = 32
_KID_HEX_CHARS = 16

PRIVATE_KEY_ENV = "WORKER_DISPATCH_SIGNING_PRIVATE_KEY"
VERIFY_KEY_ENV = "WORKER_DISPATCH_VERIFY_KEY"


def compute_kid(public_key_raw: bytes) -> str:
    """Derive the key id a public key is published and checked under."""
    return hashlib.sha256(public_key_raw).hexdigest()[:_KID_HEX_CHARS]


def _decode_raw_key(value: str, *, setting_name: str) -> bytes:
    """Decode a base64 raw key, refusing anything that is not exactly 32 bytes.

    Raises:
        ConfigurationError: Naming `setting_name` only — never the value.
    """
    try:
        raw = b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        msg = f"{setting_name} is not valid base64 (expected the 32 raw Ed25519 key bytes)."
        raise ConfigurationError(msg) from exc
    if len(raw) != ED25519_RAW_KEY_BYTES:
        msg = (
            f"{setting_name} must decode to exactly {ED25519_RAW_KEY_BYTES} bytes "
            f"(a raw Ed25519 key); it decoded to {len(raw)}."
        )
        raise ConfigurationError(msg)
    return raw


class DispatchVerifyKey:
    """A worker's public verification key and the `kid` it answers to."""

    __slots__ = ("_key", "kid", "public_key_b64")

    def __init__(self, public_key: Ed25519PublicKey) -> None:
        """Wrap an already-parsed public key; prefer `from_base64`."""
        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        self._key = public_key
        self.kid = compute_kid(raw)
        self.public_key_b64 = b64encode(raw).decode("ascii")

    @classmethod
    def from_base64(cls, value: str, *, setting_name: str = VERIFY_KEY_ENV) -> DispatchVerifyKey:
        """Parse the `WORKER_DISPATCH_VERIFY_KEY` format.

        Raises:
            ConfigurationError: The value is not base64 of 32 raw bytes.
        """
        raw = _decode_raw_key(value, setting_name=setting_name)
        return cls(Ed25519PublicKey.from_public_bytes(raw))

    def verify(self, signature: bytes, data: bytes) -> bool:
        """Return whether `signature` is this key's signature over `data`."""
        try:
            self._key.verify(signature, data)
        except InvalidSignature:
            return False
        return True

    def __repr__(self) -> str:
        """Identify the key by `kid`; the key bytes are public but noisy."""
        return f"DispatchVerifyKey(kid={self.kid!r})"


class DispatchSigningKey:
    """The cloud's private signing key. Only the cloud API process holds one."""

    __slots__ = ("_key", "verify_key")

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        """Wrap an already-parsed private key; prefer `from_secret`/`generate`."""
        self._key = private_key
        self.verify_key = DispatchVerifyKey(private_key.public_key())

    @classmethod
    def from_secret(
        cls, value: SecretStr, *, setting_name: str = PRIVATE_KEY_ENV
    ) -> DispatchSigningKey:
        """Parse the `WORKER_DISPATCH_SIGNING_PRIVATE_KEY` format.

        Raises:
            ConfigurationError: The value is not base64 of 32 raw bytes.
        """
        raw = _decode_raw_key(value.get_secret_value(), setting_name=setting_name)
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    @classmethod
    def generate(cls) -> DispatchSigningKey:
        """A fresh random key — for `generate_dispatch_keypair.py` and non-production boots."""
        return cls(Ed25519PrivateKey.generate())

    @property
    def kid(self) -> str:
        """The key id of this key's public half."""
        return self.verify_key.kid

    @property
    def public_key_b64(self) -> str:
        """The public half, in the `WORKER_DISPATCH_VERIFY_KEY` format."""
        return self.verify_key.public_key_b64

    def private_key_secret(self) -> SecretStr:
        """The private half in the `WORKER_DISPATCH_SIGNING_PRIVATE_KEY` format.

        Returned as `SecretStr` so the only way to see it is an explicit
        `get_secret_value()` — which only the keypair generator script does.
        """
        raw = self._key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        return SecretStr(b64encode(raw).decode("ascii"))

    def sign(self, data: bytes) -> bytes:
        """Sign `data` with the private key."""
        return self._key.sign(data)

    def __repr__(self) -> str:
        """Never render key material — only the public `kid`."""
        return f"DispatchSigningKey(kid={self.kid!r})"
