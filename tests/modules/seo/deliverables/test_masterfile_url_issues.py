"""Tests for url_issues masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_url_issues import URLIssuesService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_url_issues_empty(sf_export_dir: Path) -> None:
    service = URLIssuesService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_url_issues_metadata(sf_export_dir: Path) -> None:
    service = URLIssuesService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "url_issues"
    assert metadata.sheets == 1
    assert metadata.is_complex is False
