"""Tests for functional_internal_links masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_functional_internal_links import FunctionalInternalLinksService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_functional_internal_links_empty(sf_export_dir: Path) -> None:
    service = FunctionalInternalLinksService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_functional_internal_links_metadata(sf_export_dir: Path) -> None:
    service = FunctionalInternalLinksService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "functional_internal_links"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
