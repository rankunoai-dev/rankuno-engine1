"""`POST /auth/local-signin` and its wiring in `create_app()` (ADR 0033).

The gate's own single-use mechanics are `tests/core/test_local_signin.py`'s
job. This file is about the HTTP layer: when the route exists, who may reach
it, that every refusal looks the same, and that the token reaches no log line
and no error body. The dedicated operator and the Host allowlist are in
`test_local_signin_operator.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from src.api.local_signin import REJECTED_DETAIL, _is_loopback
from src.api.server import API_PREFIX
from src.core.auth import verify_session_token
from src.core.config import ProcessRole
from src.core.errors import ConfigurationError

from tests.api.conftest import TEST_SESSION_SECRET
from tests.api.local_signin_support import (
    LOOPBACK,
    SESSION_TTL_S,
    TOKEN,
    URL,
    WRONG,
)
from tests.api.local_signin_support import build_app as _build


@pytest.fixture
def captured(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture `rankuno.*` records. That root does not propagate, so attach directly."""
    root = logging.getLogger("rankuno")
    root.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="rankuno")
    try:
        yield caplog
    finally:
        root.removeHandler(caplog.handler)


def _record_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{record.getMessage()} {record.__dict__!r}" for record in caplog.records)


def test_route_does_not_exist_without_a_token(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch, auth_local_autosignin_token=None)
    with TestClient(app, **LOOPBACK) as client:
        assert client.post(URL, json={"token": TOKEN}).status_code == 404


