"""Validate an untrusted bundle upload before it is ever stored (ADR 0015 §9).

The upload path (worker -> cloud) gets the same scrutiny as any untrusted
file upload: a size cap, zip-slip/path-traversal defense, and — the
constraint specific to this tool — a hard restriction to exactly the CSV
filenames a deliverable can consume. Never an arbitrary walk of whatever a
compromised or buggy worker happened to zip up.

`ALLOWED_BUNDLE_FILENAMES` is derived mechanically from one source of truth:
`ISSUE_CATALOGUE`'s `sf_sources` filenames, plus the mandatory spine file.
That is deliberately *not* `export_manifest.py`'s `--export-tabs` /
`--bulk-export` argument strings, because for seven files those arguments
cannot produce the filename Screaming Frog actually writes:

* `H1:Over X Characters`, `Meta Description:Below/Over X Pixels` and
  `Page Titles:Below/Over X Pixels` carry a literal `X` that Screaming Frog
  replaces with the *active configuration's* threshold — `70`, `400`, `985`,
  `200`, `561` for this engine's templates — so the transform yields
  `h1_over_x_characters.csv`, a name no export has ever contained.
* `Hreflang:Incorrect Language & Region Codes` and its "Inconsistent ...
  Return Links" sibling collapse `" & "` to a single `_`, where stripping the
  `&` and mapping each space leaves a double underscore.

Confirmed empirically against 45 real Screaming Frog 19.4 export folders: the
catalogue's spelling appears 45/45, the transform's 0/45. The catalogue is also
what every consumer already asks for by name, so deriving the gate from it
makes "the allow-list refuses a file a deliverable needs" unrepresentable
rather than merely tested for.

The five thresholds live in an operator-authored `.seospiderconfig`, which is
an opaque Java-serialised binary this codebase cannot read
(`template_registry.py`). A template that changes one of those settings
silently renames its export file, and this list — and `catalogue.py` with it —
must then be corrected by hand. It is seven exact literals on purpose: a numeric
wildcard would hand the set of admissible filenames at an untrusted boundary
to whoever authors that config. `tests/.../test_upload_manifest.py` pins both
directions of the drift.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Final

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.screaming_frog_control.export_manifest import SPINE_TAB

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


class BundleUploadError(RankunoError):
    """An uploaded bundle failed validation and was rejected outright."""


ALLOWED_BUNDLE_FILENAMES: Final[frozenset[str]] = frozenset(
    {f"{SPINE_TAB.replace(':', '_').lower()}.csv"}
    | {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources}
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
                # Names the rule, not the input: this message reaches an HTTP 400
                # body, and an error channel must not echo an attacker-supplied
                # string back (`deliverables/_bundle.py`'s own stated rule).
                _logger.debug("worker_bundle_member_unexpected", extra={"member": info.filename})
                raise BundleUploadError("a bundle member is not an expected export file")
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
