"""Typed application configuration loaded from the environment.

Rules enforced here:

* No module anywhere else may read `os.environ` directly. Everything goes
  through `get_settings()` so that configuration is typed, validated once, and
  greppable.
* Secrets are held as `SecretStr` so they cannot be accidentally printed or
  serialised into an audit log.
* Production refuses to boot with guardrails disabled.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.errors import ConfigurationError
from src.core.schemas import StrictModel

__all__ = [
    "GSC_ACCOUNT_NAME_PATTERN",
    "Environment",
    "GscAccountProfile",
    "ResolvedGscCredentials",
    "Settings",
    "get_settings",
    "reset_settings_cache",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

GSC_ACCOUNT_NAME_PATTERN = r"^[a-z0-9_-]{1,64}$"
"""What a GSC profile name may look like.

Lowercase because pydantic-settings lowercases nested env keys when
`case_sensitive=False`, so `GSC_ACCOUNTS__Acme__...` arrives as `acme` and a
request naming `Acme` must resolve to the same profile. No delimiter characters,
so a name can never be mistaken for part of the `__` nesting syntax.
"""

_GSC_ACCOUNT_NAME_RE = re.compile(GSC_ACCOUNT_NAME_PATTERN)


class GscAccountProfile(StrictModel):
    """One Google account authorised to read Search Console.

    The primary case is one OAuth app authorised by several Google accounts,
    which yields one refresh token per account and a shared client id/secret.
    `client_id` and `client_secret` exist for the minority case where a client
    insists on their own OAuth app; when unset the profile inherits the shared
    `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.

    Declared in `.env.local` as nested keys, parsed by pydantic-settings:

        GSC_ACCOUNTS__ACME__REFRESH_TOKEN=...
        GSC_ACCOUNTS__ACME__CLIENT_ID=...        # optional override
        GSC_ACCOUNTS__ACME__CLIENT_SECRET=...    # optional override
    """

    refresh_token: SecretStr
    client_id: str | None = None
    client_secret: SecretStr | None = None


class ResolvedGscCredentials(StrictModel):
    """The complete triple a token manager needs, after inheritance is applied.

    Attributes:
        account: The profile name, or `None` for the flat default credentials.
            Carried so audit logs can identify the account without ever
            touching the client id.
    """

    account: str | None
    client_id: str
    client_secret: SecretStr
    refresh_token: SecretStr


class Environment(StrEnum):
    """Deployment target. Governs how strict the guardrails are."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """All runtime configuration for the platform.

    Field names map to upper-cased environment variables (see `.env.example`).
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Lets `GSC_ACCOUNTS__<name>__REFRESH_TOKEN` populate `gsc_accounts`.
        # Only keys whose prefix matches a field are split, so a `__` inside a
        # token *value* — refresh tokens contain them — is untouched.
        env_nested_delimiter="__",
    )

    # -- Application -------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_format: str = Field(default="json", pattern="^(json|text)$")
    audit_log_path: Path = REPO_ROOT / "logs" / "audit.jsonl"

    # -- Guardrails --------------------------------------------------------
    guardrails_enabled: bool = Field(
        default=True,
        description="Master switch. Disabling is permitted in development only.",
    )
    require_approval_for_writes: bool = True
    require_approval_for_spend: bool = True
    max_session_spend_usd: float = Field(
        default=5.0,
        ge=0.0,
        description="Hard ceiling on cumulative spend for one process.",
    )

    # -- Rate limiting -----------------------------------------------------
    default_requests_per_minute: int = Field(default=60, gt=0)
    default_max_retries: int = Field(default=3, ge=0, le=10)
    default_timeout_s: float = Field(default=30.0, gt=0.0)
    max_concurrent_crawls: int = Field(
        default=5,
        ge=1,
        le=10,
        description=(
            "Crawl jobs the API runs at once before returning 429. Each crawl "
            "holds its whole graph in RAM, so this is the memory bound; raise "
            "only with the RAM to match."
        ),
    )

    # -- LLM providers -----------------------------------------------------
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # -- Google OAuth 2.0 (GSC, GA4, etc.) --------------------------------
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_refresh_token: SecretStr | None = None

    # -- Google Search Console named account profiles ----------------------
    gsc_accounts: dict[str, GscAccountProfile] = Field(
        default_factory=dict,
        description=(
            "Named Search Console accounts, one refresh token each. A crawl "
            "selects one by name; none selected means the flat GOOGLE_OAUTH_* "
            "credentials above."
        ),
    )

    # -- Google Search Console (Legacy: Service Account) ------------------
    google_search_console_client_email: str | None = None
    google_search_console_private_key: SecretStr | None = None

    # -- Google Ads --------------------------------------------------------
    google_ads_developer_token: SecretStr | None = None
    google_ads_client_id: str | None = None
    google_ads_client_secret: SecretStr | None = None
    google_ads_refresh_token: SecretStr | None = None

    # -- SEO data providers ------------------------------------------------
    serp_api_key: SecretStr | None = None
    ahrefs_api_key: SecretStr | None = None
    semrush_api_key: SecretStr | None = None

    # -- Deliverables differential check (opt-in, ADR 0011) -----------------
    rae_archive_dir: Path | None = Field(
        default=None,
        description=(
            "Directory of RAE crawl-report folders, read only by "
            "scripts/diff_against_rae.py as an issue-membership oracle. A "
            "path, not a credential; unset skips the check cleanly."
        ),
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Normalise and validate the log level."""
        normalised = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalised not in allowed:
            msg = f"LOG_LEVEL must be one of {sorted(allowed)}, got '{value}'"
            raise ValueError(msg)
        return normalised

    @field_validator("gsc_accounts")
    @classmethod
    def _validate_gsc_account_names(
        cls, value: dict[str, GscAccountProfile]
    ) -> dict[str, GscAccountProfile]:
        """Refuse a profile name the request schema could never select."""
        for name in value:
            if not _GSC_ACCOUNT_NAME_RE.fullmatch(name):
                msg = (
                    f"GSC account name '{name}' is invalid: names must match "
                    f"{GSC_ACCOUNT_NAME_PATTERN} (lowercase letters, digits, '_' and '-')."
                )
                raise ValueError(msg)
        return value

    def model_post_init(self, _context: Any, /) -> None:
        """Refuse unsafe production configurations at boot rather than at call time."""
        if self.environment is Environment.PRODUCTION and not self.guardrails_enabled:
            msg = "GUARDRAILS_ENABLED=false is not permitted in production."
            raise ConfigurationError(msg)

    def gsc_account_names(self) -> tuple[str, ...]:
        """Configured profile names, sorted. Safe to publish: names, never secrets."""
        return tuple(sorted(self.gsc_accounts))

    def resolve_gsc_account(self, name: str | None) -> ResolvedGscCredentials:
        """Produce the credential triple for a profile, or for the default.

        Deliberately the only place the inheritance rule lives, so the token
        manager and any future Google connector agree on what "default" means.

        Args:
            name: A profile name, or `None` for the flat `GOOGLE_OAUTH_*` triple.

        Returns:
            Complete credentials with the account name attached.

        Raises:
            ConfigurationError: If the profile does not exist — no fallback to
                the default, because silently querying the wrong client's
                Search Console is worse than a failed crawl — or if whatever
                is selected is incomplete.
        """
        if name is None:
            if (
                not self.google_oauth_client_id
                or self.google_oauth_client_secret is None
                or self.google_oauth_refresh_token is None
            ):
                msg = (
                    "GSC OAuth credentials not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
                    "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN in .env.local"
                )
                raise ConfigurationError(msg)
            return ResolvedGscCredentials(
                account=None,
                client_id=self.google_oauth_client_id,
                client_secret=self.google_oauth_client_secret,
                refresh_token=self.google_oauth_refresh_token,
            )

        key = name.lower()
        profile = self.gsc_accounts.get(key)
        if profile is None:
            known = ", ".join(self.gsc_account_names()) or "none configured"
            msg = f"Unknown GSC account '{name}'. Configured accounts: {known}."
            raise ConfigurationError(msg)

        client_id = profile.client_id or self.google_oauth_client_id
        client_secret = profile.client_secret or self.google_oauth_client_secret
        if not client_id or client_secret is None:
            msg = (
                f"GSC account '{key}' has no OAuth client. Set GOOGLE_OAUTH_CLIENT_ID and "
                f"GOOGLE_OAUTH_CLIENT_SECRET (shared), or GSC_ACCOUNTS__{key.upper()}__CLIENT_ID "
                f"and GSC_ACCOUNTS__{key.upper()}__CLIENT_SECRET for this account."
            )
            raise ConfigurationError(msg)
        return ResolvedGscCredentials(
            account=key,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=profile.refresh_token,
        )

    def require(self, field_name: str) -> str:
        """Return a required credential, or fail loudly with an actionable message.

        Args:
            field_name: Name of a settings field holding a credential.

        Returns:
            The plain-text value.

        Raises:
            ConfigurationError: If the field is unset or is not a known field.
        """
        if field_name not in type(self).model_fields:
            msg = f"'{field_name}' is not a known setting."
            raise ConfigurationError(msg)

        value = getattr(self, field_name)
        if value is None:
            msg = (
                f"Required setting '{field_name.upper()}' is not configured. "
                f"Add it to your .env file (see .env.example)."
            )
            raise ConfigurationError(msg)
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that `.env` is parsed exactly once and every module observes an
    identical view of configuration.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache. Intended for tests only."""
    get_settings.cache_clear()
