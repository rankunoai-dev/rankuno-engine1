"""Row-count and header assertions for canonicals masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_canonicals import CanonicalService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_canonicals_empty(sf_export_dir: Path) -> None:
    """Canonical service with no CSV files should produce empty workbook."""
    service = CanonicalService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No canonical tag data found"
    assert sheet_names(payload)[0] == "Canonicals"


def test_canonicals_metadata(sf_export_dir: Path) -> None:
    """Canonical service should declare correct metadata."""
    service = CanonicalService("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "canonicals"
    assert metadata.label == "Canonical Tags"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
