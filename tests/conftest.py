"""Shared pytest fixtures.

Three invariants this file exists to protect:

1. Tests never read the developer's real `.env`. Every test gets an explicit,
   hermetic `Settings` object.
2. Tests never touch a real external service. There is no network fixture here
   on purpose - connectors are mocked at the `BaseAPIClient` boundary.
3. Tests never write to, or act on, this workstation's own durable files.
   The module-level block below is that invariant - `audit_log_path` and
   `process_supervisor_ledger_path` are redirected into a throwaway directory
   before the first `src` import. Read its comment before weakening it: it was
   added after running `pytest` killed a live 1h47m Screaming Frog crawl
   (cycle 0113).
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Iterator

# -- Invariant 3, and it has to run here ---------------------------------------
#
# Before any `src` import, not in a fixture. `get_logger` calls `setup_logging`
# on first use, and first use is at *import* time - so by the time the earliest
# fixture could run, a `FileHandler` on the real audit log is already open and
# `src.core.celery_config` has already written a line into it. Settings read
# these two names from the environment (`get_settings()`), and env set here
# survives the per-test `reset_settings_cache()` below, which rebuilds
# `Settings` from scratch between every single test.
#
# The ledger is the one that mattered. Every `TestClient(create_app(...))` runs
# startup orphan reconciliation against whatever path settings name, and on a
# workstation that is the same ledger a *live* Screaming Frog crawl is enrolled
# in - so running `pytest` killed the crawl, twice, the second time at 99.7%
# (cycle 0113). Reconciliation itself is deliberately left switched on: it is
# the routine that misfired, and disabling it under test would hide the next
# regression in exactly the code that needs watching. Only its target moves.
_TEST_STATE_DIR = tempfile.mkdtemp(prefix="rankuno-test-state-")
atexit.register(shutil.rmtree, _TEST_STATE_DIR, True)  # noqa: FBT003 - `ignore_errors`
os.environ["AUDIT_LOG_PATH"] = os.path.join(_TEST_STATE_DIR, "audit.jsonl")
os.environ["PROCESS_SUPERVISOR_LEDGER_PATH"] = os.path.join(_TEST_STATE_DIR, ".process_ledger.json")

import pytest  # noqa: E402 - must not import `src` before the block above runs
from src.core import memory_budget as _memory_budget  # noqa: E402
from src.core.config import Environment, Settings, reset_settings_cache  # noqa: E402
from src.core.guardrails import AutoApproveProvider, GuardrailEngine  # noqa: E402
from src.core.rate_limiter import CostLedger  # noqa: E402
from src.core.registry import registry  # noqa: E402
from src.core.schemas import RiskClass, ToolMetadata  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> Iterator[None]:
    """Clear the settings singleton around every test."""
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def allow_over_credit() -> None:
    """Opt a test out of `_fail_on_memory_over_credit`, for tests of the clamp itself."""


@pytest.fixture(autouse=True)
def _fail_on_memory_over_credit(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Fail any test during which the memory budget was over-credited (ADR 0035).

    Production clamps an over-credit and logs it at ERROR, because a crawl must
    not die for a bookkeeping bug. That makes the bug silent unless something
    reads the log, so the suite reads it: any test that over-credits — a body
    credited twice, or one never charged — fails here, whichever thread did it.
    """
    seen: list[object] = []
    real = _memory_budget._logger.error

    def spy(event: str, *args: object, **kwargs: object) -> None:
        if event == "crawl_memory_budget_over_credit":
            seen.append(kwargs.get("extra"))
        real(event, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_memory_budget._logger, "error", spy)
    yield
    if seen and "allow_over_credit" not in request.fixturenames:
        pytest.fail(f"the memory budget was over-credited: {seen}")


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Keep tool registrations from leaking between tests."""
    registry.clear()
    yield
    registry.clear()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Hermetic settings: no `.env`, audit log redirected into tmp."""
    return Settings(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        audit_log_path=tmp_path / "audit.jsonl",
        max_session_spend_usd=1.0,
        default_requests_per_minute=600,
        default_timeout_s=2.0,
    )


@pytest.fixture
def permissive_guardrails(settings: Settings) -> GuardrailEngine:
    """Engine that approves HITL prompts. For testing the happy path only."""
    return GuardrailEngine(approval_provider=AutoApproveProvider(), settings=settings)


@pytest.fixture
def strict_guardrails(settings: Settings) -> GuardrailEngine:
    """Engine with the production default: deny unapproved HITL actions."""
    return GuardrailEngine(settings=settings)


@pytest.fixture
def ledger() -> CostLedger:
    """A small, isolated spend ledger."""
    return CostLedger(ceiling_usd=1.0)


@pytest.fixture
def read_metadata() -> ToolMetadata:
    """Metadata for a harmless read-only tool."""
    return ToolMetadata(
        name="test.reader",
        summary="Read-only test tool.",
        risk_class=RiskClass.READ,
    )


@pytest.fixture
def write_metadata() -> ToolMetadata:
    """Metadata for a tool that mutates external state."""
    return ToolMetadata(
        name="test.writer",
        summary="Write test tool.",
        risk_class=RiskClass.WRITE,
    )
