"""Tests for the Screaming Frog preview/confirm HTTP surface (ADR 0013).

`ScreamingFrogControlTool` is replaced wholesale, exactly like
`tests/api/test_server.py` does for `PageClassificationTool`: what is under
test here is admission control, the token exchange, and status transitions —
not a real Screaming Frog launch, which `test_tool.py` and
`test_process_supervisor.py` already cover.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import get_settings
from src.core.schemas import OrgConfig, RiskClass, ToolMetadata
from src.core.state_store import DiskJobStore, DiskOrgConfigStore
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.screaming_frog_control.preview_tokens import PreviewTokenStore
from src.modules.seo.screaming_frog_control.schemas import LicenceStatus, ScreamingFrogJobOutput
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry
from src.modules.seo.screaming_frog_control.tool import SCREAMING_FROG_LICENCE_ERROR

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"


class StubResult:
    """Stands in for `ToolResult` without importing the generic machinery."""

    def __init__(self, ok: bool = True, data: object = None, error: str | None = None) -> None:
        """Record the canned outcome `.run()` should return."""
        self.ok = ok
        self.data = data
        self.error = error


_STUB_METADATA = ToolMetadata(
    name="seo.screaming_frog_control", summary="stub", risk_class=RiskClass.WRITE
)


class StubSfTool:
    """A `ScreamingFrogControlTool` that returns instantly instead of launching.

    Still calls `guardrails.enforce()`, exactly as `BaseTool.run()` would: the
    property under test in `TestConfirm` is the token exchange
    (`preview_tokens.py`), which lives entirely in the `GuardrailEngine` the
    real `_run_sf_job` constructs and hands to this stub via `guardrails=` —
    skipping that call here would make "a token cannot be reused" untestable
    through this HTTP surface for the wrong reason (the stub never asked),
    not the right one (the store said no).
    """

    result: StubResult = StubResult(ok=False, error="not configured")

    def __init__(self, *, guardrails: object | None = None, **_kwargs: object) -> None:
        """Capture `guardrails`; ignore the real tool's other constructor arguments."""
        self._guardrails = guardrails

    def run(self, _payload: object) -> StubResult:
        if self._guardrails is not None:
            try:
                self._guardrails.enforce(_STUB_METADATA, "stub invocation")  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - mirrors BaseTool.run()'s own boundary
                return StubResult(ok=False, error=str(exc))
        return type(self).result


@pytest.fixture
def stub_sf_tool(monkeypatch):
    monkeypatch.setattr(server_module, "ScreamingFrogControlTool", StubSfTool)
    return StubSfTool


@pytest.fixture
def org_store(tmp_path) -> DiskOrgConfigStore:
    store = DiskOrgConfigStore(tmp_path / "orgs")
    store.create(
        OrgConfig(
            org_id="team-a",
            display_name="Team A",
            max_concurrent_crawls=3,
            llm_credit_limit_usd=100.0,
            is_active=True,
        )
    )
    return store


@pytest.fixture
def mock_org_store(monkeypatch, org_store):
    settings = get_settings()
    monkeypatch.setattr(settings, "_org_config_store", org_store)


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def sf_templates(tmp_path) -> TemplateRegistry:
    directory = tmp_path / "sf_templates"
    directory.mkdir()
    (directory / "acme.seospiderconfig").write_bytes(b"placeholder-not-real-sf-bytes")
    return TemplateRegistry(directory)


@pytest.fixture
def client(store, mock_org_store, sf_templates):
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        sf_template_registry=sf_templates,
        sf_token_store=PreviewTokenStore(),
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app, headers=auth_headers()) as test_client:
        yield test_client


def preview(client, url: str = SAFE_URL, template_name: str | None = None):
    body: dict[str, object] = {"seed_url": url}
    if template_name is not None:
        body["template_name"] = template_name
    return client.post(f"{API_PREFIX}/screaming-frog/jobs/preview", json=body)


def confirm(client, token: str, url: str = SAFE_URL, template_name: str | None = None):
    return client.post(
        f"{API_PREFIX}/screaming-frog/jobs",
        json={"token": token, "seed_url": url, "template_name": template_name},
    )


