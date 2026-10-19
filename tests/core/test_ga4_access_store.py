"""The GA4 property id rule and the store summary shape (ADR 0038).

The pattern is the single definition the API, the table CHECK, the crawl input
and the connector all share, so these cases pin it for every one of them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.ga4_access_store import (
    GA4_PROPERTY_ID_PATTERN,
    Ga4AccessSummary,
    is_valid_ga4_property_id,
)


@pytest.mark.parametrize("value", ["1", "123456", "9" * 20])
def test_accepts_numeric_ids_up_to_twenty_digits(value: str) -> None:
    assert is_valid_ga4_property_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0",
        "01234",
        "9" * 21,
        "123\n",  # a trailing newline must not pass a `$` anchor
        "properties/123",
        "123/../456",
        "12 3",
        "-5",
        "1.5",
        "٣",  # a non-ASCII digit
    ],
)
def test_refuses_anything_else(value: str) -> None:
    assert not is_valid_ga4_property_id(value)


def test_pattern_is_the_documented_one() -> None:
    assert GA4_PROPERTY_ID_PATTERN == r"^[1-9][0-9]{0,19}$"


def test_summary_defaults_to_no_credential_and_no_mapping() -> None:
    summary = Ga4AccessSummary()
    assert summary.has_credential is False
    assert summary.property_id is None


def test_summary_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Ga4AccessSummary(has_credential=True, refresh_token="x")  # type: ignore[call-arg]
