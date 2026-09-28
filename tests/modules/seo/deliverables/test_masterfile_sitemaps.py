"""Row-count and header assertions for sitemaps masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_sitemaps import SitemapsService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_sitemaps_empty(sf_export_dir: Path) -> None:
    service = SitemapsService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No sitemaps data found"
    assert sheet_names(payload)[0] == "Sitemaps"


def test_sitemaps_metadata(sf_export_dir: Path) -> None:
    service = SitemapsService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "sitemaps"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
