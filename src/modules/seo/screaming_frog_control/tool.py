"""ADR 0013's governed entry point: launch Screaming Frog under supervision.

`RiskClass.WRITE`, `MANDATORY_HITL` — the first tool this codebase has shipped
outside `RiskClass.READ`. One `run()` launches one Screaming Frog crawl and
supervises it to completion or to a `max_runtime_s` timeout; there is no
per-page governance here, matching ADR 0003's "one `BaseTool.run()` == one
crawl job" stance, which this ADR explicitly extends to a job this engine does
not itself perform the fetching for.

`BaseAPIClient` deliberately does not apply (ADR 0013 decision 3): this
launches a local executable via `src.core.process_supervisor.launch_supervised`,
not an HTTP request, and Screaming Frog's own crawl traffic never transits
this engine's HTTP stack. The compensating control in `BaseAPIClient`'s place
is the seed-URL-only `UrlSafetyPolicy` gate below (condition 4) — explicitly
partial, because Screaming Frog's own subsequent redirects and discovered
links run inside a process this engine does not control.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from src.core.base_tool import BaseTool
from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.process_supervisor import launch_supervised
from src.core.schemas import RiskClass, StrictModel, ToolMetadata
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.screaming_frog_control.export_manifest import (
    BULK_EXPORT,
    EXPORT_TABS,
    SPINE_TAB,
)
from src.modules.seo.screaming_frog_control.license_check import (
    read_licence_status,
)
from src.modules.seo.screaming_frog_control.schemas import (
    LicenceStatus,
    ScreamingFrogJobInput,
    ScreamingFrogJobOutput,
)
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry

__all__ = ["ScreamingFrogControlTool", "ScreamingFrogLicenceError", "ScreamingFrogTimeoutError"]

_logger = get_logger(__name__)

SCREAMING_FROG_LICENCE_ERROR = "Screaming Frog license invalid/expired"
"""ADR 0013 condition 6's exact, named failure string. A job runner must
surface this verbatim as `JobRecord.error` — never a generic subprocess
exit-code message, and never retried."""

_POLL_INTERVAL_S = 2.0


class ScreamingFrogLicenceError(RankunoError):
    """The run's own log reported an inactive licence, or looked free-tier-capped.

    ADR 0013 condition 6: raised instead of returning a
    `ScreamingFrogJobOutput`, so a degraded run can never be mistaken for a
    complete one.
    """

    def __init__(self, licence: LicenceStatus) -> None:
        """Record the licence read so a caller can log or display it."""
        self.licence = licence
        super().__init__(SCREAMING_FROG_LICENCE_ERROR)


class ScreamingFrogTimeoutError(RankunoError):
    """The supervised process exceeded `max_runtime_s` and was terminated."""

    def __init__(self, max_runtime_s: float) -> None:
        """Record the ceiling that was crossed."""
        self.max_runtime_s = max_runtime_s
        super().__init__(
            f"Screaming Frog exceeded the {max_runtime_s:.0f}s runtime ceiling and was terminated"
        )


class ScreamingFrogControlTool(BaseTool[ScreamingFrogJobInput, ScreamingFrogJobOutput]):
    """Launch Screaming Frog CLI as a supervised, governed crawl job."""

    metadata: ClassVar[ToolMetadata] = ToolMetadata(
        name="seo.screaming_frog_control",
        version="0.1.0",
        summary="Launch Screaming Frog CLI as a supervised crawl and hand off its CSV bundle.",
        risk_class=RiskClass.WRITE,
        facet_id="seo.screaming_frog",
        # No metered spend: Screaming Frog is a locally licensed desktop tool,
        # not a per-call API (ADR 0013 consequences, condition 7's answer).
        estimated_cost_usd=0.0,
    )
    input_model: ClassVar[type[StrictModel]] = ScreamingFrogJobInput
    output_model: ClassVar[type[StrictModel]] = ScreamingFrogJobOutput

    def __init__(
        self,
        *,
        cli_path: Path,
        template_registry: TemplateRegistry,
        output_root: Path,
        ledger_path: Path,
        trace_log_path: Path,
        url_policy: UrlSafetyPolicy | None = None,
        max_runtime_s: float = 7200.0,
        job_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Build the tool.

        Args:
            cli_path: Path to `ScreamingFrogSEOSpiderCli.exe`.
            template_registry: Resolves a template name to a
                `.seospiderconfig` path (condition 5).
            output_root: Parent directory; a per-job subdirectory is created
                under it and handed to `--output-folder`.
            ledger_path: Passed straight to `launch_supervised` — the
                independent PID ledger of condition 2.
            trace_log_path: Screaming Frog's own rolling log file, read for
                the licence line (condition 6; see `license_check.py` for why
                this is a shared, offset-scoped file rather than a per-job
                one).
            url_policy: SSRF policy re-checked here for defense in depth
                (condition 4); the API admission layer already ran it once
                against the same seed URL.
            max_runtime_s: Wall-clock ceiling before this tool terminates its
                own supervised process, rather than trusting Screaming Frog
                to exit on its own.
            job_id: Correlates the Job Object / ledger entry with a
                `JobRecord.id`, when one exists.
            **kwargs: Forwarded to `BaseTool` (`guardrails`, `cost_ledger`).
        """
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._cli_path = cli_path
        self._templates = template_registry
        self._output_root = output_root
        self._ledger_path = ledger_path
        self._trace_log_path = trace_log_path
        self._url_policy = url_policy or UrlSafetyPolicy()
        self._max_runtime_s = max_runtime_s
        self._job_id = job_id

    def describe_invocation(self, payload: ScreamingFrogJobInput) -> str:
        """Operator-facing summary shown at the HITL approval point."""
        template = payload.template_name or "Screaming Frog's own defaults"
        return (
            f"Launch Screaming Frog CLI (headless) against {payload.seed_url} "
            f"using template '{template}'"
        )

    def execute(self, payload: ScreamingFrogJobInput) -> ScreamingFrogJobOutput:
        """Validate, launch, supervise, and hand back the CSV bundle location.

        Args:
            payload: Validated seed URL and optional template name.

        Returns:
            Where the bundle landed and the licence this run reported.

        Raises:
            UnsafeUrlError: The seed URL fails `UrlSafetyPolicy` (condition 4).
            TemplateNotFoundError: `payload.template_name` names no file.
            ScreamingFrogTimeoutError: The process exceeded `max_runtime_s`.
            ScreamingFrogLicenceError: The run's own log reported an inactive
                licence, or a free-tier-shaped page ceiling (condition 6).
        """
        safe_url = self._url_policy.validate(payload.seed_url)
        config_path = (
            self._templates.resolve(payload.template_name)
            if payload.template_name is not None
            else None
        )

        job_id = self._job_id or uuid4().hex
        bundle_dir = self._output_root / job_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        argv = self._build_argv(safe_url.url, config_path, bundle_dir)
        since_offset = self._trace_log_path.stat().st_size if self._trace_log_path.exists() else 0

        started = time.monotonic()
        process = launch_supervised(argv, ledger_path=self._ledger_path, job_id=job_id)
        timed_out = False
        try:
            while process.is_running():
                if time.monotonic() - started > self._max_runtime_s:
                    timed_out = True
                    _logger.warning(
                        "sf_max_runtime_exceeded",
                        extra={"job_id": job_id, "max_runtime_s": self._max_runtime_s},
                    )
                    break
                time.sleep(_POLL_INTERVAL_S)
        finally:
            # Idempotent and safe whether the process already exited on its
            # own or is still running: this is what releases the Job Object
            # handle and removes the ledger entry on the graceful path, not
            # only the crash path the kernel already guarantees.
            process.terminate()

        elapsed_s = time.monotonic() - started
        if timed_out:
            raise ScreamingFrogTimeoutError(self._max_runtime_s)

        licence = read_licence_status(self._trace_log_path, since_offset=since_offset)
        if not licence.active or licence.free_tier_capped:
            raise ScreamingFrogLicenceError(licence)

        return ScreamingFrogJobOutput(bundle_dir=bundle_dir, licence=licence, elapsed_s=elapsed_s)

    def _build_argv(self, seed_url: str, config_path: Path | None, output_dir: Path) -> list[str]:
        """Construct the CLI command line.

        `--headless` is `argv[1]`, always, never a configurable option: a
        non-headless run that hits an argument error pops a blocking GUI
        dialog before exiting — a hang vector on an unattended process
        (verified: `--bogus-flag-xyz` and a missing URL both logged a FATAL
        line to a real CLI run rather than raising, so a GUI prompt is the
        only thing standing between a bad argument and a hung job). Export
        flags are the fixed, verified manifest in `export_manifest.py`, not a
        per-field mapping — condition 5's field-mapping requirement is
        answered by `ScreamingFrogTemplate`, not by exposing these flags to
        the operator.
        """
        argv = [
            str(self._cli_path),
            "--headless",
            "--crawl",
            seed_url,
            "--output-folder",
            str(output_dir),
            "--overwrite",
            "--export-tabs",
            ",".join((SPINE_TAB, *EXPORT_TABS)),
            "--bulk-export",
            ",".join(BULK_EXPORT),
        ]
        if config_path is not None:
            argv.extend(["--config", str(config_path)])
        return argv
