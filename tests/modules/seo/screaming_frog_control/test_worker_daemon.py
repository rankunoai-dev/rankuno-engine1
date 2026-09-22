"""Tests for the ADR 0015 worker daemon: dual gate, dispatch, backoff, reconcile.

No real Screaming Frog CLI or win32 dependency is needed: `pywin32` is not
installed in this environment (matching every non-Windows CI runner this
codebase already supports), so `reconcile_orphans` raises
`ProcessSupervisorUnavailableError`, which `_reconcile_at_startup` already
handles as the expected, non-fatal case.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from src.core.config import Environment, Settings
from src.core.errors import (
    ConfigurationError,
    IntegrationError,
    WorkerCredentialRejectedError,
)
from src.core.schemas import ExecutionStatus, RiskClass, ToolMetadata, ToolResult
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_consumed_ledger import ConsumedJobLedger
from src.core.worker_dispatch_schemas import DispatchAssignmentClaims, WorkerJobKind, WorkerJobPhase
from src.core.worker_dispatch_signing import issue_dispatch_assignment, verify_dispatch_assignment
from src.modules.seo.screaming_frog_control import worker_daemon
from src.modules.seo.screaming_frog_control.schemas import (
    LicenceStatus,
    ScreamingFrogJobOutput,
    ScreamingFrogProgressSnapshot,
)
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry

SECRET = SecretStr("unit-test-dispatch-signing-key")
OTHER_SECRET = SecretStr("a-different-signing-key")

DUMMY_METADATA = ToolMetadata(
    name="seo.screaming_frog_control", summary="test", risk_class=RiskClass.WRITE
)

_BASE_CLAIMS_KWARGS: dict[str, object] = {
    "job_id": "job-1",
    "worker_id": "wkr-alice-desktop",
    "org_id": "acme",
    "kind": WorkerJobKind.SCREAMING_FROG_CRAWL,
    "seed_url": "https://example.com/",
    "template_name": None,
    "correlation_id": "corr-1",
    "jti": "x",
    "issued_at": datetime.now(UTC),
    "expires_at": datetime.now(UTC),
}


def _claims(**overrides: object) -> DispatchAssignmentClaims:
    return DispatchAssignmentClaims(**{**_BASE_CLAIMS_KWARGS, **overrides})  # type: ignore[arg-type]


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.DEVELOPMENT,
        "audit_log_path": tmp_path / "audit.jsonl",
        "worker_id": "wkr-alice-desktop",
        "worker_org_id": "acme",
        "worker_dispatch_signing_secret": SECRET,
        "worker_consumed_jobs_path": tmp_path / "consumed.json",
        "screaming_frog_template_dir": tmp_path / "templates",
        "worker_upload_max_bytes": 10_000,
    }
    base.update(overrides)
    return Settings(**base)


def _issue_token(settings: Settings, **overrides: object) -> str:
    kwargs: dict[str, object] = {
        "job_id": "job-1",
        "worker_id": settings.worker_id,
        "org_id": settings.worker_org_id,
        "kind": WorkerJobKind.SCREAMING_FROG_CRAWL,
        "seed_url": "https://example.com/",
        "template_name": None,
        "correlation_id": "corr-1",
        "secret": settings.dispatch_signing_secret,
        "ttl_s": 300.0,
    }
    kwargs.update(overrides)
    return issue_dispatch_assignment(**kwargs).token  # type: ignore[arg-type]


class _FakeClient:
    """Records `report_failure`/`upload_bundle` calls; `poll()` is scripted."""

    def __init__(self, poll_results: list[object] | None = None) -> None:
        self._poll_results = list(poll_results or [])
        self.failures: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.heartbeats: list[tuple[str, ...]] = []
        self.progress_reports: list[tuple[str, dict[str, object]]] = []

    def heartbeat(self, template_names: tuple[str, ...]) -> None:
        self.heartbeats.append(template_names)

    def poll(self) -> object:
        if not self._poll_results:
            return None
        return self._poll_results.pop(0)

    def report_failure(self, job_id: str, error: str) -> None:
        self.failures.append((job_id, error))

    def upload_bundle(self, job_id: str, archive_bytes: bytes) -> None:
        self.uploads.append((job_id, archive_bytes))

    def report_progress(
        self, job_id: str, *, pages_crawled: object, progress_pct: object, phase: object
    ) -> None:
        self.progress_reports.append(
            (job_id, {"pages_crawled": pages_crawled, "progress_pct": progress_pct, "phase": phase})
        )


# --- make_approval_callback: the dual gate's load-bearing half (condition 3(b)) -


def test_approval_callback_approves_a_valid_unconsumed_assignment(tmp_path):
    settings = _settings(tmp_path)
    token = _issue_token(settings)
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    callback = worker_daemon.make_approval_callback(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ledger,
    )
    assert callback(DUMMY_METADATA, "context") is True


def test_approval_callback_denies_a_token_signed_with_the_wrong_secret(tmp_path):
    """The dual gate's core scenario: cloud dispatched, worker verification fails.

    The cloud legitimately issued a signed artifact (minted with `SECRET`),
    but this worker's own configured signing secret is `OTHER_SECRET` — a
    misconfigured/mismatched deployment. `make_approval_callback` must
    refuse, never fall back to trusting that a token merely arrived.
    """
    settings = _settings(tmp_path, worker_dispatch_signing_secret=OTHER_SECRET)
    token = issue_dispatch_assignment(
        job_id="job-1",
        worker_id="wkr-alice-desktop",
        org_id="acme",
        kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
        seed_url="https://example.com/",
        template_name=None,
        correlation_id="corr-1",
        secret=SECRET,
        ttl_s=300.0,
    ).token
    claims = _claims()
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    callback = worker_daemon.make_approval_callback(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ledger,
    )
    assert callback(DUMMY_METADATA, "context") is False
    assert ledger.has_run("job-1") is False  # never consumed on a denial


def test_approval_callback_denies_an_expired_assignment(tmp_path):
    settings = _settings(tmp_path)
    token = _issue_token(settings, ttl_s=-1.0)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    callback = worker_daemon.make_approval_callback(
        token,
        _claims(),
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ledger,
    )
    assert callback(DUMMY_METADATA, "context") is False


def test_approval_callback_is_single_use(tmp_path):
    settings = _settings(tmp_path)
    token = _issue_token(settings)
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    callback = worker_daemon.make_approval_callback(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ledger,
    )
    assert callback(DUMMY_METADATA, "context") is True
    assert callback(DUMMY_METADATA, "context") is False


def test_approval_callback_never_reduces_to_an_unconditional_true(tmp_path):
    """Structural guard against the exact regression condition 3(b) forbids."""
    settings = _settings(tmp_path)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    callback = worker_daemon.make_approval_callback(
        "not-even-a-real-token",  # noqa: S106 - a deliberately bogus artifact, not a credential
        _claims(),
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ledger,
    )
    assert callback(DUMMY_METADATA, "context") is False


# --- _handle_assignment: closed-enum dispatch + ledger short-circuit ------------


def test_handle_assignment_skips_a_job_already_marked_run(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    token = _issue_token(settings)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    ledger.try_consume("job-1")

    called = []
    monkeypatch.setattr(
        worker_daemon, "_run_screaming_frog_job", lambda *a, **k: called.append(True)
    )
    worker_daemon._handle_assignment(
        token,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=_FakeClient(),
        ledger=ledger,
        templates=None,  # type: ignore[arg-type]
        url_policy=None,  # type: ignore[arg-type]
    )
    assert called == []


def test_handle_assignment_dispatches_screaming_frog_crawl_by_kind(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    token = _issue_token(settings)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)

    called = []
    monkeypatch.setattr(
        worker_daemon, "_run_screaming_frog_job", lambda *a, **k: called.append(a[1].job_id)
    )
    worker_daemon._handle_assignment(
        token,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=_FakeClient(),
        ledger=ledger,
        templates=None,  # type: ignore[arg-type]
        url_policy=None,  # type: ignore[arg-type]
    )
    assert called == ["job-1"]


def test_handle_assignment_rejects_a_malformed_token_without_raising(tmp_path):
    settings = _settings(tmp_path)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    # Must not raise: one bad artifact must not kill the daemon loop.
    worker_daemon._handle_assignment(
        "garbage-token",  # noqa: S106 - a deliberately bogus artifact, not a credential
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=_FakeClient(),
        ledger=ledger,
        templates=None,  # type: ignore[arg-type]
        url_policy=None,  # type: ignore[arg-type]
    )


# --- _run_screaming_frog_job: envelope re-validation (condition 8) -------------


def test_run_screaming_frog_job_rejects_an_unsafe_seed_url(tmp_path):
    settings = _settings(tmp_path)
    token = _issue_token(settings, seed_url="http://169.254.169.254/")
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    client = _FakeClient()
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    worker_daemon._run_screaming_frog_job(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=client,
        ledger=ledger,
        templates=TemplateRegistry(settings.screaming_frog_template_dir),
        url_policy=UrlSafetyPolicy(),
    )
    assert len(client.failures) == 1
    assert "unsafe seed_url" in client.failures[0][1]
    assert ledger.has_run("job-1") is True


def test_run_screaming_frog_job_rejects_an_unknown_template(tmp_path):
    settings = _settings(tmp_path)
    token = _issue_token(settings, template_name="does-not-exist")
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    client = _FakeClient()
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    worker_daemon._run_screaming_frog_job(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=client,
        ledger=ledger,
        templates=TemplateRegistry(settings.screaming_frog_template_dir),
        url_policy=UrlSafetyPolicy(resolver=lambda h: ["93.184.216.34"]),
    )
    assert len(client.failures) == 1
    assert ledger.has_run("job-1") is True


# --- on_progress wiring: the tool's callback reaches the cloud client ----------


def test_run_screaming_frog_job_wires_on_progress_to_the_clients_report_progress(
    tmp_path, monkeypatch
):
    """The tool's `on_progress` callback must reach the cloud client.

    `_run_screaming_frog_job` must hand the tool a callback that ends up
    calling `WorkerCloudClient.report_progress` for *this* job — not just
    construct one and drop it. Asserted by capturing the real constructor
    kwargs `ScreamingFrogControlTool` receives, then invoking the captured
    `on_progress` exactly as `progress_parser.ProgressPollThread` would.
    """
    settings = _settings(tmp_path)
    token = _issue_token(settings)
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    client = _FakeClient()
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    captured_kwargs: dict[str, object] = {}

    class _FakeTool:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        def run(self, _payload: object) -> ToolResult[ScreamingFrogJobOutput]:
            output = ScreamingFrogJobOutput(
                bundle_dir=tmp_path / "bundle", licence=LicenceStatus(active=True), elapsed_s=1.0
            )
            return ToolResult[ScreamingFrogJobOutput](
                status=ExecutionStatus.SUCCESS, tool="seo.screaming_frog_control", data=output
            )

    monkeypatch.setattr(worker_daemon, "ScreamingFrogControlTool", _FakeTool)

    worker_daemon._run_screaming_frog_job(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=client,
        ledger=ledger,
        templates=TemplateRegistry(settings.screaming_frog_template_dir),
        url_policy=UrlSafetyPolicy(resolver=lambda h: ["93.184.216.34"]),
    )

    on_progress = captured_kwargs["on_progress"]
    on_progress(  # type: ignore[operator]
        ScreamingFrogProgressSnapshot(
            pages_crawled=42, progress_pct=12.5, phase=WorkerJobPhase.CRAWLING
        )
    )

    assert client.progress_reports == [
        ("job-1", {"pages_crawled": 42, "progress_pct": 12.5, "phase": WorkerJobPhase.CRAWLING})
    ]


def test_run_screaming_frog_job_passes_progress_settings_through(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path,
        screaming_frog_progress_poll_interval_s=3.0,
        worker_progress_min_report_interval_s=9.0,
    )
    token = _issue_token(settings)
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    captured_kwargs: dict[str, object] = {}

    class _FakeTool:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        def run(self, _payload: object) -> ToolResult[ScreamingFrogJobOutput]:
            output = ScreamingFrogJobOutput(
                bundle_dir=tmp_path / "bundle", licence=LicenceStatus(active=True), elapsed_s=1.0
            )
            return ToolResult[ScreamingFrogJobOutput](
                status=ExecutionStatus.SUCCESS, tool="seo.screaming_frog_control", data=output
            )

    monkeypatch.setattr(worker_daemon, "ScreamingFrogControlTool", _FakeTool)

    worker_daemon._run_screaming_frog_job(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=_FakeClient(),
        ledger=ledger,
        templates=TemplateRegistry(settings.screaming_frog_template_dir),
        url_policy=UrlSafetyPolicy(resolver=lambda h: ["93.184.216.34"]),
    )

    assert captured_kwargs["progress_poll_interval_s"] == 3.0
    assert captured_kwargs["progress_min_report_interval_s"] == 9.0


# --- _upload_bundle: only allow-listed files, size-capped -----------------------


def test_upload_bundle_only_includes_allow_listed_files(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "internal_all.csv").write_text("Address\nhttps://example.com/\n")
    (bundle_dir / "not_an_export.csv").write_text("unexpected")

    output = ScreamingFrogJobOutput(
        bundle_dir=bundle_dir, licence=LicenceStatus(active=True), elapsed_s=1.0
    )
    client = _FakeClient()
    worker_daemon._upload_bundle(client, "job-1", output, max_bytes=1_000_000)

    assert len(client.uploads) == 1
    archive = zipfile.ZipFile(io.BytesIO(client.uploads[0][1]))
    assert archive.namelist() == ["internal_all.csv"]


def test_upload_bundle_reports_failure_over_the_size_cap(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "internal_all.csv").write_text("x" * 1000)

    output = ScreamingFrogJobOutput(
        bundle_dir=bundle_dir, licence=LicenceStatus(active=True), elapsed_s=1.0
    )
    client = _FakeClient()
    worker_daemon._upload_bundle(client, "job-1", output, max_bytes=10)

    assert client.uploads == []
    assert len(client.failures) == 1
    assert "upload limit" in client.failures[0][1]


# --- run_worker_daemon: backoff (condition 10) and bounded iterations ----------


def test_run_worker_daemon_backs_off_on_repeated_poll_failures(tmp_path):
    class _FailingClient:
        def heartbeat(self, template_names) -> None:
            return None

        def poll(self) -> object:
            raise IntegrationError("worker.cloud", "unreachable")

    sleeps: list[float] = []
    settings = _settings(tmp_path, worker_poll_interval_s=1.0, worker_poll_max_backoff_s=8.0)
    worker_daemon.run_worker_daemon(
        settings=settings,
        max_iterations=3,
        sleep=sleeps.append,
        cloud_client=_FailingClient(),  # type: ignore[arg-type]
    )
    assert sleeps == [1.0, 2.0, 4.0]


def test_run_worker_daemon_resets_backoff_after_a_successful_empty_poll(tmp_path):
    class _AlwaysEmptyClient:
        def heartbeat(self, template_names) -> None:
            return None

        def poll(self) -> object:
            return None

    sleeps: list[float] = []
    settings = _settings(tmp_path, worker_poll_interval_s=1.0)
    worker_daemon.run_worker_daemon(
        settings=settings,
        max_iterations=3,
        sleep=sleeps.append,
        cloud_client=_AlwaysEmptyClient(),  # type: ignore[arg-type]
    )
    assert sleeps == [1.0, 1.0, 1.0]


def test_run_worker_daemon_requires_worker_identity(tmp_path):
    settings = _settings(tmp_path, worker_id=None)
    with pytest.raises(ConfigurationError):
        worker_daemon.run_worker_daemon(settings=settings, max_iterations=1, sleep=lambda s: None)


# --- Lifecycle: heartbeat, shutdown, and a credential that will never work ------


def test_the_daemon_reports_its_local_templates_before_polling(tmp_path):
    """The cloud host has no .seospiderconfig files; this machine does."""
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "default-crawl.seospiderconfig").write_bytes(b"not-really-java")

    client = _FakeClient()
    worker_daemon.run_worker_daemon(
        settings=_settings(tmp_path, screaming_frog_template_dir=templates),
        max_iterations=1,
        sleep=lambda s: None,
        cloud_client=client,  # type: ignore[arg-type]
    )
    assert client.heartbeats == [("default-crawl",)]


def test_an_unchanged_template_set_is_not_re_reported_every_cycle(tmp_path):
    client = _FakeClient()
    worker_daemon.run_worker_daemon(
        settings=_settings(tmp_path),
        max_iterations=4,
        sleep=lambda s: None,
        cloud_client=client,  # type: ignore[arg-type]
    )
    assert client.heartbeats == [()]


def test_a_heartbeat_lost_to_an_unreachable_cloud_is_retried_next_cycle(tmp_path):
    """`reported` must not advance on a failure, or the report is lost for good."""

    class _FlakyHeartbeat(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def heartbeat(self, template_names: tuple[str, ...]) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise IntegrationError("worker.cloud", "unreachable")
            super().heartbeat(template_names)

    client = _FlakyHeartbeat()
    worker_daemon.run_worker_daemon(
        settings=_settings(tmp_path, worker_poll_interval_s=1.0),
        max_iterations=2,
        sleep=lambda s: None,
        cloud_client=client,  # type: ignore[arg-type]
    )
    assert client.attempts == 2
    assert client.heartbeats == [()]


def test_a_rejected_credential_stops_the_daemon_instead_of_hot_looping(tmp_path):
    """Backing off forever on a 401 hides the one failure a human must fix."""

    class _RejectedClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.polls = 0

        def poll(self) -> object:
            self.polls += 1
            raise WorkerCredentialRejectedError("the cloud API refused this credential")

    client = _RejectedClient()
    sleeps: list[float] = []
    with pytest.raises(WorkerCredentialRejectedError):
        worker_daemon.run_worker_daemon(
            settings=_settings(tmp_path),
            max_iterations=50,
            sleep=sleeps.append,
            cloud_client=client,  # type: ignore[arg-type]
        )
    assert client.polls == 1
    assert sleeps == []  # no backoff, no retry: it would never succeed


def test_should_stop_ends_the_loop_before_the_next_poll(tmp_path):
    client = _FakeClient()
    worker_daemon.run_worker_daemon(
        settings=_settings(tmp_path),
        max_iterations=10,
        sleep=lambda s: None,
        cloud_client=client,  # type: ignore[arg-type]
        should_stop=lambda: True,
    )
    assert client.heartbeats == []  # stopped before it did anything at all


def test_shutdown_requested_mid_run_finishes_the_cycle_it_is_in(tmp_path):
    """Checked between jobs, never during one: no half-uploaded bundle."""
    stop = [False]
    client = _FakeClient()

    def _sleep(_seconds: float) -> None:
        stop[0] = True  # the operator presses Ctrl+C during the idle wait

    worker_daemon.run_worker_daemon(
        settings=_settings(tmp_path),
        max_iterations=10,
        sleep=_sleep,
        cloud_client=client,  # type: ignore[arg-type]
        should_stop=lambda: stop[0],
    )
    assert client.heartbeats == [()]  # exactly one cycle ran, and it ran fully
