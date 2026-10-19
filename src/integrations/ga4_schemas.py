"""Typed boundary models for the GA4 connector (ADR 0038).

Every value that crosses from `ga4_client` to a caller is one of these models,
never a loose dict. None carries a refresh token, and the one secret that does
exist here, the short-lived access token, is a `SecretStr` that the client
keeps inside a single call.
"""

from __future__ import annotations

from pydantic import Field, SecretStr

from src.core.ga4_access_store import GA4_PROPERTY_ID_PATTERN
from src.core.schemas import StrictModel

__all__ = [
    "Ga4AccessToken",
    "Ga4HostReport",
    "Ga4PageMetrics",
    "Ga4PropertyChoice",
    "Ga4PropertyList",
]


class Ga4AccessToken(StrictModel):
    """A short-lived access token whose granted scope has already been checked.

    Only `ga4_client` constructs one, and only after the scope gate passes, so
    holding one is evidence that the credential may read GA4.
    """

    access_token: SecretStr = Field(description="Bearer token for one call sequence. Never logged.")


class Ga4PropertyChoice(StrictModel):
    """One GA4 property the credential can see, as the account picker shows it."""

    property_id: str = Field(pattern=GA4_PROPERTY_ID_PATTERN, description="Numeric id.")
    display_name: str = Field(max_length=200, description="Property name, rendered as text.")


class Ga4PropertyList(StrictModel):
    """Every property a credential can see, up to the page cap.

    Attributes:
        properties: The properties, in the order Google lists them.
        truncated: True when more summary pages existed than the cap reads.
    """

    properties: tuple[Ga4PropertyChoice, ...] = ()
    truncated: bool = False


class Ga4PageMetrics(StrictModel):
    """One page path's totals for the report window."""

    path: str = Field(max_length=2048, description="Path only, no host and no query.")
    screen_page_views: int = Field(ge=0)
    sessions: int = Field(ge=0)


class Ga4HostReport(StrictModel):
    """One host-scoped report: every path the property recorded for that host.

    Attributes:
        host: The host the report was filtered to.
        rows: Path totals, at most the requested row limit.
        row_count: Rows the property holds for the window, which may exceed `rows`.
        truncated: True when `row_count` exceeds the rows returned.
    """

    host: str = Field(max_length=253)
    rows: tuple[Ga4PageMetrics, ...] = ()
    row_count: int = Field(default=0, ge=0)
    truncated: bool = False
