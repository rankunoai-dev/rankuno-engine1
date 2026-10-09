"""The persistence seam for org GSC accounts, and its disk implementation (ADR 0037).

Org GSC accounts used to be one field of `OrgConfig`, so they lived wherever
the org config did: the container disk, which Railway wipes on every redeploy.
This seam lets the accounts move to Postgres on their own while org budget,
active flag and facets stay exactly where they are. Swapping the whole
`OrgConfigStore` would have moved admission checks too.

Design stance:

* **Narrow on purpose.** Five operations, each scoped by `org_id`, so no
  implementation can answer one org with another org's row.
* **Listing never touches a secret.** `list_accounts` and `account_names`
  return names and the non-secret client id only. Only `get_credential`, used
  at crawl time, produces a credential, and only for one account.
* **`None` from `get_credential` means "genuinely not stored".** Anything else
  (store unreachable, ciphertext unreadable) is an exception, because the
  caller falls through to `.env.local` on `None` and must not do so on an
  outage.
* **The disk implementation keeps today's local behaviour exactly**, fail-soft
  reads included. The fail-closed rule applies to the Postgres store, where an
  outage is the realistic failure (`postgres_gsc_account_store`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field

from src.core.schemas import GscAccountCredential, StrictModel

if TYPE_CHECKING:
    from src.core.state_store import OrgConfigStore

__all__ = [
    "DiskGscAccountStore",
    "GscAccountStore",
    "GscAccountSummary",
    "UpsertOutcome",
]

UpsertOutcome = Literal["created", "replaced"]
"""Whether an upsert added a new account or overwrote an existing one."""


class GscAccountSummary(StrictModel):
    """One stored account as a listing sees it: no secret, and nothing decrypted."""

    account_name: str = Field(description="Profile name, unique within the org.")
    client_id: str | None = Field(
        default=None,
        description="The account's own OAuth client id, or None to inherit the shared one.",
    )
    has_secret_override: bool = Field(
        default=False,
        description="Whether the account stores its own OAuth client secret.",
    )


class GscAccountStore(Protocol):
    """Where an org's GSC accounts live. Every method is scoped to one org."""

    def list_accounts(self, org_id: str) -> list[GscAccountSummary]:
        """Every account in the org, sorted by name. Never decrypts.

        Raises:
            KeyError: The implementation requires the org to exist and it does not.
            GscAccountStoreUnavailableError: The store cannot answer.
        """
        ...

    def account_names(self, org_id: str) -> frozenset[str]:
        """The org's account names. Never decrypts.

        Raises:
            GscAccountStoreUnavailableError: The store cannot answer.
        """
        ...

    def get_credential(self, org_id: str, account_name: str) -> GscAccountCredential | None:
        """One account's credential, or `None` if the org stores no such account.

        Raises:
            GscAccountStoreUnavailableError: The store cannot answer.
            GscCredentialDecryptionError: The stored ciphertext cannot be read.
        """
        ...

    def upsert(
        self,
        org_id: str,
        account_name: str,
        credential: GscAccountCredential,
        *,
        operator_id: str,
    ) -> UpsertOutcome:
        """Add or replace one account.

        Raises:
            KeyError: The implementation requires the org to exist and it does not.
            GscAccountStoreUnavailableError: The store cannot answer.
        """
        ...

    def delete(self, org_id: str, account_name: str) -> bool:
        """Remove one account. `False` if the org holds no such account.

        Raises:
            KeyError: The implementation requires the org to exist and it does not.
            GscAccountStoreUnavailableError: The store cannot answer.
        """
        ...


class DiskGscAccountStore:
    """A `GscAccountStore` over `OrgConfig.gsc_accounts` in an `OrgConfigStore`.

    The local store. It reads and writes exactly what the API wrote before this
    seam existed, so a workstation's `.orgs/org_configs.json` keeps working.
    """

    def __init__(self, org_store: OrgConfigStore) -> None:
        """Wrap an existing org config store.

        Args:
            org_store: The store whose `OrgConfig.gsc_accounts` holds the accounts.
        """
        self._org_store = org_store

    @property
    def org_store(self) -> OrgConfigStore:
        """The wrapped org config store."""
        return self._org_store

    def _accounts_or_empty(self, org_id: str) -> dict[str, GscAccountCredential]:
        """The org's accounts, or empty when the org or the file cannot be read.

        Fail-soft, exactly as before ADR 0037: an unknown org or an unreadable
        file means "no org-level accounts" locally. Named exceptions rather than
        a bare `except`, so a bug in the store still surfaces.
        """
        try:
            return dict(self._org_store.get(org_id).gsc_accounts)
        except (KeyError, OSError, ValueError):
            return {}

    def list_accounts(self, org_id: str) -> list[GscAccountSummary]:
        """Every account in the org. `KeyError` for an unknown org, as before."""
        org = self._org_store.get(org_id)
        return [
            GscAccountSummary(
                account_name=name,
                client_id=cred.client_id,
                has_secret_override=cred.client_secret is not None,
            )
            for name, cred in sorted(org.gsc_accounts.items())
        ]

    def account_names(self, org_id: str) -> frozenset[str]:
        """The org's account names; empty for an unknown org or unreadable file."""
        return frozenset(self._accounts_or_empty(org_id))

    def get_credential(self, org_id: str, account_name: str) -> GscAccountCredential | None:
        """One account's credential; `None` when absent or unreadable (fail-soft)."""
        return self._accounts_or_empty(org_id).get(account_name)

    def upsert(
        self,
        org_id: str,
        account_name: str,
        credential: GscAccountCredential,
        *,
        operator_id: str,
    ) -> UpsertOutcome:
        """Add or replace one account. `KeyError` for an unknown org, as before.

        `operator_id` is unused here: the disk file has no audit column, and the
        route's audit event already records who wrote the account.
        """
        del operator_id
        org = self._org_store.get(org_id)
        outcome: UpsertOutcome = "replaced" if account_name in org.gsc_accounts else "created"
        org.gsc_accounts[account_name] = credential
        self._org_store.update(org)
        return outcome

    def delete(self, org_id: str, account_name: str) -> bool:
        """Remove one account. `KeyError` for an unknown org, as before."""
        org = self._org_store.get(org_id)
        if account_name not in org.gsc_accounts:
            return False
        del org.gsc_accounts[account_name]
        self._org_store.update(org)
        return True
