"""The worker daemon's one outbound connection: to its own cloud API (ADR 0015).

`BaseAPIClient` applies here in full, unlike `ScreamingFrogControlTool`
(ADR 0013 decision 3, which launches a local executable, not an HTTP
request): every call this daemon makes leaves the machine over HTTPS, so it
gets `BaseAPIClient.call()`'s standard rate limiting, retry, and audit
logging, the same as any other connector (CLAUDE.md §1.5).

`UrlSafetyPolicy` is deliberately **not** applied to the cloud API's own
base URL. That guard exists for arbitrary, operator- or client-supplied
crawl targets; this client's target is a single fixed, operator-provisioned
endpoint (`Settings.worker_cloud_api_base_url`), not user input — the same
reasoning `GscApiClient` already applies to Google's fixed API host.
`UrlSafetyPolicy` *is* still applied, separately, to the `seed_url` inside a
claimed job's envelope (ADR 0015 condition 8) — that happens in
`screaming_frog_control.worker_daemon`, not here.

No circuit breaker for this channel (ADR 0015 condition 10 — an accepted
gap, not an oversight). `worker_daemon`'s poll loop supplies condition 10's
bounded exponential backoff instead, one layer up from this client.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import Settings
from src.core.errors import WorkerCredentialRejectedError
from src.core.logger import get_logger
from src.core.worker_dispatch_schemas import SignedDispatchAssignment, WorkerJobPhase
from src.integrations.base_client import BaseAPIClient

__all__ = ["WorkerCloudClient"]

_logger = get_logger("integrations.worker_cloud_client")

_REQUEST_TIMEOUT_S = 30.0
"""Generous relative to a poll/upload call, small relative to a crawl."""

_CREDENTIAL_REJECTED_STATUSES = frozenset({401, 403})
"""Statuses that mean "this credential will never work", not "try later".

