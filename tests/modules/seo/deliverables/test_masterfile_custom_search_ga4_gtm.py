"""Row-count and header assertions for custom_search_ga4_gtm masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_custom_search_ga4_gtm import CustomSearchGA4GTMService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_custom_search_ga4_gtm_empty(sf_export_dir: Path) -> None:
    service = CustomSearchGA4GTMService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "Not measured by this crawl"
    assert sheet_names(payload)[0] == "GA4 GTM"


def test_custom_search_ga4_gtm_metadata(sf_export_dir: Path) -> None:
    service = CustomSearchGA4GTMService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "custom_search_ga4_gtm"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
