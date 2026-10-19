"""PostgreSQL store for an organisation's GA4 access: encrypted, org-scoped, fail-closed (ADR 0038).

Mirrors `PostgresGscAccountStore` on the same deliberate points, and departs
from `PostgresJobStore` for the same reason: a credential store has no disk
fallback. An open breaker or a database error is
`Ga4AccessStoreUnavailableError`, and every caller fails closed.

* **Every statement binds `org_id`.** No SQL is built from caller input, and
  the property id is also checked against `GA4_PROPERTY_ID_PATTERN` before it
  is written (the table's CHECK is the second line of defence).
* **Database errors are logged by class and SQLSTATE only.** A psycopg message
  can quote the row, and this row holds ciphertext.
* **A fresh connection per call**, as every Postgres store here does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

import psycopg
from pydantic import SecretStr

from src.core.circuit_breaker import CircuitBreaker
from src.core.errors import Ga4AccessStoreUnavailableError
from src.core.ga4_access_store import Ga4AccessSummary, is_valid_ga4_property_id
from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings

if TYPE_CHECKING:
    from psycopg import Connection, Cursor

    from src.core.gsc_credential_crypto import GscCredentialCipher

__all__ = ["PostgresGa4AccessStore"]

_logger = get_logger(__name__)

_T = TypeVar("_T")

_PARENT_ORG_SQL = (
    "INSERT INTO org_configs (org_id, display_name, llm_credit_limit_usd) "
    "VALUES (%s, %s, 0) ON CONFLICT (org_id) DO NOTHING"
)
"""Create the FK parent row if absent, with budget 0, as the GSC store does: saving
a GA4 credential must not grant an org the ability to run crawls."""

_UPSERT_SQL = (
    "INSERT INTO org_ga4_access "
    "(org_id, refresh_token_ct, key_id, property_id, created_by, updated_by, "
    "created_at, updated_at) "
    "VALUES (%s, %s, %s, NULL, %s, %s, now(), now()) "
    "ON CONFLICT (org_id) DO UPDATE SET "
    "refresh_token_ct = EXCLUDED.refresh_token_ct, key_id = EXCLUDED.key_id, "
    "property_id = NULL, updated_by = EXCLUDED.updated_by, updated_at = now() "
    "WHERE org_ga4_access.org_id = %s"
)


class PostgresGa4AccessStore:
    """A `Ga4AccessStore` backed by the `org_ga4_access` table."""

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
            circuit_breaker: Opens after repeated database failures.
            connection_factory: Returns a new psycopg-shaped connection. Injectable
                so tests need no live database.
        """
        self._cipher = cipher
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        """A real connection, re-reading credentials on every call."""
        return psycopg.connect(get_postgres_settings().get_connection_string())

    def _run(self, operation: Callable[[Cursor[Any]], _T]) -> _T:
        """Run one transaction, mapping every database failure to fail-closed.

        Raises:
            Ga4AccessStoreUnavailableError: Breaker open, connection refused, or
                the statement failed. Raised `from None`, so the psycopg message
                never rides along in a traceback.
        """
        if self.circuit_breaker.is_open():
            raise Ga4AccessStoreUnavailableError
        try:
            conn = self._connection_factory()
        except Exception as exc:  # noqa: BLE001 - any connect failure fails closed
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise Ga4AccessStoreUnavailableError from None
        try:
            with conn, conn.cursor() as cur:
                result = operation(cur)
        except psycopg.IntegrityError as exc:
            # The API enforces the table's rules first, so this is a bug, not an outage.
            self._log_db_error(exc)
            raise Ga4AccessStoreUnavailableError from None
        except psycopg.Error as exc:
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise Ga4AccessStoreUnavailableError from None
        finally:
            conn.close()
        self.circuit_breaker.record_success()
        return result

    @staticmethod
    def _log_db_error(exc: BaseException) -> None:
        """Record a database failure by class and SQLSTATE, never by message."""
        _logger.warning(
            "ga4_access_store_db_error",
            extra={"error_class": type(exc).__name__, "sqlstate": getattr(exc, "sqlstate", None)},
        )

    def status(self, org_id: str) -> Ga4AccessSummary:
        """Whether a credential is stored, and the mapped property. Reads no ciphertext."""

        def op(cur: Cursor[Any]) -> tuple[Any, ...] | None:
            cur.execute(
                "SELECT property_id FROM org_ga4_access WHERE org_id = %s",
                (org_id,),
            )
            return cast("tuple[Any, ...] | None", cur.fetchone())

        row = self._run(op)
        if row is None:
            return Ga4AccessSummary(has_credential=False, property_id=None)
        return Ga4AccessSummary(
            has_credential=True,
            property_id=None if row[0] is None else str(row[0]),
        )

    def refresh_token(self, org_id: str) -> SecretStr | None:
        """Decrypt the organisation's GA4 refresh token, or `None` if it has none.

        Raises:
            Ga4AccessStoreUnavailableError: The database cannot answer.
            Ga4CredentialDecryptionError: The row cannot be decrypted.
        """

        def op(cur: Cursor[Any]) -> tuple[Any, ...] | None:
            cur.execute(
                "SELECT refresh_token_ct, key_id FROM org_ga4_access WHERE org_id = %s",
                (org_id,),
            )
            return cast("tuple[Any, ...] | None", cur.fetchone())

        row = self._run(op)
        if row is None:
            return None
        token_ct, key_id = row
        plaintext = self._cipher.decrypt_ga4_refresh_token(
            bytes(token_ct), key_id=str(key_id), org_id=org_id
        )
        return SecretStr(plaintext)

    def set_credential(self, org_id: str, refresh_token: SecretStr, *, operator_id: str) -> None:
        """Encrypt and store the token, creating the parent org row if absent."""
        token_ct = self._cipher.encrypt_ga4_refresh_token(
            refresh_token.get_secret_value(), org_id=org_id
        )
        params = (org_id, token_ct, self._cipher.key_id, operator_id, operator_id, org_id)

        def op(cur: Cursor[Any]) -> None:
            cur.execute(_PARENT_ORG_SQL, (org_id, f"Org {org_id}"))
            cur.execute(_UPSERT_SQL, params)

        self._run(op)

    def set_property(self, org_id: str, property_id: str, *, operator_id: str) -> bool:
        """Map a property under the org's credential. `False` when there is none.

        A malformed id is refused here before any statement is issued.
        """
        if not is_valid_ga4_property_id(property_id):
            msg = "GA4 property id is not in the expected numeric form"
            raise ValueError(msg)

        def op(cur: Cursor[Any]) -> bool:
            cur.execute(
                "UPDATE org_ga4_access SET property_id = %s, updated_by = %s, updated_at = now() "
                "WHERE org_id = %s",
                (property_id, operator_id, org_id),
            )
            return bool(cur.rowcount == 1)

        return self._run(op)

    def delete(self, org_id: str, *, operator_id: str) -> bool:
        """Remove the org's GA4 access. `False` if there was none."""
        del operator_id  # The route's audit event records who removed it.

        def op(cur: Cursor[Any]) -> bool:
            cur.execute("DELETE FROM org_ga4_access WHERE org_id = %s", (org_id,))
            return bool(cur.rowcount == 1)

        return self._run(op)
