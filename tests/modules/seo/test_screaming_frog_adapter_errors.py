"""Typed-failure tests for the Screaming Frog adapter (plan P0-3).

One exception class for every refusal, and never a cell value in its message:
each hostile bundle here carries `?token=SENTINEL` so a leak is a string match.
Happy-path and logging tests live in `test_screaming_frog_adapter`; zip and
directory guards in `test_screaming_frog_bundle`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.modules.seo.deliverables import _bundle, screaming_frog_adapter
from src.modules.seo.deliverables.screaming_frog_adapter import (
    MAX_COLUMNS,
    MAX_LINE_CHARS,
    SPINE_FILE,
    NormalizerContractError,
    ScreamingFrogBundleError,
)

from tests.modules.seo.test_screaming_frog_adapter import (
    ABOUT,
    HOME,
    SENTINEL,
    assert_clean,
    csv_text,
    load,
    load_raises,
    spine_text,
    write_bundle,
)

# --------------------------------------------------------------------------
# Typed failures: one exception class, no cell value in the message
# --------------------------------------------------------------------------


def test_exception_hierarchy():
    assert issubclass(ScreamingFrogBundleError, ValueError)
    assert issubclass(NormalizerContractError, ScreamingFrogBundleError)


def test_missing_spine_raises(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {"h1_missing.csv": csv_text(["Address"], [SENTINEL])})
    load_raises(bundle, "spine-absent")


def test_empty_spine_raises(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text()})
    load_raises(bundle, "spine-empty")
    bundle = write_bundle(tmp_path / "c", {SPINE_FILE: ""})
    load_raises(bundle, "no-header")


def test_no_url_column_raises(tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b", {SPINE_FILE: csv_text(["Url", "Status"], [SENTINEL, "200"])}
    )
    load_raises(bundle, "no-url-column")


def test_bad_encoding_raises(tmp_path: Path):
    body = b"\xef\xbb\xbf" + b'"Address"\r\n"' + SENTINEL.encode() + b'"\r\n"\xff\xfe"\r\n'
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: body})
    exc = load_raises(bundle, "read-failed")
    assert isinstance(exc.__cause__, UnicodeDecodeError)


def test_nul_in_a_cell_raises(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(SENTINEL + "\x00")})
    with pytest.raises(ScreamingFrogBundleError) as info:
        load(bundle)
    assert_clean(info.value)


def test_line_over_max_line_chars_raises(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(SENTINEL + "a" * MAX_LINE_CHARS)})
    load_raises(bundle, "line-length-cap")


def test_more_than_max_columns_raises(tmp_path: Path):
    header = ["Address", *[f"c{i}" for i in range(MAX_COLUMNS)]]
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: csv_text(header, [SENTINEL])})
    exc = load_raises(bundle, "column-count-cap")
    assert str(MAX_COLUMNS + 1) in str(exc)


def test_over_length_url_raises(tmp_path: Path):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(SENTINEL + "a" * 2048)})
    exc = load_raises(bundle, "invalid-url-cell")
    assert "row 2" in str(exc)


@pytest.mark.parametrize("cell", ["=1+1", "ftp://example.com/", "example.com/", "https:///x"])
def test_non_http_cells_are_rejected(tmp_path: Path, cell: str):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(cell)})
    load_raises(bundle, "invalid-url-cell")


def test_issue_url_outside_spine_raises(tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b",
        {SPINE_FILE: spine_text(HOME), "h1_missing.csv": csv_text(["Address"], [SENTINEL])},
    )
    exc = load_raises(bundle, "url-not-in-spine")
    assert "1 URL(s)" in str(exc)
    assert exc.filename == "h1_missing.csv"


def test_normalizer_raising_mid_file_is_wrapped_with_row_context(tmp_path: Path):
    def picky(url: str) -> str:
        if "SENTINEL" in url:
            raise KeyError(url)
        return url

    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(HOME, SENTINEL)})
    exc = load_raises(bundle, "normalizer-raised", picky)
    assert "row 3" in str(exc)


def test_normalizer_returning_bad_value_is_rejected(tmp_path: Path):
    def wrecks(url: str) -> str:
        return url if "SENTINEL" not in url else "https://example.com/a b"

    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(HOME, SENTINEL)})
    load_raises(bundle, "invalid-normalised-url", wrecks)


def test_unreadable_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(HOME)})
    original = Path.open

    def denied(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == SPINE_FILE:
            raise PermissionError(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    load_raises(bundle, "file-unreadable")


def test_row_count_cap_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(screaming_frog_adapter, "MAX_ROWS_PER_FILE", 2)
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(HOME, ABOUT, SENTINEL)})
    load_raises(bundle, "row-count-cap")


def test_directory_file_cap_is_enforced_by_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_bundle, "MAX_MEMBER_UNCOMPRESSED_BYTES", 16)
    bundle = write_bundle(tmp_path / "b", {SPINE_FILE: spine_text(SENTINEL)})
    load_raises(bundle, "member-size-cap")
