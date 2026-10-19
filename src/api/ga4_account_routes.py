"""Org GA4 access routes: status, credential, property picker, removal (ADR 0038).

Lives in the GSC account form in the UI, but is a separate credential, a separate
store and a separate set of routes. A GSC account and a GA4 credential never
share a token, and no route here reads or writes a GSC account.

Security stance:

* **The org comes from the verified principal.** The `{org_id}` path segment is
  checked against it before anything is read, as the GSC routes do (ADR 0016).
* **A credential is verified before it is stored.** Saving a token runs the
  refresh and the scope gate first. A token without the analytics read scope is
  refused with the fixed reason, and nothing is written.
* **A property is picked from the list the stored credential can see.** The
  request names a property, and the server accepts it only if the live listing
  contains it. There is no default and no environment fallback.
* **No secret leaves.** Responses carry the status, the numeric property id and
  the property display names. Audit lines carry org, operator and action only.
* **Refusals are fixed reasons.** A Google error body or exception text is never
  returned to the browser (C8).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import AfterValidator, Field, SecretStr

from src.api.auth import require_principal
from src.api.gsc_account_routes import _require_own_org
from src.core.errors import (
    ConfigurationError,
    Ga4CredentialDecryptionError,
    Ga4NotAuthorizedError,
    Ga4UnavailableError,
    IntegrationError,
)
from src.core.ga4_access_store import GA4_PROPERTY_ID_PATTERN
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.integrations.ga4_client import Ga4ApiClient
from src.modules.seo.page_classifier.ga4_enrichment import REASON_NOT_AUTHORIZED

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = [
    "Ga4AccessView",
    "Ga4PropertiesView",
    "Ga4PropertyChoiceView",
    "build_ga4_account_router",
]

_logger = get_logger(__name__)

MAX_GA4_REFRESH_TOKEN_CHARS = 2048
_PRINTABLE_RE = re.compile(r"[\x21-\x7e]+")
_NOT_CONFIGURED = "GA4 is not configured on this server"
_UNAVAILABLE = "GA4 is unavailable right now; try again shortly"
_NO_CREDENTIAL = "no GA4 credential is stored for this organisation"
_NOT_VISIBLE = "that property is not visible to the stored GA4 credential"
_NOT_IN_PAGES = "that property was not found in the listed GA4 properties"
_NO_MAPPING_TO_CLEAR = "no GA4 access is stored for this organisation"


def _bounded_token(value: SecretStr) -> SecretStr:
    """A refresh token: printable, no spaces, at most the cap. Never echoed."""
    raw = value.get_secret_value()
    if len(raw) > MAX_GA4_REFRESH_TOKEN_CHARS or _PRINTABLE_RE.fullmatch(raw) is None:
        msg = (
            f"refresh_token must be 1-{MAX_GA4_REFRESH_TOKEN_CHARS} printable "
            "characters with no spaces"
        )
        raise ValueError(msg)
    return value


class Ga4CredentialRequest(StrictModel):
    """Body for storing an organisation's GA4 refresh token. Write-only."""

    refresh_token: Annotated[SecretStr, AfterValidator(_bounded_token)] = Field(
        description="OAuth refresh token granted the GA4 read scope. Write-only."
    )


class Ga4PropertyRequest(StrictModel):
    """Body for mapping one property the stored credential can see."""

    property_id: str = Field(
        pattern=GA4_PROPERTY_ID_PATTERN,
        description="Numeric GA4 property id, as the picker lists it.",
    )


class Ga4AccessView(StrictModel):
    """An organisation's GA4 state. No token, ever.

    Attributes:
        status: `not_configured` (no credential), `unmapped` (credential stored,
            no property chosen, so GA4 is "not requested") or `mapped`.
        property_id: The mapped numeric property id, or `None`.
    """

    status: Literal["not_configured", "unmapped", "mapped"]
    property_id: str | None = None


