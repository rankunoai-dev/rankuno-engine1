"""Row-count and header assertions for overview_report masterfile service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_overview_report import OverviewReportService
from tests.modules.seo.deliverables.conftest import detail_table, first_cell, sheet_names


@pytest.fixture
def sf_export_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_overview_report_empty(sf_export_dir: Path) -> None:
    service = OverviewReportService("test-job", sf_export_dir)
    payload = service.generate()

    assert detail_table(payload) == ((), [])
    assert first_cell(payload) == "No issues found"
    assert sheet_names(payload)[0] == "Overview"


def test_overview_report_metadata(sf_export_dir: Path) -> None:
    service = OverviewReportService("test-job", sf_export_dir)
    metadata = service.metadata
    assert metadata.slug == "overview_report"
    assert metadata.sheets == 4
    assert metadata.is_complex is True
