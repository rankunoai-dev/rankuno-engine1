"""Tests for the masterfile CSV source seam (cycle 0107).

The seam exists because the 21 masterfile services had no reachable input:
they read loose CSVs from a directory nothing in this repository ever writes,
while the only real Screaming Frog export the platform holds is an encrypted
zip blob that is deliberately never extracted. These tests pin the two things
that makes true — a zip read entirely from memory, and "absent is `None`,
unreadable is one typed error" — for both implementations, because a service
must behave identically whichever one it was handed.
"""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables._bundle import ScreamingFrogBundleError, open_bundle
from src.modules.seo.deliverables.masterfile_source import (
    BundleMasterfileSource,
    DirectoryMasterfileSource,
    MasterfileSourceError,
    source_for_bundle_bytes,
    source_for_path,
)

SPINE = "Address,Status Code,Indexability,Inlinks\nhttps://e.com/,200,Indexable,3\n"


def zip_bytes(members: dict[str, str | bytes], *, prefix: str = "") -> bytes:
    """A zip of `members`, optionally nested under a containing folder."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(f"{prefix}{name}", body)
    return buffer.getvalue()


def export_dir(root: Path, members: dict[str, str | bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, body in members.items():
        path = root / name
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
    return root


class TestBundleSource:
    def test_a_member_is_read_from_memory(self) -> None:
        source = source_for_bundle_bytes(zip_bytes({"internal_all.csv": SPINE}), "job-1")
        frame = source.read_csv("internal_all.csv")
        assert frame is not None
        assert frame["Address"].tolist() == ["https://e.com/"]
        source.close()

    def test_a_nested_member_is_found_by_basename(self) -> None:
        """A real export zipped with its containing folder must still resolve."""
        data = zip_bytes({"internal_all.csv": SPINE}, prefix="crawl-2026-09-26/")
        source = source_for_bundle_bytes(data, "job-1")
        assert source.read_csv("internal_all.csv") is not None
        source.close()

    def test_an_absent_member_is_none_not_an_error(self) -> None:
        source = source_for_bundle_bytes(zip_bytes({"internal_all.csv": SPINE}), "job-1")
        assert source.read_csv("h1_missing.csv") is None
        source.close()

    def test_an_empty_member_is_none(self) -> None:
        """A zero-byte export is "nothing measured", never a failed build."""
        source = source_for_bundle_bytes(zip_bytes({"h1_missing.csv": ""}), "job-1")
        assert source.read_csv("h1_missing.csv") is None
        source.close()

    def test_a_utf8_bom_does_not_corrupt_the_first_header(self) -> None:
        """Screaming Frog writes a BOM; `gc()` looks up "Address" verbatim."""
        data = zip_bytes({"internal_all.csv": SPINE.encode("utf-8-sig")})
        source = source_for_bundle_bytes(data, "job-1")
        frame = source.read_csv("internal_all.csv")
        assert frame is not None
        assert frame.columns[0] == "Address"
        source.close()

    def test_undecodable_bytes_raise_one_typed_error(self) -> None:
        data = zip_bytes({"internal_all.csv": b"Address\n\xff\xfe\x00bad\n"})
        source = source_for_bundle_bytes(data, "job-1")
        with pytest.raises(MasterfileSourceError, match="internal_all.csv"):
            source.read_csv("internal_all.csv")
        source.close()

    def test_names_lists_every_member(self) -> None:
        data = zip_bytes({"internal_all.csv": SPINE, "custom_extraction_authors.csv": "Address\n"})
        source = source_for_bundle_bytes(data, "job-1")
        assert source.names() == frozenset({"internal_all.csv", "custom_extraction_authors.csv"})
        source.close()

    def test_bytes_that_are_not_a_zip_are_refused(self) -> None:
        with pytest.raises(ScreamingFrogBundleError, match="not-a-zip"):
            source_for_bundle_bytes(b"Address,Status Code\n", "job-1")

    def test_a_symlink_member_is_refused_before_any_read(self) -> None:
        """`_bundle`'s pre-flight is what this source reuses; prove it runs."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            info = zipfile.ZipInfo("internal_all.csv")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"/etc/passwd")
        with pytest.raises(ScreamingFrogBundleError, match="member-symlink"):
            source_for_bundle_bytes(buffer.getvalue(), "job-1")


