"""Tests for lorem_ipsum masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_lorem_ipsum import LoremIpsumService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_lorem_ipsum_empty(sf_export_dir: Path) -> None:
    service = LoremIpsumService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_lorem_ipsum_metadata(sf_export_dir: Path) -> None:
    service = LoremIpsumService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "lorem_ipsum"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
