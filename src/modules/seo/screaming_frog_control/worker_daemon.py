"""The desktop worker daemon: poll, verify, run, report (ADR 0015).

`run_worker_daemon` is the whole lifetime of the process an operator starts
on the Screaming Frog licence machine. It answers ADR 0013 condition 3's
question again for itself (ADR 0015 condition 12): same-process,
same-Job-Object-supervision design, for the identical reason the local API
server chose that — `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` does not depend on
the launching process staying alive. `reconcile_orphans()` runs once, here,
before the poll loop ever starts.

Dispatch is a closed-enum `match` (ADR 0015 condition 7) — `WorkerJobKind`
has one member today, `SCREAMING_FROG_CRAWL`. Nothing here is a
string-keyed dict of callables, `eval`, or `pickle`.

The dual approval gate, worker side (condition 3(b))
------------------------------------------------------
Every claimed assignment is verified **twice**, mirroring
`preview_tokens.py`'s own peek-then-consume split exactly:

1. `verify_dispatch_assignment` — a fast, non-mutating admission check
   before any Screaming Frog resource is reserved. A bad signature, an
   expired artifact, or one bound to a different worker/org is refused
   here, before anything expensive happens.
2. The `CallbackApprovalProvider` wired into `ScreamingFrogControlTool`'s
   own `GuardrailEngine` re-verifies the *same* artifact and atomically
   marks it consumed (`ConsumedJobLedger.try_consume`) at the exact moment
   `GuardrailEngine.authorize()` asks — never earlier, so a job later
   refused for an unrelated reason never burns the single-use mark before
   the tool actually asked for approval. This callback is the load-bearing
   check condition 3(b) requires: never a bare boolean.

If gate (b) fails, the worker calls `report_failure` so the job does not
hang in `DISPATCHED` on the cloud forever — a signature check failing
locally is not itself grounds to leave the cloud's own record silently
stuck.

Backoff (condition 10)
------------------------
No circuit breaker for the worker<->cloud channel exists in v1 — accepted
gap, not an oversight (see `worker_cloud_client`'s own docstring). Every
poll failure doubles the wait, capped at `Settings.
worker_poll_max_backoff_s`, and a success resets it to `Settings.
worker_poll_interval_s`.
"""

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from src.core.config import Settings, get_settings
from src.core.errors import IntegrationError, UnsafeUrlError, WorkerCredentialRejectedError
from src.core.guardrails import CallbackApprovalProvider, GuardrailEngine
from src.core.logger import get_logger
from src.core.process_supervisor import ProcessSupervisorUnavailableError, reconcile_orphans
from src.core.schemas import ToolMetadata
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_consumed_ledger import ConsumedJobLedger
from src.core.worker_dispatch_schemas import DispatchAssignmentClaims, WorkerJobKind
from src.core.worker_dispatch_signing import DispatchAssignmentError, verify_dispatch_assignment
from src.integrations.worker_cloud_client import WorkerCloudClient
from src.modules.seo.screaming_frog_control.schemas import (
    ScreamingFrogJobInput,
    ScreamingFrogJobOutput,
)
from src.modules.seo.screaming_frog_control.template_registry import (
    TemplateNotFoundError,
    TemplateRegistry,
)
from src.modules.seo.screaming_frog_control.tool import ScreamingFrogControlTool
from src.modules.seo.screaming_frog_control.upload_manifest import ALLOWED_BUNDLE_FILENAMES

__all__ = ["make_approval_callback", "run_worker_daemon"]

_logger = get_logger(__name__)


