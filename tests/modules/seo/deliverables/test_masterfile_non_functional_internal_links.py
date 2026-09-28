"""Row-count and header assertions for non_functional_internal_links masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_non_functional_internal_links import (
    NonFunctionalInternalLinksService,
)
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_non_functional_internal_links_empty(sf_export_dir: Path) -> None:
    service = NonFunctionalInternalLinksService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No broken internal links found"
    assert sheet_names(payload)[0] == "Broken Links"


def test_non_functional_internal_links_metadata(sf_export_dir: Path) -> None:
    service = NonFunctionalInternalLinksService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "non_functional_internal_links"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
