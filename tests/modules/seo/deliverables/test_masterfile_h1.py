"""Tests for H1 masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_h1 import H1Service


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_h1_empty(sf_export_dir: Path) -> None:
    """H1 service with no CSV files should produce empty workbook."""
    service = H1Service("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_h1_metadata(sf_export_dir: Path) -> None:
    """H1 service should declare correct metadata."""
    service = H1Service("test-job", sf_export_dir)
    metadata = service.metadata

    assert metadata.slug == "h1"
    assert metadata.label == "H1 Tags"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
