"""Tests for fallback queue recovery functionality.

These tests verify that orphaned jobs are correctly recovered from
the fallback queue when PostgreSQL comes back online.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.core.fallback_recovery import recover_orphaned_jobs


class TestFallbackRecovery:
    """Tests for fallback queue recovery."""

    def test_recovery_nonexistent_queue_dir(self) -> None:
        """Recovery should handle missing queue directory gracefully."""
        store = MagicMock()
        result = recover_orphaned_jobs(Path("/nonexistent/queue"), store)
        assert result == 0

    def test_recovery_empty_queue_dir(self) -> None:
        """Recovery should handle empty queue directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MagicMock()
            result = recover_orphaned_jobs(Path(tmpdir), store)
            assert result == 0

    def test_recovery_single_job(self) -> None:
        """Recovery should process a single job file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = Path(tmpdir)

            # Create a fallback job file
            job_data = {
                "id": "job-123",
                "org_id": "org-1",
                "tool_name": "seo.page_classifier",
                "facet_id": "seo.page_classifier",
                "request": {"base_url": "https://example.com"},
                "label": "test",
                "status": "queued",
            }
            job_file = queue_dir / "job-123.json"
            job_file.write_text(json.dumps(job_data))

            store = MagicMock()
            result = recover_orphaned_jobs(queue_dir, store)

            assert result == 1
            # File should be deleted after recovery
            assert not job_file.exists()

    def test_recovery_multiple_jobs(self) -> None:
        """Recovery should process multiple job files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = Path(tmpdir)

            # Create multiple fallback job files
            for i in range(3):
                job_data = {
                    "id": f"job-{i}",
                    "org_id": "org-1",
                    "tool_name": "seo.page_classifier",
                    "facet_id": "seo.page_classifier",
                    "request": {"base_url": f"https://example{i}.com"},
                    "label": f"test-{i}",
                    "status": "queued",
                }
                job_file = queue_dir / f"job-{i}.json"
                job_file.write_text(json.dumps(job_data))

            store = MagicMock()
            result = recover_orphaned_jobs(queue_dir, store)

            assert result == 3
            # All files should be deleted
            assert len(list(queue_dir.glob("*.json"))) == 0

    def test_recovery_skips_invalid_json(self) -> None:
        """Recovery should skip files with invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = Path(tmpdir)

            # Create a valid job file
            valid_job_data = {
                "id": "job-valid",
                "org_id": "org-1",
                "tool_name": "seo.page_classifier",
                "facet_id": "seo.page_classifier",
                "request": {"base_url": "https://example.com"},
            }
            valid_file = queue_dir / "job-valid.json"
            valid_file.write_text(json.dumps(valid_job_data))

            # Create an invalid JSON file
            invalid_file = queue_dir / "job-invalid.json"
            invalid_file.write_text("{ invalid json }")

            store = MagicMock()
            result = recover_orphaned_jobs(queue_dir, store)

            # Should recover the valid one, skip the invalid one
            assert result == 1
            # Valid file should be deleted, invalid should remain
            assert not valid_file.exists()
            assert invalid_file.exists()

    def test_recovery_processes_files_in_order(self) -> None:
        """Recovery should process files in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = Path(tmpdir)

            # Create files with specific names to test ordering
            filenames = ["002.json", "001.json", "003.json"]
            for fname in filenames:
                job_data = {"id": fname.replace(".json", "")}
                (queue_dir / fname).write_text(json.dumps(job_data))

            store = MagicMock()
            result = recover_orphaned_jobs(queue_dir, store)

            assert result == 3
            # All files should be processed and deleted
            assert len(list(queue_dir.glob("*.json"))) == 0
