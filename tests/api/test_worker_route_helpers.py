"""Unit tests for the checks every worker route performs before doing work.

`read_capped_body` gets its own file rather than being exercised only
through the upload route, because the property that matters is *when* it
refuses, not merely *that* it does: a cap applied after `await
request.body()` has already materialised 400 MB in the process is not a cap,
and an end-to-end test that only asserts a 413 cannot tell the two apart.
Driving the reader with a fake ASGI receive channel makes "how many bytes
were pulled off the wire before the refusal" directly observable.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request
from src.api.worker_route_helpers import read_capped_body

_HTTP_CONTENT_TOO_LARGE = 413


def _request(
    chunks: list[bytes], *, content_length: int | None = None
) -> tuple[Request, list[int]]:
    """A `Request` whose body arrives in `chunks`, recording what was read."""
    read_sizes: list[int] = []
    headers: list[tuple[bytes, bytes]] = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    remaining = list(chunks)

    async def receive() -> dict[str, object]:
        if not remaining:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = remaining.pop(0)
        read_sizes.append(len(chunk))
        return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}

    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
    return Request(scope, receive), read_sizes  # type: ignore[arg-type]


def _run(coro: object) -> bytes:
    """Drive one coroutine to completion.

    `pytest-asyncio` is not a dependency of this project and adding one for
    five tests would be a poor trade; `asyncio.run` is the whole of what
    these need.
    """
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]


def test_a_body_under_the_cap_is_returned_whole():
    request, _ = _request([b"abc", b"def"])
    assert _run(read_capped_body(request, max_bytes=100)) == b"abcdef"


def test_a_declared_content_length_over_the_cap_is_refused_before_any_read():
    request, read_sizes = _request([b"x" * 50], content_length=1000)
    with pytest.raises(HTTPException) as caught:
        _run(read_capped_body(request, max_bytes=10))
    assert caught.value.status_code == _HTTP_CONTENT_TOO_LARGE
    assert read_sizes == []  # not one byte of the body was pulled off the wire


def test_a_chunked_body_is_abandoned_the_moment_it_crosses_the_cap():
    """No Content-Length to check, so only the running total can stop this."""
    request, read_sizes = _request([b"x" * 8, b"x" * 8, b"x" * 8, b"x" * 8])
    with pytest.raises(HTTPException) as caught:
        _run(read_capped_body(request, max_bytes=10))
    assert caught.value.status_code == _HTTP_CONTENT_TOO_LARGE
    assert sum(read_sizes) == 16  # stopped at the second chunk, not the fourth


def test_the_refusal_names_the_limit():
    request, _ = _request([b"x"], content_length=200 * 1024 * 1024)
    with pytest.raises(HTTPException) as caught:
        _run(read_capped_body(request, max_bytes=100 * 1024 * 1024))
    assert "100 MB limit" in caught.value.detail


def test_a_lying_content_length_under_the_cap_does_not_defeat_the_stream_check():
    """A claim is not a fact: the header says 1 byte, the body is 40."""
    request, _ = _request([b"x" * 40], content_length=1)
    with pytest.raises(HTTPException) as caught:
        _run(read_capped_body(request, max_bytes=10))
    assert caught.value.status_code == _HTTP_CONTENT_TOO_LARGE