def make_approval_callback(
    token: str,
    claims: DispatchAssignmentClaims,
    *,
    worker_id: str,
    org_id: str,
    settings: Settings,
    ledger: ConsumedJobLedger,
) -> Callable[[ToolMetadata, str], bool]:
    """Build gate (b)'s real, consuming callback — never a bare boolean.

    A top-level function, not an inline closure, specifically so it is
    independently testable: this is the exact object condition 3(b) forbids
    reducing to `lambda *_: True`, and a test should be able to construct
    one and call it directly without launching Screaming Frog.

    Re-verifies the artifact and atomically marks it single-use at the
    exact moment `GuardrailEngine.authorize()` asks, mirroring
    `preview_tokens.make_approval_callback`'s own timing exactly: a
    verification that already happened once (the fast admission check in
    `_run_screaming_frog_job`) is re-done here because that earlier result
    is not what a compromised or racing caller could have altered — this
    is.
    """

    def _approval_callback(metadata: ToolMetadata, _context: str) -> bool:
        try:
            verify_dispatch_assignment(
                token, secret=settings.dispatch_signing_secret, worker_id=worker_id, org_id=org_id
            )
        except DispatchAssignmentError:
            return False
        approved = ledger.try_consume(claims.job_id)
        _logger.info(
            "worker_dispatch_assignment_consumed",
            extra={"tool": metadata.name, "job_id": claims.job_id, "approved": approved},
        )
        return approved

    return _approval_callback


