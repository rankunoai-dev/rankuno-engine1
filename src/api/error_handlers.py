"""App-wide exception handlers that keep secrets out of error bodies (ADR 0036).

Two handlers, installed once by `create_app`:

* **`RequestValidationError` → 422 without `input` or `ctx`.** FastAPI's
  default 422 body echoes each failing item's `input`. For a request body
  missing one field, that `input` is the *whole body*, so a refresh token
  sent without an `account_name` came straight back in the response. `ctx`
  can carry the offending value or a wrapped exception too. `type`, `loc`,
  `msg` and `url` remain, which is everything a client needs to show which
  field failed.
* **`GscAccountStoreUnavailableError` → 503.** One mapping, so the account
  routes, the picker list and job intake all fail closed the same way when
  the encrypted credential store cannot answer.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.errors import GscAccountStoreUnavailableError
from src.core.logger import get_logger

__all__ = ["install_error_handlers", "redact_validation_errors"]

_logger = get_logger(__name__)

_REDACTED_KEYS = frozenset({"input", "ctx"})


def redact_validation_errors(errors: object) -> list[dict[str, object]]:
    """Drop `input` and `ctx` from every validation error item."""
    if not isinstance(errors, list | tuple):
        return []
    return [
        {key: value for key, value in item.items() if key not in _REDACTED_KEYS}
        for item in errors
        if isinstance(item, dict)
    ]


def install_error_handlers(app: FastAPI) -> None:
    """Register both handlers on `app`."""

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(redact_validation_errors(exc.errors()))},
        )

    @app.exception_handler(GscAccountStoreUnavailableError)
    async def _store_unavailable(
        request: Request, exc: GscAccountStoreUnavailableError
    ) -> JSONResponse:
        _logger.warning("gsc_account_store_unavailable", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )
