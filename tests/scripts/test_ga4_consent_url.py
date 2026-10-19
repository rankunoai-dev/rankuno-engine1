"""`scripts/ga4_consent_url.py`: one URL, the GA4 read scope only, and no secret (ADR 0038)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import scripts.ga4_consent_url as consent
from pydantic import SecretStr
from src.core.config import Settings

CLIENT_SECRET = "GOCSPX-SCRIPT-SECRET-CANARY"  # noqa: S105 - fake canary


def test_url_requests_only_the_ga4_read_scope_offline_with_consent() -> None:
    url = consent.build_consent_url("shared-client-id", "https://example.test/cb")
    parsed = urlparse(url)
    assert parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["scope"] == ["https://www.googleapis.com/auth/analytics.readonly"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["shared-client-id"]


def test_main_prints_the_url_and_never_the_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None,
        google_oauth_client_id="shared-client-id",
        google_oauth_client_secret=SecretStr(CLIENT_SECRET),
    )
    monkeypatch.setattr(consent, "get_settings", lambda: settings)
    assert consent.main([]) == 0
    out = capsys.readouterr().out
    assert "accounts.google.com" in out
    assert CLIENT_SECRET not in out


def test_main_refuses_without_a_client_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, google_oauth_client_id=None)
    monkeypatch.setattr(consent, "get_settings", lambda: settings)
    assert consent.main([]) == 1
    assert "GOOGLE_OAUTH_CLIENT_ID" in capsys.readouterr().err
