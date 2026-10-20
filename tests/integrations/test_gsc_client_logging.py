"""What a paged Search Console fetch writes to the log.

The log is read by people who should not see the searcher's text, and an
exception message can quote the request. So a failed page is logged by exception
class name and row count only. These tests patch `call` itself, so the assertion
covers this module's own log lines and not the base client's traceback log.
"""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.integrations.gsc_client import GscApiClient

SECRET_PHRASE = "private search phrase"


@pytest.fixture
def settings() -> Settings:
    """Settings carrying the fields the client reads, and nothing real."""
    settings = Mock(spec=Settings)
    settings.google_search_console_client_email = "test@example.iam.gserviceaccount.com"
    settings.google_search_console_private_key = SecretStr(
        "-----BEGIN PRIVATE KEY-----\nMIIEvQ\n-----END PRIVATE KEY-----\n"
    )
    settings.default_timeout_s = 30.0
    settings.default_requests_per_minute = 60
    settings.default_max_retries = 3
    return settings


def _client(settings: Settings) -> GscApiClient:
    token_manager = Mock()
    token_manager.get_or_refresh_token.return_value = "ya29.test-token"
    token_manager.get_account_email.return_value = "test@example.iam.gserviceaccount.com"
    with patch("src.integrations.gsc_client.GscTokenManager", return_value=token_manager):
        return GscApiClient(settings=settings)


def test_a_failed_page_logs_the_class_name_and_never_the_message(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    client = _client(settings)

    with (
        patch.object(client, "call", side_effect=RuntimeError(SECRET_PHRASE)),
        caplog.at_level(logging.WARNING),
    ):
        result = client.fetch_top_queries("https://example.com", "2026-01-01", "2026-01-31")

    assert result.stop_reason == "fetch_failed"
    assert SECRET_PHRASE not in caplog.text
    failed = [r for r in caplog.records if r.getMessage() == "gsc_page_fetch_failed"]
    assert len(failed) == 1
    assert failed[0].error == "RuntimeError"  # type: ignore[attr-defined]
    assert failed[0].rows_kept == 0  # type: ignore[attr-defined]


def test_the_success_log_carries_counts_and_the_stop_reason_only(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    client = _client(settings)
    row = {"keys": ["https://example.com/a", SECRET_PHRASE], "clicks": 1, "impressions": 2}

    with (
        patch.object(client, "call", return_value=[row]),
        caplog.at_level(logging.INFO),
    ):
        result = client.fetch_top_queries("https://example.com", "2026-01-01", "2026-01-31")

    assert result.stop_reason == "exhausted"
    assert SECRET_PHRASE not in caplog.text
    done = [r for r in caplog.records if r.getMessage() == "gsc_top_queries_fetched"]
    assert len(done) == 1
    assert done[0].rows == 1  # type: ignore[attr-defined]
    assert done[0].stop_reason == "exhausted"  # type: ignore[attr-defined]
