"""Tests for page_titles masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_page_titles import PageTitlesService

__all__ = ["test_page_titles_empty_export", "test_page_titles_metadata"]


@pytest.fixture
def sf_export_dir() -> Path:
    """Temporary Screaming Frog export directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_page_titles_empty_export(sf_export_dir: Path) -> None:
    """Page titles service with no CSV files should produce empty workbook."""
    service = PageTitlesService("test-job", sf_export_dir)
    result = service.generate()

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_page_titles_metadata() -> None:
    """Page titles service should declare correct metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = PageTitlesService("test-job", Path(tmpdir))
        metadata = service.metadata

        assert metadata.slug == "page_titles"
        assert metadata.label == "Page Titles"
        assert metadata.sheets == 1
        assert metadata.is_complex is False
