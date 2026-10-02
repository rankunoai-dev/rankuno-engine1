"""Frozen-aware paths (ADR 0030): the packaged worker writes to its profile, nothing else moves.

A frozen build is simulated by setting `sys.frozen`, the attribute PyInstaller
sets, and pointing `LOCALAPPDATA` at a temp directory. The two env overrides
`tests/conftest.py` sets for every test (audit log, process ledger) are removed
here, because they would mask exactly the defaults under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import SecretStr
from src.core import app_paths
from src.core.app_paths import REPO_ROOT, WORKER_HOME_ENV, env_files, resolve_user_data_root
from src.core.config import Environment, ProcessRole, Settings
from src.core.errors import ConfigurationError
from src.core.worker_consumed_ledger import ConsumedJobLedger

_WORKER_PATH_FIELDS = (
    "audit_log_path",
    "deliverables_output_dir",
    "screaming_frog_template_dir",
    "process_supervisor_ledger_path",
    "worker_consumed_jobs_path",
)


@pytest.fixture
def unmasked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the conftest's path overrides so Settings shows its real defaults."""
    for name in ("AUDIT_LOG_PATH", "PROCESS_SUPERVISOR_LEDGER_PATH", WORKER_HOME_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unmasked: None) -> Path:
    """Simulate a PyInstaller build whose `%LOCALAPPDATA%` is `tmp_path`."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "Rankuno" / "Worker"


# --- resolve_user_data_root -----------------------------------------------------


def test_a_checkout_always_resolves_to_the_repository() -> None:
    environ = {WORKER_HOME_ENV: "C:/elsewhere", "LOCALAPPDATA": "C:/Users/x/AppData/Local"}
    assert resolve_user_data_root(environ, frozen=False) == REPO_ROOT


def test_frozen_resolves_under_local_app_data() -> None:
    root = resolve_user_data_root({"LOCALAPPDATA": "C:/L"}, frozen=True)
    assert root == Path("C:/L") / "Rankuno" / "Worker"


def test_frozen_honours_the_override() -> None:
    environ = {WORKER_HOME_ENV: "D:/support", "LOCALAPPDATA": "C:/L"}
    assert resolve_user_data_root(environ, frozen=True) == Path("D:/support")


def test_frozen_without_local_app_data_falls_back_to_the_profile_default() -> None:
    root = resolve_user_data_root({}, frozen=True)
    assert root == Path.home() / "AppData" / "Local" / "Rankuno" / "Worker"


def test_env_files_keep_the_checkout_pair_and_give_the_worker_one_file(tmp_path: Path) -> None:
    assert env_files(tmp_path, frozen=False) == (tmp_path / ".env", tmp_path / ".env.local")
    assert env_files(tmp_path, frozen=True) == (tmp_path / "worker.env",)


def test_is_frozen_reads_sys_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    assert app_paths.is_frozen() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert app_paths.is_frozen() is True


def test_ensure_private_dir_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    assert app_paths.ensure_private_dir(target) == target
    assert target.is_dir()


# --- Settings defaults ------------------------------------------------------------


def test_checkout_defaults_are_unchanged(unmasked: None) -> None:
    """Byte-for-byte the pre-ADR-0030 REPO_ROOT paths, and the server role."""
    settings = Settings(_env_file=None)
    assert settings.audit_log_path == REPO_ROOT / "logs" / "audit.jsonl"
    assert settings.deliverables_output_dir == REPO_ROOT / "deliverables" / "output"
    assert settings.screaming_frog_template_dir == REPO_ROOT / "templates" / "screaming_frog"
    assert settings.process_supervisor_ledger_path == REPO_ROOT / ".process_ledger.json"
    assert settings.worker_consumed_jobs_path == REPO_ROOT / ".worker_consumed_jobs.json"
    assert settings.rankuno_process_role is ProcessRole.SERVER
    assert Settings.model_config["env_file"] == (REPO_ROOT / ".env", REPO_ROOT / ".env.local")


def test_frozen_puts_every_worker_path_under_the_user_root(frozen: Path) -> None:
    settings = Settings()
    for name in _WORKER_PATH_FIELDS:
        path: Path = getattr(settings, name)
        assert path.is_relative_to(frozen), f"{name} escaped the user root: {path}"
    assert settings.rankuno_process_role is ProcessRole.WORKER


def test_frozen_reads_worker_env_from_the_user_root(frozen: Path) -> None:
    frozen.mkdir(parents=True)
    (frozen / "worker.env").write_text("WORKER_ID=wkr-from-profile\n", encoding="utf-8")
    assert Settings().worker_id == "wkr-from-profile"


def test_frozen_still_honours_an_explicit_env_file(frozen: Path, tmp_path: Path) -> None:
    """A caller's own `_env_file` wins, so frozen-simulation tests stay hermetic."""
    frozen.mkdir(parents=True)
    (frozen / "worker.env").write_text("WORKER_ID=wkr-from-profile\n", encoding="utf-8")
    assert Settings(_env_file=None).worker_id is None


def test_the_consumed_jobs_ledger_survives_a_restart(frozen: Path) -> None:
    """ADR 0015 single-use across restarts: a fresh process sees the old ledger."""
    first = ConsumedJobLedger(Settings().worker_consumed_jobs_path)
    assert first.try_consume("job-1") is True

    restarted = ConsumedJobLedger(Settings().worker_consumed_jobs_path)
    assert restarted.has_run("job-1") is True
    assert restarted.try_consume("job-1") is False
    assert (frozen / ".worker_consumed_jobs.json").is_file()


# --- Process role: cloud-only checks apply to the server only ----------------------


def test_a_production_worker_needs_no_cloud_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        audit_log_path=tmp_path / "a.jsonl",
        environment=Environment.PRODUCTION,
        rankuno_process_role=ProcessRole.WORKER,
    )
    assert settings.auth_session_secret is None


def test_a_production_worker_still_refuses_disabled_guardrails(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings(
            _env_file=None,
            audit_log_path=tmp_path / "a.jsonl",
            environment=Environment.PRODUCTION,
            rankuno_process_role=ProcessRole.WORKER,
            guardrails_enabled=False,
        )


def test_a_production_server_still_demands_its_secrets(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="AUTH_SESSION_SECRET"):
        Settings(
            _env_file=None,
            audit_log_path=tmp_path / "a.jsonl",
            environment=Environment.PRODUCTION,
            worker_bundle_encryption_secret=SecretStr("x"),
        )


def test_a_frozen_production_worker_boots_without_cloud_secrets(frozen: Path) -> None:
    settings = Settings(_env_file=None, environment=Environment.PRODUCTION)
    assert settings.rankuno_process_role is ProcessRole.WORKER
