"""Worker credential storage and precedence (ADR 0030).

Orchestration runs against `_InMemoryVault`. `WindowsCredentialVault` is tested
against a fake `win32cred` for its error mapping, and once against the real
Credential Manager (integration, Windows only) with a throwaway target it
deletes again.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from src.core import credential_vault
from src.core.config import Settings, WorkerCredentialStore
from src.core.credential_vault import (
    CredentialVaultError,
    WindowsCredentialVault,
    resolve_worker_credential,
    worker_credential_target,
)


class _InMemoryVault:
    """A `CredentialVault` that never touches the OS."""

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self.entries = dict(entries or {})

    def read(self, target: str) -> SecretStr | None:
        value = self.entries.get(target)
        return SecretStr(value) if value is not None else None

    def write(self, target: str, *, username: str, secret: SecretStr) -> None:
        self.entries[target] = secret.get_secret_value()

    def delete(self, target: str) -> None:
        self.entries.pop(target, None)


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "audit_log_path": tmp_path / "a.jsonl",
        "worker_id": "wkr-1",
        "worker_credential": SecretStr("env-cred"),
    }
    base.update(overrides)
    return Settings(**base)


def _vault_with(secret: str) -> _InMemoryVault:
    return _InMemoryVault({worker_credential_target("wkr-1"): secret})


def _no_vault() -> _InMemoryVault:  # pragma: no cover - asserted never to be called
    raise AssertionError("the default checkout path must not touch Credential Manager")


# --- Precedence ----------------------------------------------------------------------


def test_target_name_is_fixed_and_per_worker() -> None:
    assert worker_credential_target("wkr-9") == "Rankuno Worker/wkr-9"


def test_checkout_default_reads_the_env_value_and_never_the_vault(tmp_path: Path) -> None:
    result = resolve_worker_credential(_settings(tmp_path), vault_factory=_no_vault, frozen=False)
    assert result is not None and result.get_secret_value() == "env-cred"


def test_checkout_configured_for_the_vault_prefers_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path, worker_credential_store=WorkerCredentialStore.CREDENTIAL_MANAGER)
    result = resolve_worker_credential(
        settings, vault_factory=lambda: _vault_with("vault-cred"), frozen=False
    )
    assert result is not None and result.get_secret_value() == "vault-cred"


def test_checkout_falls_back_to_env_when_the_vault_is_empty(tmp_path: Path) -> None:
    settings = _settings(tmp_path, worker_credential_store=WorkerCredentialStore.CREDENTIAL_MANAGER)
    result = resolve_worker_credential(settings, vault_factory=_InMemoryVault, frozen=False)
    assert result is not None and result.get_secret_value() == "env-cred"


def test_frozen_reads_the_vault_and_ignores_a_plaintext_env_value(tmp_path: Path) -> None:
    result = resolve_worker_credential(
        _settings(tmp_path), vault_factory=lambda: _vault_with("vault-cred"), frozen=True
    )
    assert result is not None and result.get_secret_value() == "vault-cred"


def test_frozen_never_falls_back_to_plaintext(tmp_path: Path) -> None:
    """Even `WORKER_CREDENTIAL_STORE=env` cannot put the packaged worker on a file."""
    settings = _settings(tmp_path, worker_credential_store=WorkerCredentialStore.ENV)
    assert resolve_worker_credential(settings, vault_factory=_InMemoryVault, frozen=True) is None


def test_no_worker_id_means_no_credential(tmp_path: Path) -> None:
    settings = _settings(tmp_path, worker_id=None)
    assert resolve_worker_credential(settings, vault_factory=_InMemoryVault, frozen=True) is None


def test_frozen_detection_defaults_to_sys_frozen(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    result = resolve_worker_credential(_settings(tmp_path), vault_factory=_InMemoryVault)
    assert result is None


def test_default_vault_refuses_a_non_windows_platform(monkeypatch) -> None:
    monkeypatch.setattr(credential_vault.sys, "platform", "linux")
    with pytest.raises(CredentialVaultError, match="Windows only"):
        credential_vault.default_vault()


def test_default_vault_is_credential_manager_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(credential_vault.sys, "platform", "win32")
    assert isinstance(credential_vault.default_vault(), WindowsCredentialVault)


# --- WindowsCredentialVault against a fake win32cred ----------------------------------


class _FakeWin32Error(Exception):
    def __init__(self, winerror: int) -> None:
        super().__init__(winerror)
        self.winerror = winerror


def _fake_modules(store: dict[str, Any], *, fail_with: int | None = None) -> tuple[Any, Any]:
    def _guard() -> None:
        if fail_with is not None:
            raise _FakeWin32Error(fail_with)

    def cred_read(target: str, _type: int) -> dict[str, Any]:
        _guard()
        if target not in store:
            raise _FakeWin32Error(1168)
        return {"CredentialBlob": store[target]["CredentialBlob"].encode("utf-16-le")}

    def cred_write(credential: dict[str, Any], _flags: int) -> None:
        _guard()
        store[credential["TargetName"]] = credential

    def cred_delete(target: str, _type: int) -> None:
        _guard()
        if target not in store:
            raise _FakeWin32Error(1168)
        del store[target]

    win32cred = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CRED_PERSIST_LOCAL_MACHINE=2,
        CredRead=cred_read,
        CredWrite=cred_write,
        CredDelete=cred_delete,
    )
    return win32cred, SimpleNamespace(error=_FakeWin32Error)


def test_windows_vault_round_trips_and_writes_a_string_blob(monkeypatch) -> None:
    store: dict[str, Any] = {}
    monkeypatch.setattr(
        WindowsCredentialVault, "_modules", staticmethod(lambda: _fake_modules(store))
    )
    vault = WindowsCredentialVault()
    vault.write("t", username="wkr-1", secret=SecretStr("s3cret-é"))
    assert isinstance(store["t"]["CredentialBlob"], str)
    assert store["t"]["Persist"] == 2
    read = vault.read("t")
    assert read is not None and read.get_secret_value() == "s3cret-é"
    vault.delete("t")
    assert vault.read("t") is None
    vault.delete("t")  # absent: already the desired state


@pytest.mark.parametrize("operation", ["read", "write", "delete"])
def test_windows_vault_maps_os_errors_without_echoing_the_secret(monkeypatch, operation) -> None:
    monkeypatch.setattr(
        WindowsCredentialVault,
        "_modules",
        staticmethod(lambda: _fake_modules({}, fail_with=5)),
    )
    vault = WindowsCredentialVault()
    with pytest.raises(CredentialVaultError, match="error 5") as caught:
        if operation == "read":
            vault.read("t")
        elif operation == "write":
            vault.write("t", username="u", secret=SecretStr("never-shown"))
        else:
            vault.delete("t")
    assert "never-shown" not in str(caught.value)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager only")
def test_real_credential_manager_round_trip() -> None:
    """One live write/read/delete under a unique throwaway target."""
    vault = WindowsCredentialVault()
    target = f"Rankuno Worker Test/{uuid.uuid4().hex}"
    try:
        vault.write(target, username="test", secret=SecretStr("round-trip-value"))
        read = vault.read(target)
        assert read is not None and read.get_secret_value() == "round-trip-value"
    finally:
        vault.delete(target)
    assert vault.read(target) is None
