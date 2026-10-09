"""At-rest encryption for org GSC credentials held in Postgres (ADR 0036).

A refresh token reads a client's Search Console for as long as Google honours
it, so the cloud copy is ciphertext: a database dump, a backup, or a stray
`SELECT *` yields nothing usable without the server's key.

Design stance:

* **AES-256-GCM from `cryptography`, not the stdlib construction in
  `worker_bundle_crypto`.** That module's own docstring names `AESGCM` as its
  replacement once the dependency was justified; `cryptography` now is one
  (`worker_dispatch_keys`), so new code starts on the vetted AEAD.
* **A fresh 12-byte nonce per encryption** from `os.urandom`. The stored blob
  is `nonce || ciphertext+tag`.
* **Everything that identifies a value is bound as AAD**: a version label, the
  key id, the org, the account name and which field it is. A ciphertext
  copied onto another org's row, another account, or the other column fails
  authentication rather than decrypting into the wrong place.
* **Key selection by key id, not trial decryption.** Each row records the id
  of the key that wrote it, so a read uses exactly one key: the current one or
  the previous one during a rotation. A row naming neither is reported as
  "re-add this account" rather than tried against every key.
* **Nothing secret leaves this module in an exception or a repr.** Failures are
  `GscCredentialDecryptionError(account_name)`, raised `from None` so no
  chained exception carries bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from src.core.errors import ConfigurationError, GscCredentialDecryptionError

__all__ = [
    "CredentialField",
    "GscCredentialCipher",
    "key_id_for",
    "parse_credential_key",
]

CredentialField = Literal["refresh_token", "client_secret"]
"""The two encrypted columns. Bound into the AAD, so they cannot be swapped."""

_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_AAD_LABEL = b"rankuno-gsc-cred-v1"
_KEY_ID_LABEL = b"rankuno-gsc-cred-key-id-v1"


def parse_credential_key(secret: SecretStr, *, var_name: str) -> bytes:
    """Decode a base64url key that must hold exactly 32 bytes.

    Padding is optional, so a key copied with or without its trailing `=`
    both work. The error names the variable and never the value.

    Args:
        secret: The configured value.
        var_name: Environment variable name, for the error message.

    Returns:
        The 32 raw key bytes.

    Raises:
        ConfigurationError: Not base64url, or not exactly 32 bytes.
    """
    raw = secret.get_secret_value().strip()
    msg = (
        f"{var_name} must be base64url of exactly {_KEY_BYTES} bytes "
        "(see docs/adr/0036 for how to generate one)."
    )
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        raise ConfigurationError(msg) from None
    if len(decoded) != _KEY_BYTES:
        raise ConfigurationError(msg)
    return decoded


def key_id_for(key: bytes) -> str:
    """The short public identifier stored beside each ciphertext.

    An HMAC of a fixed label, so it reveals nothing about the key and two keys
    collide only with probability 2^-32 — acceptable for choosing between at
    most two configured keys.
    """
    return hmac.new(key, _KEY_ID_LABEL, hashlib.sha256).hexdigest()[:8]


def _aad(key_id: str, org_id: str, account_name: str, field: CredentialField) -> bytes:
    """Associated data binding a ciphertext to exactly one (key, org, account, field)."""
    return b"|".join(
        (
            _AAD_LABEL,
            key_id.encode("ascii"),
            org_id.encode("utf-8"),
            account_name.encode("utf-8"),
            field.encode("ascii"),
        )
    )


class GscCredentialCipher:
    """Encrypts with the current key; decrypts with whichever key wrote the row."""

    __slots__ = ("_keys", "key_id")

    def __init__(self, current: bytes, previous: bytes | None = None) -> None:
        """Hold the current key and, during a rotation, the previous one.

        Args:
            current: 32-byte key every new write uses.
            previous: 32-byte key rows written before a rotation still use.

        Raises:
            ConfigurationError: A key is not 32 bytes, or both keys are the same.
        """
        for key in (current, previous):
            if key is not None and len(key) != _KEY_BYTES:
                msg = f"GSC credential keys must be exactly {_KEY_BYTES} bytes."
                raise ConfigurationError(msg)
        self.key_id = key_id_for(current)
        self._keys: dict[str, bytes] = {self.key_id: current}
        if previous is not None:
            previous_id = key_id_for(previous)
            if previous_id == self.key_id:
                msg = (
                    "GSC_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS must differ from "
                    "GSC_CREDENTIAL_ENCRYPTION_KEY."
                )
                raise ConfigurationError(msg)
            self._keys[previous_id] = previous

    def __repr__(self) -> str:
        """Key ids only; the key bytes never appear in a repr or a log."""
        return f"GscCredentialCipher(key_ids={sorted(self._keys)})"

    def encrypt(
        self, plaintext: str, *, org_id: str, account_name: str, field: CredentialField
    ) -> bytes:
        """Encrypt one credential field under the current key.

        Returns:
            `nonce || ciphertext+tag`, to store beside `self.key_id`.
        """
        nonce = os.urandom(_NONCE_BYTES)
        aad = _aad(self.key_id, org_id, account_name, field)
        return nonce + AESGCM(self._keys[self.key_id]).encrypt(
            nonce, plaintext.encode("utf-8"), aad
        )

    def decrypt(
        self,
        blob: bytes,
        *,
        key_id: str,
        org_id: str,
        account_name: str,
        field: CredentialField,
    ) -> str:
        """Decrypt one credential field written under `key_id`.

        Raises:
            GscCredentialDecryptionError: The key is not held, the blob is
                malformed or tampered with, or it belongs to another org,
                account or field.
        """
        key = self._keys.get(key_id)
        if key is None or len(blob) < _NONCE_BYTES + _TAG_BYTES:
            raise GscCredentialDecryptionError(account_name)
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        try:
            plaintext = AESGCM(key).decrypt(nonce, body, _aad(key_id, org_id, account_name, field))
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            raise GscCredentialDecryptionError(account_name) from None
