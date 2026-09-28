"""Row-count and header assertions for hreflang masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_hreflang import HrefLangService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_hreflang_empty(sf_export_dir: Path) -> None:
    service = HrefLangService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No hreflang data found"
    assert sheet_names(payload)[0] == "Summary"


def test_hreflang_metadata(sf_export_dir: Path) -> None:
    service = HrefLangService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "hreflang"
    assert metadata.sheets == 8
    assert metadata.is_complex is True
