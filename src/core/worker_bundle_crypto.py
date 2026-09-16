"""At-rest encryption for uploaded Screaming Frog bundles (ADR 0015 condition 11).

Crawled page content flows off the operator's desktop for the first time
under this ADR. Condition 11 requires the implementation to actually use
at-rest encryption in whatever storage holds an uploaded bundle, not merely
describe one. `postgres_worker_dispatch_store`'s upload table stores the
output of `encrypt_bytes` below, never a plaintext blob.

Why hand-rolled, stdlib-only HMAC-SHA256, not a vetted AEAD library
---------------------------------------------------------------------
This project's dependency surface is deliberately minimal (`pyproject.toml`'s
own comment: "the core layer must stay importable without any domain/vendor
SDK installed"), and `cryptography`/`pynacl` are not already a dependency
anywhere in this codebase. Adding one is out of scope for this cycle's
smallest-safe-change discipline (CLAUDE.md "Scope discipline"). This module
is the documented trade that follows from that constraint, not a claim that
hand-rolled crypto is generally preferable to a vetted library — it is not,
and replacing this with `cryptography`'s `AESGCM`/`Fernet` is named as
follow-up work the moment that dependency is justified for some other
reason too.

Construction (encrypt-then-MAC, both halves keyed by HMAC-SHA256, a proven
PRF under a standard hardness assumption):

1. Derive two independent 32-byte subkeys from the caller's secret via
   `HMAC(secret, b"enc")` and `HMAC(secret, b"mac")` — never reusing one key
   for both roles, which is what would make an encrypt-then-MAC composition
   unsound.
2. A random 16-byte nonce seeds a keystream: block `i` is
   `HMAC(enc_key, nonce || i.to_bytes(8))`, concatenated until it covers the
   plaintext, then XORed against it — the same "HMAC as a keyed PRF, used to
   build a stream cipher" construction a counter-mode DRBG uses.
3. The output is `nonce || ciphertext || HMAC(mac_key, nonce || ciphertext)`.
   `decrypt_bytes` recomputes and constant-time-compares the tag before
   touching the ciphertext, so a tampered blob is refused rather than
   silently decrypted into garbage.

This gives confidentiality and integrity against a static-key threat model.
It does **not** replace disk/volume-level encryption at the storage layer,
which remains an infrastructure decision ADR 0015 condition 13 explicitly
scopes out of this document.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from pydantic import SecretStr

from src.core.errors import RankunoError

__all__ = ["BundleDecryptionError", "decrypt_bytes", "encrypt_bytes"]

_NONCE_BYTES = 16
_TAG_BYTES = 32
_BLOCK_BYTES = 32


class BundleDecryptionError(RankunoError):
    """An encrypted bundle failed to authenticate. Never decoded further."""


def _subkeys(secret: SecretStr) -> tuple[bytes, bytes]:
    """Independent encryption and MAC subkeys, never the same bytes twice."""
    raw = secret.get_secret_value().encode("utf-8")
    enc_key = hmac.new(raw, b"rankuno-bundle-enc", hashlib.sha256).digest()
    mac_key = hmac.new(raw, b"rankuno-bundle-mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """HMAC-SHA256 counter-mode keystream, long enough to cover `length` bytes."""
    blocks = []
    counter = 0
    produced = 0
    while produced < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        blocks.append(block)
        produced += _BLOCK_BYTES
        counter += 1
    return b"".join(blocks)[:length]


def _xor(data: bytes, keystream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, keystream, strict=True))


def encrypt_bytes(data: bytes, *, secret: SecretStr) -> bytes:
    """Encrypt-then-MAC `data` under `secret`.

    Args:
        data: Plaintext bytes (the validated, rebuilt upload archive).
        secret: The shared at-rest encryption key, read via `get_settings()`
            by the caller — never a raw `os.environ` read here.

    Returns:
        `nonce || ciphertext || tag`, safe to store as-is.
    """
    enc_key, mac_key = _subkeys(secret)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = _xor(data, _keystream(enc_key, nonce, len(data)))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    return nonce + ciphertext + tag


def decrypt_bytes(blob: bytes, *, secret: SecretStr) -> bytes:
    """Verify and decrypt a blob produced by `encrypt_bytes`.

    Args:
        blob: `nonce || ciphertext || tag`.
        secret: The same secret `encrypt_bytes` was called with.

    Returns:
        The original plaintext.

    Raises:
        BundleDecryptionError: The blob is too short to be well-formed, or
            the authentication tag does not match — tampering or the wrong
            key, indistinguishably, on purpose (no oracle for which).
    """
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        raise BundleDecryptionError("encrypted bundle is too short to be well-formed")

    nonce = blob[:_NONCE_BYTES]
    ciphertext = blob[_NONCE_BYTES:-_TAG_BYTES]
    tag = blob[-_TAG_BYTES:]

    enc_key, mac_key = _subkeys(secret)
    expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_tag, tag):
        raise BundleDecryptionError("encrypted bundle failed authentication")

    return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))
