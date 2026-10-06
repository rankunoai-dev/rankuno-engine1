"""`scripts/push_job_to_cloud.py`, end to end against an in-process cloud (ADR 0034).

The "cloud" is a real `create_app` over a temporary `DiskJobStore`, reached
through an `httpx.MockTransport` that hands each request to a `TestClient`. So
these tests cross the CLI, the client, the HTTP route and the store, and no
socket is ever opened.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import scripts.push_job_to_cloud as cli
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api.server import create_app
from src.core.auth import DiskOperatorStore, Operator, hash_password
from src.core.rate_limiter import RateLimiterRegistry
from src.core.state_store import DiskJobStore
from src.integrations import base_client
from src.integrations.rankuno_cloud_client import RankunoCloudClient

from tests.modules.seo.test_local_job_export import finished_job

CLOUD = "https://cloud.example.com"
PASSWORD = "a long test password"
SECRET = SecretStr("push-job-cli-test-session-secret-0123456789")


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_client, "_SHARED_LIMITERS", RateLimiterRegistry())


@pytest.fixture
def local(tmp_path: Path) -> tuple[Path, str]:
    jobs = tmp_path / "local-jobs"
    store = DiskJobStore(jobs)
    record = finished_job(store, base="https://www.groundsguys.com/")
    return jobs, record.id


@pytest.fixture
def cloud(tmp_path: Path) -> Iterator[tuple[TestClient, DiskJobStore]]:
    operators = DiskOperatorStore(tmp_path / "operators")
    operators.create(
        Operator(
            operator_id="alice",
            org_id="default",
            display_name="Alice",
            password_hash=hash_password(PASSWORD),
        )
    )
    store = DiskJobStore(tmp_path / "cloud-jobs")
    app = create_app(store=store, operator_store=operators, session_secret=SECRET)
    with TestClient(app) as client:
        yield client, store


def _bridge(client: TestClient, seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response = client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    return lambda base_url: RankunoCloudClient(base_url, transport=httpx.MockTransport(handler))


def _run(args: list[str], **kw: Any) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.run(
        args,
        out=out,
        read_password=kw.pop("read_password", lambda _prompt: PASSWORD),
        read_line=kw.pop("read_line", lambda _prompt: "alice"),
        is_interactive=kw.pop("is_interactive", lambda: True),
        client_factory=kw.pop("client_factory", _refuse_network),
    )
    return code, out.getvalue()


def _refuse_network(_base_url: str) -> RankunoCloudClient:
    raise AssertionError("this path must not build a network client")


class TestLocalOnly:
    def test_list_filters_by_target(self, local: tuple[Path, str]) -> None:
        jobs, job_id = local
        code, out = _run(["--list", "--target", "groundsguys.com", "--jobs-dir", str(jobs)])
        assert code == 0
        assert "1 finished crawl(s)" in out
        assert job_id in out
        code, out = _run(["--list", "--target", "other.org", "--jobs-dir", str(jobs)])
        assert "0 finished crawl(s)" in out

    def test_dry_run_checks_everything_and_writes_nothing(self, local: tuple[Path, str]) -> None:
        jobs, job_id = local
        before = sorted(p.name for p in jobs.iterdir())
        code, out = _run(["--job", job_id, "--dry-run", "--jobs-dir", str(jobs)])
        assert code == 0, out
        assert "Nothing was sent" in out
        assert sorted(p.name for p in jobs.iterdir()) == before  # no .instance-id

    def test_latest_needs_a_target(self, local: tuple[Path, str]) -> None:
        jobs, _ = local
        assert _run(["--latest", "--jobs-dir", str(jobs)])[0] == cli.EXIT_LOCAL

    @pytest.mark.parametrize("job", ["../../etc/passwd", "ABCDEF", "0" * 31])
    def test_a_job_id_that_is_not_a_local_id_is_refused(
        self, local: tuple[Path, str], job: str
    ) -> None:
        jobs, _ = local
        code, out = _run(["--job", job, "--jobs-dir", str(jobs)])
        assert code == cli.EXIT_LOCAL
        assert "32 lowercase hex" in out

    def test_an_insecure_cloud_url_is_refused_before_any_prompt(
        self, local: tuple[Path, str]
    ) -> None:
        jobs, job_id = local
        prompts: list[str] = []
        code, out = _run(
            ["--job", job_id, "--cloud-url", "http://cloud.example.com", "--jobs-dir", str(jobs)],
            read_password=lambda p: prompts.append(p) or "",
        )
        assert code == cli.EXIT_LOCAL
        assert "https" in out
        assert prompts == []

    def test_no_terminal_means_no_password_read(self, local: tuple[Path, str]) -> None:
        jobs, job_id = local
        code, out = _run(
            ["--job", job_id, "--cloud-url", CLOUD, "--jobs-dir", str(jobs)],
            is_interactive=lambda: False,
            read_password=lambda _p: pytest.fail("must not read a password"),
        )
        assert code == cli.EXIT_LOCAL
        assert "interactive terminal" in out


class TestAgainstTheCloud:
    def test_push_then_push_again_is_a_duplicate(
        self, local: tuple[Path, str], cloud: tuple[TestClient, DiskJobStore]
    ) -> None:
        jobs, job_id = local
        client, cloud_store = cloud
        seen: list[httpx.Request] = []
        args = ["--job", job_id, "--cloud-url", CLOUD, "--yes", "--jobs-dir", str(jobs)]

        code, out = _run(args, client_factory=_bridge(client, seen))
        assert code == 0, out
        assert "Imported as cloud job" in out
        [imported] = cloud_store.list_jobs()
        assert imported.org_id == "default"
        assert imported.provenance is not None
        assert imported.provenance.source_job_id == job_id
        assert f"{CLOUD}/api/v1/jobs/{imported.id}" in out
        assert (jobs / ".instance-id").exists()

        code, out = _run(args, client_factory=_bridge(client, seen))
        assert code == 0
        assert f"Already imported as cloud job {imported.id}" in out
        assert len(cloud_store.list_jobs()) == 1
        bodies = [r.content for r in seen if r.url.path.endswith("/jobs/import")]
        assert bodies[0] == bodies[1]  # deterministic bytes across runs
        assert all(
            PASSWORD.encode() not in r.content for r in seen if r.url.path.endswith("/jobs/import")
        )

    def test_a_wrong_password_exits_3(
        self, local: tuple[Path, str], cloud: tuple[TestClient, DiskJobStore]
    ) -> None:
        jobs, job_id = local
        client, cloud_store = cloud
        code, out = _run(
            ["--job", job_id, "--cloud-url", CLOUD, "--yes", "--jobs-dir", str(jobs)],
            read_password=lambda _p: "wrong",
            client_factory=_bridge(client, []),
        )
        assert code == cli.EXIT_AUTH
        assert "Sign-in refused" in out
        assert cloud_store.list_jobs() == []

    def test_declining_the_confirmation_sends_nothing(
        self, local: tuple[Path, str], cloud: tuple[TestClient, DiskJobStore]
    ) -> None:
        jobs, job_id = local
        answers = iter(["alice", "n"])
        code, out = _run(
            ["--job", job_id, "--cloud-url", CLOUD, "--jobs-dir", str(jobs)],
            read_line=lambda _p: next(answers),
        )
        assert code == 0
        assert "Not uploaded" in out
        assert cloud[1].list_jobs() == []
