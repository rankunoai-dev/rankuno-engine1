"""PostgreSQL store for org GSC accounts: they survive a redeploy, encrypted (ADR 0036).

The cloud's org GSC accounts lived in `.orgs/org_configs.json` on the Railway
container disk and vanished on every redeploy. They now live in the
`org_gsc_accounts` table (migration 010), with the refresh token and any
client secret encrypted by `GscCredentialCipher`.

Design stance, and where it deliberately departs from `PostgresJobStore`:

* **No disk fallback, ever.** `PostgresJobStore` falls back to disk when its
  breaker opens. A credential store must not: a disk copy is exactly what
  this table replaces, and a fallback that answered "no such account" would
  let a same-named `.env.local` profile read the wrong client's Search
  Console. An open breaker or a database error is
  `GscAccountStoreUnavailableError`, and callers fail closed.
* **Every statement is scoped by the caller's org.** Each one binds `org_id`
  as a parameter, and single-row operations add `account_name`. No SQL is
  ever built from caller input.
* **Listing never decrypts.** `has_secret_override` is
  `client_secret_ct IS NOT NULL`, so a lost or rotated-out key never breaks
  the accounts page, only the one account being resolved.
* **Database errors are logged by class and SQLSTATE only.** A psycopg
  message's DETAIL can quote the offending row, and on this table that row
  holds ciphertext beside the account name.
* **A fresh connection per call**, as every Postgres store here does, so a
  rotated database credential takes effect without a restart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

import psycopg

from src.core.circuit_breaker import CircuitBreaker
from src.core.errors import GscAccountStoreUnavailableError
from src.core.gsc_account_store import GscAccountSummary, UpsertOutcome
from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.schemas import GscAccountCredential

if TYPE_CHECKING:
    from psycopg import Connection, Cursor

    from src.core.gsc_credential_crypto import GscCredentialCipher

__all__ = ["PostgresGscAccountStore"]

_logger = get_logger(__name__)

_T = TypeVar("_T")

_PARENT_ORG_SQL = (
    "INSERT INTO org_configs (org_id, display_name, llm_credit_limit_usd) "
    "VALUES (%s, %s, 0) ON CONFLICT (org_id) DO NOTHING"
)
"""Create the FK parent row if absent. Budget 0, never the column default of
100: `PostgresJobStore.create` admits jobs on a positive budget, so saving a
GSC account must not quietly grant an org the ability to run crawls. An
existing row is left exactly as it is."""

_UPSERT_SQL = (
    "INSERT INTO org_gsc_accounts "
    "(org_id, account_name, client_id, client_secret_ct, refresh_token_ct, key_id, "
    "created_by, updated_by, created_at, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
    "ON CONFLICT (org_id, account_name) DO UPDATE SET "
    "client_id = EXCLUDED.client_id, client_secret_ct = EXCLUDED.client_secret_ct, "
    "refresh_token_ct = EXCLUDED.refresh_token_ct, key_id = EXCLUDED.key_id, "
    "updated_by = EXCLUDED.updated_by, updated_at = now() "
    "WHERE org_gsc_accounts.org_id = %s "
    "RETURNING (xmax = 0)"
)
"""`xmax = 0` is true only for a freshly inserted row, which is how one
round-trip tells "created" from "replaced" for the audit event."""


class PostgresGscAccountStore:
    """A `GscAccountStore` backed by the `org_gsc_accounts` table."""

    def __init__(
        self,
        cipher: GscCredentialCipher,
        *,
        circuit_breaker: CircuitBreaker | None = None,
        connection_factory: Callable[[], Connection] | None = None,
    ) -> None:
        """Build the store.

        Args:
            cipher: Encrypts writes under the current key and decrypts reads.
            circuit_breaker: Opens after repeated database failures, after which
                calls fail fast with `GscAccountStoreUnavailableError`.
            connection_factory: Returns a new psycopg-shaped connection.
                Injectable so tests need no live database.
        """
        self._cipher = cipher
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        """A real connection, re-reading credentials on every call."""
        return psycopg.connect(get_postgres_settings().get_connection_string())

    def _log_db_error(self, exc: BaseException) -> None:
        """Record a database failure by class and SQLSTATE, never by message."""
        _logger.warning(
            "gsc_account_store_db_error",
            extra={
                "error_class": type(exc).__name__,
                "sqlstate": getattr(exc, "sqlstate", None),
            },
        )

    def _run(self, operation: Callable[[Cursor[Any]], _T]) -> _T:
        """Run one transaction, mapping every database failure to fail-closed.

        Raises:
            GscAccountStoreUnavailableError: Breaker open, connection refused,
                or the statement failed. Raised `from None`, so the psycopg
                exception and its DETAIL never ride along in a traceback.
        """
        if self.circuit_breaker.is_open():
            raise GscAccountStoreUnavailableError
        try:
            conn = self._connection_factory()
        except Exception as exc:  # noqa: BLE001 - any connect failure fails closed
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise GscAccountStoreUnavailableError from None
        try:
            with conn, conn.cursor() as cur:
                result = operation(cur)
        except psycopg.IntegrityError as exc:
            # The API enforces the same rules as the table's CHECKs, so this is
            # a bug rather than an outage: fail closed without opening the breaker.
            self._log_db_error(exc)
            raise GscAccountStoreUnavailableError from None
        except psycopg.Error as exc:
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise GscAccountStoreUnavailableError from None
        finally:
            conn.close()
        self.circuit_breaker.record_success()
        return result

    def list_accounts(self, org_id: str) -> list[GscAccountSummary]:
        """Every account in the org, sorted by name. Reads no ciphertext."""

        def op(cur: Cursor[Any]) -> list[tuple[Any, ...]]:
            cur.execute(
                "SELECT account_name, client_id, client_secret_ct IS NOT NULL "
                "FROM org_gsc_accounts WHERE org_id = %s ORDER BY account_name",
                (org_id,),
            )
            return list(cur.fetchall())

        return [
            GscAccountSummary(
                account_name=str(name),
                client_id=None if client_id is None else str(client_id),
                has_secret_override=bool(has_secret),
            )
            for name, client_id, has_secret in self._run(op)
        ]

    def account_names(self, org_id: str) -> frozenset[str]:
        """The org's account names. Reads no ciphertext."""

        def op(cur: Cursor[Any]) -> list[tuple[Any, ...]]:
            cur.execute(
                "SELECT account_name FROM org_gsc_accounts WHERE org_id = %s",
                (org_id,),
            )
            return list(cur.fetchall())

        return frozenset(str(row[0]) for row in self._run(op))

    def get_credential(self, org_id: str, account_name: str) -> GscAccountCredential | None:
        """Decrypt exactly one account, or `None` if the org stores no such account.

        Raises:
            GscAccountStoreUnavailableError: The database cannot answer.
            GscCredentialDecryptionError: This row cannot be decrypted. Other
                accounts are unaffected.
        """

        def op(cur: Cursor[Any]) -> tuple[Any, ...] | None:
            cur.execute(
                "SELECT client_id, client_secret_ct, refresh_token_ct, key_id "
                "FROM org_gsc_accounts WHERE org_id = %s AND account_name = %s",
                (org_id, account_name),
            )
            return cast("tuple[Any, ...] | None", cur.fetchone())

        row = self._run(op)
        if row is None:
            return None
        client_id, secret_ct, token_ct, key_id = row
        decrypt = self._cipher.decrypt
        refresh_token = decrypt(
            bytes(token_ct),
            key_id=str(key_id),
            org_id=org_id,
            account_name=account_name,
            field="refresh_token",
        )
        client_secret = (
            None
            if secret_ct is None
            else decrypt(
                bytes(secret_ct),
                key_id=str(key_id),
                org_id=org_id,
                account_name=account_name,
                field="client_secret",
            )
        )
        return GscAccountCredential.model_validate(
            {
                "refresh_token": refresh_token,
                "client_id": None if client_id is None else str(client_id),
                "client_secret": client_secret,
            }
        )

    def upsert(
        self,
        org_id: str,
        account_name: str,
        credential: GscAccountCredential,
        *,
        operator_id: str,
    ) -> UpsertOutcome:
        """Encrypt and store one account, creating the parent org row if absent."""
        encrypt = self._cipher.encrypt
        token_ct = encrypt(
            credential.refresh_token.get_secret_value(),
            org_id=org_id,
            account_name=account_name,
            field="refresh_token",
        )
        secret_ct = (
            None
            if credential.client_secret is None
            else encrypt(
                credential.client_secret.get_secret_value(),
                org_id=org_id,
                account_name=account_name,
                field="client_secret",
            )
        )
        params = (
            org_id,
            account_name,
            credential.client_id,
            secret_ct,
            token_ct,
            self._cipher.key_id,
            operator_id,
            operator_id,
            org_id,
        )

        def op(cur: Cursor[Any]) -> bool:
            cur.execute(_PARENT_ORG_SQL, (org_id, f"Org {org_id}"))
            cur.execute(_UPSERT_SQL, params)
            row = cur.fetchone()
            return bool(row[0]) if row is not None else False

        return "created" if self._run(op) else "replaced"

    def delete(self, org_id: str, account_name: str) -> bool:
        """Remove one account. `False` if the org holds no such account."""

        def op(cur: Cursor[Any]) -> bool:
            cur.execute(
                "DELETE FROM org_gsc_accounts WHERE org_id = %s AND account_name = %s",
                (org_id, account_name),
            )
            return bool(cur.rowcount == 1)

        return self._run(op)
