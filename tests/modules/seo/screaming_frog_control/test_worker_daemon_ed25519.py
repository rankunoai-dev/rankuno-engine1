"""ADR 0028 on the worker: a verify key means Ed25519 only, end of story.

`test_worker_dispatch_ed25519.py` proves the primitive. This file proves the
daemon actually wires it that way — that `make_approval_callback` (gate (b)'s
consuming check) and `_handle_assignment` (the fast admission check) both
refuse an HMAC-only claim once a verify key is configured, even though the
same worker still has the legacy secret in its settings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from src.core.config import Environment, Settings
from src.core.schemas import RiskClass, ToolMetadata
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_consumed_ledger import ConsumedJobLedger
from src.core.worker_dispatch_keys import DispatchSigningKey
from src.core.worker_dispatch_schemas import WorkerJobKind
from src.core.worker_dispatch_signing import issue_dispatch_assignment, verify_dispatch_assignment
from src.modules.seo.screaming_frog_control import worker_daemon
from src.modules.seo.screaming_frog_control.template_registry import TemplateRegistry

SECRET = SecretStr("legacy-shared-hmac-key")
KEY = DispatchSigningKey.generate()
METADATA = ToolMetadata(name="seo.screaming_frog_control", summary="t", risk_class=RiskClass.WRITE)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.DEVELOPMENT,
        "audit_log_path": tmp_path / "audit.jsonl",
        "worker_id": "wkr-alice-desktop",
        "worker_org_id": "acme",
        "worker_dispatch_signing_secret": SECRET,
        "worker_dispatch_verify_key": KEY.public_key_b64,
        "worker_consumed_jobs_path": tmp_path / "consumed.json",
        "screaming_frog_template_dir": tmp_path / "templates",
    }
    base.update(overrides)
    return Settings(**base)


def _token(**signing: object) -> str:
    return issue_dispatch_assignment(
        job_id="job-1",
        worker_id="wkr-alice-desktop",
        org_id="acme",
        kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
        seed_url="https://example.com/",
        template_name=None,
        correlation_id="corr-1",
        ttl_s=300.0,
        **signing,  # type: ignore[arg-type]
    ).token


def _callback(token: str, settings: Settings) -> bool:
    claims = verify_dispatch_assignment(
        token, secret=SECRET, worker_id="wkr-alice-desktop", org_id="acme"
    )
    callback = worker_daemon.make_approval_callback(
        token,
        claims,
        worker_id="wkr-alice-desktop",
        org_id="acme",
        settings=settings,
        ledger=ConsumedJobLedger(settings.worker_consumed_jobs_path),
    )
    return callback(METADATA, "context")


def test_a_verify_key_worker_approves_a_dual_signed_claim(tmp_path):
    assert _callback(_token(secret=SECRET, signing_key=KEY), _settings(tmp_path)) is True


def test_a_verify_key_worker_refuses_an_hmac_only_claim_despite_holding_the_secret(tmp_path):
    """The no-fallback property, through the daemon's real gate (b) callback."""
    assert _callback(_token(secret=SECRET), _settings(tmp_path)) is False


def test_a_legacy_worker_still_approves_a_dual_signed_claim(tmp_path):
    settings = _settings(tmp_path, worker_dispatch_verify_key=None)
    assert _callback(_token(secret=SECRET, signing_key=KEY), settings) is True


def test_the_admission_check_drops_an_hmac_only_claim_without_running_anything(
    tmp_path, monkeypatch
):
    ran: list[object] = []
    monkeypatch.setattr(worker_daemon, "_run_screaming_frog_job", lambda *a, **k: ran.append(a))
    settings = _settings(tmp_path)
    common = {
        "worker_id": "wkr-alice-desktop",
        "org_id": "acme",
        "settings": settings,
        "client": object(),
        "ledger": ConsumedJobLedger(settings.worker_consumed_jobs_path),
        "templates": TemplateRegistry(settings.screaming_frog_template_dir),
        "url_policy": UrlSafetyPolicy(),
    }
    worker_daemon._handle_assignment(_token(secret=SECRET), **common)  # type: ignore[arg-type]
    assert ran == []
    worker_daemon._handle_assignment(_token(signing_key=KEY), **common)  # type: ignore[arg-type]
    assert len(ran) == 1


class _Recorder:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, event: str, **_kwargs: object) -> None:
        self.warnings.append(event)

    def info(self, *_args: object, **_kwargs: object) -> None:
        return None


class _IdleClient:
    def heartbeat(self, _report: object) -> None:
        return None

    def poll(self) -> None:
        return None


def _start(settings: Settings, monkeypatch) -> list[str]:
    recorder = _Recorder()
    monkeypatch.setattr(worker_daemon, "_logger", recorder)
    worker_daemon.run_worker_daemon(
        settings=settings,
        max_iterations=1,
        sleep=lambda _s: None,
        cloud_client=_IdleClient(),  # type: ignore[arg-type]
    )
    return recorder.warnings


def test_a_legacy_worker_logs_a_deprecation_warning_at_every_start(tmp_path, monkeypatch):
    settings = _settings(tmp_path, worker_dispatch_verify_key=None)
    assert "worker_dispatch_legacy_hmac_deprecated" in _start(settings, monkeypatch)


def test_an_upgraded_worker_logs_no_deprecation_warning(tmp_path, monkeypatch):
    assert "worker_dispatch_legacy_hmac_deprecated" not in _start(_settings(tmp_path), monkeypatch)
