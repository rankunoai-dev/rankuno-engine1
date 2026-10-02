"""`rankuno-worker setup`: sign in once (ADR 0030). No socket, no real vault."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.core.credential_vault import CredentialVaultError, worker_credential_target
from src.core.worker_dispatch_keys import DispatchSigningKey
from src.integrations.worker_registration_client import (
    DEFAULT_CLOUD_URL,
    VERIFY_KEY_PATH,
    WorkerRegistrationClient,
)
from src.modules.seo.screaming_frog_control.worker_setup import (
    SetupConsole,
    normalise_cloud_url,
    read_configured_worker_id,
    run_setup,
)

KEY = DispatchSigningKey.generate()
PASSWORD = "operator-pass-7c1"
CREDENTIAL = "minted-worker-cred-55"


class _Vault:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.entries: dict[str, str] = {}
        self.fail_write = fail_write

    def read(self, target: str) -> SecretStr | None:
        value = self.entries.get(target)
        return SecretStr(value) if value is not None else None

    def write(self, target: str, *, username: str, secret: SecretStr) -> None:
        if self.fail_write:
            raise CredentialVaultError("Windows Credential Manager could not write (error 5).")
        self.entries[target] = secret.get_secret_value()

    def delete(self, target: str) -> None:
        self.entries.pop(target, None)


class _Cloud:
    def __init__(self, *, verify: int = 200, worker_id: str = "wkr-new") -> None:
        self.paths: list[str] = []
        self.verify = verify
        self.worker_id = worker_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"token": "tok", "org_id": "acme"})
        if request.url.path == VERIFY_KEY_PATH:
            body = {"kid": KEY.kid, "public_key": KEY.public_key_b64}
            return httpx.Response(self.verify, json=body)
        body = {"worker_id": self.worker_id, "worker_secret": CREDENTIAL, "org_id": "acme"}
        return httpx.Response(201, json=body)


class _Console(SetupConsole):
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.secret_prompts: list[str] = []
        self.output: list[str] = []
        super().__init__(ask=self._ask, ask_secret=self._ask_secret, say=self.output.append)

    def _ask(self, prompt: str) -> str:
        for fragment, answer in self.answers.items():
            if fragment in prompt:
                return answer
        return ""

    def _ask_secret(self, prompt: str) -> str:
        self.secret_prompts.append(prompt)
        return PASSWORD


ANSWERS = {"Rankuno URL": "https://cloud.example.com", "Operator ID": "alice", "Name": "Alice PC"}


def _run(
    root: Path, cloud: _Cloud, vault: _Vault, answers: dict[str, str] | None = None
) -> tuple[bool, _Console]:
    console = _Console(answers if answers is not None else ANSWERS)
    settings = Settings(_env_file=None, audit_log_path=root / "audit.jsonl", default_timeout_s=2.0)

    def _factory(url: str) -> WorkerRegistrationClient:
        return WorkerRegistrationClient(
            url, settings=settings, transport=httpx.MockTransport(cloud.handler)
        )

    ok = run_setup(root, console=console, vault_factory=lambda: vault, client_factory=_factory)
    return ok, console


def _everything_written(root: Path, console: _Console, caplog: Any) -> str:
    files = "".join(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file())
    return files + "\n".join(console.output) + caplog.text


def test_the_happy_path_stores_the_credential_and_writes_non_secret_config(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    vault = _Vault()
    ok, console = _run(tmp_path, _Cloud(), vault)

    assert ok is True
    assert vault.entries == {worker_credential_target("wkr-new"): CREDENTIAL}
    config = (tmp_path / "worker.env").read_text(encoding="utf-8")
    assert "WORKER_CLOUD_API_BASE_URL=https://cloud.example.com" in config
    assert "WORKER_ID=wkr-new" in config
    assert "WORKER_ORG_ID=acme" in config
    assert f"WORKER_DISPATCH_VERIFY_KEY={KEY.public_key_b64}" in config
    assert KEY.kid in config
    assert "WORKER_CREDENTIAL" not in config
    assert console.secret_prompts == ["Password: "]
    everything = _everything_written(tmp_path, console, caplog)
    assert PASSWORD not in everything
    assert CREDENTIAL not in everything


def test_the_written_config_is_what_settings_reads(tmp_path):
    _run(tmp_path, _Cloud(), _Vault())
    settings = Settings(_env_file=tmp_path / "worker.env", audit_log_path=tmp_path / "a.jsonl")
    assert settings.worker_id == "wkr-new"
    assert settings.dispatch_verify_key is not None
    assert settings.dispatch_verify_key.kid == KEY.kid
    assert settings.worker_credential is None


def test_a_verify_key_failure_registers_nothing(tmp_path):
    cloud = _Cloud(verify=503)
    vault = _Vault()
    ok, console = _run(tmp_path, cloud, vault)

    assert ok is False
    assert "POST /api/v1/workers" not in cloud.paths
    assert vault.entries == {}
    assert not (tmp_path / "worker.env").exists()
    assert any("does not sign crawl dispatches" in line for line in console.output)


def test_plain_http_is_refused_before_the_password_is_asked(tmp_path):
    cloud = _Cloud()
    ok, console = _run(tmp_path, cloud, _Vault(), {**ANSWERS, "Rankuno URL": "http://evil.example"})
    assert ok is False
    assert console.secret_prompts == []
    assert cloud.paths == []


def test_an_unusable_vault_stops_setup_before_any_network_call(tmp_path):
    cloud = _Cloud()
    console = _Console(ANSWERS)

    def _unavailable() -> _Vault:
        raise CredentialVaultError("runs on Windows only.")

    assert run_setup(tmp_path, console=console, vault_factory=_unavailable) is False
    assert cloud.paths == []
    assert console.output == ["runs on Windows only."]


def test_a_vault_write_failure_writes_no_config_and_names_the_orphan(tmp_path):
    ok, console = _run(tmp_path, _Cloud(), _Vault(fail_write=True))
    assert ok is False
    assert not (tmp_path / "worker.env").exists()
    assert any("wkr-new" in line and "revoke" in line for line in console.output)


def test_missing_operator_id_is_refused_before_signing_in(tmp_path):
    cloud = _Cloud()
    ok, _console = _run(tmp_path, cloud, _Vault(), {**ANSWERS, "Operator ID": "  "})
    assert ok is False
    assert cloud.paths == []


def test_a_transport_failure_is_reported_by_type(tmp_path):
    def _broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cloud = _Cloud()
    cloud.handler = _broken  # type: ignore[method-assign]
    ok, console = _run(tmp_path, cloud, _Vault())
    assert ok is False
    assert console.output[-1] == "Could not reach the Rankuno server (ConnectError)."


def test_reconfiguring_asks_and_a_no_changes_nothing(tmp_path):
    (tmp_path / "worker.env").write_text("WORKER_ID=wkr-old\n", encoding="utf-8")
    cloud = _Cloud()
    ok, _console = _run(tmp_path, cloud, _Vault(), {**ANSWERS, "Replace it": "n"})
    assert ok is False
    assert cloud.paths == []
    assert (tmp_path / "worker.env").read_text(encoding="utf-8") == "WORKER_ID=wkr-old\n"


def test_reconfiguring_with_yes_replaces_and_drops_the_old_credential(tmp_path):
    (tmp_path / "worker.env").write_text("WORKER_ID=wkr-old\n", encoding="utf-8")
    vault = _Vault()
    vault.entries[worker_credential_target("wkr-old")] = "old-cred"
    ok, console = _run(tmp_path, _Cloud(), vault, {**ANSWERS, "Replace it": "y"})
    assert ok is True
    assert set(vault.entries) == {worker_credential_target("wkr-new")}
    assert read_configured_worker_id(tmp_path / "worker.env") == "wkr-new"
    assert any("revoke the old worker 'wkr-old'" in line for line in console.output)


def test_url_normalisation() -> None:
    assert normalise_cloud_url("") == DEFAULT_CLOUD_URL
    assert normalise_cloud_url(" cloud.example.com/ ") == "https://cloud.example.com"
    assert normalise_cloud_url("http://localhost:8000") == "http://localhost:8000"


def test_read_configured_worker_id(tmp_path) -> None:
    config = tmp_path / "worker.env"
    assert read_configured_worker_id(config) is None
    config.write_text("# c\nWORKER_ORG_ID=acme\nWORKER_ID=\n", encoding="utf-8")
    assert read_configured_worker_id(config) is None


@pytest.mark.parametrize("answer", ["", "no", "N"])
def test_anything_but_yes_cancels(tmp_path, answer):
    (tmp_path / "worker.env").write_text("WORKER_ID=wkr-old\n", encoding="utf-8")
    ok, _console = _run(tmp_path, _Cloud(), _Vault(), {**ANSWERS, "Replace it": answer})
    assert ok is False
