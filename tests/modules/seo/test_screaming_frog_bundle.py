"""Tests for the bundle guards behind the Screaming Frog adapter (`_bundle.py`).

Every archive here is built in `tmp_path`. Names, flags and sizes are patched
at the byte level where the stdlib would otherwise refuse to write the hostile
shape, because a guard that is only tested through `zipfile`'s writer is a
guard that has never seen a real attack.
"""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest
from src.modules.seo.contracts.audit import AuditDataset
from src.modules.seo.deliverables import _bundle
from src.modules.seo.deliverables._bundle import (
    MAX_ZIP_MEMBERS,
    ScreamingFrogBundleError,
    open_bundle,
)
from src.modules.seo.deliverables.screaming_frog_adapter import (
    SPINE_FILE,
    load_screaming_frog_bundle,
)

from tests.modules.seo.test_screaming_frog_adapter import (
    FIXTURE_BUNDLE,
    HOME,
    SENTINEL,
    assert_clean,
    csv_text,
    identity,
    load,
    load_raises,
    spine_text,
    write_bundle,
)

MINIMAL = {SPINE_FILE: spine_text(HOME, SENTINEL)}


def make_zip(
    path: Path,
    members: dict[str, str | bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    raw_names: bool = False,
) -> Path:
    """Write a zip; `raw_names` bypasses `ZipInfo`'s own name normalisation."""
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, body in members.items():
            data = body if isinstance(body, bytes) else body.encode("utf-8-sig")
            if raw_names:
                info = zipfile.ZipInfo("placeholder.csv")
                info.filename = name
                info.compress_type = compression
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
    return path


def zip_of_fixture(path: Path, prefix: str = "") -> Path:
    members = {prefix + p.name: p.read_bytes() for p in FIXTURE_BUNDLE.iterdir()}
    return make_zip(path, members)


def patch_headers(path: Path, offset_local: int, offset_central: int, mutate) -> None:
    """Apply `mutate(buffer, index)` at a field of every local and central header."""
    data = bytearray(path.read_bytes())
    for signature, offset in ((b"PK\x03\x04", offset_local), (b"PK\x01\x02", offset_central)):
        index = data.find(signature)
        while index >= 0:
            mutate(data, index + offset)
            index = data.find(signature, index + 1)
    path.write_bytes(data)


# --------------------------------------------------------------------------
# Zip and directory are the same dataset; dispatch is by content
# --------------------------------------------------------------------------


def test_zip_equals_directory(tmp_path: Path):
    archive = zip_of_fixture(tmp_path / "export.zip")
    assert load(archive) == load(FIXTURE_BUNDLE)


def test_single_top_level_folder_is_accepted(tmp_path: Path):
    archive = zip_of_fixture(tmp_path / "export.zip", prefix="export/")
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("export/", b"")  # explicit directory entry, must be skipped
    assert load(archive) == load(FIXTURE_BUNDLE)


def test_dispatch_is_by_magic_not_extension(tmp_path: Path):
    archive = zip_of_fixture(tmp_path / "export.csv")
    assert isinstance(load(archive), AuditDataset)
    folder = write_bundle(tmp_path / "export.zip", MINIMAL)
    assert isinstance(load(folder), AuditDataset)
    (tmp_path / "text.zip").write_text("not a zip", encoding="utf-8")
    load_raises(tmp_path / "text.zip", "not-a-bundle")
    load_raises(tmp_path / "missing", "not-a-bundle")
    (tmp_path / "corrupt.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    load_raises(tmp_path / "corrupt.zip", "not-a-zip")


def test_zip_is_never_extracted_to_disk(tmp_path: Path):
    archive = zip_of_fixture(tmp_path / "export.zip")
    before = sorted(tmp_path.rglob("*"))
    load(archive)
    assert sorted(tmp_path.rglob("*")) == before == [archive]


def test_uncatalogued_members_are_never_opened(tmp_path: Path):
    inner = make_zip(tmp_path / "inner.zip", {SPINE_FILE: spine_text(SENTINEL)})
    archive = make_zip(
        tmp_path / "export.zip",
        {**MINIMAL, "evil.csv": b"\xff\xfe\x00garbage", "nested.zip": inner.read_bytes()},
    )
    dataset = load(archive)
    assert {page.url for page in dataset.pages} == {HOME, SENTINEL}


# --------------------------------------------------------------------------
# Member-name policy: reject, never normalise
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "rule"),
    [
        ("/" + SPINE_FILE, "member-name-absolute"),
        ("//share/" + SPINE_FILE, "member-name-absolute"),
        ("C:" + SPINE_FILE, "member-name-absolute"),
        ("../" + SPINE_FILE, "member-name-traversal"),
        ("export/../" + SPINE_FILE, "member-name-traversal"),
    ],
)
def test_hostile_member_names_in_a_real_zip_are_rejected(tmp_path: Path, name: str, rule: str):
    archive = make_zip(tmp_path / "export.zip", {name: MINIMAL[SPINE_FILE]}, raw_names=True)
    exc = load_raises(archive, rule)
    assert SPINE_FILE not in str(exc)


