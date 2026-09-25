"""Tests for directives masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_directives import DirectivesService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_directives_empty(sf_export_dir: Path) -> None:
    service = DirectivesService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_directives_metadata(sf_export_dir: Path) -> None:
    service = DirectivesService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "directives"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
