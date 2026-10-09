"""AES-256-GCM for stored GSC credentials (ADR 0036).

Each property here is one the cloud relies on: a stolen row is useless without
the key, a row cannot be moved to another org, account or column, and a
rotation keeps old rows readable while new writes use the new key. The keys
are fixed test bytes, never real keys.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import SecretStr
from src.core.errors import ConfigurationError, GscCredentialDecryptionError
from src.core.gsc_credential_crypto import (
    GscCredentialCipher,
    key_id_for,
    parse_credential_key,
)

KEY_A = bytes(range(32))
KEY_B = bytes(range(32, 64))
TOKEN = "1//0gCANARY-refresh-token-must-never-leak"  # noqa: S105 - fake canary


def _encrypt(cipher: GscCredentialCipher, **overrides: str) -> bytes:
    args = {"org_id": "org-a", "account_name": "acme", "field": "refresh_token"}
    args.update(overrides)
    return cipher.encrypt(TOKEN, **args)  # type: ignore[arg-type]


def _decrypt(cipher: GscCredentialCipher, blob: bytes, **overrides: str) -> str:
    args = {
        "key_id": cipher.key_id,
        "org_id": "org-a",
        "account_name": "acme",
        "field": "refresh_token",
    }
    args.update(overrides)
    return cipher.decrypt(blob, **args)  # type: ignore[arg-type]


class TestRoundTrip:
    def test_round_trip(self) -> None:
        cipher = GscCredentialCipher(KEY_A)
        assert _decrypt(cipher, _encrypt(cipher)) == TOKEN

    def test_ciphertext_does_not_contain_the_plaintext(self) -> None:
        cipher = GscCredentialCipher(KEY_A)
        assert TOKEN.encode() not in _encrypt(cipher)

    def test_every_encryption_uses_a_fresh_nonce(self) -> None:
        cipher = GscCredentialCipher(KEY_A)
        first, second = _encrypt(cipher), _encrypt(cipher)
        assert first[:12] != second[:12]
        assert first != second


class TestTamperDetection:
    @pytest.mark.parametrize("index", [0, 11, 12, -1])
    def test_flipping_any_byte_fails(self, index: int) -> None:
        cipher = GscCredentialCipher(KEY_A)
        blob = bytearray(_encrypt(cipher))
        blob[index] ^= 0x01
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(cipher, bytes(blob))

    def test_a_truncated_blob_fails(self) -> None:
        cipher = GscCredentialCipher(KEY_A)
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(cipher, _encrypt(cipher)[:20])


class TestAadBinding:
    """A ciphertext is bound to its org, its account and its column."""

    @pytest.mark.parametrize(
        "override",
        [
            {"org_id": "org-b"},
            {"account_name": "globex"},
            {"field": "client_secret"},
        ],
        ids=["other-org", "other-account", "other-field"],
    )
    def test_moving_a_ciphertext_fails(self, override: dict[str, str]) -> None:
        cipher = GscCredentialCipher(KEY_A)
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(cipher, _encrypt(cipher), **override)


class TestKeys:
    def test_wrong_key_fails(self) -> None:
        blob = _encrypt(GscCredentialCipher(KEY_A))
        other = GscCredentialCipher(KEY_B)
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(other, blob, key_id=key_id_for(KEY_A))
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(other, blob)

    def test_a_previous_key_row_still_decrypts(self) -> None:
        old = GscCredentialCipher(KEY_A)
        blob = _encrypt(old)
        rotated = GscCredentialCipher(KEY_B, previous=KEY_A)
        assert _decrypt(rotated, blob, key_id=old.key_id) == TOKEN

    def test_new_writes_use_the_current_key(self) -> None:
        rotated = GscCredentialCipher(KEY_B, previous=KEY_A)
        assert rotated.key_id == key_id_for(KEY_B)
        blob = _encrypt(rotated)
        with pytest.raises(GscCredentialDecryptionError):
            _decrypt(GscCredentialCipher(KEY_A), blob, key_id=key_id_for(KEY_A))

    def test_the_same_key_twice_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            GscCredentialCipher(KEY_A, previous=KEY_A)

    def test_a_short_key_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            GscCredentialCipher(b"short")

    def test_repr_never_shows_key_bytes(self) -> None:
        cipher = GscCredentialCipher(KEY_A, previous=KEY_B)
        text = repr(cipher)
        assert KEY_A.hex() not in text
        assert str(KEY_A) not in text
        assert cipher.key_id in text

    def test_decryption_error_names_the_account_only(self) -> None:
        cipher = GscCredentialCipher(KEY_A)
        blob = bytearray(_encrypt(cipher))
        blob[-1] ^= 0x01
        with pytest.raises(GscCredentialDecryptionError) as info:
            _decrypt(cipher, bytes(blob))
        message = str(info.value)
        assert "acme" in message
        assert TOKEN not in message
        assert bytes(blob).hex() not in message
        assert info.value.__cause__ is None


class TestParseKey:
    def test_accepts_32_bytes_with_or_without_padding(self) -> None:
        encoded = base64.urlsafe_b64encode(KEY_A).decode()
        assert parse_credential_key(SecretStr(encoded), var_name="X") == KEY_A
        assert parse_credential_key(SecretStr(encoded.rstrip("=")), var_name="X") == KEY_A

    @pytest.mark.parametrize(
        "value",
        [
            base64.urlsafe_b64encode(bytes(31)).decode(),
            base64.urlsafe_b64encode(bytes(33)).decode(),
            "not base64 at all!!",
            "",
        ],
        ids=["31-bytes", "33-bytes", "garbage", "empty"],
    )
    def test_refuses_without_echoing_the_value(self, value: str) -> None:
        with pytest.raises(ConfigurationError) as info:
            parse_credential_key(SecretStr(value), var_name="GSC_CREDENTIAL_ENCRYPTION_KEY")
        assert "GSC_CREDENTIAL_ENCRYPTION_KEY" in str(info.value)
        if value:
            assert value not in str(info.value)