class Ga4PropertyChoiceView(StrictModel):
    """One property in the picker."""

    property_id: str = Field(pattern=GA4_PROPERTY_ID_PATTERN)
    display_name: str = Field(max_length=200)


class Ga4PropertiesView(StrictModel):
    """The properties a stored credential can see, or the fixed reason it cannot say.

    Attributes:
        status: `ok`, or the reason the list is not available.
        reason: The fixed explanation for any status other than `ok`.
        truncated: True when more properties existed than were read.
        properties: The picker's choices.
    """

    status: Literal["ok", "not_configured", "not_authorized", "unavailable"]
    reason: str = ""
    truncated: bool = False
    properties: list[Ga4PropertyChoiceView] = Field(default_factory=list)


def _view(store_summary_has: bool, property_id: str | None) -> Ga4AccessView:
    """The status for a stored state: no credential, credential unmapped, or mapped."""
    if not store_summary_has:
        return Ga4AccessView(status="not_configured", property_id=None)
    if property_id is None:
        return Ga4AccessView(status="unmapped", property_id=None)
    return Ga4AccessView(status="mapped", property_id=property_id)


def build_ga4_account_router(state: ApiState) -> APIRouter:
    """The GA4 access routes, bound to one app's state."""
    router = APIRouter()

    def _consume_rate_limit(operator_id: str) -> None:
        """Charge the caller's shared per-principal bucket, as the GSC routes do."""
        bucket = state.principal_rate_limiter.get_or_create(f"principal:{operator_id}")
        if not bucket.try_acquire():
            _logger.warning("ga4_access_rate_limited", extra={"operator_id": operator_id})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests from this session; please slow down",
            )

    def _status_for(org_id: str) -> Ga4AccessView:
        store = state.ga4_access_store
        if store is None:
            return Ga4AccessView(status="not_configured", property_id=None)
        summary = store.status(org_id)
        return _view(summary.has_credential, summary.property_id)

    def _listing(org_id: str) -> Ga4PropertiesView:
        """Read the properties the org's stored credential can see, failing closed."""
        store = state.ga4_access_store
        if store is None:
            return Ga4PropertiesView(status="not_configured", reason=_NOT_CONFIGURED)
        if not store.status(org_id).has_credential:
            return Ga4PropertiesView(status="not_configured", reason=_NO_CREDENTIAL)
        try:
            secret = store.refresh_token(org_id)
            if secret is None:
                return Ga4PropertiesView(status="not_configured", reason=_NO_CREDENTIAL)
            client = Ga4ApiClient()
            token = client.refresh_access_token(secret)
            listing = client.list_properties(token)
        except Ga4NotAuthorizedError:
            return Ga4PropertiesView(status="not_authorized", reason=REASON_NOT_AUTHORIZED)
        except Ga4CredentialDecryptionError:
            return Ga4PropertiesView(
                status="unavailable",
                reason="the stored GA4 credential cannot be read; re-add the GA4 access",
            )
        except ConfigurationError:
            return Ga4PropertiesView(status="unavailable", reason=_NOT_CONFIGURED)
        except (Ga4UnavailableError, IntegrationError):
            return Ga4PropertiesView(status="unavailable", reason=_UNAVAILABLE)
        return Ga4PropertiesView(
            status="ok",
            truncated=listing.truncated,
            properties=[
                Ga4PropertyChoiceView(property_id=p.property_id, display_name=p.display_name)
                for p in listing.properties
            ],
        )

    @router.get("/orgs/{org_id}/ga4", response_model=Ga4AccessView)
    def get_org_ga4(org_id: str, authorization: str | None = Header(default=None)) -> Ga4AccessView:
        """An organisation's GA4 state.

        Raises:
            HTTPException: `401` without a valid token, `403` for another org.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        return _status_for(org_id)

    @router.get("/ga4/mapping", response_model=Ga4AccessView)
    def get_my_ga4_mapping(authorization: str | None = Header(default=None)) -> Ga4AccessView:
        """The caller's own organisation's GA4 state, for the crawl form's dropdown.

        Raises:
            HTTPException: `401` without a valid token.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        return _status_for(principal.org_id)

    @router.put("/orgs/{org_id}/ga4/credential", response_model=Ga4AccessView)
    def put_org_ga4_credential(
        org_id: str, req: Ga4CredentialRequest, authorization: str | None = Header(default=None)
    ) -> Ga4AccessView:
        """Verify and store the organisation's GA4 refresh token.

        Verification runs first: the token must refresh and must carry the GA4
        read scope. A token that fails either check is not stored.

        Raises:
            HTTPException: `401`, `403` for another org, `422` when the scope
                check refuses the token, `429`, `503` when GA4 is not configured,
                cannot be reached, or the store is unavailable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _consume_rate_limit(principal.operator_id)
        store = state.ga4_access_store
        if store is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED)
        try:
            Ga4ApiClient().refresh_access_token(req.refresh_token)
        except Ga4NotAuthorizedError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=REASON_NOT_AUTHORIZED
            ) from exc
        except (ConfigurationError, Ga4UnavailableError, IntegrationError) as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from exc
        store.set_credential(org_id, req.refresh_token, operator_id=principal.operator_id)
        _logger.info(
            "org_ga4_access_audit",
            extra={
                "org": org_id,
                "operator_id": principal.operator_id,
                "action": "credential_saved",
            },
        )
        return _status_for(org_id)

    @router.get("/orgs/{org_id}/ga4/properties", response_model=Ga4PropertiesView)
    def list_org_ga4_properties(
        org_id: str, authorization: str | None = Header(default=None)
    ) -> Ga4PropertiesView:
        """Properties the org's stored GA4 credential can see, or the reason it cannot say.

        Raises:
            HTTPException: `401`, `403` for another org, `429`.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _consume_rate_limit(principal.operator_id)
        return _listing(org_id)

    @router.put("/orgs/{org_id}/ga4/property", response_model=Ga4AccessView)
    def put_org_ga4_property(
        org_id: str, req: Ga4PropertyRequest, authorization: str | None = Header(default=None)
    ) -> Ga4AccessView:
        """Map a property the stored credential can see. Refuses any other id.

        Raises:
            HTTPException: `401`, `403` for another org, `422` when the property
                is not in the live listing or no credential is stored, `429`,
                `503` when GA4 cannot be asked.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _consume_rate_limit(principal.operator_id)
        store = state.ga4_access_store
        if store is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED)
        listing = _listing(org_id)
        if listing.status == "not_configured":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=listing.reason)
        if listing.status == "not_authorized":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=listing.reason)
        if listing.status == "unavailable":
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=listing.reason)
        visible = {choice.property_id for choice in listing.properties}
        if req.property_id not in visible:
            detail = _NOT_IN_PAGES if listing.truncated else _NOT_VISIBLE
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
        if not store.set_property(org_id, req.property_id, operator_id=principal.operator_id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=_NO_CREDENTIAL)
        _logger.info(
            "org_ga4_access_audit",
            extra={
                "org": org_id,
                "operator_id": principal.operator_id,
                "action": "property_mapped",
            },
        )
        return _status_for(org_id)

    @router.delete("/orgs/{org_id}/ga4", status_code=status.HTTP_204_NO_CONTENT)
    def delete_org_ga4(org_id: str, authorization: str | None = Header(default=None)) -> Response:
        """Remove the organisation's GA4 credential and mapping.

        Raises:
            HTTPException: `401`, `403` for another org, `404` if none is stored,
                `429`, `503` when the store is unavailable or not configured.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        _require_own_org(org_id, principal.org_id)
        _consume_rate_limit(principal.operator_id)
        store = state.ga4_access_store
        if store is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED)
        if not store.delete(org_id, operator_id=principal.operator_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_NO_MAPPING_TO_CLEAR)
        _logger.info(
            "org_ga4_access_audit",
            extra={"org": org_id, "operator_id": principal.operator_id, "action": "access_removed"},
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
