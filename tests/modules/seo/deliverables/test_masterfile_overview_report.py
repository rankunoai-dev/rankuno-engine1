"""Tests for overview_report masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_overview_report import OverviewReportService


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_overview_report_empty(sf_export_dir: Path) -> None:
    service = OverviewReportService("test-job", sf_export_dir)
    result = service.generate()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_overview_report_metadata(sf_export_dir: Path) -> None:
    service = OverviewReportService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "overview_report"
    assert metadata.sheets == 4
    assert metadata.is_complex is True
