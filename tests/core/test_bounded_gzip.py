"""`gunzip_capped`: an untrusted body cannot choose how much it inflates to."""

from __future__ import annotations

import gzip
import hashlib
import os

import pytest
from src.core.bounded_gzip import DecompressedTooLargeError, InvalidGzipError, gunzip_capped


def test_round_trips_and_hashes_the_inflated_bytes() -> None:
    raw = os.urandom(300_000)
    result = gunzip_capped(gzip.compress(raw), max_output=len(raw))
    assert result.data == raw
    assert result.sha256 == hashlib.sha256(raw).hexdigest()


def test_the_hash_ignores_the_gzip_header_timestamp() -> None:
    raw = b'{"same": "bundle"}'
    first = gunzip_capped(gzip.compress(raw, mtime=1), max_output=1024)
    second = gunzip_capped(gzip.compress(raw, mtime=2), max_output=1024)
    assert first.sha256 == second.sha256


def test_exactly_at_the_cap_is_accepted_and_one_over_is_not() -> None:
    raw = b"x" * 10_000
    assert len(gunzip_capped(gzip.compress(raw), max_output=10_000).data) == 10_000
    with pytest.raises(DecompressedTooLargeError):
        gunzip_capped(gzip.compress(raw), max_output=9_999)


def test_a_bomb_is_stopped_without_inflating_it() -> None:
    bomb = gzip.compress(b"\0" * (64 * 1024 * 1024))
    assert len(bomb) < 100_000
    with pytest.raises(DecompressedTooLargeError):
        gunzip_capped(bomb, max_output=1024 * 1024)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not gzip at all",
        gzip.compress(b"payload")[:-6],
        gzip.compress(b"payload") + b"trailing",
        gzip.compress(b"one") + gzip.compress(b"two"),
    ],
    ids=["empty", "not-gzip", "truncated", "trailing-bytes", "two-members"],
)
def test_anything_but_one_complete_member_is_refused(body: bytes) -> None:
    with pytest.raises(InvalidGzipError):
        gunzip_capped(body, max_output=1024)


def test_a_large_body_spanning_many_input_chunks_round_trips() -> None:
    raw = os.urandom(1024 * 1024)  # incompressible: the compressed body spans ~16 chunks
    assert gunzip_capped(gzip.compress(raw), max_output=len(raw)).data == raw
