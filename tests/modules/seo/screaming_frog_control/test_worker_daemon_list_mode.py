"""The worker daemon's list-mode path, end to end inside the process (ADR 0022).

`test_worker_url_list.py` proves the digest check in isolation. This file
proves the daemon *uses* it: that a job whose claims carry a digest fetches,
verifies and passes a `UrlListInvocation` into the tool, that a mismatch fails
the job with the distinct message rather than a generic one, and that a job
without a digest still takes the untouched `--crawl` path.

`ScreamingFrogControlTool` is replaced throughout, so nothing here launches a
process; what is under test is the daemon's own orchestration.
"""

from __future__ import annotations

from pathlib import Path

from src.core.errors import IntegrationError
from src.core.schemas import ExecutionStatus, ToolResult
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_consumed_ledger import ConsumedJobLedger
from src.core.worker_dispatch_schemas import WorkerJobPhase
from src.core.worker_dispatch_signing import verify_dispatch_assignment
from src.modules.seo.screaming_frog_control import worker_daemon
from src.modules.seo.screaming_frog_control.schemas import (
    LicenceStatus,
    ScreamingFrogJobInput,
    ScreamingFrogJobOutput,
)
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry
from src.modules.seo.screaming_frog_control.url_list import fingerprint, render_url_list
from src.modules.seo.screaming_frog_control.worker_url_list import URL_LIST_FILENAME
from tests.modules.seo.screaming_frog_control.test_worker_daemon import (
    _FakeClient,
    _issue_token,
    _settings,
)

URLS = ("https://example.com/a", "https://example.com/b")
BODY = render_url_list(URLS)
DIGEST = fingerprint(BODY)


class _ListClient(_FakeClient):
    """A `_FakeClient` that can also answer a URL-list fetch."""

    def __init__(self, body: bytes | None = BODY, error: Exception | None = None) -> None:
        super().__init__()
        self._body = body
        self._error = error
        self.list_fetches: list[str] = []

    def fetch_url_list(self, job_id: str) -> bytes:
        self.list_fetches.append(job_id)
        if self._error is not None:
            raise self._error
        assert self._body is not None
        return self._body


def _run(
    tmp_path,
    monkeypatch,
    *,
    client,
    url_list_sha256: str | None,
    licence: LicenceStatus | None = None,
) -> dict[str, object]:
    """Drive `_run_screaming_frog_job` and return what the fake tool received."""
    settings = _settings(tmp_path, deliverables_output_dir=tmp_path / "deliverables")
    token = _issue_token(settings, url_list_sha256=url_list_sha256)
    claims = verify_dispatch_assignment(
        token,
        secret=settings.dispatch_signing_secret,
        worker_id="wkr-alice-desktop",
        org_id="acme",
    )
    captured: dict[str, object] = {}

    class _FakeTool:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, payload: ScreamingFrogJobInput) -> ToolResult[ScreamingFrogJobOutput]:
            captured["payload"] = payload
            output = ScreamingFrogJobOutput(
                bundle_dir=tmp_path / "bundle",
                licence=licence or LicenceStatus(active=True),
                elapsed_s=1.0,
            )
            return ToolResult[ScreamingFrogJobOutput](
                status=ExecutionStatus.SUCCESS, tool="seo.screaming_frog_control", data=output
            )

    monkeypatch.setattr(worker_daemon, "ScreamingFrogControlTool", _FakeTool)

    worker_daemon._run_screaming_frog_job(  # noqa: SLF001 - the unit under test
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        client=client,
        ledger=ConsumedJobLedger(settings.worker_consumed_jobs_path),
        templates=TemplateRegistry(settings.screaming_frog_template_dir),
        url_policy=UrlSafetyPolicy(resolver=lambda _h: ["93.184.216.34"]),
    )
    return captured


