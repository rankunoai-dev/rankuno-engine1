"""GA4 refresh tokens use their own AAD label, so a GSC ciphertext never decrypts as GA4 (ADR 0038).

Each test is about one way a ciphertext could be moved to the wrong place. A
GA4 token copied onto a GSC row, a GSC token copied onto a GA4 row, a GA4 token
copied to another org, and a token written under one key read under another
must all fail to decrypt, and fail with the GA4 error class carrying no value.
"""

from __future__ import annotations

import pytest
from src.core.errors import Ga4CredentialDecryptionError, GscCredentialDecryptionError
from src.core.gsc_credential_crypto import GscCredentialCipher

KEY = bytes(range(32))
OTHER_KEY = bytes(range(32, 64))
TOKEN = "1//0gGA4-CANARY-refresh-token"  # noqa: S105 - fake canary


def _cipher() -> GscCredentialCipher:
    return GscCredentialCipher(KEY)


def test_round_trip_under_the_writing_key() -> None:
    cipher = _cipher()
    blob = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    assert cipher.decrypt_ga4_refresh_token(blob, key_id=cipher.key_id, org_id="acme") == TOKEN


def test_ciphertext_is_not_plaintext_and_is_not_deterministic() -> None:
    cipher = _cipher()
    first = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    second = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    assert TOKEN.encode() not in first
    assert first != second  # a fresh nonce per write


def test_ga4_token_is_bound_to_its_org() -> None:
    cipher = _cipher()
    blob = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    with pytest.raises(Ga4CredentialDecryptionError) as info:
        cipher.decrypt_ga4_refresh_token(blob, key_id=cipher.key_id, org_id="globex")
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None  # raised `from None`


def test_ga4_ciphertext_does_not_decrypt_as_gsc() -> None:
    """A GA4 token copied onto a GSC row fails authentication (distinct AAD label)."""
    cipher = _cipher()
    blob = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    with pytest.raises(GscCredentialDecryptionError):
        cipher.decrypt(
            blob, key_id=cipher.key_id, org_id="acme", account_name="acme", field="refresh_token"
        )


def test_gsc_ciphertext_does_not_decrypt_as_ga4() -> None:
    """A GSC refresh token copied onto the GA4 row fails: the two never share a key-use."""
    cipher = _cipher()
    gsc_blob = cipher.encrypt(TOKEN, org_id="acme", account_name="acme", field="refresh_token")
    with pytest.raises(Ga4CredentialDecryptionError):
        cipher.decrypt_ga4_refresh_token(gsc_blob, key_id=cipher.key_id, org_id="acme")


def test_unknown_key_id_is_refused_without_trying_other_keys() -> None:
    cipher = _cipher()
    blob = cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    with pytest.raises(Ga4CredentialDecryptionError):
        cipher.decrypt_ga4_refresh_token(blob, key_id="ffffffff", org_id="acme")


def test_previous_key_still_reads_rows_written_before_rotation() -> None:
    old = GscCredentialCipher(OTHER_KEY)
    blob = old.encrypt_ga4_refresh_token(TOKEN, org_id="acme")
    rotated = GscCredentialCipher(KEY, previous=OTHER_KEY)
    assert rotated.decrypt_ga4_refresh_token(blob, key_id=old.key_id, org_id="acme") == TOKEN


def test_tampered_or_short_blob_is_refused() -> None:
    cipher = _cipher()
    blob = bytearray(cipher.encrypt_ga4_refresh_token(TOKEN, org_id="acme"))
    blob[-1] ^= 0x01
    with pytest.raises(Ga4CredentialDecryptionError):
        cipher.decrypt_ga4_refresh_token(bytes(blob), key_id=cipher.key_id, org_id="acme")
    with pytest.raises(Ga4CredentialDecryptionError):
        cipher.decrypt_ga4_refresh_token(b"short", key_id=cipher.key_id, org_id="acme")
