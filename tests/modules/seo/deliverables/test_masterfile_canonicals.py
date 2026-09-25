"""Tests for canonicals masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_canonicals import CanonicalService


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_canonicals_empty(sf_export_dir: Path) -> None:
    """Canonical service with no CSV files should produce empty workbook."""
    service = CanonicalService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_canonicals_metadata(sf_export_dir: Path) -> None:
    """Canonical service should declare correct metadata."""
    service = CanonicalService("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "canonicals"
    assert metadata.label == "Canonical Tags"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
