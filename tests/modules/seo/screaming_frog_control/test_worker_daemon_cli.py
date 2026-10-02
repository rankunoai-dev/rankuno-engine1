"""Tests for the worker daemon's entry point.

`run_worker_daemon` previously had no caller anywhere outside its own module
and its tests — a correct loop nothing could start. What this file proves is
the part an operator actually meets: a missing setting is named rather than
producing a stack trace, a rejected credential exits with its own code
instead of restarting forever, and no secret is ever accepted as an argument
or printed back.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest
from pydantic import SecretStr
from src.core.config import Environment, Settings
from src.core.errors import ConfigurationError, WorkerCredentialRejectedError
from src.core.worker_dispatch_keys import DispatchSigningKey
from src.modules.seo.screaming_frog_control import worker_daemon_cli


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.DEVELOPMENT,
        "audit_log_path": tmp_path / "audit.jsonl",
        "worker_cloud_api_base_url": "https://api.example.com",
        "worker_id": "wkr-alice-desktop",
        "worker_org_id": "acme",
        "worker_credential": SecretStr("a-real-worker-secret"),
        "worker_dispatch_signing_secret": SecretStr("a-shared-signing-key"),
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: settings)
    return settings


# --- Configuration reporting ----------------------------------------------------


def test_missing_settings_names_every_environment_variable(tmp_path):
    settings = _settings(tmp_path, worker_id=None, worker_credential=None)
    assert worker_daemon_cli.missing_settings(settings) == ["WORKER_ID", "WORKER_CREDENTIAL"]


def test_missing_settings_is_empty_when_fully_configured(tmp_path):
    assert worker_daemon_cli.missing_settings(_settings(tmp_path)) == []


def test_a_missing_verification_key_is_reported_not_left_mysterious(tmp_path):
    """Every dispatch would fail signature verification with no clue why.

    `Settings` generates a random HMAC key outside production, so this is
    exactly the case that otherwise presents as "the cloud approved it and
    the worker silently refused it", over and over. Since ADR 0028 the name
    reported is the public verify key — a new install must never be sent to
    fetch the shared HMAC secret.
    """
    settings = _settings(tmp_path, worker_dispatch_signing_secret=None)
    assert worker_daemon_cli.missing_settings(settings) == ["WORKER_DISPATCH_VERIFY_KEY"]


def test_the_daemon_starts_with_only_the_verify_key(tmp_path, monkeypatch):
    """ADR 0028: a new worker needs the public key and never the HMAC secret.

    Fails on the pre-ADR-0028 code, which listed WORKER_DISPATCH_SIGNING_SECRET
    as unconditionally required and exited with EXIT_CONFIGURATION here.
    """
    verify_key = DispatchSigningKey.generate().public_key_b64
    settings = _settings(
        tmp_path, worker_dispatch_signing_secret=None, worker_dispatch_verify_key=verify_key
    )
    assert worker_daemon_cli.missing_settings(settings) == []

    started: list[Settings] = []
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        worker_daemon_cli, "run_worker_daemon", lambda **kw: started.append(kw["settings"])
    )
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_OK
    assert started == [settings]


def test_main_refuses_to_start_and_names_what_is_missing(tmp_path, monkeypatch, capsys):
    settings = _settings(tmp_path, worker_cloud_api_base_url=None)
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: settings)

    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CONFIGURATION
    assert "WORKER_CLOUD_API_BASE_URL" in capsys.readouterr().err


def test_check_reports_configuration_without_polling(configured, monkeypatch, capsys):
    def _never_called(**_kwargs: object) -> None:  # pragma: no cover - must not run
        raise AssertionError("--check must not start the poll loop")

    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", _never_called)
    assert worker_daemon_cli.main(["--check"]) == worker_daemon_cli.EXIT_OK
    out = capsys.readouterr().out
    assert "wkr-alice-desktop" in out
    assert "a-real-worker-secret" not in out


def test_no_output_path_ever_prints_a_secret(configured, monkeypatch, capsys):
    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", lambda **_k: None)
    worker_daemon_cli.main(["--check"])
    worker_daemon_cli.main([])
    captured = capsys.readouterr()
    assert "a-real-worker-secret" not in captured.out + captured.err
    assert "a-shared-signing-key" not in captured.out + captured.err


def test_the_parser_accepts_no_secret_bearing_option():
    """A secret passed positionally lands in shell history and `ps` output."""
    options = {
        action.dest
        for action in worker_daemon_cli.build_parser()._actions  # noqa: SLF001
    }
    assert not {"worker_secret", "credential", "secret", "password"} & options


# --- Exit codes: "restart me" vs "a human must fix something" -------------------


def test_a_rejected_credential_exits_with_its_own_code(configured, monkeypatch):
    def _rejected(**_kwargs: object) -> None:
        raise WorkerCredentialRejectedError("the cloud API refused this worker's credential")

    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", _rejected)
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CREDENTIAL_REJECTED


def test_a_configuration_error_raised_by_the_loop_exits_as_configuration(configured, monkeypatch):
    def _misconfigured(**_kwargs: object) -> None:
        raise ConfigurationError("worker_org_id is unset")

    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", _misconfigured)
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CONFIGURATION


def test_a_clean_shutdown_exits_zero(configured, monkeypatch):
    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", lambda **_k: None)
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_OK


# --- Signals ---------------------------------------------------------------------


def test_sigint_sets_the_stop_flag_rather_than_raising_mid_job(configured, monkeypatch):
    """The default handler would raise KeyboardInterrupt inside the upload."""
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> None:
        captured["should_stop"] = kwargs["should_stop"]
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        assert handler is not signal.default_int_handler
        handler(signal.SIGINT, None)

    monkeypatch.setattr(worker_daemon_cli, "run_worker_daemon", _capture)
    original = signal.getsignal(signal.SIGINT)
    try:
        assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_OK
    finally:
        signal.signal(signal.SIGINT, original)

    should_stop = captured["should_stop"]
    assert callable(should_stop)
    assert should_stop() is True


def test_max_iterations_is_forwarded_to_the_loop(configured, monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        worker_daemon_cli, "run_worker_daemon", lambda **kwargs: captured.update(kwargs)
    )
    worker_daemon_cli.main(["--max-iterations", "3"])
    assert captured["max_iterations"] == 3


# --- The packaged worker (ADR 0030) ---------------------------------------------


@pytest.fixture
def frozen_root(tmp_path, monkeypatch):
    """Simulate `rankuno-worker.exe` with its profile directory under `tmp_path`."""
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("RANKUNO_WORKER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


class _Vault:
    def __init__(self, entries: dict[str, str]) -> None:
        self.entries = entries

    def read(self, target: str) -> SecretStr | None:
        value = self.entries.get(target)
        return SecretStr(value) if value is not None else None


def test_setup_is_refused_in_a_checkout(capsys):
    assert worker_daemon_cli.main(["setup"]) == worker_daemon_cli.EXIT_CONFIGURATION
    assert "scripts/register_worker.py" in capsys.readouterr().err


def test_setup_runs_in_the_packaged_worker(frozen_root, monkeypatch):
    calls: list[Path] = []

    def _fake_setup(root: Path, **_kwargs: object) -> bool:
        calls.append(root)
        return True

    monkeypatch.setattr(worker_daemon_cli, "run_setup", _fake_setup)
    assert worker_daemon_cli.main(["setup"]) == worker_daemon_cli.EXIT_OK
    assert calls == [frozen_root]
    assert frozen_root.is_dir()


def test_a_failed_setup_exits_as_configuration(frozen_root, monkeypatch):
    monkeypatch.setattr(worker_daemon_cli, "run_setup", lambda root, **_k: False)
    assert worker_daemon_cli.main(["setup"]) == worker_daemon_cli.EXIT_CONFIGURATION


def test_first_launch_runs_setup_then_starts(frozen_root, tmp_path, monkeypatch):
    settings = _settings(tmp_path, worker_credential=None)
    vault = _Vault({"Rankuno Worker/wkr-alice-desktop": "vault-secret"})
    setups: list[Path] = []
    started: list[Settings] = []
    monkeypatch.setattr(worker_daemon_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        worker_daemon_cli, "run_setup", lambda root, **_k: setups.append(root) or True
    )
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_daemon_cli, "default_vault", lambda: vault)
    monkeypatch.setattr(
        worker_daemon_cli, "run_worker_daemon", lambda **kw: started.append(kw["settings"])
    )

    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_OK
    assert setups == [frozen_root]
    credential = started[0].worker_credential
    assert credential is not None and credential.get_secret_value() == "vault-secret"


def test_first_launch_without_a_terminal_says_to_run_setup(frozen_root, monkeypatch, capsys):
    monkeypatch.setattr(worker_daemon_cli.sys.stdin, "isatty", lambda: False)
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CONFIGURATION
    assert "rankuno-worker setup" in capsys.readouterr().err


def test_first_launch_setup_failure_does_not_start(frozen_root, monkeypatch):
    monkeypatch.setattr(worker_daemon_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(worker_daemon_cli, "run_setup", lambda root, **_k: False)
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CONFIGURATION


def test_the_packaged_worker_ignores_a_plaintext_credential(
    frozen_root, tmp_path, monkeypatch, capsys
):
    """An env-file WORKER_CREDENTIAL with an empty vault is reported missing, never used."""
    frozen_root.mkdir(parents=True)
    (frozen_root / "worker.env").write_text("WORKER_ID=wkr-alice-desktop\n", encoding="utf-8")
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(worker_daemon_cli, "default_vault", lambda: _Vault({}))
    assert worker_daemon_cli.main([]) == worker_daemon_cli.EXIT_CONFIGURATION
    err = capsys.readouterr().err
    assert "WORKER_CREDENTIAL" in err
    assert "rankuno-worker setup" in err


def test_an_unusable_vault_exits_as_configuration(frozen_root, tmp_path, monkeypatch):
    frozen_root.mkdir(parents=True)
    (frozen_root / "worker.env").write_text("WORKER_ID=wkr-alice-desktop\n", encoding="utf-8")
    monkeypatch.setattr(worker_daemon_cli, "get_settings", lambda: _settings(tmp_path))

    def _unavailable() -> _Vault:
        raise ConfigurationError("runs on Windows only")

    monkeypatch.setattr(worker_daemon_cli, "default_vault", _unavailable)
    assert worker_daemon_cli.main(["--check"]) == worker_daemon_cli.EXIT_CONFIGURATION
