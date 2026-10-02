"""The cloud API refuses to start under the worker role (ADR 0030).

A worker skips production's cloud-secret checks; a server that inherited that
role would boot without them. `create_app` refuses before building anything.
"""

from __future__ import annotations

import pytest
from src.api.server import create_app
from src.core.errors import ConfigurationError


def test_create_app_refuses_the_worker_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RANKUNO_PROCESS_ROLE", "worker")
    with pytest.raises(ConfigurationError, match="RANKUNO_PROCESS_ROLE=worker"):
        create_app()
