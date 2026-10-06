"""Settings for the local sign-in link and the Host allowlist (ADR 0033).

Split from `test_config.py`, already past the 400-line target.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from src.core.config import Environment, Settings
from src.core.errors import ConfigurationError

TOKEN = "0123456789abcdef" * 4


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None, "audit_log_path": tmp_path / "a.jsonl"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_token_is_off_by_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.auth_local_autosignin_token is None
    assert settings.auth_local_autosignin_operator_id == "local"
    assert settings.auth_local_autosignin_org_id == "default"


@pytest.mark.parametrize("token", [TOKEN, TOKEN.upper(), "a" * 256])
def test_a_hex_token_is_accepted_in_development(tmp_path: Path, token: str) -> None:
    settings = _settings(tmp_path, auth_local_autosignin_token=SecretStr(token))
    assert settings.auth_local_autosignin_token is not None
    assert settings.auth_local_autosignin_token.get_secret_value() == token


@pytest.mark.parametrize(
    "token",
    ["a" * 63, "a" * 257, "g" * 64, TOKEN[:-1] + " ", "zz-not-hex-" * 8],
)
def test_a_malformed_token_is_refused_without_echoing_it(tmp_path: Path, token: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        _settings(tmp_path, auth_local_autosignin_token=SecretStr(token))
    assert token.strip() not in str(excinfo.value)
    assert "64-256 hexadecimal" in str(excinfo.value)


@pytest.mark.parametrize(
    "environment", [env for env in Environment if env is not Environment.DEVELOPMENT]
)
def test_the_token_is_refused_outside_development(tmp_path: Path, environment: Environment) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        _settings(tmp_path, environment=environment, auth_local_autosignin_token=SecretStr(TOKEN))
    assert "ENVIRONMENT=development" in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)


def test_an_empty_token_reads_as_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The launcher blanks the variable under -NoAutoSignIn; that must mean off."""
    monkeypatch.setenv("AUTH_LOCAL_AUTOSIGNIN_TOKEN", "")
    monkeypatch.setenv("API_ALLOWED_HOSTS", " ")
    settings = _settings(tmp_path)
    assert settings.auth_local_autosignin_token is None
    assert settings.api_allowed_host_list == []


def test_the_token_is_read_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_LOCAL_AUTOSIGNIN_TOKEN", TOKEN)
    settings = _settings(tmp_path)
    assert settings.auth_local_autosignin_token is not None


def test_repr_masks_the_token(tmp_path: Path) -> None:
    settings = _settings(tmp_path, auth_local_autosignin_token=SecretStr(TOKEN))
    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)
    assert TOKEN not in settings.model_dump_json()


@pytest.mark.parametrize(
    "field", ["auth_local_autosignin_operator_id", "auth_local_autosignin_org_id"]
)
@pytest.mark.parametrize("value", ["Local", "a b", "", "x" * 65, "../etc"])
def test_operator_and_org_ids_are_validated(tmp_path: Path, field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, **{field: value})


def test_allowed_hosts_are_split_on_commas(tmp_path: Path) -> None:
    settings = _settings(tmp_path, api_allowed_hosts=" 127.0.0.1, localhost ,,")
    assert settings.api_allowed_host_list == ["127.0.0.1", "localhost"]


def test_allowed_hosts_are_off_by_default(tmp_path: Path) -> None:
    assert _settings(tmp_path).api_allowed_host_list == []
