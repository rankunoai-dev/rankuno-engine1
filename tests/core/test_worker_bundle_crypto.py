"""Tests for ADR 0015 condition 11's at-rest bundle encryption."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from src.core.worker_bundle_crypto import BundleDecryptionError, decrypt_bytes, encrypt_bytes

SECRET = SecretStr("unit-test-bundle-encryption-key")
OTHER_SECRET = SecretStr("a-different-key")


def test_round_trips():
    plaintext = b"hello, screaming frog bundle" * 100
    ciphertext = encrypt_bytes(plaintext, secret=SECRET)
    assert ciphertext != plaintext
    assert decrypt_bytes(ciphertext, secret=SECRET) == plaintext


def test_round_trips_empty_bytes():
    ciphertext = encrypt_bytes(b"", secret=SECRET)
    assert decrypt_bytes(ciphertext, secret=SECRET) == b""


def test_two_encryptions_of_the_same_plaintext_differ():
    """A fresh random nonce each call — never a deterministic ciphertext."""
    plaintext = b"same plaintext twice"
    assert encrypt_bytes(plaintext, secret=SECRET) != encrypt_bytes(plaintext, secret=SECRET)


def test_decrypt_rejects_the_wrong_key():
    ciphertext = encrypt_bytes(b"secret bundle contents", secret=SECRET)
    with pytest.raises(BundleDecryptionError):
        decrypt_bytes(ciphertext, secret=OTHER_SECRET)


def test_decrypt_rejects_a_tampered_ciphertext():
    ciphertext = bytearray(encrypt_bytes(b"secret bundle contents", secret=SECRET))
    ciphertext[20] ^= 0xFF  # flip a bit inside the ciphertext region
    with pytest.raises(BundleDecryptionError):
        decrypt_bytes(bytes(ciphertext), secret=SECRET)


def test_decrypt_rejects_a_truncated_blob():
    with pytest.raises(BundleDecryptionError):
        decrypt_bytes(b"too short", secret=SECRET)


def test_decrypt_rejects_an_empty_blob():
    with pytest.raises(BundleDecryptionError):
        decrypt_bytes(b"", secret=SECRET)
