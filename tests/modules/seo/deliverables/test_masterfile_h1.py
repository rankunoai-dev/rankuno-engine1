"""Row-count and header assertions for H1 masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_h1 import H1Service
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_h1_empty(sf_export_dir: Path) -> None:
    """H1 service with no CSV files should produce empty workbook."""
    service = H1Service("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No H1 tag data found"
    assert sheet_names(payload)[0] == "H1 Tags"


def test_h1_metadata(sf_export_dir: Path) -> None:
    """H1 service should declare correct metadata."""
    service = H1Service("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "h1"
    assert metadata.label == "H1 Tags"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
