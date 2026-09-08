"""Guarded access to a Screaming Frog export, whether a directory or a zip.

The adapter never globs. It asks for catalogue filenames by name and gets back
either a text stream or `None` for "absent", which is how "not measured" is
distinguished from "measured, none found" (ADR 0011 §5). Everything hostile a
bundle can do - traversal names, symlinks, junctions, duplicate members, zip
bombs, nested archives, encrypted or exotically compressed members - is refused
here with one typed error, before the adapter parses a byte.

Zip members are streamed, never read whole and never extracted to disk. A
member's declared size is a fast refusal, not the guard: bytes are counted as
they are decompressed, because a header can lie about `file_size`.

Error messages name a file, a rule, and counts. They never carry member names
outside the catalogue vocabulary, cell values, or URLs (Step 5 audit, item 6).
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

__all__ = [
    "MAX_BUNDLE_UNCOMPRESSED_BYTES",
    "MAX_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_ZIP_MEMBERS",
    "Bundle",
    "ScreamingFrogBundleError",
    "open_bundle",
]

MAX_ZIP_MEMBERS: Final[int] = 1_000
"""A real export has 118 entries; anything near this is not an export."""

MAX_MEMBER_UNCOMPRESSED_BYTES: Final[int] = 2 * 1024**3
"""Largest single file we will stream (a 732 MB inlinks file has been seen)."""

MAX_BUNDLE_UNCOMPRESSED_BYTES: Final[int] = 8 * 1024**3
"""Ceiling on bytes decompressed across the whole bundle."""

_ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"
_ALLOWED_COMPRESSION: Final[frozenset[int]] = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_ENCRYPTED_FLAG: Final[int] = 0x1
_DRIVE_PREFIX: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:")
_CONTROL_CHARS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")
_ENCODING: Final[str] = "utf-8-sig"


class ScreamingFrogBundleError(ValueError):
    """The one exception for every bundle, zip, read, parse or encoding failure.

    A `ValueError` so callers that already reject bad input by that type keep
    working; one class so a caller has one thing to catch and the adapter has
    no path on which a failure could become "no issues".
    """

    def __init__(self, filename: str, rule: str, detail: str = "") -> None:
        """Build a message from a fixed vocabulary: file, rule, optional counts."""
        self.filename = filename
        self.rule = rule
        message = f"{filename}: {rule}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


class Bundle(Protocol):
    """A source of named CSV text streams. Absent is `None`, never an error."""

    def open_text(self, name: str) -> IO[str] | None:
        """Return a text stream for `name`, or `None` when the bundle lacks it."""
        ...

    def close(self) -> None:
        """Release the underlying archive or directory handle."""
        ...


class _ByteMeter:
    """Running totals that turn a lying zip header into a refusal."""

    def __init__(self) -> None:
        self.bundle_total = 0
        self._member_totals: dict[str, int] = {}

    def add(self, filename: str, count: int) -> None:
        member = self._member_totals.get(filename, 0) + count
        self._member_totals[filename] = member
        self.bundle_total += count
        if member > MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise ScreamingFrogBundleError(filename, "member-size-cap")
        if self.bundle_total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise ScreamingFrogBundleError(filename, "bundle-size-cap")


class _MeteredStream(io.RawIOBase):
    """Counts decompressed bytes on the way through so caps hold on real data."""

    def __init__(self, inner: IO[bytes], filename: str, meter: _ByteMeter) -> None:
        super().__init__()
        self._inner = inner
        self._filename = filename
        self._meter = meter

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: WriteableBuffer, /) -> int:
        view = memoryview(buffer).cast("B")
        data = self._inner.read(len(view))
        self._meter.add(self._filename, len(data))
        view[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self._inner.close()
        super().close()


def _check_member_name(name: str) -> None:
    """Reject, never normalise, a member name that could escape or confuse.

    A backslash is refused outright rather than translated: a zip written with
    Windows separators is not a Screaming Frog export.
    """
    if not name:
        raise ScreamingFrogBundleError("<zip>", "empty-member-name")
    if "\\" in name or _CONTROL_CHARS.search(name):
        raise ScreamingFrogBundleError("<zip>", "member-name-forbidden-character")
    if name.startswith("/") or _DRIVE_PREFIX.match(name):
        raise ScreamingFrogBundleError("<zip>", "member-name-absolute")
    if ".." in name.split("/"):
        raise ScreamingFrogBundleError("<zip>", "member-name-traversal")


class _ZipBundle:
    """A zip opened by path and pre-flighted before any member is opened."""

    def __init__(self, path: Path) -> None:
        self._meter = _ByteMeter()
        try:
            self._archive = zipfile.ZipFile(path)
            infos = self._archive.infolist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
            raise ScreamingFrogBundleError(path.name, "not-a-zip") from exc
        try:
            self._members = self._preflight(path.name, infos)
        except ScreamingFrogBundleError:
            # A refused archive must not keep a handle open; on Windows that
            # would pin the file and defeat the caller's cleanup.
            self._archive.close()
            raise

    @staticmethod
    def _preflight(archive_name: str, infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
        if len(infos) > MAX_ZIP_MEMBERS:
            raise ScreamingFrogBundleError(archive_name, "member-count-cap", f"{len(infos)}")
        members: dict[str, zipfile.ZipInfo] = {}
        declared_total = 0
        for info in infos:
            if info.is_dir():
                continue
            _check_member_name(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ScreamingFrogBundleError(archive_name, "member-symlink")
            if info.flag_bits & _ENCRYPTED_FLAG:
                raise ScreamingFrogBundleError(archive_name, "member-encrypted")
            if info.compress_type not in _ALLOWED_COMPRESSION:
                raise ScreamingFrogBundleError(archive_name, "member-compression-unsupported")
            if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
                raise ScreamingFrogBundleError(archive_name, "member-size-cap")
            declared_total += info.file_size
            if declared_total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
                raise ScreamingFrogBundleError(archive_name, "bundle-size-cap")
            base = PurePosixPath(info.filename).name
            if base in members:
                raise ScreamingFrogBundleError(archive_name, "duplicate-member-basename")
            members[base] = info
        return members

    def open_text(self, name: str) -> IO[str] | None:
        info = self._members.get(name)
        if info is None:
            return None
        try:
            raw = self._archive.open(info)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
            raise ScreamingFrogBundleError(name, "member-open-failed") from exc
        metered = io.BufferedReader(_MeteredStream(raw, name, self._meter))
        return io.TextIOWrapper(metered, encoding=_ENCODING, errors="strict", newline="")

    def close(self) -> None:
        self._archive.close()


class _DirectoryBundle:
    """A directory whose entries are matched by exact name, then re-verified."""

    def __init__(self, path: Path) -> None:
        self._meter = _ByteMeter()
        try:
            self._root = path.resolve(strict=True)
            # Listing rather than probing: on a case-insensitive filesystem
            # `root / "Internal_All.csv"` would open the wrong-case file.
            self._names = frozenset(entry.name for entry in self._root.iterdir())
        except OSError as exc:
            raise ScreamingFrogBundleError(path.name, "directory-unreadable") from exc

    def open_text(self, name: str) -> IO[str] | None:
        if name not in self._names:
            return None
        candidate = self._root / name
        try:
            escapes = candidate.is_symlink() or candidate.resolve().parent != self._root
            if escapes or not candidate.is_file():
                raise ScreamingFrogBundleError(name, "unsafe-path")
            self._meter.add(name, candidate.stat().st_size)
            return candidate.open("r", encoding=_ENCODING, errors="strict", newline="")
        except OSError as exc:
            raise ScreamingFrogBundleError(name, "file-unreadable") from exc

    def close(self) -> None:
        return None


def _looks_like_zip(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(_ZIP_MAGIC)) == _ZIP_MAGIC
    except OSError as exc:
        raise ScreamingFrogBundleError(path.name, "bundle-unreadable") from exc


def open_bundle(path: Path) -> Bundle:
    """Dispatch on what the path is, never on its extension.

    Raises:
        ScreamingFrogBundleError: The path is neither a directory nor a zip,
            or the zip fails pre-flight.
    """
    if path.is_dir():
        return _DirectoryBundle(path)
    if path.is_file() and _looks_like_zip(path):
        return _ZipBundle(path)
    raise ScreamingFrogBundleError(path.name, "not-a-bundle")
