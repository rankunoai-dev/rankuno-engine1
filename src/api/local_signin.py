"""`POST /auth/local-signin`: the local launcher's single-use sign-in link (ADR 0033).

`scripts/run_local.ps1` opens the browser at
`http://127.0.0.1:<port>/#autosignin=<token>`. The fragment never reaches the
server or its access log; the SPA strips it from the address bar and posts the
token in a JSON body to this route, which exchanges it for the same
`LoginResponse` `/auth/login` returns, with the same TTL.

The route exists only when `AUTH_LOCAL_AUTOSIGNIN_TOKEN` is set, and the layers
that keep it out of production are deliberately independent of each other:

* `Settings` refuses the token outside `ENVIRONMENT=development`.
* `create_app()` refuses it whenever Postgres is configured, which is true on
  Railway even if `ENVIRONMENT` were somehow unset there.
* This route answers only a loopback peer on a loopback-bound socket. Behind
  a reverse proxy the peer is the proxy, so this fails closed. Its honest
  limit: a proxy running on the *same* machine also looks like loopback.
* The token is single-use and expires five minutes after startup.

Not a `BaseTool` and no `RiskClass`, for the same reason `/auth/login` has
none: it issues a session for an operator that already exists in this org and
changes nothing else.
"""

from __future__ import annotations

import ipaddress
import secrets
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field

from src.api.auth import LoginResponse
from src.core.auth import Operator, OperatorNotFoundError, hash_password, issue_session_token
from src.core.errors import ConfigurationError
from src.core.local_signin import LocalSigninGate, SigninOutcome
from src.core.logger import get_logger
from src.core.schemas import StrictModel

if TYPE_CHECKING:
    from src.api.server import ApiState
    from src.core.auth import OperatorStore
    from src.core.config import Settings

__all__ = [
    "LOCAL_SIGNIN_PATH",
    "LocalSigninRequest",
    "build_local_signin_router",
    "ensure_local_operator",
]

_logger = get_logger("api.local_signin")

LOCAL_SIGNIN_PATH = "/auth/local-signin"
REJECTED_DETAIL = "sign-in link is invalid or expired"
"""One message for every refusal, so a response says nothing about why."""


class LocalSigninRequest(StrictModel):
    """The token from the sign-in link's fragment, posted in the body.

    Only a length bound, no pattern: a pattern failure's 422 would echo the
    value back with a description of what was wrong with it.
    """

    token: str = Field(max_length=256)


def ensure_local_operator(operator_store: OperatorStore, settings: Settings) -> Operator:
    """Return the dedicated local sign-in operator, creating it if absent.

    A departure from bootstrap's empty-store-only rule (ADR 0033): the local
    operator is created alongside whatever operators already exist, because
    the alternative, signing in as whichever operator happens to exist, would
    hand a test artefact or another org's operator the browser session.

    Created with the hash of 32 random bytes that are then discarded, so it can
    never log in by password; only the sign-in link reaches it.

    Raises:
        ConfigurationError: The operator exists but is inactive or belongs to
            another org. Refusing to start beats silently signing a browser
            into the wrong tenant.
    """
    operator_id = settings.auth_local_autosignin_operator_id
    org_id = settings.auth_local_autosignin_org_id
    try:
        operator = operator_store.get(operator_id)
    except OperatorNotFoundError:
        operator = Operator(
            operator_id=operator_id,
            org_id=org_id,
            display_name=operator_id,
            password_hash=hash_password(secrets.token_bytes(32).hex()),
        )
        operator_store.create(operator)
        _logger.warning(
            "local_signin_operator_created", extra={"operator_id": operator_id, "org": org_id}
        )
        return operator
    if not operator.is_active:
        msg = f"Local sign-in operator '{operator_id}' is inactive; refusing to start."
        raise ConfigurationError(msg)
    if operator.org_id != org_id:
        msg = (
            f"Local sign-in operator '{operator_id}' belongs to org '{operator.org_id}', "
            f"not '{org_id}'; refusing to start."
        )
        raise ConfigurationError(msg)
    return operator


def _is_loopback(host: object) -> bool:
    """Whether `host` is a loopback IP literal. Anything unparseable is not."""
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _reject(reason: str) -> NoReturn:
    """Log the category, never the token, and raise the one shared `401`."""
    _logger.warning("local_signin_rejected", extra={"reason": reason})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=REJECTED_DETAIL)


def build_local_signin_router(
    state: ApiState, gate: LocalSigninGate, *, operator_id: str, org_id: str
) -> APIRouter:
    """Build the sign-in-link route over `state` and an armed `gate`.

    Args:
        state: The app's shared state (operator store, session key and TTL).
        gate: Holds the link's digest and enforces single use.
        operator_id: The operator `ensure_local_operator` vouched for.
        org_id: The org that operator must still belong to at redemption.
    """
    router = APIRouter()

    @router.post(LOCAL_SIGNIN_PATH, response_model=LoginResponse)
    def local_signin(payload: LocalSigninRequest, request: Request) -> LoginResponse:
        """Exchange the launcher's one-time token for a session token.

        Raises:
            HTTPException: `401` with one message for a non-loopback request
                and for a wrong, expired, reused or locked-out token; `429`
                when rate-limited.
        """
        client_host = request.client.host if request.client is not None else None
        server = request.scope.get("server")
        server_host = server[0] if server else None
        if not (_is_loopback(client_host) and _is_loopback(server_host)):
            _reject("not_loopback")

        bucket = state.principal_rate_limiter.get_or_create(
            "local-signin", requests_per_minute=10, burst=10
        )
        if not bucket.try_acquire():
            _logger.warning("local_signin_rate_limited")
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many sign-in attempts; wait a moment and try again",
            )

        outcome = gate.redeem(payload.token)
        if outcome is not SigninOutcome.OK:
            _reject(outcome.value)

        # Re-read, because the operator could have been deactivated or moved
        # since startup. The link is already spent, so this fails closed.
        try:
            operator = state.operator_store.get(operator_id)
        except OperatorNotFoundError:
            _reject("operator_unavailable")
        if not operator.is_active or operator.org_id != org_id:
            _reject("operator_unavailable")

        session = issue_session_token(
            operator, secret=state.session_secret, ttl_s=state.session_ttl_s
        )
        _logger.info(
            "local_signin_succeeded",
            extra={"operator_id": operator.operator_id, "org": operator.org_id},
        )
        return LoginResponse(
            token=session.token, org_id=operator.org_id, expires_at=session.expires_at
        )

    return router
