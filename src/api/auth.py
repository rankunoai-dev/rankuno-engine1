"""HTTP-layer authentication glue for ADR 0016.

Three things live here, deliberately kept out of `server.py` (already well
past this project's 400-line target — see that module's own docstring for
the same reasoning `deliverables_routes.py` gives):

* `require_principal` — turns a request's `Authorization` header into a
  verified `Principal`, or a `401`. Every route that used to read `X-Org-Id`
  calls this instead.
* `org_scoped_or_404` — the one shared ownership check ADR 0016 condition 2
  requires in place of fourteen ad-hoc ones. Generalised from
  `deliverables_routes.py`'s original private `_org_scoped_or_404`: that
  module now imports it from here too, so both callers share one
  implementation instead of two copies drifting apart.
* `build_auth_router` — the login route. A factory over `ApiState`, matching
  `build_deliverables_router`'s own shape, for the same reason: the route
  closes over `state` rather than declaring a `Depends`, because
  `from __future__ import annotations` turns every annotation into a string
  FastAPI resolves against the *module* namespace, where a factory-local
  alias would be invisible.
* `require_worker_principal` — ADR 0015 condition 1's equivalent for a
  desktop worker daemon rather than a human operator: turns a request's
  `Authorization` header into a verified `WorkerPrincipal`, or a `401`.
  Every worker-facing dispatch route (`src/api/worker_routes.py`) calls this
  instead of trusting a `worker_id` the request merely claims (condition 2).

`src/core/auth.py` holds the human-operator identity and token primitives
this module verifies against; `src/core/worker_auth.py` holds the parallel
worker-credential primitives. Nothing here duplicates either.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, HTTPException, status
from pydantic import Field, SecretStr

from src.core.auth import (
    AuthenticationError,
    OperatorNotFoundError,
    Principal,
    hash_password,
    issue_session_token,
    verify_password,
    verify_session_token,
)
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.worker_auth import (
    WorkerAuthenticationError,
    WorkerPrincipal,
    WorkerStoreUnavailableError,
    verify_worker_credential,
)

if TYPE_CHECKING:
    from src.api.server import ApiState
    from src.core.state_store import JobRecord
    from src.core.worker_auth import Worker, WorkerStore
    from src.core.worker_dispatch_schemas import WorkerJob
    from src.modules.seo.deliverables.rulebook_store import RulebookRecord

__all__ = [
    "LoginRequest",
    "LoginResponse",
    "build_auth_router",
    "org_scoped_or_404",
    "require_principal",
    "require_worker_principal",
]

_logger = get_logger("api.auth")

# A precomputed, valid-shaped hash with no real operator behind it. Verifying
# a real password against this on every unknown-operator login keeps the
# rejection path's cost close to the real one, so a timing measurement is a
# weak way to learn whether an operator id exists.
_DUMMY_PASSWORD_HASH = hash_password("no-operator-has-this-password")


def require_principal(authorization: str | None, *, session_secret: SecretStr) -> Principal:
    """Verify this request's bearer session token and return its principal.

    Args:
        authorization: The raw `Authorization` header value, or `None`.
        session_secret: The key `state.session_secret` holds for this app.

    Returns:
        The verified `Principal` — `org_id` here is ground truth for the
        rest of the request (ADR 0016 condition 4).

    Raises:
        HTTPException: `401` if the header is missing, is not a `Bearer`
            token, or the token fails verification for any reason.
    """
    if not authorization:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_session_token(token, secret=session_secret)
    except AuthenticationError as exc:
        _logger.warning("session_token_rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_worker_principal(
    authorization: str | None, *, worker_store: WorkerStore
) -> WorkerPrincipal:
    """Verify this request's worker credential and return its principal.

    ADR 0015 condition 1: every worker-facing dispatch route goes through
    this — never a bare header a request merely asserts. Condition 2's
    distinct-credential-type requirement is why this is a separate function
    from `require_principal` rather than a shared one: a worker credential
    is a static long-lived secret (`<worker_id>:<secret>`), never a signed,
    expiring session token — the two are not interchangeable, and a route
    that accidentally accepted either would blur ADR 0016's two-credential
    design back together.

    Args:
        authorization: The raw `Authorization` header value, or `None`.
        worker_store: Where registered workers live.

    Returns:
        The verified `WorkerPrincipal` — `worker_id`/`org_id` here are
        ground truth for the rest of the request, never a value the
        request body or a path parameter merely claims.

    Raises:
        HTTPException: `401` if the header is missing, malformed, or the
            credential fails verification; `503` if the worker store could
            not be read at all. The two must not be collapsed: a daemon
            told `401` is supposed to stop, and a Postgres blip answering
            `401` would stop the whole fleet until a human restarted it.
    """
    if not authorization:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <worker_id>:<secret>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    worker_id, separator, secret = token.partition(":")
    if not separator or not worker_id or not secret:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <worker_id>:<secret>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_worker_credential(worker_id, secret, store=worker_store)
    except WorkerStoreUnavailableError as exc:
        _logger.error(  # noqa: TRY400 - the cause is infrastructure, not this frame
            "worker_store_unavailable_during_auth", extra={"error": str(exc)}
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"worker store unavailable: {exc}",
        ) from exc
    except WorkerAuthenticationError as exc:
        _logger.warning("worker_credential_rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid worker credential",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def org_scoped_or_404(
    *,
    record: JobRecord | RulebookRecord | Worker | WorkerJob,
    record_id: str,
    org_id: str,
    kind: str,
) -> None:
    """Raise the shared `403` for a record that exists but belongs to another org.

    `record_id`/`org_id`/`kind` name what to log, not what to check — the
    check is always the same equality. One function, used by every
    job-family route in `server.py` (ADR 0016 condition 2) and by every
    deliverable route in `deliverables_routes.py`, so the inconsistency
    condition 2 retrofits cannot recur route by route.
    """
    if record.org_id != org_id:
        _logger.warning(
            f"{kind}_access_denied_org_mismatch",
            extra={"id": record_id, "requesting_org": org_id, "owner_org": record.org_id},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="access denied")


class LoginRequest(StrictModel):
    """Operator credentials, posted once to obtain a session token."""

    operator_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]{1,64}$")
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(StrictModel):
    """A session token and the org it authenticates for."""

    token: str
    token_type: str = "bearer"  # noqa: S105 - an auth *scheme* name, not a credential
    org_id: str
    expires_at: datetime


def build_auth_router(state: ApiState) -> APIRouter:
    """Build the `/auth/login` route over `state`.

    Not a `BaseTool` (ADR 0003 governs crawl jobs, not a login call), and
    carries no `RiskClass`: it mutates nothing an operator did not already
    own, the same reason `/health` needs none.
    """
    router = APIRouter()

    @router.post("/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        """Exchange an operator id and password for a session token.

        Raises:
            HTTPException: `401` if the operator id is unknown, inactive, or
                the password does not match. The same message and status for
                all three, so a response cannot be used to enumerate
                operators.
        """
        bucket = state.principal_rate_limiter.get_or_create(
            f"login:{payload.operator_id}", requests_per_minute=10, burst=10
        )
        if not bucket.try_acquire():
            _logger.warning("login_rate_limited", extra={"operator_id": payload.operator_id})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many login attempts; wait a moment and try again",
            )

        try:
            operator = state.operator_store.get(payload.operator_id)
        except OperatorNotFoundError:
            verify_password(payload.password, _DUMMY_PASSWORD_HASH)
            _reject_login(payload.operator_id)

        if not operator.is_active or not verify_password(payload.password, operator.password_hash):
            _reject_login(payload.operator_id)

        session = issue_session_token(
            operator, secret=state.session_secret, ttl_s=state.session_ttl_s
        )
        _logger.info(
            "operator_logged_in",
            extra={"operator_id": operator.operator_id, "org": operator.org_id},
        )
        return LoginResponse(
            token=session.token, org_id=operator.org_id, expires_at=session.expires_at
        )

    return router


def _reject_login(operator_id: str) -> NoReturn:
    """Log and raise the one `401` every login failure shares."""
    _logger.warning("login_rejected", extra={"operator_id": operator_id})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid operator id or password")