Raised as a `WorkerCredentialRejectedError` so `BaseAPIClient.call()`
propagates it unwrapped and `with_retries` does not treat it as transient.
`503` is deliberately *not* here: that is what the cloud answers when its
own worker store is unreachable, and retrying it is exactly right."""


def _raise_for_credential(response: httpx.Response, operation: str) -> None:
    """Turn a `401`/`403` into the one error that stops the daemon."""
    if response.status_code in _CREDENTIAL_REJECTED_STATUSES:
        msg = (
            f"the cloud API refused this worker's credential on {operation} "
            f"(HTTP {response.status_code}). Check WORKER_ID and WORKER_CREDENTIAL "
            f"against the values from POST /api/v1/workers; the worker may also "
            f"have been deactivated or lost to a redeploy of a disk-backed store."
        )
        raise WorkerCredentialRejectedError(msg)


class WorkerCloudClient(BaseAPIClient):
    """Poll, upload, and failure-report calls to this worker's cloud API."""

    service_name = "rankuno.worker_cloud"
    rate_limit_key = "worker.cloud_dispatch"
    requests_per_minute = 120
    """Generous: the daemon's own poll interval (`Settings.
    worker_poll_interval_s`, default 15s) is the real pacing control. This
    bucket exists so a misbehaving retry loop cannot hammer the cloud API,
    not to shape steady-state traffic."""

    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        """Build the client. Does not connect until first use.

        Args:
            settings: Configuration override, primarily for tests.
            transport: Injectable `httpx` transport — `httpx.MockTransport`
                in tests, so no socket is ever opened, matching
                `HttpFetcher`'s own testability pattern.

        Raises:
            ConfigurationError: `Settings.worker_cloud_api_base_url` is unset.
        """
        super().__init__(settings=settings)
        base_url = self._settings.require("worker_cloud_api_base_url")
        self._client = httpx.Client(
            base_url=base_url, timeout=_REQUEST_TIMEOUT_S, transport=transport
        )
        self._bearer: str | None = None

    def authenticate(self) -> None:
        """Build this worker's static bearer credential.

        No network call: the credential is a long-lived secret this
        process already holds via `get_settings()` (ADR 0015 condition 2),
        not a token that needs refreshing.

        Raises:
            ConfigurationError: `Settings.worker_id`/`worker_credential`
                are unset.
        """
        worker_id = self._settings.require("worker_id")
        secret = self._settings.require("worker_credential")
        self._bearer = f"{worker_id}:{secret}"

    def _auth_headers(self) -> dict[str, str]:
        if self._bearer is None:
            self.authenticate()
        return {"Authorization": f"Bearer {self._bearer}"}

    def poll(self) -> SignedDispatchAssignment | None:
        """Ask the cloud for this worker's next queued job, if any.

        Returns:
            A signed assignment (ADR 0015 condition 3(b)) to independently
            verify before running anything, or `None` — the ordinary,
            most-of-the-time answer when the queue is empty.
        """

        def _do() -> SignedDispatchAssignment | None:
            response = self._client.get(
                "/api/v1/workers/dispatch/poll", headers=self._auth_headers()
            )
            _raise_for_credential(response, "poll")
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            raw_assignment = payload.get("assignment")
            if raw_assignment is None:
                return None
            return SignedDispatchAssignment.model_validate(raw_assignment)

        return self.call("poll", _do)

    def upload_bundle(self, job_id: str, archive_bytes: bytes) -> None:
        """Upload a completed job's validated bundle archive.

        Args:
            job_id: The job this bundle belongs to.
            archive_bytes: A zip archive. The cloud re-validates it fully
                (allow-list, size cap, zip-slip — ADR 0015 condition 9);
                this client trusts nothing about the response beyond
                "did the request succeed".
        """

        def _do() -> None:
            response = self._client.post(
                f"/api/v1/workers/jobs/{job_id}/upload",
                content=archive_bytes,
                headers={**self._auth_headers(), "Content-Type": "application/zip"},
            )
            _raise_for_credential(response, "upload_bundle")
            response.raise_for_status()

        self.call("upload_bundle", _do)

    def heartbeat(self, template_names: tuple[str, ...]) -> None:
        """Tell the cloud this worker is awake and which templates it holds.

        The poll call already records last-seen, so this exists for the
        second half: `.seospiderconfig` files live only on the machine that
        runs Screaming Frog, and the cloud cannot list a directory it does
        not have. Reporting them is what lets the dashboard show a dropdown
        for *this* desktop.

        Args:
            template_names: Names from the local `TemplateRegistry`. The
                cloud re-validates every one against its own pattern before
                storing it — this client makes no claim to be trusted.
        """

        def _do() -> None:
            response = self._client.post(
                "/api/v1/workers/heartbeat",
                json={"template_names": list(template_names)},
                headers=self._auth_headers(),
            )
            _raise_for_credential(response, "heartbeat")
            response.raise_for_status()

        self.call("heartbeat", _do)

    def report_failure(self, job_id: str, error: str) -> None:
        """Tell the cloud a claimed job could not be completed."""

        def _do() -> None:
            response = self._client.post(
                f"/api/v1/workers/jobs/{job_id}/failed",
                json={"error": error},
                headers=self._auth_headers(),
            )
            _raise_for_credential(response, "report_failure")
            response.raise_for_status()

        self.call("report_failure", _do)

    def report_progress(
        self,
        job_id: str,
        *,
        pages_crawled: int | None,
        progress_pct: float | None,
        phase: WorkerJobPhase | None,
    ) -> None:
        """Tell the cloud how a claimed job is progressing.

        Unlike `report_failure`/`upload_bundle`, the caller
        (`progress_parser.ProgressPollThread`) already treats every
        exception this raises as disposable: a lost progress update is a
        stale dashboard, not a failed crawl, so it is never retried and
        never blocks the crawl it describes. This method still raises like
        every other `BaseAPIClient` call rather than swallowing the failure
        itself — deciding that a given failure is disposable is the
        caller's call to make, not this client's.
        """

        def _do() -> None:
            response = self._client.post(
                f"/api/v1/workers/jobs/{job_id}/progress",
                json={
                    "pages_crawled": pages_crawled,
                    "progress_pct": progress_pct,
                    "phase": phase.value if phase is not None else None,
                },
                headers=self._auth_headers(),
            )
            _raise_for_credential(response, "report_progress")
            response.raise_for_status()

        self.call("report_progress", _do)

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> WorkerCloudClient:
        """Support `with WorkerCloudClient() as client: ...`."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close on context exit, success or failure alike."""
        self.close()
