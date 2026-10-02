"""Tests for ``scripts/prune_lessons.py``, which deletes files and so must be exact."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.prune_lessons import lesson_files, main, prune


def _lesson(directory: Path, stamp: str, slug: str = "topic") -> Path:
    path = directory / f"{stamp}-{slug}.md"
    path.write_text("# lesson\n", encoding="utf-8")
    return path


def _six_lessons(directory: Path) -> list[Path]:
    return [_lesson(directory, f"20261001-12000{i}") for i in range(6)]


def test_keeps_the_newest_five_and_deletes_the_oldest(tmp_path: Path) -> None:
    lessons = _six_lessons(tmp_path)

    deleted = prune(tmp_path, keep=5)

    assert deleted == [lessons[0]]
    assert lesson_files(tmp_path) == lessons[1:]


def test_newest_is_decided_by_the_timestamp_not_creation_order(tmp_path: Path) -> None:
    newer = _lesson(tmp_path, "20261002-090000", "written-first")
    older = _lesson(tmp_path, "20261001-090000", "written-second")

    prune(tmp_path, keep=1)

    assert newer.exists()
    assert not older.exists()


def test_files_that_are_not_lessons_are_never_touched(tmp_path: Path) -> None:
    _six_lessons(tmp_path)
    progress = tmp_path / "tour-progress.json"
    progress.write_text("{}", encoding="utf-8")
    hand_note = tmp_path / "my-notes.md"
    hand_note.write_text("mine", encoding="utf-8")

    prune(tmp_path, keep=1)

    assert progress.exists()
    assert hand_note.exists()
    assert len(lesson_files(tmp_path)) == 1


def test_five_or_fewer_lessons_deletes_nothing(tmp_path: Path) -> None:
    for i in range(5):
        _lesson(tmp_path, f"20261001-12000{i}")

    assert prune(tmp_path, keep=5) == []
    assert len(lesson_files(tmp_path)) == 5


def test_a_missing_folder_is_not_an_error(tmp_path: Path) -> None:
    assert prune(tmp_path / "absent", keep=5) == []


def test_keep_below_one_is_refused(tmp_path: Path) -> None:
    _six_lessons(tmp_path)

    with pytest.raises(ValueError, match="at least 1"):
        prune(tmp_path, keep=0)
    assert len(lesson_files(tmp_path)) == 6


def test_cli_prunes_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _six_lessons(tmp_path)

    assert main(["--dir", str(tmp_path), "--keep", "5"]) == 0

    out = capsys.readouterr().out
    assert "deleted 20261001-120000-topic.md" in out
    assert "5 lesson(s) kept" in out