def wait_for_terminal(store, job_id: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if store.get(job_id).is_terminal:
            return
        time.sleep(0.01)
    pytest.fail(f"job {job_id} never reached a terminal status")


class TestListTemplates:
    def test_lists_the_seeded_template(self, client) -> None:
        response = client.get(f"{API_PREFIX}/screaming-frog/templates")
        assert response.status_code == 200
        names = [t["name"] for t in response.json()["templates"]]
        assert names == ["acme"]

    def test_empty_directory_lists_nothing(self, tmp_path, store, mock_org_store) -> None:
        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            sf_template_registry=TemplateRegistry(tmp_path / "empty"),
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers()) as isolated_client:
            response = isolated_client.get(f"{API_PREFIX}/screaming-frog/templates")
        assert response.json()["templates"] == []


class TestPreview:
    def test_a_safe_url_mints_a_token(self, client) -> None:
        response = preview(client)
        assert response.status_code == 200
        body = response.json()
        assert body["seed_url"] == SAFE_URL
        assert body["token"]
        assert body["expires_at"]

    def test_an_unsafe_url_is_rejected_before_any_token_exists(self, client) -> None:
        response = preview(client, url="http://169.254.169.254/")
        assert response.status_code == 400

    def test_an_unknown_template_is_rejected(self, client) -> None:
        response = preview(client, template_name="does-not-exist")
        assert response.status_code == 400

    def test_a_known_template_is_accepted(self, client) -> None:
        response = preview(client, template_name="acme")
        assert response.status_code == 200
        assert response.json()["template_name"] == "acme"


class TestConfirm:
    def test_nothing_runs_without_a_valid_token(self, client, stub_sf_tool) -> None:
        bogus_token = "not-a-real-token"  # noqa: S105 - a preview token, not a secret
        response = confirm(client, token=bogus_token)
        assert response.status_code == 403

    def test_a_valid_token_starts_a_job(self, client, store, stub_sf_tool, tmp_path) -> None:
        stub_sf_tool.result = StubResult(
            ok=True,
            data=ScreamingFrogJobOutput(
                bundle_dir=tmp_path / "bundle",
                licence=LicenceStatus(active=True, pages_crawled=3),
                elapsed_s=1.0,
            ),
        )
        token = preview(client).json()["token"]

        response = confirm(client, token)

        assert response.status_code == 202
        job_id = response.json()["id"]
        wait_for_terminal(store, job_id)
        assert store.get(job_id).status.value == "succeeded"

    def test_a_token_cannot_be_reused(self, client, store, stub_sf_tool) -> None:
        stub_sf_tool.result = StubResult(ok=False, error="doesn't matter")
        token = preview(client).json()["token"]

        first = confirm(client, token)
        assert first.status_code == 202
        wait_for_terminal(store, first.json()["id"])

        second = confirm(client, token)
        assert second.status_code == 403

    def test_confirm_binds_to_the_exact_previewed_seed_url(self, client, stub_sf_tool) -> None:
        token = preview(client, url=SAFE_URL).json()["token"]

        response = confirm(client, token, url="https://a-different-url.example/")

        assert response.status_code == 403

    def test_confirm_binds_to_the_exact_previewed_template(self, client, stub_sf_tool) -> None:
        token = preview(client, template_name="acme").json()["token"]

        response = confirm(client, token, template_name=None)

        assert response.status_code == 403

    def test_a_licence_failure_surfaces_as_the_named_job_error(
        self, client, store, stub_sf_tool
    ) -> None:
        """Verify ADR 0013 condition 6 at the API layer.

        The exact string, not a generic exit-code message, lands in
        `JobRecord.error`.
        """
        stub_sf_tool.result = StubResult(ok=False, error=SCREAMING_FROG_LICENCE_ERROR)
        token = preview(client).json()["token"]

        response = confirm(client, token)
        job_id = response.json()["id"]
        wait_for_terminal(store, job_id)

        record = store.get(job_id)
        assert record.status.value == "failed"
        assert record.error == SCREAMING_FROG_LICENCE_ERROR

    def test_unsafe_url_is_rejected_even_with_a_token(self, client, stub_sf_tool) -> None:
        irrelevant_token = "irrelevant"  # noqa: S105 - a preview token, not a secret
        response = confirm(client, token=irrelevant_token, url="http://127.0.0.1:9/")
        assert response.status_code == 400
