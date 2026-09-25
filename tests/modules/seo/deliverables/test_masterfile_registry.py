"""Tests for masterfile_registry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.modules.seo.deliverables.masterfile_registry import (
    AVAILABLE_SERVICES,
    get_masterfile_service,
)

__all__ = ["test_available_services", "test_get_response_codes_service", "test_get_invalid_service"]


def test_available_services() -> None:
    """Available services should include at least response_codes and page_titles."""
    assert "response_codes" in AVAILABLE_SERVICES
    assert "page_titles" in AVAILABLE_SERVICES
    assert len(AVAILABLE_SERVICES) >= 2


def test_get_response_codes_service() -> None:
    """get_masterfile_service should instantiate response_codes service."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = get_masterfile_service("response_codes", "test-job", Path(tmpdir))
        assert service is not None
        assert service.metadata.slug == "response_codes"


def test_get_page_titles_service() -> None:
    """get_masterfile_service should instantiate page_titles service."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = get_masterfile_service("page_titles", "test-job", Path(tmpdir))
        assert service is not None
        assert service.metadata.slug == "page_titles"


def test_get_invalid_service() -> None:
    """get_masterfile_service should raise ValueError for unknown slug."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="Unknown masterfile service"):
            get_masterfile_service("nonexistent_service", "test-job", Path(tmpdir))
