"""Tests for `RulebookStore` (cycle 0087).

No rulebook-shaped `.xlsx` is committed to the repository, the same stance
`test_rulebook.py` takes: every workbook here is written by `openpyxl` into
`tmp_path` and read back as bytes.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from src.modules.seo.deliverables.rulebook import RULEBOOK_SHEET_NAME, RulebookError
from src.modules.seo.deliverables.rulebook_store import (
    RulebookNotFoundError,
    RulebookRecord,
    RulebookStore,
)


def write_rulebook_xlsx(path: Path, *, rows: tuple[tuple[object, ...], ...] = ()) -> bytes:
    """A minimal valid rulebook workbook, returned as bytes ready to upload."""
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = RULEBOOK_SHEET_NAME
    sheet.append(
        ("URL Pattern", "Rule Type", "Theme 1", "Theme 2", "Language", "Business Priority")
    )
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path.read_bytes()


VALID_ROWS = (("/en/", "starts with", "English", None, "en", "High"),)


class TestCreate:
    def test_a_valid_upload_is_stored_and_parsed(self, tmp_path: Path) -> None:
        content = write_rulebook_xlsx(tmp_path / "src.xlsx", rows=VALID_ROWS)
        store = RulebookStore(tmp_path / "store")

        record = store.create("acme", "English rules", content)

        assert record.org_id == "acme"
        assert record.label == "English rules"
        assert record.rule_count == 1
        assert record.size_bytes == len(content)
        assert store.path_for(record.id).read_bytes() == content

    def test_an_unreadable_upload_raises_and_stores_nothing(self, tmp_path: Path) -> None:
        store = RulebookStore(tmp_path / "store")

        with pytest.raises(RulebookError):
            store.create("acme", "", b"not a workbook at all")

        assert store.list_all() == []
        # No stray temp file left behind either.
        assert list((tmp_path / "store").iterdir()) == []

    def test_a_label_over_the_length_cap_is_truncated_not_rejected(self, tmp_path: Path) -> None:
        content = write_rulebook_xlsx(tmp_path / "src.xlsx")
        store = RulebookStore(tmp_path / "store")

        record = store.create("acme", "x" * 500, content)

        assert len(record.label) == 200


class TestGetListDelete:
    def test_get_of_an_unknown_id_raises(self, tmp_path: Path) -> None:
        store = RulebookStore(tmp_path / "store")
        with pytest.raises(RulebookNotFoundError):
            store.get("nope")

    def test_list_all_is_unfiltered_and_newest_first(self, tmp_path: Path) -> None:
        """Mirrors `DiskJobStore.list_jobs()` exactly.

        Org filtering is the caller's job - see the module docstring.
        """
        store = RulebookStore(tmp_path / "store")
        content = write_rulebook_xlsx(tmp_path / "src.xlsx")
        first = store.create("org-a", "first", content)
        second = store.create("org-b", "second", content)

        listed = store.list_all()

        assert [r.id for r in listed] == [second.id, first.id]
        assert {r.org_id for r in listed} == {"org-a", "org-b"}

    def test_delete_removes_both_the_metadata_and_the_file(self, tmp_path: Path) -> None:
        root = tmp_path / "store"
        store = RulebookStore(root)
        content = write_rulebook_xlsx(tmp_path / "src.xlsx")
        record = store.create("acme", "", content)

        store.delete(record.id)

        with pytest.raises(RulebookNotFoundError):
            store.get(record.id)
        assert not (root / f"{record.id}.xlsx").exists()
        assert not (root / f"{record.id}.json").exists()

    def test_delete_of_an_unknown_id_raises(self, tmp_path: Path) -> None:
        store = RulebookStore(tmp_path / "store")
        with pytest.raises(RulebookNotFoundError):
            store.delete("nope")

    def test_path_for_of_a_record_missing_its_file_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "store"
        store = RulebookStore(root)
        content = write_rulebook_xlsx(tmp_path / "src.xlsx")
        record = store.create("acme", "", content)
        (root / f"{record.id}.xlsx").unlink()

        with pytest.raises(RulebookNotFoundError):
            store.path_for(record.id)


class TestRecordShape:
    def test_record_round_trips_through_json(self, tmp_path: Path) -> None:
        store = RulebookStore(tmp_path / "store")
        content = write_rulebook_xlsx(tmp_path / "src.xlsx", rows=VALID_ROWS)
        created = store.create("acme", "label", content)

        reread = store.get(created.id)

        assert reread == created
        assert RulebookRecord.model_validate_json(created.model_dump_json()) == created
