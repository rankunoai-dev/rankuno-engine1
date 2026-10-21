"""The deletion password on `PageClassificationInput` (ADR 0042).

The field is write-only by construction: `SecretStr` masks it in `repr` and in
every dump, and the validator keeps out any password a request header cannot
carry. These tests are the only guard on that, so each rule has its own case.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.modules.seo.page_classifier.tool import PageClassificationInput

SECRET = "crawl-password-12"


def _request(**overrides: object) -> PageClassificationInput:
    return PageClassificationInput(base_url="https://a.test", **overrides)


def test_password_is_masked_in_repr_and_every_dump() -> None:
    request = _request(deletion_password=SECRET)
    assert SECRET not in repr(request)
    assert SECRET not in request.model_dump_json()
    assert SECRET not in str(request.model_dump(mode="json"))


def test_unset_password_is_none() -> None:
    assert _request().deletion_password is None


def test_a_password_of_twelve_characters_is_accepted() -> None:
    assert _request(deletion_password="x" * 12).deletion_password is not None


@pytest.mark.parametrize("short", ["", "x", "x" * 11])
def test_a_password_under_twelve_characters_is_refused(short: str) -> None:
    with pytest.raises(ValidationError):
        _request(deletion_password=short)


@pytest.mark.parametrize(
    "bad",
    ["pässwörd-long-1", "tab\tseparated-pw", "new\nline-password"],
)
def test_a_password_outside_printable_ascii_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        _request(deletion_password=bad)
