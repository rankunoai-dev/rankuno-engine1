"""The deletion-password gate every write to an existing crawl job passes through (ADR 0042).

Why one module: the delete route already had a per-job lock. Cancel, retry,
reparse, resume, reconciliation, the GSC attachments and the deliverable
builds must not each grow a copy of the rate limit, the lock and the verify.
A copy that drifts is a route that quietly skips the lock.

Why it is synchronous: PBKDF2 at 210,000 iterations costs about a quarter
second of CPU. Async routes call `enforce_job_password` through
`asyncio.to_thread` so the event loop is not held. The synchronous `def`
routes call it directly, because FastAPI already runs them on a worker thread.

Order of checks, which callers must not reorder: the rate limit first, so a
guesser spends attempts whether or not the password is right; then a missing
password, which is not a guess and costs nothing; then the lock, which refuses
even the right password; then the verify.
"""

from __future__ import annotations

import math

from fastapi import HTTPException, status
from pydantic import SecretStr

from src.core.auth import hash_password, verify_password
from src.core.job_password import MAX_DELETION_PASSWORD_LENGTH
from src.core.logger import get_logger
from src.core.postgres_store import PostgresJobStore
from src.core.rate_limiter import RateLimiterRegistry
from src.core.state_store import DiskJobStore, JobRecord, JobStore

__all__ = [
    "RATE_LIMITED_DETAIL",
    "enforce_job_password",
    "header_password",
    "require_job_password",
]

_logger = get_logger(__name__)

RATE_LIMITED_DETAIL = "too many delete attempts; wait a moment and try again"
"""The 429 text for both the per-minute buckets and an active lock.

Kept as the delete route's original wording so existing clients see no change.
"""

_DUMMY_HASH = hash_password("no-job-has-this-delete-password")
"""Checked against on a locked job, so a lock costs the same PBKDF2 time as a real check.

Without it a locked answer returns in microseconds and the response time reveals
that the job is locked, and therefore that the password was not tried.
"""

_PER_JOB_PER_MINUTE = 5
_PER_OPERATOR_PER_MINUTE = 20


def header_password(value: str | None) -> SecretStr | None:
    """Wrap the `X-Deletion-Password` header value, treating an empty one as absent.

    The raw string is wrapped at once so it is masked in any `repr` or log that
    might catch the local variable.

    A value longer than `MAX_DELETION_PASSWORD_LENGTH` is refused with `422`
    before any hashing or bucket. Creation caps a password at that length, so
    such a value can never match, and an unbounded header would otherwise be
    hashed in full on every attempt.

    Raises:
        HTTPException: `422` for a value longer than the maximum.
    """
    if not value:
        return None
    if len(value) > MAX_DELETION_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="job password header is too long",
        )
    return SecretStr(value)


def _lockout_store(store: JobStore) -> DiskJobStore:
    """The disk store that holds a job's lock counter.

    The counter is a disk sidecar by design (see `DiskJobStore.record_failed_delete`),
    so under Postgres it lives on the disk fallback.

    Fails closed. A store with no disk sidecar would take guesses with no lock
    at all, so the gated write is refused with `503` rather than run unlocked.
    The rate limiter alone is not an acceptable substitute for the lock.

    Raises:
        HTTPException: `503` when the store cannot hold the lock counter.
    """
    if isinstance(store, DiskJobStore):
        return store
    if isinstance(store, PostgresJobStore) and isinstance(store.fallback_store, DiskJobStore):
        return store.fallback_store
    _logger.error("job_password_lock_unavailable", extra={"store": type(store).__name__})
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="job lock unavailable; write refused",
    )


def _locked(job_id: str, operator_id: str, retry_after_s: float) -> HTTPException:
    """The `429` for a locked job, with the seconds left in `Retry-After`."""
    seconds = math.ceil(retry_after_s)
    _logger.warning(
        "job_password_locked",
        extra={"job_id": job_id, "operator_id": operator_id, "retry_after_s": seconds},
    )
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMITED_DETAIL,
        headers={"Retry-After": str(seconds)},
    )


def require_job_password(
    *,
    limiter: RateLimiterRegistry,
    store: JobStore,
    record: JobRecord,
    operator_id: str,
    password: SecretStr | None,
    action: str,
) -> None:
    """Gate one write to an existing job. A job with no hash is not gated (D1).

    Callers have already authenticated the operator and checked the org. The
    hash check lives here, so a route cannot forget it and gate a job that has
    no password, which would make an unprotected job unwritable.

    Raises:
        HTTPException: as `enforce_job_password`.
    """
    if record.password_hash is None:
        return
    enforce_job_password(
        limiter=limiter,
        store=store,
        job_id=record.id,
        operator_id=operator_id,
        password_hash=record.password_hash,
        password=password,
        action=action,
    )


def enforce_job_password(
    *,
    limiter: RateLimiterRegistry,
    store: JobStore,
    job_id: str,
    operator_id: str,
    password_hash: str,
    password: SecretStr | None,
    action: str,
) -> None:
    """Admit one write to a password-protected job, or refuse it.

    Args:
        limiter: The principal rate-limit registry (`ApiState.principal_rate_limiter`).
        store: The job store, used to reach the lock counter.
        job_id: The job being written.
        operator_id: The verified operator. Keys the buckets, so one operator
            cannot spend another's attempts.
        password_hash: The job's stored PBKDF2 hash.
        password: The password the caller supplied, or `None` if none was.
        action: The route name, for logs only.

    Raises:
        HTTPException: `429` when a bucket is empty or the job is locked (with
            `Retry-After` for a lock), `403` for a missing or wrong password.
    """
    # The bucket key keeps its historical `delete:` prefix. Renaming it would
    # reset every operator's live budget on deploy, and it now bounds every gated write.
    per_job = limiter.get_or_create(
        f"delete:{operator_id}:{job_id}",
        requests_per_minute=_PER_JOB_PER_MINUTE,
        burst=_PER_JOB_PER_MINUTE,
    )
    per_operator = limiter.get_or_create(
        f"delete-op:{operator_id}",
        requests_per_minute=_PER_OPERATOR_PER_MINUTE,
        burst=_PER_OPERATOR_PER_MINUTE,
    )
    if not per_job.try_acquire() or not per_operator.try_acquire():
        _logger.warning(
            "job_password_rate_limited",
            extra={"job_id": job_id, "operator_id": operator_id, "action": action},
        )
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    if password is None:
        _logger.warning(
            "job_password_missing",
            extra={"job_id": job_id, "operator_id": operator_id, "action": action},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="job password required")

    raw = password.get_secret_value()
    lockout = _lockout_store(store)
    remaining_s = lockout.delete_lockout_remaining_s(job_id)
    if remaining_s > 0:
        verify_password(raw, _DUMMY_HASH)
        raise _locked(job_id, operator_id, remaining_s)

    if not verify_password(raw, password_hash):
        _logger.warning(
            "job_password_wrong",
            extra={"job_id": job_id, "operator_id": operator_id, "action": action},
        )
        locked_for = lockout.record_failed_delete(job_id)
        if locked_for > 0:
            raise _locked(job_id, operator_id, locked_for)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="incorrect password")

    # Cleared only on a correct password, so a guesser cannot reset the count.
    lockout.clear_delete_lockout(job_id)
