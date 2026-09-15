"""Tests for `ScreamingFrogControlTool`.

`launch_supervised` is replaced with a fake `SupervisedProcess`-like object
throughout: this suite proves the tool's own orchestration (argv shape, the
URL/template guards, licence evaluation, timeout handling, governance), not
`src.core.process_supervisor`, which has its own test suite.

Trace-log content is always written as a side effect of the *fake launch*
call, never before it — `execute()` records `since_offset` immediately
before launching, so content written earlier must never be visible to
`read_licence_status`, exactly as a prior run's history must not be.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.errors import UnsafeUrlError
from src.core.guardrails import CallbackApprovalProvider, GuardrailEngine
from src.core.schemas import ExecutionStatus, RiskClass
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.screaming_frog_control import tool as tool_module
from src.modules.seo.screaming_frog_control.schemas import ScreamingFrogJobInput
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry
from src.modules.seo.screaming_frog_control.tool import (
    SCREAMING_FROG_LICENCE_ERROR,
    ScreamingFrogControlTool,
    ScreamingFrogLicenceError,
    ScreamingFrogTimeoutError,
)

_PUBLIC_IP = "93.184.216.34"
_ACTIVE_LICENCE_LINE = "INFO  - Licence Status: Active, expires on 26 Jan 2027 GMT. (Username: x)\n"
_COMPLETED_LINE = (
    "INFO  - Completed the spider of https://e.com/ in 0 hrs 0 mins 1 secs (1), "
    "null, crawled 2 urls\n"
)
_DEFAULT_TRACE_CONTENT = _ACTIVE_LICENCE_LINE + _COMPLETED_LINE


class FakeSupervisedProcess:
    """Stands in for `SupervisedProcess` without touching Windows."""

    def __init__(self, *, running_for_polls: int = 0) -> None:
        """Stay `is_running() -> True` for `running_for_polls` calls, then stop."""
        self._remaining_polls = running_for_polls
        self.terminate_calls = 0

    def is_running(self) -> bool:
        if self._remaining_polls <= 0:
            return False
        self._remaining_polls -= 1
        return True

    def terminate(self, *, timeout_s: float = 5.0) -> None:
        self.terminate_calls += 1


def _install_fake_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trace_content: str = _DEFAULT_TRACE_CONTENT
) -> list[list[str]]:
    """Patch `launch_supervised`, appending `trace_content` as its side effect."""
    calls: list[list[str]] = []
    trace_log = tmp_path / "trace.txt"

    def _fake_launch_supervised(
        argv: list[str], *, ledger_path: Path, job_id: str | None = None
    ) -> FakeSupervisedProcess:
        calls.append(list(argv))
        with trace_log.open("a", encoding="utf-8") as handle:
            handle.write(trace_content)
        return FakeSupervisedProcess(running_for_polls=0)

    monkeypatch.setattr(tool_module, "launch_supervised", _fake_launch_supervised)
    return calls


@pytest.fixture
def fake_launch(tmp_path, monkeypatch) -> list[list[str]]:
    """The common case: a run that completes instantly with an active licence."""
    return _install_fake_launch(tmp_path, monkeypatch)


def _build_tool(
    tmp_path, *, guardrails=None, max_runtime_s: float = 7200.0
) -> ScreamingFrogControlTool:
    return ScreamingFrogControlTool(
        guardrails=guardrails,
        cli_path=Path("C:/fake/ScreamingFrogSEOSpiderCli.exe"),
        template_registry=TemplateRegistry(tmp_path / "templates"),
        output_root=tmp_path / "output",
        ledger_path=tmp_path / "ledger.json",
        trace_log_path=tmp_path / "trace.txt",
        url_policy=UrlSafetyPolicy(resolver=lambda host: [_PUBLIC_IP]),
        max_runtime_s=max_runtime_s,
        job_id="job-1",
    )


def _allow_all() -> GuardrailEngine:
    from src.core.config import Environment, Settings

    return GuardrailEngine(
        approval_provider=CallbackApprovalProvider(lambda *_: True),
        settings=Settings(environment=Environment.DEVELOPMENT),
    )


class TestMetadata:
    def test_declares_write_risk_class(self) -> None:
        assert ScreamingFrogControlTool.metadata.risk_class is RiskClass.WRITE

    def test_declares_the_screaming_frog_facet(self) -> None:
        assert ScreamingFrogControlTool.metadata.facet_id == "seo.screaming_frog"

    def test_declares_zero_cost_not_financial(self) -> None:
        assert ScreamingFrogControlTool.metadata.estimated_cost_usd == 0.0


class TestArgvConstruction:
    def test_headless_is_argv_index_one_always(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert fake_launch[0][1] == "--headless"

    def test_crawl_flag_carries_the_validated_seed_url(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        argv = fake_launch[0]
        assert argv[argv.index("--crawl") + 1] == "https://e.com/"

    def test_no_config_flag_when_no_template_is_selected(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert "--config" not in fake_launch[0]

    def test_config_flag_carries_the_resolved_template_path(self, tmp_path, fake_launch) -> None:
        templates = tmp_path / "templates"
        templates.mkdir()
        (templates / "acme.seospiderconfig").write_bytes(b"placeholder")
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/", template_name="acme"))

        argv = fake_launch[0]
        assert argv[argv.index("--config") + 1].endswith("acme.seospiderconfig")


class TestUrlSafetyGate:
    def test_unsafe_seed_url_is_refused_before_launch(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        with pytest.raises(UnsafeUrlError):
            tool.execute(ScreamingFrogJobInput(seed_url="http://169.254.169.254/"))

        assert fake_launch == []


class TestLicenceHandling:
    def test_active_licence_returns_output(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        output = tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert output.licence.active is True
        assert output.bundle_dir == tmp_path / "output" / "job-1"

    def test_inactive_licence_raises_the_named_error(self, tmp_path, monkeypatch) -> None:
        content = "INFO  - Licence Status: Expired GMT. (Username: x)\n" + _COMPLETED_LINE
        _install_fake_launch(tmp_path, monkeypatch, content)
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        with pytest.raises(ScreamingFrogLicenceError) as exc_info:
            tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert str(exc_info.value) == SCREAMING_FROG_LICENCE_ERROR

    def test_free_tier_capped_page_count_raises_even_with_active_licence(
        self, tmp_path, monkeypatch
    ) -> None:
        completed_at_500 = _COMPLETED_LINE.replace("crawled 2 urls", "crawled 500 urls")
        _install_fake_launch(tmp_path, monkeypatch, _ACTIVE_LICENCE_LINE + completed_at_500)
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        with pytest.raises(ScreamingFrogLicenceError):
            tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

    def test_run_reports_failed_not_success_on_licence_error(self, tmp_path, monkeypatch) -> None:
        _install_fake_launch(tmp_path, monkeypatch, "no licence line here\n")
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        result = tool.run(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert result.status is ExecutionStatus.FAILED
        assert result.error == SCREAMING_FROG_LICENCE_ERROR


class TestTimeout:
    def test_exceeding_max_runtime_terminates_and_raises(self, tmp_path, monkeypatch) -> None:
        process = FakeSupervisedProcess(running_for_polls=10_000)
        monkeypatch.setattr(
            tool_module,
            "launch_supervised",
            lambda argv, *, ledger_path, job_id=None: process,
        )
        # `time.monotonic` advances past `max_runtime_s` on the first check.
        clock = iter([0.0, 100.0, 100.0])
        monkeypatch.setattr(tool_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(tool_module.time, "sleep", lambda _seconds: None)
        tool = _build_tool(tmp_path, guardrails=_allow_all(), max_runtime_s=1.0)

        with pytest.raises(ScreamingFrogTimeoutError):
            tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert process.terminate_calls == 1


class TestGovernance:
    def test_write_class_is_blocked_with_no_approval_provider(self, tmp_path, fake_launch) -> None:
        """Deny-by-default: an engine with no approval provider wired refuses."""
        tool = _build_tool(tmp_path, guardrails=GuardrailEngine())

        result = tool.run(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert result.status is ExecutionStatus.BLOCKED_PENDING_APPROVAL
        assert fake_launch == []

    def test_a_denying_callback_provider_also_blocks(self, tmp_path, fake_launch) -> None:
        engine = GuardrailEngine(approval_provider=CallbackApprovalProvider(lambda *_: False))
        tool = _build_tool(tmp_path, guardrails=engine)

        result = tool.run(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert result.status is ExecutionStatus.BLOCKED_PENDING_APPROVAL
        assert fake_launch == []

    def test_describe_invocation_names_the_seed_url_and_template(self, tmp_path) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())
        description = tool.describe_invocation(
            ScreamingFrogJobInput(seed_url="https://e.com/", template_name=None)
        )
        assert "https://e.com/" in description
        assert "defaults" in description
