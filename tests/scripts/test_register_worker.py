"""`scripts/register_worker.py` after ADR 0028.

What changed and is proven here: the installer never asks for or writes the
shared HMAC secret; it fetches the public verify key instead (before
registering, so a failure cannot orphan a one-time worker credential); it
refuses a non-https cloud URL unless it is loopback; and it never echoes a
server's raw error body. Every HTTP call goes to `httpx.MockTransport`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import scripts.register_worker as register_worker
from src.core.worker_dispatch_keys import DispatchSigningKey

KEY = DispatchSigningKey.generate()
LEAKY_BODY = "Traceback: password=hunter2 at db.internal:5432"


class _Server:
    """A scripted cloud API that records every request path."""

    def __init__(self, *, login: int = 200, verify: int = 200, kid: str | None = None) -> None:
        self.paths: list[str] = []
        self.login_status = login
        self.verify_status = verify
        self.kid = kid or KEY.kid

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == "/api/v1/auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, text=LEAKY_BODY)
            return httpx.Response(200, json={"token": "session-tok", "org_id": "acme"})
        if path == register_worker.VERIFY_KEY_PATH:
            assert request.headers["Authorization"] == "Bearer session-tok"
            if self.verify_status != 200:
                return httpx.Response(self.verify_status, json={"detail": LEAKY_BODY})
            body = {"algorithm": "Ed25519", "kid": self.kid, "public_key": KEY.public_key_b64}
            return httpx.Response(200, json=body)
        if path == "/api/v1/workers":
            body = {"worker_id": "wkr-1", "worker_secret": "the-worker-cred", "org_id": "acme"}
            return httpx.Response(201, json=body)
        return httpx.Response(404, text=LEAKY_BODY)


@pytest.fixture
def prompts(monkeypatch) -> list[str]:
    """Answer the operator prompts and record every hidden prompt shown."""
    hidden: list[str] = []
    monkeypatch.setattr("builtins.input", lambda _p: "alice")

    def _getpass(prompt: str) -> str:
        hidden.append(prompt)
        return "the-password"

    monkeypatch.setattr(register_worker, "getpass", _getpass)
    return hidden


def _run(server: _Server, env_path: Path, url: str = "https://cloud.example.com") -> int:
    return register_worker.main(
        ["--cloud-url", url],
        transport=httpx.MockTransport(server.handler),
        env_path=env_path,
    )


def _env(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_writes_the_verify_key_and_never_the_hmac_secret(tmp_path, prompts):
    env_path = tmp_path / ".env.local"
    server = _Server()
    assert _run(server, env_path) == 0

    env = _env(env_path)
    assert env == {
        "WORKER_CLOUD_API_BASE_URL": "https://cloud.example.com",
        "WORKER_ID": "wkr-1",
        "WORKER_ORG_ID": "acme",
        "WORKER_CREDENTIAL": "the-worker-cred",
        "WORKER_DISPATCH_VERIFY_KEY": KEY.public_key_b64,
    }
    assert prompts == ["Operator Password: "], "only the password is ever asked for"
    assert "WORKER_DISPATCH_SIGNING_SECRET" not in env_path.read_text(encoding="utf-8")


def test_the_verify_key_is_fetched_before_the_worker_is_registered(tmp_path, prompts):
    server = _Server()
    _run(server, tmp_path / ".env.local")
    assert server.paths.index(f"GET {register_worker.VERIFY_KEY_PATH}") < server.paths.index(
        "POST /api/v1/workers"
    )


def test_a_cloud_without_an_ed25519_key_stops_before_registering(tmp_path, prompts, capsys):
    env_path = tmp_path / ".env.local"
    server = _Server(verify=503)
    assert _run(server, env_path) == 1
    assert "POST /api/v1/workers" not in server.paths
    assert not env_path.exists()
    assert "WORKER_DISPATCH_SIGNING_PRIVATE_KEY" in capsys.readouterr().err


def test_a_key_that_does_not_match_its_kid_is_refused(tmp_path, prompts, capsys):
    assert _run(_Server(kid="0" * 16), tmp_path / ".env.local") == 1
    assert "does not match" in capsys.readouterr().err


@pytest.mark.parametrize("status", [401, 500])
def test_error_bodies_are_never_echoed(tmp_path, prompts, capsys, status):
    """Fails on the pre-ADR-0028 script, which printed `resp.text` verbatim."""
    assert _run(_Server(login=status), tmp_path / ".env.local") == 1
    captured = capsys.readouterr()
    assert LEAKY_BODY not in captured.out + captured.err
    assert f"HTTP {status}" in captured.err


@pytest.mark.parametrize("url", ["http://cloud.example.com", "http://10.0.0.5:8000"])
def test_plain_http_to_a_remote_host_is_refused_before_any_prompt(tmp_path, monkeypatch, url):
    """Fails on the pre-ADR-0028 script, which would send the password in clear."""

    def _no_prompt(_p: str) -> str:  # pragma: no cover - must not run
        raise AssertionError("must refuse before asking for credentials")

    monkeypatch.setattr("builtins.input", _no_prompt)
    server = _Server()
    assert _run(server, tmp_path / ".env.local", url=url) == 1
    assert server.paths == []


def test_plain_http_to_localhost_is_allowed_for_development(tmp_path, prompts):
    env_path = tmp_path / ".env.local"
    assert _run(_Server(), env_path, url="http://localhost:8000") == 0
    assert _env(env_path)["WORKER_CLOUD_API_BASE_URL"] == "http://localhost:8000"


def test_a_bare_host_defaults_to_https(tmp_path, prompts):
    env_path = tmp_path / ".env.local"
    assert _run(_Server(), env_path, url="cloud.example.com") == 0
    assert _env(env_path)["WORKER_CLOUD_API_BASE_URL"] == "https://cloud.example.com"


def test_a_transport_failure_reports_its_type_not_its_details(tmp_path, prompts, capsys):
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(LEAKY_BODY)

    code = register_worker.main(
        ["--cloud-url", "https://cloud.example.com"],
        transport=httpx.MockTransport(_boom),
        env_path=tmp_path / ".env.local",
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "ConnectError" in err
    assert LEAKY_BODY not in err
    assert json.dumps(LEAKY_BODY) not in err
