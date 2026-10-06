"""The local sign-in operator and the Host allowlist (ADR 0033).

Split from `test_local_signin.py` to keep both files under 400 lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api.local_signin import REJECTED_DETAIL, ensure_local_operator
from src.api.server import API_PREFIX
from src.core.auth import DiskOperatorStore, Operator, hash_password, verify_password
from src.core.errors import ConfigurationError

from tests.api.local_signin_support import LOOPBACK, TOKEN, URL
from tests.api.local_signin_support import build_app as _build
from tests.api.local_signin_support import local_settings as _settings

# -- The dedicated operator ------------------------------------------------------


def _operator(operator_id: str, org_id: str, *, active: bool = True) -> Operator:
    return Operator(
        operator_id=operator_id,
        org_id=org_id,
        display_name=operator_id,
        password_hash=hash_password("a real password"),
        is_active=active,
    )


def test_an_absent_local_operator_is_created_without_a_usable_password(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    operator = ensure_local_operator(store, _settings(tmp_path))
    assert (operator.operator_id, operator.org_id) == ("local", "default")
    stored = store.get("local")
    assert stored.password_hash.startswith("pbkdf2_sha256$")
    for guess in ("", "local", "password", TOKEN):
        assert not verify_password(guess, stored.password_hash)


def test_an_existing_operator_is_never_borrowed(tmp_path):
    """The main checkout holds `claude-test-op` in `test-org`; it must stay untouched."""
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(_operator("claude-test-op", "test-org"))
    operator = ensure_local_operator(store, _settings(tmp_path))
    assert operator.operator_id == "local"
    assert {op.operator_id for op in store.list_operators()} == {"claude-test-op", "local"}


def test_an_existing_valid_local_operator_is_reused_unchanged(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    existing = store.create(_operator("local", "default"))
    assert ensure_local_operator(store, _settings(tmp_path)) == existing


def test_an_inactive_local_operator_refuses_to_start(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(_operator("local", "default", active=False))
    with pytest.raises(ConfigurationError, match="inactive"):
        ensure_local_operator(store, _settings(tmp_path))


def test_a_local_operator_in_another_org_refuses_to_start(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(_operator("local", "org1"))
    with pytest.raises(ConfigurationError, match="belongs to org 'org1'"):
        ensure_local_operator(store, _settings(tmp_path))


def test_the_configured_operator_and_org_are_used(tmp_path, monkeypatch):
    app, store = _build(
        tmp_path,
        monkeypatch,
        auth_local_autosignin_operator_id="gaurav",
        auth_local_autosignin_org_id="org2",
    )
    with TestClient(app, **LOOPBACK) as client:
        body = client.post(URL, json={"token": TOKEN}).json()
    assert body["org_id"] == "org2"
    assert store.get("gaurav").org_id == "org2"


@pytest.mark.parametrize("change", ["deactivated", "deleted"])
def test_an_operator_changed_after_startup_is_refused(tmp_path, monkeypatch, change):
    app, store = _build(tmp_path, monkeypatch)
    if change == "deactivated":
        store._operators["local"]["is_active"] = False
    else:
        del store._operators["local"]
    with TestClient(app, **LOOPBACK) as client:
        response = client.post(URL, json={"token": TOKEN})
    assert (response.status_code, response.json()) == (401, {"detail": REJECTED_DETAIL})


def test_an_empty_store_gets_both_the_bootstrap_and_the_local_operator(tmp_path, monkeypatch):
    _, store = _build(
        tmp_path,
        monkeypatch,
        auth_bootstrap_operator_id="admin",
        auth_bootstrap_operator_password=SecretStr("bootstrap-password"),
    )
    assert {op.operator_id for op in store.list_operators()} == {"admin", "local"}


# -- Host allowlist (TrustedHostMiddleware) ----------------------------------------


@pytest.fixture
def ui_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "cwd" / "rankuno-ui" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "cwd")
    return dist


def test_allowed_hosts_refuse_a_foreign_host(tmp_path, monkeypatch, ui_dist):
    app, _ = _build(tmp_path, monkeypatch, api_allowed_hosts="127.0.0.1,localhost")
    with TestClient(app, **LOOPBACK) as client:
        assert client.get(f"{API_PREFIX}/health", headers={"Host": "evil.example"}).status_code == (
            400
        )
        assert client.get(f"{API_PREFIX}/health").status_code == 200
        assert client.get("/", headers={"Host": "localhost:8000"}).text == "<html>spa</html>"
        assert client.post(URL, json={"token": TOKEN}).status_code == 200


def test_without_allowed_hosts_nothing_changes(tmp_path, monkeypatch, ui_dist):
    app, _ = _build(tmp_path, monkeypatch, auth_local_autosignin_token=None)
    with TestClient(app) as client:
        assert client.get(f"{API_PREFIX}/health", headers={"Host": "evil.example"}).status_code == (
            200
        )
        assert client.get("/").text == "<html>spa</html>"
