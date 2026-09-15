"""Tests for `run_build` (cycle 0087).

Exercises the state transitions a build-triggering API endpoint depends on:
`queued` -> `running` -> a terminal status, with the workbook written under
`deliverable_store.root / deliverable_id` and a distinguishable failure for
the page-limit case. No HTTP layer involved - `deliverables_routes.py` has
its own tests for that.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.core.state_store import DiskJobStore, JobStatus
from src.modules.seo.contracts.audit import AuditDataset, AuditPage, AuditSource, Coverage
from src.modules.seo.contracts.issue_ids import IssueId
from src.modules.seo.deliverables.build_runner import run_build
from src.modules.seo.deliverables.workbook import MAX_PAGES_PER_WORKBOOK

PRODUCED_AT = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def identity(url: str) -> str:
    return url


def full_coverage() -> dict[IssueId, Coverage]:
    return dict.fromkeys(IssueId, Coverage.NOT_MEASURED)


def make_dataset(**overrides: object) -> AuditDataset:
    base: dict[str, object] = {
        "source": AuditSource.ENGINE,
        "site": "example.com",
        "produced_at": PRODUCED_AT,
        "pages": (AuditPage(url="https://example.com/"),),
        "issues": {},
        "coverage": full_coverage(),
    }
    base.update(overrides)
    return AuditDataset.model_validate(base)


@pytest.fixture
def store(tmp_path: Path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "deliverable_jobs")


def create_job(store: DiskJobStore) -> str:
    return store.create("seo.deliverables.workbook", {}, org_id="acme").id


class TestSuccess:
    def test_a_successful_build_finishes_with_the_workbook_filename(
        self, store: DiskJobStore
    ) -> None:
        job_id = create_job(store)

        run_build(store, job_id, lambda: make_dataset(), identity, None, "engine")

        record = store.get(job_id)
        assert record.status is JobStatus.SUCCEEDED
        assert record.has_result
        result = store.read_result(job_id)
        assert result["source"] == "engine"
        assert result["pages"] == 1
        workbook_path = store.root / job_id / str(result["filename"])
        assert workbook_path.is_file()

    def test_the_workbook_lives_under_the_jobs_own_subdirectory(self, store: DiskJobStore) -> None:
        job_id = create_job(store)
        run_build(store, job_id, lambda: make_dataset(), identity, None, "engine")
        result = store.read_result(job_id)
        workbook_path = store.root / job_id / str(result["filename"])
        assert workbook_path.parent == store.root / job_id


class TestFailure:
    def test_a_page_limit_failure_is_distinguishable_in_the_error_text(
        self, store: DiskJobStore
    ) -> None:
        job_id = create_job(store)

        class _OversizedTuple(tuple):
            def __len__(self) -> int:
                return MAX_PAGES_PER_WORKBOOK + 1

        oversized = make_dataset()
        oversized = oversized.model_copy(update={"pages": _OversizedTuple(oversized.pages)})

        run_build(store, job_id, lambda: oversized, identity, None, "engine")

        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert record.error is not None
        assert "too many pages" in record.error

    def test_a_dataset_loader_failure_marks_the_job_failed_not_crashed(
        self, store: DiskJobStore
    ) -> None:
        job_id = create_job(store)

        def _boom() -> AuditDataset:
            raise ValueError("no profiles to export")

        run_build(store, job_id, _boom, identity, None, "engine")

        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert record.error == "no profiles to export"

    def test_an_unexpected_exception_is_caught_not_leaked(self, store: DiskJobStore) -> None:
        job_id = create_job(store)

        def _boom() -> AuditDataset:
            raise RuntimeError("something unrelated broke")

        run_build(store, job_id, _boom, identity, None, "engine")  # must not raise

        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert "RuntimeError" in (record.error or "")
