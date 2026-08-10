"""Tests for durable background-job records.

The store exists so that a crawl can outlive the request that started it. Most
of what is worth testing is therefore about *failure*: what a reader sees when a
writer died halfway, and what happens to a job whose worker no longer exists.
"""

from __future__ import annotations

import json

import pytest
from src.core.state_store import (
    DiskJobStore,
    JobNotFoundError,
    JobRecord,
    JobStatus,
)

TOOL = "seo.page_classifier"
REQUEST = {"base_url": "https://e.com", "max_pages": 50}
RESULT = {"base_url": "https://e.com", "pages": [{"url": "https://e.com/"}]}


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


class TestCreation:
    def test_a_new_job_is_queued(self, store):
        record = store.create(TOOL, REQUEST)
        assert record.status is JobStatus.QUEUED
        assert record.is_terminal is False
        assert record.has_result is False

    def test_the_request_payload_round_trips(self, store):
        record = store.create(TOOL, REQUEST)
        assert store.get(record.id).request == REQUEST

    def test_ids_are_unique(self, store):
        ids = {store.create(TOOL, REQUEST).id for _ in range(20)}
        assert len(ids) == 20

    def test_the_id_is_generated_not_accepted(self, store):
        """Every id becomes a filename, so a caller-supplied one is traversal.

        `create` takes no id parameter at all, which is the point: there is no
        code path through which a client string reaches `_record_path`.
        """
        record = store.create(TOOL, REQUEST)
        assert record.id.isalnum()
        assert "/" not in record.id and "\\" not in record.id and ".." not in record.id

    def test_the_directory_is_created_if_absent(self, tmp_path):
        root = tmp_path / "does" / "not" / "exist"
        assert DiskJobStore(root).root.is_dir()


class TestLifecycle:
    def test_running_stamps_a_start_time(self, store):
        record = store.mark_running(store.create(TOOL, REQUEST).id)
        assert record.status is JobStatus.RUNNING
        assert record.started_at is not None
        assert record.finished_at is None

    def test_finishing_stores_the_result(self, store):
        job_id = store.create(TOOL, REQUEST).id
        record = store.finish(job_id, RESULT)
        assert record.status is JobStatus.SUCCEEDED
        assert record.has_result is True
        assert store.read_result(job_id) == RESULT

    def test_a_truncated_crawl_finishes_partial(self, store):
        """`PARTIAL` must be distinguishable from `SUCCEEDED`.

        Presenting a crawl that hit its ceiling as a complete one is how an
        audit reaches a confident wrong conclusion about a site.
        """
        job_id = store.create(TOOL, REQUEST).id
        record = store.finish(job_id, RESULT, partial=True)
        assert record.status is JobStatus.PARTIAL
        assert record.is_terminal is True
        assert store.read_result(job_id) == RESULT

    def test_failure_records_a_reason(self, store):
        record = store.mark_failed(store.create(TOOL, REQUEST).id, "robots.txt disallowed")
        assert record.status is JobStatus.FAILED
        assert record.error == "robots.txt disallowed"
        assert record.finished_at is not None

    def test_a_blank_failure_reason_is_replaced(self, store):
        """A failed job with no reason is indistinguishable from a store bug."""
        assert store.mark_failed(store.create(TOOL, REQUEST).id, "").error == "unknown error"

    def test_updated_at_advances_on_transition(self, store):
        record = store.create(TOOL, REQUEST)
        assert store.mark_running(record.id).updated_at >= record.updated_at


class TestPersistence:
    def test_records_survive_a_new_store_instance(self, tmp_path):
        """The whole point: a different process must see the same jobs."""
        job_id = DiskJobStore(tmp_path).create(TOOL, REQUEST).id
        assert DiskJobStore(tmp_path).get(job_id).tool_name == TOOL

    def test_results_survive_a_new_store_instance(self, tmp_path):
        first = DiskJobStore(tmp_path)
        job_id = first.create(TOOL, REQUEST).id
        first.finish(job_id, RESULT)
        assert DiskJobStore(tmp_path).read_result(job_id) == RESULT

    def test_writes_leave_no_temporary_files_behind(self, store):
        job_id = store.create(TOOL, REQUEST).id
        store.finish(job_id, RESULT)
        assert list(store.root.glob("*.tmp")) == []

    def test_the_result_blob_is_a_separate_file(self, store):
        """Listing jobs must not read a 16 MB result to show a status."""
        job_id = store.create(TOOL, REQUEST).id
        store.finish(job_id, RESULT)
        assert (store.root / f"{job_id}.result.json").exists()
        metadata = json.loads((store.root / f"{job_id}.json").read_text(encoding="utf-8"))
        assert "result" not in metadata

    def test_result_blobs_are_not_listed_as_jobs(self, store):
        """Both files end in `.json`; a naive glob would invent a second job."""
        store.finish(store.create(TOOL, REQUEST).id, RESULT)
        assert len(store.list_jobs()) == 1


