"""Tests for duplicate_content masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_duplicate_content import DuplicateContentService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_duplicate_content_empty(sf_export_dir: Path) -> None:
    service = DuplicateContentService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_duplicate_content_metadata(sf_export_dir: Path) -> None:
    service = DuplicateContentService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "duplicate_content"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