class TestDirectorySource:
    def test_a_file_is_read(self, tmp_path: Path) -> None:
        source = DirectoryMasterfileSource(export_dir(tmp_path / "e", {"internal_all.csv": SPINE}))
        frame = source.read_csv("internal_all.csv")
        assert frame is not None
        assert frame["Status Code"].tolist() == [200]

    def test_an_absent_file_is_none(self, tmp_path: Path) -> None:
        source = DirectoryMasterfileSource(tmp_path / "missing")
        assert source.read_csv("internal_all.csv") is None

    def test_an_empty_file_is_none(self, tmp_path: Path) -> None:
        root = export_dir(tmp_path / "e", {"h1_missing.csv": ""})
        assert DirectoryMasterfileSource(root).read_csv("h1_missing.csv") is None

    def test_a_utf8_bom_does_not_corrupt_the_first_header(self, tmp_path: Path) -> None:
        root = export_dir(tmp_path / "e", {"internal_all.csv": SPINE.encode("utf-8-sig")})
        frame = DirectoryMasterfileSource(root).read_csv("internal_all.csv")
        assert frame is not None
        assert frame.columns[0] == "Address"

    def test_a_latin1_export_still_reads(self, tmp_path: Path) -> None:
        body = "Address,Title\nhttps://e.com/,café\n".encode("latin-1")
        root = export_dir(tmp_path / "e", {"page_titles_missing.csv": body})
        frame = DirectoryMasterfileSource(root).read_csv("page_titles_missing.csv")
        assert frame is not None

    def test_names_lists_files_only(self, tmp_path: Path) -> None:
        root = export_dir(tmp_path / "e", {"internal_all.csv": SPINE})
        (root / "subdir").mkdir()
        assert DirectoryMasterfileSource(root).names() == frozenset({"internal_all.csv"})

    def test_names_of_a_missing_directory_is_empty(self, tmp_path: Path) -> None:
        assert DirectoryMasterfileSource(tmp_path / "nope").names() == frozenset()

    def test_close_is_a_no_op(self, tmp_path: Path) -> None:
        DirectoryMasterfileSource(tmp_path).close()


class TestSourceForPath:
    def test_a_directory_becomes_a_directory_source(self, tmp_path: Path) -> None:
        root = export_dir(tmp_path / "e", {"internal_all.csv": SPINE})
        assert isinstance(source_for_path(root), DirectoryMasterfileSource)

    def test_a_zip_on_disk_becomes_a_bundle_source(self, tmp_path: Path) -> None:
        archive = tmp_path / "export.zip"
        archive.write_bytes(zip_bytes({"internal_all.csv": SPINE}))
        source = source_for_path(archive)
        assert isinstance(source, BundleMasterfileSource)
        assert source.read_csv("internal_all.csv") is not None
        source.close()

    def test_something_that_is_neither_is_refused(self, tmp_path: Path) -> None:
        plain = tmp_path / "notes.txt"
        plain.write_text("not an export", encoding="utf-8")
        with pytest.raises(ScreamingFrogBundleError, match="not-a-bundle"):
            source_for_path(plain)


def test_a_bundle_source_wraps_any_bundle(tmp_path: Path) -> None:
    """The source takes the `Bundle` Protocol, not only a zip in memory."""
    root = export_dir(tmp_path / "e", {"internal_all.csv": SPINE})
    source = BundleMasterfileSource(open_bundle(root))
    assert source.read_csv("internal_all.csv") is not None
    assert source.names() == frozenset({"internal_all.csv"})
    source.close()
