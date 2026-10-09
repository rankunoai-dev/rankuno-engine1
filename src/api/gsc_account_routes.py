"""Org GSC account routes: list, add or replace, delete (ADR 0016, ADR 0036).

Moved out of `server.py` when the accounts gained their own store. The routes
validate, authorise, rate-limit and audit; persistence is entirely
`GscAccountStore`, which is disk locally and encrypted Postgres in the cloud.

Security stance:

* **The org comes from the verified principal.** The `{org_id}` path segment
  is checked against it and refused with an identical `403` whether or not
  the target org exists, before anything is looked up (ADR 0016 condition 1).
* **No secret ever leaves.** Responses carry the name, the non-secret client
  id and a boolean. Audit events carry org, account and operator id only.
  Validation messages never quote the value, and the app-wide 422 handler
  strips `input` and `ctx` (`src/api/error_handlers.py`).
* **Bounded input.** Names use full-match semantics, so a trailing newline is refused,
  and every credential field has a length cap and a character set.
* **Store outages are `503`, never a fall-back.** `GscAccountStoreUnavailableError`
  is mapped app-wide, so these routes, the picker list and job intake agree.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import AfterValidator, Field, SecretStr

from src.api.auth import require_principal
from src.core.logger import get_logger
from src.core.schemas import GscAccountCredential, StrictModel

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = [
    "OrgGscAccountRequest",
    "OrgGscAccountView",
    "OrgGscAccountsView",
    "build_gsc_account_router",
]

_logger = get_logger(__name__)

_ACCOUNT_NAME_RE = re.compile(r"[a-z0-9_-]{1,64}")
_CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,256}")
_PRINTABLE_RE = re.compile(r"[\x21-\x7e]+")
MAX_REFRESH_TOKEN_CHARS = 2048
MAX_CLIENT_SECRET_CHARS = 512
_NAME_RULE = "account_name must match ^[a-z0-9_-]{1,64}$"


def _valid_account_name(value: str) -> str:
    """Full-match the name. `re.match` with `$` accepted a trailing newline."""
    if _ACCOUNT_NAME_RE.fullmatch(value) is None:
        raise ValueError(_NAME_RULE)
    return value


def _valid_client_id(value: str | None) -> str | None:
    """Letters, digits, `.`, `_` and `-`, at most 256: the shape of a Google client id."""
    if value is not None and _CLIENT_ID_RE.fullmatch(value) is None:
        msg = "client_id must be 1-256 characters of letters, digits, '.', '_' or '-'"
        raise ValueError(msg)
    return value


def _bounded_secret(field: str, limit: int) -> AfterValidator:
    """A validator capping a secret's length and characters without quoting it."""

    def check(value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if len(raw) > limit or _PRINTABLE_RE.fullmatch(raw) is None:
            msg = f"{field} must be 1-{limit} printable characters with no spaces"
            raise ValueError(msg)
        return value

    return AfterValidator(check)


class OrgGscAccountRequest(StrictModel):
    """Request body for adding or replacing an org-level GSC account."""

    account_name: Annotated[str, AfterValidator(_valid_account_name)] = Field(
        max_length=64,
        description="Profile name. Full match of ^[a-z0-9_-]{1,64}$.",
    )
    refresh_token: Annotated[
        SecretStr, _bounded_secret("refresh_token", MAX_REFRESH_TOKEN_CHARS)
    ] = Field(description="OAuth 2.0 refresh token. Write-only: never returned or logged.")
    client_id: Annotated[str | None, AfterValidator(_valid_client_id)] = Field(
        default=None,
        description="Optional OAuth client id override; None inherits the shared client.",
    )
    client_secret: Annotated[
        SecretStr | None, _bounded_secret("client_secret", MAX_CLIENT_SECRET_CHARS)
    ] = Field(
        default=None,
        description="Optional OAuth client secret override. Write-only.",
    )


class OrgGscAccountView(StrictModel):
    """One org-level GSC account as the API returns it. No secret, ever."""

    account_name: str = Field(description="Profile name.")
    client_id: str | None = Field(
        default=None, description="OAuth client id, or None if it inherits the shared one."
    )
    has_secret_override: bool = Field(
        default=False, description="Whether the account stores its own client secret."
    )


class OrgGscAccountsView(StrictModel):
    """Every org-level GSC account in the caller's org."""

    accounts: list[OrgGscAccountView] = Field(description="Accounts, sorted by name.")


def _require_own_org(path_org_id: str, principal_org_id: str) -> None:
    """Refuse a path `org_id` that disagrees with the verified principal's own org.

    ADR 0016 condition 1: the org these routes act on is the principal's. The
    path segment is a consistency check, never ground truth, and the refusal
    happens before any lookup, so it is identical whether or not the target
    org exists.
    """
    if path_org_id != principal_org_id:
        _logger.warning(
            "gsc_account_access_denied_org_mismatch",
            extra={"path_org": path_org_id, "principal_org": principal_org_id},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="access denied")


def _require_valid_name(account_name: str) -> None:
    """Validate a path account name as strictly as a body one, without echoing it."""
    if _ACCOUNT_NAME_RE.fullmatch(account_name) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_NAME_RULE)


