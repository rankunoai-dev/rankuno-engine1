"""Inflate an untrusted gzip body without letting it choose how much memory it takes.

A gzip body is a promise about its own size that only becomes true once it is
inflated. `gzip.decompress` makes that promise binding: a 30 KB body can expand
to gigabytes before the call returns, and a size check after the fact runs
on a process that has already run out of memory. The cap here is applied
*while* inflating, through `decompressobj(...).decompress(chunk, max_length)`,
so output stops one byte past the limit no matter what the input claims.

The SHA-256 is computed over the inflated bytes as they are produced. Hashing
the compressed bytes instead would make every re-run of a client look like a
different upload: gzip writes a timestamp into its header.
"""

from __future__ import annotations

import hashlib
import zlib

from src.core.errors import RankunoError

__all__ = ["DecompressedTooLargeError", "GunzipResult", "InvalidGzipError", "gunzip_capped"]

_CHUNK = 64 * 1024
"""Input fed to the inflater per step. Small enough that one step's output is bounded."""


class InvalidGzipError(RankunoError):
    """The body is not exactly one complete gzip member."""


class DecompressedTooLargeError(RankunoError):
    """The body inflates past the permitted size."""


class GunzipResult:
    """Inflated bytes and their digest."""

    __slots__ = ("data", "sha256")

    def __init__(self, data: bytes, sha256: str) -> None:
        """Hold the result.

        Args:
            data: The inflated bytes.
            sha256: Hex SHA-256 of `data`.
        """
        self.data = data
        self.sha256 = sha256


def gunzip_capped(body: bytes, *, max_output: int) -> GunzipResult:
    """Inflate one gzip member, refusing output beyond `max_output` bytes.

    Args:
        body: The compressed bytes, already size-capped by the caller.
        max_output: Most bytes the inflated result may hold.

    Returns:
        The inflated bytes and their SHA-256.

    Raises:
        DecompressedTooLargeError: Inflating would exceed `max_output`.
        InvalidGzipError: Not gzip, truncated, or followed by trailing bytes
            (a second member included: one bundle is one member).
    """
    inflater = zlib.decompressobj(wbits=31)
    digest = hashlib.sha256()
    out = bytearray()
    view = memoryview(body)
    try:
        for start in range(0, len(view), _CHUNK):
            pending = bytes(view[start : start + _CHUNK])
            while pending:
                # One byte past the remaining room, so "exactly at the cap" is
                # accepted and "one byte over" is detected without inflating more.
                piece = inflater.decompress(pending, max_output - len(out) + 1)
                _append(out, digest, piece, max_output)
                pending = inflater.unconsumed_tail
                if inflater.eof:
                    break
            if inflater.eof:
                if inflater.unused_data or start + _CHUNK < len(view):
                    msg = "body continues after the end of the gzip stream"
                    raise InvalidGzipError(msg)
                break
        _append(out, digest, inflater.flush(), max_output)
    except zlib.error as exc:
        msg = "body is not valid gzip"
        raise InvalidGzipError(msg) from exc
    if not inflater.eof:
        msg = "gzip stream is truncated"
        raise InvalidGzipError(msg)
    return GunzipResult(bytes(out), digest.hexdigest())


def _append(out: bytearray, digest: hashlib._Hash, piece: bytes, max_output: int) -> None:
    if len(out) + len(piece) > max_output:
        msg = f"body inflates past the {max_output:,}-byte limit"
        raise DecompressedTooLargeError(msg)
    out += piece
    digest.update(piece)
