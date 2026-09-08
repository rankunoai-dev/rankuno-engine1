"""Tests for the structured audit logger.

The important invariant: a caller's `extra=` fields must reach the `LogRecord`
and therefore the JSON audit trail. On Python < 3.13 the stock `LoggerAdapter`
replaces them with its own dict, which silently empties the audit payload.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from src.core.logger import JsonFormatter, get_logger, trace_context


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _adapter_with(extra: dict[str, object]) -> logging.LoggerAdapter[logging.Logger]:
    """Build an adapter of whatever class `get_logger` returns, with its own `extra`."""
    return type(get_logger("test_logger"))(logging.getLogger("rankuno.test_logger"), extra)


@pytest.fixture
def capture() -> Iterator[_Capture]:
    handler = _Capture()
    target = logging.getLogger("rankuno.test_logger")
    target.addHandler(handler)
    target.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        target.removeHandler(handler)


def test_caller_extra_reaches_record(capture: _Capture) -> None:
    get_logger("test_logger").info("m", extra={"job_id": "j1"})

    assert capture.records[-1].job_id == "j1"  # type: ignore[attr-defined]


def test_caller_extra_reaches_json_output(capture: _Capture) -> None:
    get_logger("test_logger").info("m", extra={"job_id": "j1", "rows": 5})

    payload = json.loads(JsonFormatter().format(capture.records[-1]))

    assert payload["job_id"] == "j1"
    assert payload["rows"] == 5
    assert payload["message"] == "m"


def test_caller_keys_win_over_adapter_keys(capture: _Capture) -> None:
    adapter = _adapter_with({"k": "adapter", "only": 1})

    adapter.info("m", extra={"k": "caller"})

    record = capture.records[-1]
    assert record.k == "caller"  # type: ignore[attr-defined]
    assert record.only == 1  # type: ignore[attr-defined]


def test_adapter_extra_survives_call_without_extra(capture: _Capture) -> None:
    adapter = _adapter_with({"k": "adapter"})

    adapter.info("m")

    assert capture.records[-1].k == "adapter"  # type: ignore[attr-defined]


def test_trace_id_falls_back_to_context(capture: _Capture) -> None:
    with trace_context("ctx-trace"):
        get_logger("test_logger").info("m", extra={"job_id": "j1"})
        payload = json.loads(JsonFormatter().format(capture.records[-1]))

    assert payload["trace_id"] == "ctx-trace"
    assert payload["job_id"] == "j1"


def test_explicit_trace_id_extra_wins_over_context(capture: _Capture) -> None:
    with trace_context("ctx-trace"):
        get_logger("test_logger").info("m", extra={"trace_id": "explicit"})
        payload = json.loads(JsonFormatter().format(capture.records[-1]))

    assert payload["trace_id"] == "explicit"