def _org_not_found(org_id: str) -> HTTPException:
    """The disk store's unknown-org answer, unchanged from before ADR 0036."""
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Organization '{org_id}' not found")


def build_gsc_account_router(state: ApiState) -> APIRouter:
    """The three `/orgs/{org_id}/gsc-accounts` routes, bound to one app's state."""
    router = APIRouter()

    def _consume_rate_limit(operator_id: str) -> None:
        """Charge the caller's shared per-principal bucket, as job creation does."""
        bucket = state.principal_rate_limiter.get_or_create(f"principal:{operator_id}")
        if not bucket.try_acquire():
            _logger.warning("gsc_account_rate_limited", extra={"operator_id": operator_id})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests from this session; please slow down",
            )

    @router.get("/orgs/{org_id}/gsc-accounts", response_model=OrgGscAccountsView)
    def list_org_gsc_accounts(
        org_id: str, authorization: str | None = Header(default=None)
    ) -> OrgGscAccountsView:
        """List the caller's org's GSC accounts. Names and metadata only.

        Raises:
            HTTPException: `401` without a valid token, `403` for another org,
                `404` if a disk-backed org does not exist, `503` if the
                account store is unavailable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        try:
            summaries = state.gsc_account_store.list_accounts(org_id)
        except KeyError as exc:
            raise _org_not_found(org_id) from exc
        return OrgGscAccountsView(
            accounts=[OrgGscAccountView(**summary.model_dump()) for summary in summaries]
        )

    @router.post("/orgs/{org_id}/gsc-accounts", status_code=status.HTTP_201_CREATED)
    def create_org_gsc_account(
        org_id: str, req: OrgGscAccountRequest, authorization: str | None = Header(default=None)
    ) -> OrgGscAccountView:
        """Add or replace a GSC account in the caller's org.

        Raises:
            HTTPException: `401`, `403` for another org, `404` if a disk-backed
                org does not exist, `422` for an invalid body, `429` when the
                caller's request rate is exhausted, `503` if the store is
                unavailable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _consume_rate_limit(principal.operator_id)
        credential = GscAccountCredential(
            refresh_token=req.refresh_token,
            client_id=req.client_id,
            client_secret=req.client_secret,
        )
        try:
            outcome = state.gsc_account_store.upsert(
                org_id, req.account_name, credential, operator_id=principal.operator_id
            )
        except KeyError as exc:
            raise _org_not_found(org_id) from exc
        _logger.info(
            f"org_gsc_account_{outcome}",
            extra={
                "org": org_id,
                "account": req.account_name,
                "operator_id": principal.operator_id,
            },
        )
        return OrgGscAccountView(
            account_name=req.account_name,
            client_id=req.client_id,
            has_secret_override=req.client_secret is not None,
        )

    @router.delete(
        "/orgs/{org_id}/gsc-accounts/{account_name}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_org_gsc_account(
        org_id: str, account_name: str, authorization: str | None = Header(default=None)
    ) -> None:
        """Delete a GSC account. Crawls not yet enriched lose it too (lazy resolution).

        Raises:
            HTTPException: `401`, `403` for another org, `404` if the org (disk)
                or the account does not exist, `422` for an invalid name, `429`
                when rate-limited, `503` if the store is unavailable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _require_valid_name(account_name)
        _consume_rate_limit(principal.operator_id)
        try:
            deleted = state.gsc_account_store.delete(org_id, account_name)
        except KeyError as exc:
            raise _org_not_found(org_id) from exc
        if not deleted:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Account '{account_name}' not found in organization '{org_id}'",
            )
        _logger.info(
            "org_gsc_account_deleted",
            extra={"org": org_id, "account": account_name, "operator_id": principal.operator_id},
        )

    return router
