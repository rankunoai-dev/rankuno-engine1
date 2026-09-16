"""Tests for ADR 0015 condition 9's untrusted-upload validation."""

from __future__ import annotations

import io
import zipfile

import pytest
from src.modules.seo.screaming_frog_control.upload_manifest import (
    ALLOWED_BUNDLE_FILENAMES,
    BundleUploadError,
    _check_member_name,
    validate_and_extract_bundle,
)


def _zip(members: dict[str, bytes], *, raw_names: bool = False) -> bytes:
    """Build a zip.

    `raw_names` bypasses `ZipInfo`'s own name normalisation, the same
    technique `tests/modules/seo/test_screaming_frog_bundle.py`'s
    `make_zip` uses to get a hostile literal name past `zipfile` itself.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for name, data in members.items():
            if raw_names:
                info = zipfile.ZipInfo("placeholder.csv")
                info.filename = name
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
    return buffer.getvalue()


def _set_encryption_flag(data: bytes) -> bytes:
    """Flip the general-purpose encryption bit in both zip header copies.

    `zipfile` recomputes `flag_bits` on write and will not honour a
    caller-set encryption bit, so the only way to produce a
    zipfile-readable "encrypted" entry for this test is to patch the raw
    bytes after writing — the same technique
    `test_screaming_frog_bundle.py`'s `patch_headers` uses.
    """
    buffer = bytearray(data)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = buffer.find(signature)
        while index >= 0:
            buffer[index + offset] |= 0x1
            index = buffer.find(signature, index + 1)
    return bytes(buffer)


def test_allowed_filenames_includes_the_mandatory_spine_file():
    assert "internal_all.csv" in ALLOWED_BUNDLE_FILENAMES


def test_valid_bundle_extracts_allowed_members():
    data = _zip({"internal_all.csv": b"Address\nhttps://example.com/\n"})
    extracted = validate_and_extract_bundle(data, max_total_bytes=10_000)
    assert extracted == {"internal_all.csv": b"Address\nhttps://example.com/\n"}


def test_bundle_missing_optional_files_is_not_an_error():
    """`export_manifest.py`'s own convention: absent means 'not measured'."""
    data = _zip({"internal_all.csv": b"spine only"})
    extracted = validate_and_extract_bundle(data, max_total_bytes=10_000)
    assert set(extracted) == {"internal_all.csv"}


def test_rejects_a_member_not_in_the_allowlist():
    data = _zip({"internal_all.csv": b"ok", "evil.exe": b"MZ..."})
    with pytest.raises(BundleUploadError, match="not an expected export file"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_traversal_member_name():
    data = _zip({"../../../etc/passwd": b"pwned"})
    with pytest.raises(BundleUploadError, match="traversal"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_an_absolute_member_name():
    data = _zip({"/etc/passwd": b"pwned"})
    with pytest.raises(BundleUploadError, match="absolute"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_windows_drive_prefixed_member_name():
    data = _zip({"C:/Windows/System32/evil.dll": b"pwned"})
    with pytest.raises(BundleUploadError):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_backslash_member_name():
    """A backslash-containing member name is refused, in principle.

    `zipfile` itself rewrites a backslash to `/` when it parses the
    central directory (confirmed against this stdlib, matching
    `tests/modules/seo/test_screaming_frog_bundle.py`'s own documented
    finding for `_bundle.py`'s identical guard) — so a real round-tripped
    archive can never carry one through to `_check_member_name`. The guard
    is exercised directly, the same way that sibling test suite does, so it
    still holds on a platform or zipfile version where the rewrite does not
    happen.
    """
    with pytest.raises(BundleUploadError, match="forbidden character"):
        _check_member_name("..\\..\\evil.csv")


def test_rejects_not_a_zip():
    with pytest.raises(BundleUploadError, match="not a valid zip"):
        validate_and_extract_bundle(b"this is not a zip file at all", max_total_bytes=10_000)


def test_rejects_over_the_total_size_cap():
    data = _zip({"internal_all.csv": b"x" * 1000})
    with pytest.raises(BundleUploadError, match="size cap"):
        validate_and_extract_bundle(data, max_total_bytes=10)


def test_rejects_an_encrypted_member():
    data = _set_encryption_flag(_zip({"internal_all.csv": b"secret"}))
    assert zipfile.ZipFile(io.BytesIO(data)).infolist()[0].flag_bits & 0x1
    with pytest.raises(BundleUploadError, match="encrypted"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_duplicate_basenames():
    """Two members that would produce the same allow-listed basename."""
    data = _zip({"a/internal_all.csv": b"one", "b/internal_all.csv": b"two"})
    with pytest.raises(BundleUploadError, match="duplicate"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_too_many_members():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for i in range(201):
            archive.writestr(f"unexpected_{i}.csv", b"x")
    with pytest.raises(BundleUploadError, match="too many members"):
        validate_and_extract_bundle(buffer.getvalue(), max_total_bytes=10_000_000)