def test_the_link_signs_in_as_the_local_operator(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        before = datetime.now(UTC)
        response = client.post(URL, json={"token": TOKEN})
    assert response.status_code == 200
    body = response.json()
    principal = verify_session_token(body["token"], secret=TEST_SESSION_SECRET)
    assert (principal.operator_id, principal.org_id) == ("local", "default")
    assert body["org_id"] == "default"
    assert body["token_type"] == "bearer"
    # Same lifetime as /auth/login, not a shorter or longer one of its own.
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert abs((expires_at - before) - timedelta(seconds=SESSION_TTL_S)) < timedelta(seconds=30)


def test_the_session_authenticates_other_routes(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        token = client.post(URL, json={"token": TOKEN}).json()["token"]
        listed = client.get(f"{API_PREFIX}/jobs", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200


def _reject_cases(client: TestClient) -> dict[str, object]:
    """Drive a wrong token and a reused one; return each response."""
    bodies: dict[str, object] = {}
    wrong = client.post(URL, json={"token": WRONG})
    bodies["wrong"] = (wrong.status_code, wrong.json())
    assert client.post(URL, json={"token": TOKEN}).status_code == 200
    reused = client.post(URL, json={"token": TOKEN})
    bodies["reused"] = (reused.status_code, reused.json())
    return bodies


def test_every_refusal_is_the_same_401(tmp_path, monkeypatch):
    clock = [0.0]
    app, _ = _build(tmp_path, monkeypatch, clock=clock)
    with TestClient(app, **LOOPBACK) as client:
        bodies = _reject_cases(client)

    expired_clock = [0.0]
    app, _ = _build(tmp_path / "b", monkeypatch, clock=expired_clock)
    with TestClient(app, **LOOPBACK) as client:
        expired_clock[0] = 300.0
        response = client.post(URL, json={"token": TOKEN})
        bodies["expired"] = (response.status_code, response.json())

    app, _ = _build(tmp_path / "c", monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        for _ in range(5):
            client.post(URL, json={"token": WRONG})
        response = client.post(URL, json={"token": TOKEN})
        bodies["locked"] = (response.status_code, response.json())

    app, _ = _build(tmp_path / "d", monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1", client=("10.0.0.5", 1)) as client:
        response = client.post(URL, json={"token": TOKEN})
        bodies["remote_client"] = (response.status_code, response.json())
    with TestClient(app) as client:  # default `testserver`: not a loopback bind
        response = client.post(URL, json={"token": TOKEN})
        bodies["non_loopback_server"] = (response.status_code, response.json())

    expected = (401, {"detail": REJECTED_DETAIL})
    assert bodies == dict.fromkeys(bodies, expected)
    assert set(bodies) == {
        "wrong",
        "reused",
        "expired",
        "locked",
        "remote_client",
        "non_loopback_server",
    }


def test_a_refused_remote_request_does_not_spend_the_link(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.9", 1)) as client:
        assert client.post(URL, json={"token": TOKEN}).status_code == 401
    with TestClient(app, **LOOPBACK) as client:
        assert client.post(URL, json={"token": TOKEN}).status_code == 200


def test_an_ipv6_loopback_client_is_accepted(tmp_path, monkeypatch):
    # TestClient cannot parse an IPv6 base_url; the bind side is unit-tested below.
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1", client=("::1", 50000)) as client:
        assert client.post(URL, json={"token": TOKEN}).status_code == 200


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("localhost", False),
        ("10.0.0.1", False),
        ("::ffff:10.0.0.1", False),
        ("", False),
        (None, False),
        (8000, False),
    ],
)
def test_loopback_detection(host, expected):
    assert _is_loopback(host) is expected


def test_the_route_is_rate_limited(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        statuses = [client.post(URL, json={"token": WRONG}).status_code for _ in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


def test_the_route_declares_no_query_parameter(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch)
    operation = app.openapi()["paths"][URL]["post"]
    assert "parameters" not in operation or operation["parameters"] == []
    with TestClient(app, **LOOPBACK) as client:
        # A token in the query string is ignored, never accepted.
        assert client.post(f"{URL}?token={TOKEN}", json={"token": WRONG}).status_code == 401


@pytest.mark.parametrize(
    "body", [{"token": TOKEN, "extra": 1}, {"token": "a" * 257}, {}, {"token": 5}]
)
def test_a_malformed_body_is_422(tmp_path, monkeypatch, body):
    app, _ = _build(tmp_path, monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        assert client.post(URL, json=body).status_code == 422


def test_the_token_reaches_no_log_and_no_error_body(tmp_path, monkeypatch, captured):
    clock = [0.0]
    app, _ = _build(tmp_path, monkeypatch, clock=clock)
    bodies: list[str] = []
    with TestClient(app, **LOOPBACK) as client:
        bodies.append(client.post(URL, json={"token": WRONG}).text)  # wrong
        assert client.post(URL, json={"token": TOKEN}).status_code == 200  # success
        bodies.append(client.post(URL, json={"token": TOKEN}).text)  # reused
        for _ in range(8):  # past the 10-per-minute bucket: rate-limited
            bodies.append(client.post(URL, json={"token": TOKEN}).text)
        assert '"too many sign-in attempts' in bodies[-1]
    expired_clock = [0.0]
    app, _ = _build(tmp_path / "b", monkeypatch, clock=expired_clock)
    with TestClient(app, **LOOPBACK) as client:
        expired_clock[0] = 301.0
        bodies.append(client.post(URL, json={"token": TOKEN}).text)  # expired
    app, _ = _build(tmp_path / "c", monkeypatch)
    with TestClient(app, **LOOPBACK) as client:
        for _ in range(5):
            client.post(URL, json={"token": WRONG})
        bodies.append(client.post(URL, json={"token": TOKEN}).text)  # locked

    text = _record_text(captured)
    events = {record.getMessage() for record in captured.records}
    # Non-vacuous: the capture really saw this route's events.
    assert {"local_signin_succeeded", "local_signin_rejected", "local_signin_rate_limited"} <= (
        events
    )
    reasons = {getattr(record, "reason", None) for record in captured.records}
    assert {"mismatch", "consumed", "expired", "locked"} <= reasons
    assert TOKEN not in text
    for body in bodies:
        assert TOKEN not in body


def test_create_app_refuses_the_token_with_postgres_configured(tmp_path, monkeypatch):
    with pytest.raises(ConfigurationError, match="Postgres is configured"):
        _build(tmp_path, monkeypatch, postgres=True)


def test_postgres_alone_still_starts(tmp_path, monkeypatch):
    app, _ = _build(tmp_path, monkeypatch, postgres=True, auth_local_autosignin_token=None)
    assert app is not None


def test_the_worker_refusal_still_comes_first(tmp_path, monkeypatch):
    with pytest.raises(ConfigurationError, match="RANKUNO_PROCESS_ROLE=worker"):
        _build(tmp_path, monkeypatch, postgres=True, rankuno_process_role=ProcessRole.WORKER)
