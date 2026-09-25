"""Tests for custom_search_og_twitter masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_custom_search_og_twitter import CustomSearchOGTwitterService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_custom_search_og_twitter_empty(sf_export_dir: Path) -> None:
    service = CustomSearchOGTwitterService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_custom_search_og_twitter_metadata(sf_export_dir: Path) -> None:
    service = CustomSearchOGTwitterService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "custom_search_og_twitter"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