class TestListModeDispatch:
    def test_a_digest_in_the_claims_fetches_and_passes_a_url_list(self, tmp_path, monkeypatch):
        client = _ListClient()

        captured = _run(tmp_path, monkeypatch, client=client, url_list_sha256=DIGEST)

        assert client.list_fetches == ["job-1"]
        payload = captured["payload"]
        assert isinstance(payload, ScreamingFrogJobInput)
        assert payload.url_list is not None
        assert payload.url_list.url_count == 2
        assert payload.url_list.sha256 == DIGEST
        # The fake tool writes no CSVs, so the run ends on the pre-existing
        # "empty bundle" report. What matters here is that no URL-list
        # failure was raised on the way in.
        assert not any("fingerprint" in message for _job, message in client.failures)

    def test_the_file_lands_in_the_jobs_own_output_directory(self, tmp_path, monkeypatch):
        """`output_root / job_id` is the only directory a job may write to."""
        captured = _run(tmp_path, monkeypatch, client=_ListClient(), url_list_sha256=DIGEST)

        payload = captured["payload"]
        expected = tmp_path / "deliverables" / "screaming_frog" / "job-1" / URL_LIST_FILENAME
        assert payload.url_list.path == expected
        assert expected.read_bytes() == BODY

    def test_the_tool_and_the_written_file_agree_on_the_directory(self, tmp_path, monkeypatch):
        """The daemon must not write the list somewhere `execute()` will not look."""
        captured = _run(tmp_path, monkeypatch, client=_ListClient(), url_list_sha256=DIGEST)

        assert Path(captured["output_root"]) == tmp_path / "deliverables" / "screaming_frog"
        assert captured["payload"].url_list.path.parent == Path(captured["output_root"]) / "job-1"

    def test_no_digest_takes_the_untouched_crawl_path(self, tmp_path, monkeypatch):
        client = _ListClient()

        captured = _run(tmp_path, monkeypatch, client=client, url_list_sha256=None)

        assert client.list_fetches == []
        assert captured["payload"].url_list is None


class TestListModeRefusals:
    def test_a_mismatched_download_fails_the_job_with_the_distinct_message(
        self, tmp_path, monkeypatch
    ):
        client = _ListClient(body=render_url_list(["https://example.com/EVIL"]))

        captured = _run(tmp_path, monkeypatch, client=client, url_list_sha256=DIGEST)

        assert "payload" not in captured, "the crawl must not have been launched"
        assert len(client.failures) == 1
        job_id, message = client.failures[0]
        assert job_id == "job-1"
        assert "does not match the approved fingerprint" in message
        assert "Nothing was crawled" in message

    def test_a_mismatch_is_not_reported_as_a_generic_tool_failure(self, tmp_path, monkeypatch):
        client = _ListClient(body=b"not the approved list\r\n")

        _run(tmp_path, monkeypatch, client=client, url_list_sha256=DIGEST)

        _job_id, message = client.failures[0]
        assert "the tool returned no data" not in message
        assert "not a transient failure" in message

    def test_an_unfetchable_list_fails_the_job_rather_than_crawling_blind(
        self, tmp_path, monkeypatch
    ):
        client = _ListClient(error=IntegrationError("rankuno.worker_cloud", "unreachable"))

        captured = _run(tmp_path, monkeypatch, client=client, url_list_sha256=DIGEST)

        assert "payload" not in captured
        _job_id, message = client.failures[0]
        assert "could not fetch this job's approved URL list" in message


class TestFinalPageCountReport:
    """Without this report the cloud compares against a live estimate, not a total."""

    def test_the_completion_count_is_reported_before_the_upload(self, tmp_path, monkeypatch):
        client = _ListClient()

        _run(
            tmp_path,
            monkeypatch,
            client=client,
            url_list_sha256=DIGEST,
            licence=LicenceStatus(active=True, pages_crawled=7, expected_url_count=2),
        )

        assert client.progress_reports == [
            ("job-1", {"pages_crawled": 7, "progress_pct": None, "phase": WorkerJobPhase.EXPORTING})
        ]

    def test_a_run_with_no_completion_line_reports_nothing(self, tmp_path, monkeypatch):
        """Absence is not zero; reporting zero would fabricate a shortfall."""
        client = _ListClient()

        _run(tmp_path, monkeypatch, client=client, url_list_sha256=DIGEST)

        assert client.progress_reports == []
