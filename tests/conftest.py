"""Shared pytest fixtures.

Two invariants this file exists to protect:

1. Tests never read the developer's real `.env`. Every test gets an explicit,
   hermetic `Settings` object.
2. Tests never touch a real external service. There is no network fixture here
   on purpose - connectors are mocked at the `BaseAPIClient` boundary.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from src.core.config import Environment, Settings, reset_settings_cache
from src.core.guardrails import AutoApproveProvider, GuardrailEngine
from src.core.rate_limiter import CostLedger
from src.core.registry import registry
from src.core.schemas import RiskClass, ToolMetadata


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> Iterator[None]:
    """Clear the settings singleton around every test."""
    reset_settings_cache()
    yield
    reset_settings_cache()


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