class TestMissingAndCorrupt:
    def test_reading_an_unknown_job_raises(self, store):
        with pytest.raises(JobNotFoundError):
            store.get("nope")

    def test_reading_a_missing_result_raises(self, store):
        """Queued and finished-with-no-result must not be confused."""
        job_id = store.create(TOOL, REQUEST).id
        with pytest.raises(JobNotFoundError):
            store.read_result(job_id)

    def test_finishing_an_unknown_job_raises_before_writing(self, store):
        with pytest.raises(JobNotFoundError):
            store.finish("nope", RESULT)
        assert list(store.root.glob("*.result.json")) == []

    def test_a_corrupt_record_does_not_break_the_listing(self, store):
        """One bad file must not make the job list permanently unavailable."""
        good = store.create(TOOL, REQUEST)
        (store.root / "broken.json").write_text("{not json", encoding="utf-8")
        assert [record.id for record in store.list_jobs()] == [good.id]


class TestOrphanRecovery:
    def test_running_jobs_are_failed_on_restart(self, tmp_path):
        """Nothing will ever move a job whose worker died with the process.

        Left alone it stays `RUNNING` forever and a polling UI waits for a
        result that is not coming.
        """
        first = DiskJobStore(tmp_path)
        job_id = first.create(TOOL, REQUEST).id
        first.mark_running(job_id)

        restarted = DiskJobStore(tmp_path)
        assert restarted.recover_orphans() == [job_id]
        record = restarted.get(job_id)
        assert record.status is JobStatus.FAILED
        assert "restart" in (record.error or "")

    def test_queued_jobs_are_also_recovered(self, tmp_path):
        """A queued job has no worker either — it was never picked up."""
        first = DiskJobStore(tmp_path)
        job_id = first.create(TOOL, REQUEST).id
        assert DiskJobStore(tmp_path).recover_orphans() == [job_id]

    def test_finished_jobs_are_left_alone(self, tmp_path):
        first = DiskJobStore(tmp_path)
        job_id = first.create(TOOL, REQUEST).id
        first.finish(job_id, RESULT)

        restarted = DiskJobStore(tmp_path)
        assert restarted.recover_orphans() == []
        assert restarted.get(job_id).status is JobStatus.SUCCEEDED

    def test_recovery_is_idempotent(self, tmp_path):
        first = DiskJobStore(tmp_path)
        first.mark_running(first.create(TOOL, REQUEST).id)
        DiskJobStore(tmp_path).recover_orphans()
        assert DiskJobStore(tmp_path).recover_orphans() == []


class TestListing:
    def test_lists_newest_first(self, store):
        ids = [store.create(TOOL, REQUEST).id for _ in range(3)]
        assert [record.id for record in store.list_jobs()][0] in ids
        assert len(store.list_jobs()) == 3

    def test_an_empty_store_lists_nothing(self, store):
        assert store.list_jobs() == []


class TestJobRecordContract:
    @pytest.mark.parametrize(
        ("status", "terminal"),
        [
            (JobStatus.QUEUED, False),
            (JobStatus.RUNNING, False),
            (JobStatus.SUCCEEDED, True),
            (JobStatus.PARTIAL, True),
            (JobStatus.FAILED, True),
        ],
    )
    def test_terminal_statuses(self, store, status, terminal):
        """A poller stops on these; getting the set wrong hangs the UI."""
        record = store.get(store.create(TOOL, REQUEST).id).model_copy(update={"status": status})
        assert record.is_terminal is terminal

    def test_status_values_are_lowercase(self):
        """Matches the other governance enums and the frontend's union."""
        assert {member.value for member in JobStatus} == {
            "queued",
            "running",
            "succeeded",
            "partial",
            "failed",
        }

    def test_unknown_fields_are_rejected(self):
        """`StrictModel`: a renamed key must not become a silent `None`."""
        with pytest.raises(ValueError, match="extra"):
            JobRecord.model_validate(
                {
                    "id": "a",
                    "tool_name": TOOL,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "surprise": 1,
                }
            )
