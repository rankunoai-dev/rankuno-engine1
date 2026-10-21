"""The persistence seam for user accounts, and the one-time admin bootstrap (ADR 0040).

This module is the contract. The Postgres implementation is
`postgres_user_store`. Nothing here reads a request or issues a session.

Design stance:

* **The bootstrap is one statement, not a check-then-create.** A list followed
  by a create lets two starting processes both see "no admin" and both insert.
  The store issues a single guarded INSERT and relies on the partial unique
  index `ux_users_single_admin` as the final guarantee. Migration 0014 explains
  why the index, not the `NOT EXISTS` fast path, is the real guard.
* **An existing row is never touched.** The bootstrap inserts or does nothing.
  It never updates a row, so an env password cannot reset an existing admin.
* **The environment password is a first-boot credential, not a standing one.**
  It is refused when weak, and a startup warning records that it is still set.
  Only the hash is stored, with `must_change_password=true`.
* **Logs carry facts, not values.** Neither the email address nor the password
  is ever logged, because a log line outlives the first login.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import Field, SecretStr

from src.core.config import get_settings
from src.core.errors import ConfigurationError
from src.core.logger import get_logger
from src.core.schemas import StrictModel

if TYPE_CHECKING:
    from src.core.config import Settings

__all__ = [
    "MIN_ADMIN_PASSWORD_LENGTH",
    "AdminBootstrapOutcome",
    "UserRecord",
    "UserRole",
    "UserStore",
    "bootstrap_admin_from_settings",
    "normalize_admin_email",
    "validate_initial_password",
]

_logger = get_logger(__name__)

MIN_ADMIN_PASSWORD_LENGTH = 12
"""Shorter initial passwords are refused at bootstrap, before any SQL is issued."""

_KNOWN_WEAK_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd",
        "changeme",
        "letmein",
        "qwerty",
        "admin",
        "admin123",
        "administrator",
        "rankuno",
        "iloveyou",
        "12345678",
        "123456789",
        "1234567890",
    }
)
"""A small list of values that appear first in every breach corpus.

Compared case-insensitively, so `Password123` is refused too. It is a floor, not
a strength meter: the length rule does the real work.
"""

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_MAX_EMAIL_LENGTH = 254


class UserRole(StrEnum):
    """Governance role. Lowercase, like the other governance enums (ruling 3)."""

    ADMIN = "admin"
    USER = "user"


class AdminBootstrapOutcome(StrEnum):
    """What one bootstrap call did. Carries no email address and no password."""

    CREATED = "created"
    """This call inserted the first admin row."""

    NOT_CREATED = "not_created"
    """No row was inserted. An admin already exists, or the email is already taken
    by a non-admin row. The two cases are not distinguished here, on purpose: a
    distinction would need a second query, and the log line must not name the row."""

    NOT_CONFIGURED = "not_configured"
    """`ADMIN_EMAIL` or `ADMIN_INITIAL_PASSWORD` is unset, so there is nothing to do."""


class UserRecord(StrictModel):
    """One row of the `users` table, as the application may read it."""

    id: str = Field(min_length=1)
    role: UserRole
    is_active: bool
    session_version: int = Field(ge=0)
    email: str = Field(min_length=3, max_length=_MAX_EMAIL_LENGTH)
    google_sub: str | None = None
    password_hash: SecretStr | None = None
    must_change_password: bool
    created_at: datetime


class UserStore(Protocol):
    """Read and bootstrap user accounts. Every method is safe to call repeatedly."""

    def bootstrap_admin(self, email: str, initial_password: SecretStr) -> AdminBootstrapOutcome:
        """Insert the first admin, or do nothing if one exists.

        Raises:
            ConfigurationError: The email is malformed or the password is weak.
            UserStoreUnavailableError: The database cannot answer.
        """
        ...

    def get_by_email(self, email: str) -> UserRecord | None:
        """Return the row for `email` (case-insensitive), or `None`.

        Raises:
            UserStoreUnavailableError: The database cannot answer.
        """
        ...


def normalize_admin_email(raw: str) -> str:
    """Strip and lower-case an address, and refuse anything that is not one.

    The refusal message never echoes the input: the address is personal data.

    Raises:
        ConfigurationError: The value is not a plausible `local@domain.tld`.
    """
    email = raw.strip().lower()
    if len(email) > _MAX_EMAIL_LENGTH or _EMAIL_RE.fullmatch(email) is None:
        msg = "ADMIN_EMAIL is not a well-formed email address"
        raise ConfigurationError(msg)
    return email


def validate_initial_password(password: str) -> None:
    """Refuse a first-boot password that is short or on the known-weak list.

    Raises:
        ConfigurationError: Too short, or a known-weak value. The message names
            the rule, never the value.
    """
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        msg = f"ADMIN_INITIAL_PASSWORD must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters"
        raise ConfigurationError(msg)
    if password.lower() in _KNOWN_WEAK_PASSWORDS:
        msg = "ADMIN_INITIAL_PASSWORD is a known-weak value; choose another"
        raise ConfigurationError(msg)


def bootstrap_admin_from_settings(
    store: UserStore, settings: Settings | None = None
) -> AdminBootstrapOutcome:
    """Run the admin bootstrap from `ADMIN_EMAIL` and `ADMIN_INITIAL_PASSWORD`.

    The warning is logged on every call while the password is set, whatever the
    outcome, because the risk is the value sitting in the environment. It names
    the fact only.

    Args:
        store: The user store to bootstrap into.
        settings: Settings to read. Defaults to the process singleton, so tests
            can pass a hermetic `Settings(_env_file=None, ...)`.

    Returns:
        `NOT_CONFIGURED` when either value is unset, otherwise the store's outcome.
    """
    cfg = settings if settings is not None else get_settings()
    password = cfg.admin_initial_password
    email = cfg.admin_email
    if password is not None:
        _logger.warning(
            "admin_initial_password_still_set",
            extra={"action": "remove_admin_initial_password_after_first_login"},
        )
    if password is None or not email:
        return AdminBootstrapOutcome.NOT_CONFIGURED
    return store.bootstrap_admin(email, password)
