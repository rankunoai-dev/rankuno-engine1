"""Shared setup for the `/auth/local-signin` tests (ADR 0033).

Not a test module (no `test_` prefix), so pytest does not collect it; both
`test_local_signin.py` and `test_local_signin_operator.py` import from here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import src.api.server as server_module
from fastapi import FastAPI
from pydantic import SecretStr
from src.api.local_signin import LOCAL_SIGNIN_PATH
from src.api.server import API_PREFIX, create_app
from src.core.auth import DiskOperatorStore
from src.core.config import Settings
from src.core.local_signin import LocalSigninGate
from src.core.state_store import DiskJobStore

from tests.api.conftest import TEST_SESSION_SECRET

__all__ = [
    "LOOPBACK",
    "SESSION_TTL_S",
    "TOKEN",
    "URL",
    "WRONG",
    "build_app",
    "local_settings",
]

TOKEN = "5a" * 32
WRONG = "a5" * 32
URL = f"{API_PREFIX}{LOCAL_SIGNIN_PATH}"
LOOPBACK: dict[str, Any] = {"base_url": "http://127.0.0.1:8000", "client": ("127.0.0.1", 50000)}
SESSION_TTL_S = 43_200


def local_settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "audit_log_path": tmp_path / "audit.jsonl",
        "auth_operator_store_path": tmp_path / "operators",
        "auth_local_autosignin_token": SecretStr(TOKEN),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def build_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    postgres: bool = False,
    clock: list[float] | None = None,
    **overrides: object,
) -> tuple[FastAPI, DiskOperatorStore]:
    settings = local_settings(tmp_path, **overrides)
    monkeypatch.setattr(server_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        server_module,
        "get_postgres_settings",
        lambda: SimpleNamespace(is_configured=lambda: postgres),
    )
    if clock is not None:
        monkeypatch.setattr(
            server_module,
            "LocalSigninGate",
            lambda token: LocalSigninGate(token, clock=lambda: clock[0]),
        )
    store = DiskOperatorStore(tmp_path / "operators")
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        operator_store=store,
        session_secret=TEST_SESSION_SECRET,
        process_ledger_path=tmp_path / "ledger.json",
    )
    return app, store
