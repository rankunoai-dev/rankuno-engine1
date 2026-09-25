"""Tests for masterfile_base utilities and abstract base."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from src.modules.seo.deliverables.masterfile_base import (
    gc,
    read_csv_safe,
    safe_cell,
    sanitize_sheet_name,
    truncate_cell,
)

__all__ = [
    "test_gc_column_lookup",
    "test_gc_case_insensitive",
    "test_gc_not_found",
    "test_read_csv_safe_missing",
    "test_read_csv_safe_exists",
    "test_safe_cell_no_trigger",
    "test_safe_cell_with_trigger",
    "test_truncate_cell",
    "test_sanitize_sheet_name",
]


def test_gc_column_lookup() -> None:
    """gc() should find exact column match."""
    header = ["Address", "Status Code", "Indexability"]
    assert gc(header, "Status Code") == 1


def test_gc_case_insensitive() -> None:
    """gc() should be case-insensitive."""
    header = ["Address", "STATUS CODE", "Indexability"]
    assert gc(header, "status code") == 1


def test_gc_not_found() -> None:
    """gc() should raise KeyError when column not found."""
    header = ["Address", "Status Code"]
    with pytest.raises(KeyError):
        gc(header, "NonExistent")


def test_read_csv_safe_missing() -> None:
    """read_csv_safe should return None for missing file."""
    result = read_csv_safe(Path("/nonexistent/file.csv"))
    assert result is None


def test_read_csv_safe_exists() -> None:
    """read_csv_safe should read existing CSV file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test.csv"
        csv_path.write_text("Address,Status Code\nhttps://example.com/,200\n")

        result = read_csv_safe(csv_path)
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "Address" in result.columns


def test_safe_cell_no_trigger() -> None:
    """safe_cell should pass through non-trigger strings."""
    assert safe_cell("normal text") == "normal text"
    assert safe_cell(123) == 123
    assert safe_cell(None) is None


def test_safe_cell_with_trigger() -> None:
    """safe_cell should prefix formula-trigger characters."""
    assert safe_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert safe_cell("+100") == "'+100"
    assert safe_cell("-50") == "'-50"
    assert safe_cell("@function") == "'@function"


def test_truncate_cell() -> None:
    """truncate_cell should limit string length with marker."""
    short_text = "This is short"
    assert truncate_cell(short_text) == short_text

    long_text = "x" * 50000
    result = truncate_cell(long_text, max_length=100)
    assert len(result) == 100
    assert result.endswith("[truncated]")


def test_sanitize_sheet_name() -> None:
    """sanitize_sheet_name should remove forbidden characters."""
    # Forbidden characters: \\/?*:[]
    assert sanitize_sheet_name("My/Sheet") == "My_Sheet"
    assert sanitize_sheet_name("Sheet:Name") == "Sheet_Name"
    assert sanitize_sheet_name("Sheet*Name") == "Sheet_Name"

    # Should cap at 31 characters
    long_name = "A" * 50
    result = sanitize_sheet_name(long_name)
    assert len(result) <= 31

    # Should handle deduplication
    existing = {"Sheet", "Sheet_"}
    result = sanitize_sheet_name("Sheet", existing)
    assert result != "Sheet"
    assert result not in existing
