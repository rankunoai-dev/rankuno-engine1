"""Celery worker task for executing crawl jobs.

Worker tasks that run in Celery processes to execute page classification
crawls with automatic cost refund on failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.celery_config import get_celery_app
from src.core.logger import get_logger
from src.core.state_store import JobNotFoundError

if TYPE_CHECKING:
    from celery import Task

__all__ = ["execute_crawl"]

_logger = get_logger(__name__)

app = get_celery_app()


# `celery` ships no type information (see the `celery.*` mypy override in
# `pyproject.toml`), so `app.task` is `Any` and mypy cannot see through the
# decorator to confirm the wrapped function stays typed. The signature below is
# annotated in full; only mypy's view of the decorator is suppressed.
@app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[untyped-decorator]
def execute_crawl(self: Task, job_id: str) -> dict[str, str]:
    """Execute a crawl job from the queue.

    Loads the job from the store, runs the page classifier, and marks
    the job as completed. On failure, refunds the cost ledger entry.

    Args:
        self: The bound task instance supplied by `bind=True`. Needed for
            `self.retry`, which is the only way a task can reschedule itself.
        job_id: Job ID to execute.

    Returns:
        Result dict with job_id and status.

    Raises:
        JobNotFoundError: If job not found in store.
    """
    from src.core.state_store import JobStore, get_job_store

    job_store: JobStore = get_job_store()

    try:
        # Load job record
        job = job_store.get(job_id)
        _logger.info(
            "job_execution_started",
            extra={"job_id": job_id, "status": job.status.value},
        )

        # Mark running
        job_store.mark_running(job_id)

        # Execute the crawl (deferred: full implementation in Phase 2c)
        # For now, just mark as succeeded
        result = {"crawl_complete": True, "pages_found": 0}

        # Mark finished
        job_store.finish(job_id, result)

        _logger.info("job_execution_succeeded", extra={"job_id": job_id})

        return {"job_id": job_id, "status": "succeeded"}

    except JobNotFoundError:
        _logger.error("job_execution_not_found", extra={"job_id": job_id})
        raise

    except Exception as err:
        _logger.error(
            "job_execution_failed",
            extra={"job_id": job_id, "error": str(err)},
        )

        try:
            # Mark job as failed
            job_store.mark_failed(job_id, str(err))

            # Refund cost on failure
            _refund_job_cost(job_id)

        except Exception as refund_err:
            _logger.error(
                "job_cost_refund_failed",
                extra={"job_id": job_id, "error": str(refund_err)},
            )

        # Retry with exponential backoff. `self.retry` normally raises `Retry`
        # itself; the explicit `raise ... from err` covers the path where it
        # returns the exception instead of raising it, and keeps the original
        # failure as the cause either way.
        raise self.retry(exc=err) from err


def _refund_job_cost(job_id: str) -> None:
    """Refund the cost ledger entry for a failed job.

    Args:
        job_id: Job ID to refund.
    """
    # Deferred: full implementation requires PostgreSQL connection
    # For Phase 2c, this would query cost_ledger and mark as refunded
    _logger.debug("job_cost_refund_recorded", extra={"job_id": job_id})


@app.task(bind=True)  # type: ignore[untyped-decorator]
def recover_job(self: Task, job_id: str) -> dict[str, object]:
    """Attempt to recover a failed or abandoned job.

    Called when a job times out or is manually retried. Attempts to
    resume work from the last checkpoint.

    Args:
        self: The bound task instance supplied by `bind=True`.
        job_id: Job ID to recover.

    Returns:
        Recovery result dict.
    """
    from src.core.state_store import JobStore, get_job_store

    job_store: JobStore = get_job_store()

    try:
        # Existence check, not a value fetch: `get` raises `JobNotFoundError`, so
        # a recovery request for an unknown job id fails loudly instead of
        # reporting `recovered: False` as though the job merely lacked a
        # checkpoint. The record itself is not needed until Phase 2c resumes it.
        job_store.get(job_id)
        checkpoint = job_store.read_checkpoint(job_id)

        if not checkpoint:
            _logger.warning(
                "job_recovery_no_checkpoint",
                extra={"job_id": job_id},
            )
            return {"job_id": job_id, "recovered": False}

        _logger.info(
            "job_recovery_started",
            extra={"job_id": job_id},
        )

        # Mark running again
        job_store.mark_running(job_id)

        # Deferred: resume from checkpoint (Phase 2c full implementation)

        return {"job_id": job_id, "recovered": True}

    except Exception as err:
        _logger.error(
            "job_recovery_failed",
            extra={"job_id": job_id, "error": str(err)},
        )
        raise
