"""Row-count and header assertions for content_issues masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_content_issues import ContentIssuesService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_content_issues_empty(sf_export_dir: Path) -> None:
    service = ContentIssuesService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No content issues data found"
    assert sheet_names(payload)[0] == "Content Issues"


def test_content_issues_metadata(sf_export_dir: Path) -> None:
    service = ContentIssuesService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "content_issues"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
