"""Validate an untrusted bundle upload before it is ever stored (ADR 0015 §9).

The upload path (worker -> cloud) gets the same scrutiny as any untrusted
file upload: a size cap, zip-slip/path-traversal defense, and — the
constraint specific to this tool — a hard restriction to exactly the CSV
filenames `export_manifest.py` already defines. Never an arbitrary walk of
whatever a compromised or buggy worker happened to zip up.

`ALLOWED_BUNDLE_FILENAMES` is derived mechanically from `SPINE_TAB`,
`EXPORT_TABS`, and `BULK_EXPORT` using the exact naming transform
`export_manifest.py`'s own module docstring documents (lowercase; strip
`-`, `<`, `>`, `&`; `.` -> `_`; ` ` and `:` -> `_`; for `--bulk-export`'s
nested arguments, only the last `:`-separated segment contributes) — never
a second, hand-typed filename list that could drift from the CLI argument
list that actually produces it.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Final

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.modules.seo.screaming_frog_control.export_manifest import (
    BULK_EXPORT,
    EXPORT_TABS,
    SPINE_TAB,
)

__all__ = ["ALLOWED_BUNDLE_FILENAMES", "BundleUploadError", "validate_and_extract_bundle"]

_logger = get_logger(__name__)

MAX_ZIP_MEMBERS: Final[int] = 200
"""A real bundle has one spine file plus up to ~95 export/bulk-export files —
well under 118 confirmed in `_bundle.py`'s own sibling constant reasoning.
Generous headroom, still bounded."""

MAX_MEMBER_BYTES: Final[int] = 200 * 1024 * 1024
"""Largest single CSV this endpoint will accept, decompressed."""

_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_ENCRYPTED_FLAG = 0x1
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_STRIPPED_CHARS = ("-", "<", ">", "&")


class BundleUploadError(RankunoError):
    """An uploaded bundle failed validation and was rejected outright."""


def _filename_for(argument: str, *, bulk: bool) -> str:
    """Screaming Frog's own `--export-tabs`/`--bulk-export` naming transform."""
    segment = argument.rsplit(":", 1)[-1] if bulk else argument
    for char in _STRIPPED_CHARS:
        segment = segment.replace(char, "")
    segment = segment.replace(".", "_").replace(" ", "_").replace(":", "_")
    return f"{segment.lower()}.csv"


ALLOWED_BUNDLE_FILENAMES: Final[frozenset[str]] = frozenset(
    {f"{SPINE_TAB.replace(':', '_').lower()}.csv"}
    | {_filename_for(arg, bulk=False) for arg in EXPORT_TABS}
    | {_filename_for(arg, bulk=True) for arg in BULK_EXPORT}
)
"""Every filename this endpoint will ever accept. Nothing else survives
`validate_and_extract_bundle`, regardless of what a worker's zip contains."""


def _check_member_name(name: str) -> None:
    """Reject, never normalise, a member name that could escape or confuse.

    Mirrors `deliverables._bundle._check_member_name`'s checks — that
    module is private to its own package (leading underscore), so this is a
    deliberate, independent re-implementation for this untrusted-upload
    boundary rather than a cross-package import of a private module.
    """
    if not name:
        raise BundleUploadError("empty member name in uploaded bundle")
    if "\\" in name or _CONTROL_CHARS.search(name):
        raise BundleUploadError(f"member name '{name}' contains a forbidden character")
    if name.startswith("/") or _DRIVE_PREFIX.match(name):
        raise BundleUploadError(f"member name '{name}' is an absolute path")
    if ".." in name.split("/"):
        raise BundleUploadError(f"member name '{name}' attempts path traversal")


def validate_and_extract_bundle(data: bytes, *, max_total_bytes: int) -> dict[str, bytes]:
    """Validate an uploaded zip and return only its allow-listed members.

    Args:
        data: The raw uploaded bytes.
        max_total_bytes: Ceiling on the sum of every extracted member's
            decompressed size (ADR 0015 condition 9's size cap).

    Returns:
        `{filename: raw_bytes}` for every member that matched
        `ALLOWED_BUNDLE_FILENAMES`. A bundle missing some optional files is
        not an error — `export_manifest.py`'s own convention is that an
        absent export means "not measured", not a failure.

    Raises:
        BundleUploadError: The archive is not a valid zip, exceeds a size or
            member-count cap, contains a symlink, an encrypted or
            exotically-compressed member, a traversal/absolute member name,
            a duplicate basename, or **any** member whose basename is not
            in `ALLOWED_BUNDLE_FILENAMES` — an unexpected file rejects the
            whole upload rather than being silently dropped, because an
            unlisted file in a Screaming Frog export bundle is itself
            suspicious.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        raise BundleUploadError(f"not a valid zip archive: {exc}") from exc

    try:
        if len(infos) > MAX_ZIP_MEMBERS:
            raise BundleUploadError(f"bundle has too many members ({len(infos)})")

        extracted: dict[str, bytes] = {}
        total_bytes = 0
        for info in infos:
            if info.is_dir():
                continue
            _check_member_name(info.filename)
            if info.external_attr >> 16 & 0o170000 == 0o120000:  # S_IFLNK
                raise BundleUploadError(f"member '{info.filename}' is a symlink")
            if info.flag_bits & _ENCRYPTED_FLAG:
                raise BundleUploadError(f"member '{info.filename}' is encrypted")
            if info.compress_type not in _ALLOWED_COMPRESSION:
                raise BundleUploadError(f"member '{info.filename}' uses unsupported compression")

            basename = PurePosixPath(info.filename).name
            if basename not in ALLOWED_BUNDLE_FILENAMES:
                raise BundleUploadError(f"member '{info.filename}' is not an expected export file")
            if basename in extracted:
                raise BundleUploadError(f"duplicate member basename '{basename}'")

            try:
                raw = archive.read(info)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
                raise BundleUploadError(f"failed to read member '{info.filename}': {exc}") from exc

            if len(raw) > MAX_MEMBER_BYTES:
                raise BundleUploadError(f"member '{info.filename}' exceeds the per-file size cap")
            total_bytes += len(raw)
            if total_bytes > max_total_bytes:
                raise BundleUploadError("bundle exceeds the total size cap")

            extracted[basename] = raw
    finally:
        archive.close()

    _logger.info(
        "worker_bundle_validated", extra={"members": len(extracted), "total_bytes": total_bytes}
    )
    return extracted