def run_worker_daemon(  # noqa: C901, PLR0912 - one loop, every branch a named failure mode
    *,
    settings: Settings | None = None,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    cloud_client: WorkerCloudClient | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Reconcile orphans, then poll for and run jobs until told to stop.

    The four failure modes this loop is built around, all of them ordinary
    on a machine under someone's desk:

    * **The cloud is unreachable at startup.** Nothing here connects
      eagerly; the first poll fails like any other and enters condition
      10's bounded backoff. The daemon stays up.
    * **The cloud goes away mid-run.** Identical path — a failed poll is a
      failed poll whether it is the first or the thousandth.
    * **The credential is invalid or has been revoked.** A
      `WorkerCredentialRejectedError` ends the loop deliberately, with a
      message naming the settings to check. Backing off and retrying a
      `401` forever is a hot loop with extra steps, and it hides the one
      failure a human has to act on.
    * **Ctrl+C.** `should_stop` is checked between jobs, never during one,
      so a shutdown requested mid-upload finishes that upload rather than
      leaving a half-written bundle behind. `worker_daemon_cli` is what
      wires a signal handler to it.

    Args:
        settings: Configuration override, primarily for tests. Defaults to
            `get_settings()`.
        max_iterations: Stop after this many poll cycles. `None` runs
            forever — the production default; tests pass a small number so
            the loop terminates.
        sleep: Injectable for tests, so a backoff wait does not actually
            block the test suite.
        cloud_client: Injectable for tests. Defaults to a real
            `WorkerCloudClient`.
        should_stop: Checked at the top of every cycle. Returning `True`
            ends the loop cleanly.

    Raises:
        ConfigurationError: `Settings.worker_id`/`worker_org_id` are unset
            — this daemon cannot verify anything against itself without
            knowing its own identity.
    """
    settings = settings or get_settings()
    worker_id = settings.require("worker_id")
    org_id = settings.require("worker_org_id")

    _reconcile_at_startup(settings)

    client = cloud_client or WorkerCloudClient(settings)
    ledger = ConsumedJobLedger(settings.worker_consumed_jobs_path)
    templates = TemplateRegistry(settings.screaming_frog_template_dir)
    url_policy = UrlSafetyPolicy()

    poll_interval_s = settings.worker_poll_interval_s
    backoff_s = poll_interval_s
    reported_templates: tuple[str, ...] | None = None
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        if should_stop is not None and should_stop():
            _logger.info("worker_daemon_stopping", extra={"iterations": iterations})
            return
        iterations += 1

        try:
            reported_templates = _report_templates(client, templates, reported_templates)
            assignment = client.poll()
        except WorkerCredentialRejectedError as exc:
            _logger.error(  # noqa: TRY400 - the traceback adds nothing a human can act on
                "worker_credential_rejected_stopping", extra={"error": str(exc)}
            )
            raise
        except IntegrationError as exc:
            _logger.warning("worker_poll_failed", extra={"error": str(exc), "backoff_s": backoff_s})
            sleep(backoff_s)
            backoff_s = min(backoff_s * 2, settings.worker_poll_max_backoff_s)
            continue

        backoff_s = poll_interval_s  # A successful poll resets condition 10's backoff.
        if assignment is None:
            sleep(poll_interval_s)
            continue

        _handle_assignment(
            assignment.token,
            worker_id=worker_id,
            org_id=org_id,
            settings=settings,
            client=client,
            ledger=ledger,
            templates=templates,
            url_policy=url_policy,
        )


def _report_templates(
    client: WorkerCloudClient, templates: TemplateRegistry, reported: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    """Send a heartbeat when this worker's local template set has changed.

    Re-sent on change rather than on a timer, and `reported` stays `None`
    until a heartbeat actually succeeds, so a startup heartbeat lost to an
    unreachable cloud is retried on the next cycle instead of being
    forgotten. A failure is raised to the caller, which already knows how to
    tell a credential rejection from a transient outage — silently swallowing
    it here would mean a worker whose templates never reach the dashboard and
    no log line saying why.
    """
    current = tuple(t.name for t in templates.list_templates())
    if current == reported:
        return reported
    client.heartbeat(current)
    return current


def _reconcile_at_startup(settings: Settings) -> None:
    """ADR 0015 condition 12: must complete before the daemon ever polls."""
    try:
        killed = reconcile_orphans(settings.process_supervisor_ledger_path)
        if killed:
            _logger.warning("worker_daemon_orphans_reconciled", extra={"count": len(killed)})
    except ProcessSupervisorUnavailableError:
        _logger.info("worker_daemon_reconciliation_skipped_no_win32")


def _handle_assignment(
    token: str,
    *,
    worker_id: str,
    org_id: str,
    settings: Settings,
    client: WorkerCloudClient,
    ledger: ConsumedJobLedger,
    templates: TemplateRegistry,
    url_policy: UrlSafetyPolicy,
) -> None:
    """Gate (b)'s fast admission check, then dispatch on the closed job-kind enum."""
    try:
        claims = verify_dispatch_assignment(
            token, secret=settings.dispatch_signing_secret, worker_id=worker_id, org_id=org_id
        )
    except DispatchAssignmentError as exc:
        # No `job_id` survives an artifact that fails to verify — nothing to
        # report failure against, and nothing ran. Logged, not raised: one
        # bad artifact must not kill the whole daemon loop.
        _logger.warning("dispatch_assignment_rejected", extra={"error": str(exc)})
        return

    if ledger.has_run(claims.job_id):
        _logger.info("worker_job_already_run_skipping", extra={"job_id": claims.job_id})
        return

    match claims.kind:
        case WorkerJobKind.SCREAMING_FROG_CRAWL:
            _run_screaming_frog_job(
                token,
                claims,
                worker_id=worker_id,
                org_id=org_id,
                settings=settings,
                client=client,
                ledger=ledger,
                templates=templates,
                url_policy=url_policy,
            )
        case _:  # pragma: no cover
            # mypy sees this as unreachable today because `WorkerJobKind`
            # has exactly one member (condition 7) — kept deliberately, not
            # dead code: the day a second member is added, this branch is
            # what stops an unhandled kind from falling through silently,
            # and it is cheap insurance against a `claims.kind` value this
            # process's own enum somehow does not recognise (a version
            # skew between cloud and worker, for instance).
            _logger.error(  # type: ignore[unreachable]
                "worker_job_kind_unhandled", extra={"kind": str(claims.kind)}
            )


def _run_screaming_frog_job(  # noqa: PLR0913 - every argument is load-bearing, not incidental
    token: str,
    claims: DispatchAssignmentClaims,
    *,
    worker_id: str,
    org_id: str,
    settings: Settings,
    client: WorkerCloudClient,
    ledger: ConsumedJobLedger,
    templates: TemplateRegistry,
    url_policy: UrlSafetyPolicy,
) -> None:
    """Re-validate the envelope, run the tool, and report the outcome.

    ADR 0015 condition 8: `seed_url` and `template_name` are re-validated
    here, independently — the cloud's own earlier check is not trusted
    across the network hop.
    """
    try:
        safe_url = url_policy.validate(claims.seed_url)
    except UnsafeUrlError as exc:
        _report_and_consume(client, ledger, claims.job_id, f"unsafe seed_url: {exc}")
        return

    if claims.template_name is not None:
        try:
            templates.resolve(claims.template_name)
        except TemplateNotFoundError as exc:
            _report_and_consume(client, ledger, claims.job_id, str(exc))
            return

    approval_callback = make_approval_callback(
        token, claims, worker_id=worker_id, org_id=org_id, settings=settings, ledger=ledger
    )
    guardrails = GuardrailEngine(approval_provider=CallbackApprovalProvider(approval_callback))
    tool = ScreamingFrogControlTool(
        guardrails=guardrails,
        cli_path=settings.screaming_frog_cli_path,
        template_registry=templates,
        output_root=settings.deliverables_output_dir / "screaming_frog",
        ledger_path=settings.process_supervisor_ledger_path,
        trace_log_path=settings.screaming_frog_trace_log_path,
        url_policy=url_policy,
        max_runtime_s=settings.screaming_frog_max_runtime_s,
        job_id=claims.job_id,
    )

    result = tool.run(
        ScreamingFrogJobInput(seed_url=safe_url.url, template_name=claims.template_name)
    )
    if not result.ok or result.data is None:
        client.report_failure(claims.job_id, result.error or "the tool returned no data")
        return

    output = result.data
    if not isinstance(output, ScreamingFrogJobOutput):  # pragma: no cover - defensive
        client.report_failure(claims.job_id, f"unexpected output type {type(output).__name__}")
        return

    _upload_bundle(client, claims.job_id, output, max_bytes=settings.worker_upload_max_bytes)


def _report_and_consume(
    client: WorkerCloudClient, ledger: ConsumedJobLedger, job_id: str, error: str
) -> None:
    """Report a pre-execution failure and mark the job consumed either way.

    Consumed even on this early-rejection path: a job whose envelope fails
    local re-validation will fail identically on every future attempt with
    the same artifact, so there is nothing to gain by allowing a retry of
    the *same* signed assignment — a fresh one requires a fresh cloud-side
    approval (gate (a)) in any case.
    """
    _logger.warning("worker_job_envelope_rejected", extra={"job_id": job_id, "error": error})
    ledger.try_consume(job_id)
    client.report_failure(job_id, error)


def _upload_bundle(
    client: WorkerCloudClient, job_id: str, output: ScreamingFrogJobOutput, *, max_bytes: int
) -> None:
    """Zip the allow-listed export files and upload them.

    Only files named in `ALLOWED_BUNDLE_FILENAMES` are ever included — the
    same manifest the cloud re-validates the upload against (ADR 0015
    condition 9) — so a stray file in `bundle_dir` is never sent at all.
    """
    buffer = io.BytesIO()
    included = 0
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(output.bundle_dir).glob("*.csv")):
            if path.name not in ALLOWED_BUNDLE_FILENAMES:
                continue
            archive.write(path, arcname=path.name)
            included += 1

    archive_bytes = buffer.getvalue()
    if len(archive_bytes) > max_bytes:
        client.report_failure(
            job_id, f"bundle exceeds the {max_bytes // (1024 * 1024)} MB upload limit"
        )
        return

    client.upload_bundle(job_id, archive_bytes)
    _logger.info("worker_bundle_uploaded", extra={"job_id": job_id, "files": included})
