"""Row-count and header assertions for meta_description masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_base import NOT_MEASURED
from src.modules.seo.deliverables.masterfile_meta_description import MetaDescriptionService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names

__all__ = ["test_meta_description_empty", "test_meta_description_metadata"]


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_meta_description_empty(sf_export_dir: Path) -> None:
    """Meta description service with no CSV files should produce empty workbook."""
    service = MetaDescriptionService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No meta description data found"
    assert sheet_names(payload)[0] == "Meta Descriptions"


def test_meta_description_metadata(sf_export_dir: Path) -> None:
    """Meta description service should declare correct metadata."""
    service = MetaDescriptionService("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "meta_description"
    assert metadata.label == "Meta Description"
    assert metadata.sheets == 1
    assert metadata.is_complex is False


def test_meta_description_with_data(sf_export_dir: Path) -> None:
    """Two real exports, one enriched URL, and a URL absent from the spine.

    `meta_description_over_985_pixels.csv` replaces the
    `meta_description_too_long.csv` this test used to write: that name is not
    a Screaming Frog export and never reached the service (build-log 0116).
    """
    (sf_export_dir / "internal_all.csv").write_text(
        '"Address","Status Code","Indexability","Inlinks"\n'
        '"https://example.com/","200","Indexable","5"\n'
        '"https://example.com/old/","404","Non-Indexable","2"\n'
    )
    (sf_export_dir / "search_console_all.csv").write_text(
        '"Address","Impressions","Clicks"\n"https://example.com/","100","10"\n'
    )
    (sf_export_dir / "meta_description_missing.csv").write_text(
        '"Address"\n"https://example.com/"\n'
    )
    (sf_export_dir / "meta_description_over_985_pixels.csv").write_text(
        '"Address"\n"https://example.com/product"\n'
    )

    header, body = detail_table(MetaDescriptionService("test-job", sf_export_dir).generate())

    assert header == ("URL", "Inlinks", "Impressions", "Clicks")
    assert body == [("https://example.com/", 5, 100, 10)]


def test_meta_description_with_non_indexable(sf_export_dir: Path) -> None:
    """A Non-Indexable page is dropped; this service declares INDEXABLE_ONLY."""
    (sf_export_dir / "internal_all.csv").write_text(
        '"Address","Status Code","Indexability","Inlinks"\n'
        '"https://example.com/indexable","200","Indexable","5"\n'
        '"https://example.com/non-indexable","200","Non-Indexable","2"\n'
    )
    (sf_export_dir / "meta_description_missing.csv").write_text(
        '"Address"\n"https://example.com/indexable"\n"https://example.com/non-indexable"\n'
    )

    header, body = detail_table(MetaDescriptionService("test-job", sf_export_dir).generate())

    assert header == ("URL", "Inlinks", "Impressions", "Clicks")
    assert body == [("https://example.com/indexable", 5, NOT_MEASURED, NOT_MEASURED)]