@pytest.mark.parametrize(
    ("name", "rule"),
    [
        ("dir\\" + SPINE_FILE, "member-name-forbidden-character"),
        ("\\\\share\\" + SPINE_FILE, "member-name-forbidden-character"),
        ("a\x00" + SPINE_FILE, "member-name-forbidden-character"),
        ("a\x01.csv", "member-name-forbidden-character"),
        ("a\x7f.csv", "member-name-forbidden-character"),
        ("", "empty-member-name"),
        ("d:/x.csv", "member-name-absolute"),
        ("a/b/../c.csv", "member-name-traversal"),
    ],
)
def test_member_name_guard_rejects_shapes_the_stdlib_rewrites_on_read(name: str, rule: str):
    # `ZipInfo.__init__` replaces os.sep and truncates at NUL when the central
    # directory is read, so on Windows these never reach the guard through a
    # real archive. The guard is tested directly so it holds on every platform.
    with pytest.raises(ScreamingFrogBundleError) as info:
        _bundle._check_member_name(name)
    assert info.value.rule == rule
    assert_clean(info.value)


def test_member_name_guard_accepts_export_shapes():
    for name in (SPINE_FILE, "export/" + SPINE_FILE, "internal_client_error_(4xx)_inlinks.csv"):
        _bundle._check_member_name(name)


def test_duplicate_basenames_are_rejected(tmp_path: Path):
    archive = make_zip(
        tmp_path / "export.zip",
        {"a/" + SPINE_FILE: MINIMAL[SPINE_FILE], "b/" + SPINE_FILE: spine_text(SENTINEL)},
    )
    load_raises(archive, "duplicate-member-basename")


def test_member_matching_is_case_sensitive(tmp_path: Path):
    archive = make_zip(tmp_path / "export.zip", {"Internal_All.csv": MINIMAL[SPINE_FILE]})
    load_raises(archive, "spine-absent")


# --------------------------------------------------------------------------
# Member flags and compression
# --------------------------------------------------------------------------


def test_symlink_member_is_rejected(tmp_path: Path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo(SPINE_FILE)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"/etc/passwd")
    load_raises(path, "member-symlink")


def test_encrypted_member_is_rejected(tmp_path: Path):
    archive = make_zip(tmp_path / "export.zip", MINIMAL, compression=zipfile.ZIP_STORED)

    def set_encrypted(buffer: bytearray, index: int) -> None:
        buffer[index] |= 0x1

    patch_headers(archive, 6, 8, set_encrypted)
    assert zipfile.ZipFile(archive).infolist()[0].flag_bits & 0x1
    load_raises(archive, "member-encrypted")


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_exotic_compression_is_rejected(tmp_path: Path, compression: int):
    archive = make_zip(tmp_path / "export.zip", MINIMAL, compression=compression)
    load_raises(archive, "member-compression-unsupported")


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_stored_and_deflated_are_accepted(tmp_path: Path, compression: int):
    archive = make_zip(tmp_path / "export.zip", MINIMAL, compression=compression)
    assert len(load(archive).pages) == 2


