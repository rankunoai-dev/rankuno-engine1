"""Row-count and header assertions for structured_data masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_structured_data import StructuredDataService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_structured_data_empty(sf_export_dir: Path) -> None:
    service = StructuredDataService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No structured data found"
    assert sheet_names(payload)[0] == "Summary"


def test_structured_data_metadata(sf_export_dir: Path) -> None:
    service = StructuredDataService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "structured_data"
    assert metadata.sheets == 8
    assert metadata.is_complex is True
