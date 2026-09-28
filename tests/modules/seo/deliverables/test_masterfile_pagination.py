"""Row-count and header assertions for pagination masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_pagination import PaginationService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_pagination_empty(sf_export_dir: Path) -> None:
    service = PaginationService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No pagination data found"
    assert sheet_names(payload)[0] == "Pagination"


def test_pagination_metadata(sf_export_dir: Path) -> None:
    service = PaginationService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "pagination"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
