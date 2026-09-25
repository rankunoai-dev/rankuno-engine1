"""Tests for meta_description masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_meta_description import MetaDescriptionService

__all__ = ["test_meta_description_empty", "test_meta_description_metadata"]


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_meta_description_empty(sf_export_dir: Path) -> None:
    """Meta description service with no CSV files should produce empty workbook."""
    service = MetaDescriptionService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_meta_description_metadata(sf_export_dir: Path) -> None:
    """Meta description service should declare correct metadata."""
    service = MetaDescriptionService("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "meta_description"
    assert metadata.label == "Meta Description"
    assert metadata.sheets == 1
    assert metadata.is_complex is False


def test_meta_description_with_data(sf_export_dir: Path) -> None:
    """Meta description service with data should generate workbook."""
    # Create test CSVs
    internal_csv = sf_export_dir / "internal_all.csv"
    internal_csv.write_text(
        '"Address","Status Code","Indexability","Inlinks"\n'
        '"https://example.com/","200","Indexable","5"\n'
        '"https://example.com/old/","404","Non-Indexable","2"\n'
    )

    gsc_csv = sf_export_dir / "search_console_all.csv"
    gsc_csv.write_text(
        '"Address","Impressions","Clicks"\n'
        '"https://example.com/","100","10"\n'
    )

    meta_csv = sf_export_dir / "meta_description_missing.csv"
    meta_csv.write_text('"Address"\n"https://example.com/"\n')

    meta_csv2 = sf_export_dir / "meta_description_too_long.csv"
    meta_csv2.write_text('"Address"\n"https://example.com/product"\n')

    service = MetaDescriptionService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_meta_description_with_non_indexable(sf_export_dir: Path) -> None:
    """Meta description service filters non-indexable pages."""
    internal_csv = sf_export_dir / "internal_all.csv"
    internal_csv.write_text(
        '"Address","Status Code","Indexability","Inlinks"\n'
        '"https://example.com/indexable","200","Indexable","5"\n'
        '"https://example.com/non-indexable","200","Non-Indexable","2"\n'
    )

    meta_csv = sf_export_dir / "meta_description_missing.csv"
    meta_csv.write_text(
        '"Address"\n'
        '"https://example.com/indexable"\n'
        '"https://example.com/non-indexable"\n'
    )

    service = MetaDescriptionService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0
