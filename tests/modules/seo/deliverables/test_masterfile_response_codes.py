"""Tests for response_codes masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_response_codes import ResponseCodesService

__all__ = ["test_response_codes_empty_export", "test_response_codes_with_data"]


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_response_codes_empty_export(sf_export_dir: Path) -> None:
    """Response codes service with no CSV files should produce empty workbook."""
    service = ResponseCodesService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_response_codes_metadata() -> None:
    """Response codes service should declare correct metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = ResponseCodesService("test-job", Path(tmpdir))
        metadata = service.metadata

        assert metadata.slug == "response_codes"
        assert metadata.label == "Response Codes"
        assert metadata.sheets == 1
        assert metadata.is_complex is False


def test_response_codes_with_response_csv(sf_export_dir: Path) -> None:
    """Response codes service with data should generate workbook."""
    # Create test CSVs
    internal_csv = sf_export_dir / "internal_all.csv"
    internal_csv.write_text(
        '"Address","Status Code","Indexability","Inlinks"\n'
        '"https://example.com/","200","Indexable","5"\n'
        '"https://example.com/old/","404","Non-Indexable","2"\n'
    )

    response_csv = sf_export_dir / "response_codes_internal_success_(2xx).csv"
    response_csv.write_text('"Address","Status Code"\n"https://example.com/","200"\n')

    service = ResponseCodesService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0
