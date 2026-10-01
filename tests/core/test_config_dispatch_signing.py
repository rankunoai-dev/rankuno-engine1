"""ADR 0028 settings: which dispatch signatures the cloud emits, and when it refuses to boot.

The production matrix is the part that matters for the live deployment:
deploying this change *before* the operator sets a private key must keep the
cloud running on the legacy HMAC secret exactly as it did, and switching the
legacy flag off must never leave it with nothing to sign with.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from src.core.config import Environment, Settings
from src.core.errors import ConfigurationError
from src.core.worker_dispatch_keys import DispatchSigningKey

HMAC = SecretStr("legacy-shared-hmac-key")
KEY = DispatchSigningKey.generate()


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None, "audit_log_path": tmp_path / "a.jsonl"}
    base.update(overrides)
    return Settings(**base)


def _production(tmp_path: Path, **overrides: object) -> Settings:
    return _settings(
        tmp_path,
        environment=Environment.PRODUCTION,
        auth_session_secret=SecretStr("session"),
        worker_bundle_encryption_secret=SecretStr("bundle"),
        **overrides,
    )


def test_production_with_neither_signing_method_refuses_to_boot(tmp_path):
    with pytest.raises(ConfigurationError, match="WORKER_DISPATCH_SIGNING_PRIVATE_KEY"):
        _production(tmp_path)


def test_production_with_the_legacy_flag_off_and_no_private_key_refuses_to_boot(tmp_path):
    with pytest.raises(ConfigurationError):
        _production(
            tmp_path,
            worker_dispatch_signing_secret=HMAC,
            worker_dispatch_legacy_hmac_enabled=False,
        )


def test_production_today_hmac_only_still_boots_and_emits_hmac_only(tmp_path):
    """The live deployment's configuration at the moment this change ships."""
    settings = _production(tmp_path, worker_dispatch_signing_secret=HMAC)
    assert settings.dispatch_hmac_issuing_secret == HMAC
    assert settings.dispatch_ed25519_signing_key is None


def test_production_transition_emits_both(tmp_path):
    settings = _production(
        tmp_path,
        worker_dispatch_signing_secret=HMAC,
        worker_dispatch_signing_private_key=KEY.private_key_secret(),
    )
    assert settings.dispatch_hmac_issuing_secret == HMAC
    signing_key = settings.dispatch_ed25519_signing_key
    assert signing_key is not None
    assert signing_key.kid == KEY.kid


def test_production_with_the_legacy_flag_off_emits_ed25519_only(tmp_path):
    settings = _production(
        tmp_path,
        worker_dispatch_signing_secret=HMAC,
        worker_dispatch_legacy_hmac_enabled=False,
        worker_dispatch_signing_private_key=KEY.private_key_secret(),
    )
    assert settings.dispatch_hmac_issuing_secret is None
    assert settings.dispatch_ed25519_signing_key is not None


def test_outside_production_an_unset_key_is_generated_once_and_hmac_is_not_emitted(tmp_path):
    settings = _settings(tmp_path)
    first = settings.dispatch_ed25519_signing_key
    assert first is not None
    assert settings.dispatch_ed25519_signing_key is first, "cached, not regenerated per call"
    assert settings.dispatch_hmac_issuing_secret is None


def test_a_malformed_private_key_stops_the_process_at_boot_without_echoing_it(tmp_path):
    bad = "definitely-not-a-key"
    with pytest.raises(ConfigurationError) as error:
        _settings(tmp_path, worker_dispatch_signing_private_key=SecretStr(bad))
    assert bad not in str(error.value)


def test_a_malformed_verify_key_stops_the_worker_at_boot(tmp_path):
    with pytest.raises(ConfigurationError, match="WORKER_DISPATCH_VERIFY_KEY"):
        _settings(tmp_path, worker_dispatch_verify_key="AAAA")


def test_the_verify_key_is_parsed_and_never_generated(tmp_path):
    assert _settings(tmp_path).dispatch_verify_key is None
    parsed = _settings(tmp_path, worker_dispatch_verify_key=KEY.public_key_b64).dispatch_verify_key
    assert parsed is not None
    assert parsed.kid == KEY.kid
