"""Tests for custom_extraction masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_custom_extraction import CustomExtractionService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_custom_extraction_empty(sf_export_dir: Path) -> None:
    service = CustomExtractionService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_custom_extraction_metadata(sf_export_dir: Path) -> None:
    service = CustomExtractionService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "custom_extraction"
    assert metadata.is_complex is True
