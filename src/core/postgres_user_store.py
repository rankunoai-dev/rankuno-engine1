"""PostgreSQL store for user accounts and the atomic admin bootstrap (ADR 0040).

Follows `PostgresGa4AccessStore` on the same deliberate points: a circuit
breaker, a fresh connection per call, and database errors logged by class and
SQLSTATE only. An open breaker or a failed statement is
`UserStoreUnavailableError`, and every caller fails closed.

* **The bootstrap is one INSERT.** `_INSERT_ADMIN_SQL` checks for an admin and
  inserts in the same statement, with `ON CONFLICT DO NOTHING`. Two processes
  starting together cannot both insert: whichever commits second hits the
  partial unique index `ux_users_single_admin` and inserts nothing. That is the
  guarantee. The `NOT EXISTS` clause only avoids a needless conflict on the
  common path.
* **`ON CONFLICT DO NOTHING` has no target, on purpose.** It also absorbs a
  clash on `email`, so a non-admin row with the same address makes the
  bootstrap a no-op rather than an error. The outcome is `NOT_CREATED`.
* **Every statement binds its parameters.** No SQL is built from input.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

import psycopg
from pydantic import SecretStr

from src.core.auth import hash_password
from src.core.circuit_breaker import CircuitBreaker
from src.core.errors import UserStoreUnavailableError
from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.user_store import (
    AdminBootstrapOutcome,
    UserRecord,
    normalize_admin_email,
    validate_initial_password,
)

if TYPE_CHECKING:
    from psycopg import Connection, Cursor

__all__ = ["PostgresUserStore"]

_logger = get_logger(__name__)

_T = TypeVar("_T")

_INSERT_ADMIN_SQL = (
    "INSERT INTO users "
    "(id, role, is_active, session_version, email, google_sub, password_hash, "
    "must_change_password, created_at) "
    "SELECT %s, 'admin', true, 0, %s, NULL, %s, true, now() "
    "WHERE NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin') "
    "ON CONFLICT DO NOTHING RETURNING id"
)

_SELECT_BY_EMAIL_SQL = (
    "SELECT id, role, is_active, session_version, email, google_sub, password_hash, "
    "must_change_password, created_at FROM users WHERE email = %s"
)


class PostgresUserStore:
    """A `UserStore` backed by the `users` table."""

    def __init__(
        self,
        *,
        circuit_breaker: CircuitBreaker | None = None,
        connection_factory: Callable[[], Connection] | None = None,
    ) -> None:
        """Build the store.

        Args:
            circuit_breaker: Opens after repeated database failures.
            connection_factory: Returns a new psycopg-shaped connection. Injectable
                so tests need no live database.
        """
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        """A real connection, re-reading credentials on every call."""
        return psycopg.connect(get_postgres_settings().get_connection_string())

    def _run(self, operation: Callable[[Cursor[Any]], _T]) -> _T:
        """Run one transaction, mapping every database failure to fail-closed.

        Raises:
            UserStoreUnavailableError: Breaker open, connection refused, or the
                statement failed. Raised `from None`, so the psycopg message never
                rides along in a traceback.
        """
        if self.circuit_breaker.is_open():
            raise UserStoreUnavailableError
        try:
            conn = self._connection_factory()
        except Exception as exc:  # noqa: BLE001 - any connect failure fails closed
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise UserStoreUnavailableError from None
        try:
            with conn, conn.cursor() as cur:
                result = operation(cur)
        except psycopg.IntegrityError as exc:
            # A CHECK violation here is a bug in the caller, not an outage.
            self._log_db_error(exc)
            raise UserStoreUnavailableError from None
        except psycopg.Error as exc:
            self.circuit_breaker.record_failure(exc)
            self._log_db_error(exc)
            raise UserStoreUnavailableError from None
        finally:
            conn.close()
        self.circuit_breaker.record_success()
        return result

    @staticmethod
    def _log_db_error(exc: BaseException) -> None:
        """Record a database failure by class and SQLSTATE, never by message."""
        _logger.warning(
            "user_store_db_error",
            extra={"error_class": type(exc).__name__, "sqlstate": getattr(exc, "sqlstate", None)},
        )

    def bootstrap_admin(self, email: str, initial_password: SecretStr) -> AdminBootstrapOutcome:
        """Insert the first admin with a hashed password and `must_change_password=true`.

        Validation and hashing happen before any statement, so a refused value
        costs no database round trip. The password is hashed here and never
        stored in clear.

        Raises:
            ConfigurationError: The email is malformed or the password is weak.
            UserStoreUnavailableError: The database cannot answer.
        """
        address = normalize_admin_email(email)
        password = initial_password.get_secret_value()
        validate_initial_password(password)
        password_hash = hash_password(password)
        params = (str(uuid.uuid4()), address, password_hash)

        def op(cur: Cursor[Any]) -> bool:
            cur.execute(_INSERT_ADMIN_SQL, params)
            return cur.fetchone() is not None

        created = self._run(op)
        if created:
            _logger.info("admin_bootstrap_created", extra={"role": "admin"})
            return AdminBootstrapOutcome.CREATED
        _logger.info("admin_bootstrap_not_created")
        return AdminBootstrapOutcome.NOT_CREATED

    def get_by_email(self, email: str) -> UserRecord | None:
        """Return the row for `email` (lower-cased first), or `None`.

        Raises:
            UserStoreUnavailableError: The database cannot answer.
        """
        # A lookup key is normalised, not validated: a malformed address is a miss, not an error.
        address = email.strip().lower()

        def op(cur: Cursor[Any]) -> tuple[Any, ...] | None:
            cur.execute(_SELECT_BY_EMAIL_SQL, (address,))
            return cast("tuple[Any, ...] | None", cur.fetchone())

        row = self._run(op)
        if row is None:
            return None
        return _to_record(row)


def _to_record(row: tuple[Any, ...]) -> UserRecord:
    """Map a `_SELECT_BY_EMAIL_SQL` row to the boundary model."""
    (
        user_id,
        role,
        is_active,
        session_version,
        email,
        google_sub,
        password_hash,
        must_change_password,
        created_at,
    ) = row
    return UserRecord(
        id=str(user_id),
        role=role,
        is_active=bool(is_active),
        session_version=int(session_version),
        email=str(email),
        google_sub=None if google_sub is None else str(google_sub),
        password_hash=None if password_hash is None else SecretStr(str(password_hash)),
        must_change_password=bool(must_change_password),
        created_at=created_at,
    )