# --------------------------------------------------------------------------
# Caps: member count, declared sizes, and bytes actually decompressed
# --------------------------------------------------------------------------


def test_too_many_members_is_rejected(tmp_path: Path):
    members = {f"m{i}.csv": b"x" for i in range(MAX_ZIP_MEMBERS + 1)}
    archive = make_zip(tmp_path / "export.zip", members, compression=zipfile.ZIP_STORED)
    exc = load_raises(archive, "member-count-cap")
    assert str(MAX_ZIP_MEMBERS + 1) in str(exc)


def test_declared_member_size_over_cap_is_refused_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = make_zip(tmp_path / "export.zip", MINIMAL)
    monkeypatch.setattr(_bundle, "MAX_MEMBER_UNCOMPRESSED_BYTES", 16)
    load_raises(archive, "member-size-cap")


def test_declared_bundle_size_over_cap_is_refused_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = make_zip(
        tmp_path / "export.zip", {**MINIMAL, "h1_missing.csv": csv_text(["Address"])}
    )
    monkeypatch.setattr(_bundle, "MAX_BUNDLE_UNCOMPRESSED_BYTES", 60)
    load_raises(archive, "bundle-size-cap")


def test_decompressed_bytes_are_metered_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = make_zip(tmp_path / "export.zip", MINIMAL)
    handle = open_bundle(archive)
    try:
        # Lower the cap after pre-flight so only the streaming meter can enforce it.
        monkeypatch.setattr(_bundle, "MAX_MEMBER_UNCOMPRESSED_BYTES", 8)
        stream = handle.open_text(SPINE_FILE)
        assert stream is not None
        with stream, pytest.raises(ScreamingFrogBundleError) as info:
            stream.read()
        assert info.value.rule == "member-size-cap"
    finally:
        handle.close()


def test_under_declared_file_size_fails_the_crc_check(tmp_path: Path):
    archive = make_zip(tmp_path / "export.zip", MINIMAL, compression=zipfile.ZIP_STORED)

    def shrink(buffer: bytearray, index: int) -> None:
        buffer[index : index + 4] = (5).to_bytes(4, "little")

    patch_headers(archive, 22, 24, shrink)
    exc = load_raises(archive, "read-failed")
    assert isinstance(exc.__cause__, zipfile.BadZipFile)


def test_byte_meter_totals_across_members():
    meter = _bundle._ByteMeter()
    meter.add("a.csv", 10)
    meter.add("b.csv", 10)
    assert meter.bundle_total == 20


# --------------------------------------------------------------------------
# Directory input
# --------------------------------------------------------------------------


def test_directory_lookup_is_case_sensitive(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {"Internal_All.csv": MINIMAL[SPINE_FILE]})
    load_raises(bundle, "spine-absent")


def test_directory_entry_named_like_a_file_is_unsafe(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", MINIMAL)
    (bundle / "h1_missing.csv").mkdir()
    load_raises(bundle, "unsafe-path")


def test_symlinked_file_in_directory_is_refused(tmp_path: Path):
    outside = tmp_path / "outside.csv"
    outside.write_text(MINIMAL[SPINE_FILE], encoding="utf-8-sig", newline="")
    bundle = tmp_path / "b"
    bundle.mkdir()
    try:
        os.symlink(outside, bundle / SPINE_FILE)
    except OSError as exc:
        pytest.skip(f"symlink creation needs a privilege this account lacks: {exc.errno}")
    load_raises(bundle, "unsafe-path")


def test_directory_bundle_close_is_a_no_op(tmp_path: Path):
    handle = open_bundle(write_bundle(tmp_path / "b", MINIMAL))
    assert handle.open_text("h1_missing.csv") is None
    handle.close()


def test_loader_uses_the_normalizer_for_both_inputs(tmp_path: Path):
    archive = zip_of_fixture(tmp_path / "export.zip")
    assert load_screaming_frog_bundle(archive, normalize=identity).site == "example.com"
