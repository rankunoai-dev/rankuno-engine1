"""The persistence seam for an organisation's GA4 access (ADR 0038).

GA4 is a second Google credential beside the Search Console accounts, and it is
held per organisation: one encrypted refresh token and at most one mapped
property. This module is the narrow contract the API and the crawl use; the
Postgres implementation is `postgres_ga4_access_store`.

Design stance:

* **Separate from `GscAccountStore` on purpose.** A GA4 token is never read
  through the GSC store, and no GSC lookup can ever return a GA4 token. The
  two stores share a cipher key, but every ciphertext carries its own AAD label.
* **Nothing is inferred from the environment.** There is no `.env.local` GA4
  profile and no default property. An organisation with no row has no GA4
  access, and that is a reportable state, not a fallback (CLAUDE.md §8).
* **Listing never decrypts.** `status` reads the property id and whether a
  credential exists, nothing secret.
* **Every method is scoped by `org_id`.** No implementation can answer one
  organisation with another's row.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import SecretStr

from src.core.schemas import StrictModel

__all__ = [
    "GA4_PROPERTY_ID_PATTERN",
    "Ga4AccessStore",
    "Ga4AccessSummary",
    "is_valid_ga4_property_id",
]

GA4_PROPERTY_ID_PATTERN = r"^[1-9][0-9]{0,19}$"
"""What a GA4 property id may look like: the numeric part of `properties/<id>`.

Anchored and fully matched, so a value with a trailing newline or a path
separator cannot reach a URL. The same pattern is the table's CHECK constraint.
"""

_PROPERTY_ID_RE = re.compile(GA4_PROPERTY_ID_PATTERN)


def is_valid_ga4_property_id(value: str) -> bool:
    """Whether `value` is a well-formed GA4 property id (full match, no echo)."""
    return _PROPERTY_ID_RE.fullmatch(value) is not None


class Ga4AccessSummary(StrictModel):
    """One organisation's GA4 state as a listing sees it: no token, nothing decrypted.

    Attributes:
        has_credential: Whether the organisation has stored a GA4 refresh token.
        property_id: The mapped property's numeric id, or `None` if unmapped.
    """

    has_credential: bool = False
    property_id: str | None = None


class Ga4AccessStore(Protocol):
    """Where an organisation's GA4 credential and property mapping live."""

    def status(self, org_id: str) -> Ga4AccessSummary:
        """Whether a credential is stored and which property is mapped. Never decrypts.

        Raises:
            Ga4AccessStoreUnavailableError: The store cannot answer.
        """
        ...

    def refresh_token(self, org_id: str) -> SecretStr | None:
        """The organisation's GA4 refresh token, or `None` if it has none.

        Raises:
            Ga4AccessStoreUnavailableError: The store cannot answer.
            Ga4CredentialDecryptionError: The stored ciphertext cannot be read.
        """
        ...

    def set_credential(self, org_id: str, refresh_token: SecretStr, *, operator_id: str) -> None:
        """Store or replace the GA4 refresh token. Clears any mapped property.

        A new token may not see the property the old one did, so the operator
        must pick again from the list the new token can see.

        Raises:
            Ga4AccessStoreUnavailableError: The store cannot answer.
        """
        ...

    def set_property(self, org_id: str, property_id: str, *, operator_id: str) -> bool:
        """Map a property. `False` if the organisation has no credential to map it under.

        Raises:
            Ga4AccessStoreUnavailableError: The store cannot answer.
        """
        ...

    def delete(self, org_id: str, *, operator_id: str) -> bool:
        """Remove the credential and the mapping. `False` if there was none.

        Raises:
            Ga4AccessStoreUnavailableError: The store cannot answer.
        """
        ...
