"""Tests for pagination masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_pagination import PaginationService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_pagination_empty(sf_export_dir: Path) -> None:
    service = PaginationService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_pagination_metadata(sf_export_dir: Path) -> None:
    service = PaginationService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "pagination"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
