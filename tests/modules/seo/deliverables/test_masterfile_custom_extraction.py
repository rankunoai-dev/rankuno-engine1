"""Tests for custom_extraction masterfile service.

This is the one service whose sheet names come from **untrusted input**: the
extractor name is a slice of an uploaded filename, handed straight to
`openpyxl.Workbook.create_sheet`, which raises on any of the six characters
Excel forbids in a sheet title, on a name over 31 characters, and on a second
sheet whose name collides with the first. Every case below made a build fail
before build-log 0116.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping
from pathlib import Path

import openpyxl
from src.modules.seo.deliverables.masterfile_base import NOT_MEASURED
from src.modules.seo.deliverables.masterfile_custom_extraction import (
    NOT_REQUESTED,
    CustomExtractionService,
)
from src.modules.seo.deliverables.masterfile_source import source_for_bundle_bytes
from tests.modules.seo.deliverables.conftest import (
    detail_table,
    first_cell,
    sheet_rows,
    urls_in,
)
from tests.modules.seo.deliverables.sf_export import HOME, csv_bytes, write_export

EXTRACTOR_HEADER = ("Address", "Status Code", "Status", "Phone 1")
"""Observed in `custom_extraction_all.csv` in a real export, plus the one
extractor column a configured crawl adds."""


def extractor(name: str, urls: tuple[str, ...] = (HOME,)) -> tuple[str, bytes]:
    """`{filename: bytes}` for one extractor's export."""
    rows = [(url, "200", "OK", "555-0100") for url in urls]
    return f"custom_extraction_{name}.csv", csv_bytes(EXTRACTOR_HEADER, rows)


def sheet_names(payload: bytes) -> list[str]:
    return openpyxl.load_workbook(io.BytesIO(payload)).sheetnames


def bundle(members: Mapping[str, bytes]) -> bytes:
    """A zip shaped like a worker upload.

    The hostile-name cases have to go through a zip rather than a directory:
    Windows cannot hold `:`, `?` or `*` in a filename at all (`a:b` opens an
    NTFS alternate data stream instead), so a filesystem fixture would test
    something other than the input this service actually receives.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def generate_from(members: Mapping[str, bytes]) -> bytes:
    source = source_for_bundle_bytes(bundle(members), "job-1")
    try:
        return CustomExtractionService("test-job", source).generate()
    finally:
        source.close()


def test_an_absent_extraction_export_is_not_measured_not_misconfigured(
    empty_export: Path,
) -> None:
    """The placeholder must name our gap, not the operator's configuration.

    The cell used to read "No custom extractors configured", which is a
    claim about the operator's `.seospiderconfig` - a binary this codebase
    cannot read - made on evidence that only showed the export was missing.
    It must say what its siblings say, then the part they cannot.
    """
    payload = CustomExtractionService("test-job", empty_export).generate()

    assert sheet_names(payload) == ["Summary"]
    assert first_cell(payload) == NOT_MEASURED
    rows = sheet_rows(payload)
    assert rows[1][0] == NOT_REQUESTED
    assert "configured" not in str(rows[0][0])


def test_the_reason_names_the_unrequested_tab_not_the_crawl_settings() -> None:
    """The reason names the tab and the file, not a vague absence.

    Precision is the point: "we never asked for this export" is a different
    fact from "this crawl had none", and only one of them is the operator's to
    fix.
    """
    assert "Custom Extraction:All" in NOT_REQUESTED
    assert "custom_extraction_all.csv" in NOT_REQUESTED
    assert "gap is in this engine" in NOT_REQUESTED


def test_metadata(empty_export: Path) -> None:
    metadata = CustomExtractionService("test-job", empty_export).metadata

    assert metadata.slug == "custom_extraction"
    assert metadata.is_complex is True
    assert metadata.sheets == 1


def test_an_extractor_produces_its_rows(tmp_path: Path) -> None:
    export = write_export(tmp_path / "e", extra=dict([extractor("phone")]))

    payload = CustomExtractionService("test-job", export).generate()

    assert sheet_names(payload) == ["phone"]
    header, body = detail_table(payload, "phone")
    assert header == ("URL", "Inlinks", "Impressions", "Clicks")
    assert urls_in(body) == [HOME]


def test_the_real_screaming_frog_filename_is_read(tmp_path: Path) -> None:
    """A real 19.4 export writes exactly one file: `custom_extraction_all.csv`.

    Confirmed present in all 45 populated export folders checked. It is *not*
    in `ALLOWED_BUNDLE_FILENAMES`, so this only ever arrives through a loose
    export directory - see the module docstring on the service.
    """
    export = write_export(tmp_path / "e", extra=dict([extractor("all")]))

    payload = CustomExtractionService("test-job", export).generate()

    assert sheet_names(payload) == ["all"]


class TestUntrustedSheetNames:
    def test_a_forbidden_character_does_not_raise(self) -> None:
        payload = generate_from(dict([extractor("a:b?c*d[e]f")]))

        assert sheet_names(payload) == ["a_b_c_d_e_f"]

    def test_an_over_long_name_is_capped_at_the_excel_limit(self) -> None:
        payload = generate_from(dict([extractor("x" * 80)]))

        (name,) = sheet_names(payload)
        assert len(name) <= 31

    def test_two_names_that_truncate_alike_do_not_collide(self) -> None:
        """The second `create_sheet` is where a truncation collision raised."""
        prefix = "y" * 40
        payload = generate_from(dict([extractor(f"{prefix}one"), extractor(f"{prefix}two")]))

        names = sheet_names(payload)
        assert len(names) == 2
        assert len(set(names)) == 2
        assert all(len(name) <= 31 for name in names)
