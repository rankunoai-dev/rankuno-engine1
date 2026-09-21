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
import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.errors import ConfigurationError
from src.core.schemas import StrictModel

if TYPE_CHECKING:
    from src.core.auth import OperatorStore
    from src.core.schemas import GscAccountCredential
    from src.core.state_store import OrgConfigStore
    from src.core.worker_auth import WorkerStore

__all__ = [
    "DEFAULT_ORG_ID",
    "GSC_ACCOUNT_NAME_PATTERN",
    "Environment",
    "GscAccountProfile",
    "ResolvedGscCredentials",
    "Settings",
    "WorkerStoreBackend",
    "get_settings",
    "reset_settings_cache",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ORG_ID = "default"
"""The organization a request belongs to when it names none.

The API reads tenancy from the `X-Org-Id` header and substitutes this when the
header is absent, so credential resolution has to agree: an account added
through the UI — which sends no header — lands in this org, and a crawl started
without a header must find it there.
"""

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


class WorkerStoreBackend(StrEnum):
    """Where ADR 0015 worker identity is persisted.

    A closed enum rather than a free string so a typo in
    `WORKER_STORE_BACKEND` fails at boot with the valid options named,
    instead of silently falling back to the disk store whose ephemerality is
    the defect this setting exists to fix.
    """

    DISK = "disk"
    POSTGRES = "postgres"


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

    # -- Deliverables workbook (Phase 2a/2b, ADR 0011) ----------------------
    deliverables_output_dir: Path = Field(
        default=REPO_ROOT / "deliverables" / "output",
        description=(
            "Where build_workbook() writes client workbooks. A local path; "
            "the upload endpoint that moves a workbook off this workstation "
            "is a separate, deferred cycle (plan §2)."
        ),
    )

    # -- PostgreSQL database (Phase 2a) ----------------------------------------
    postgres_host: str = Field(
        default="localhost",
        description="PostgreSQL server hostname or IP address.",
    )
    postgres_port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="PostgreSQL server port.",
    )
    postgres_database: str = Field(
        default="rankuno",
        description="PostgreSQL database name.",
    )
    postgres_user: str = Field(
        default="rankuno",
        description="PostgreSQL user name.",
    )
    postgres_password: SecretStr | None = Field(
        default=None,
        description="PostgreSQL user password (held as SecretStr).",
    )
    postgres_credentials_cache_ttl_s: int = Field(
        default=300,
        ge=60,
        le=3600,
        description=(
            "Time in seconds to cache PostgreSQL credentials before re-reading "
            "from environment. Used for periodic connection pool rebuild and "
            "secret rotation testing."
        ),
    )

    # -- Screaming Frog CLI process governance (ADR 0013) --------------------
    screaming_frog_cli_path: Path = Field(
        default=Path(
            r"C:\Program Files (x86)\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe"
        ),
        description=(
            "ScreamingFrogSEOSpiderCli.exe on this workstation (ADR 0004: single "
            "Windows workstation, not a fleet). Existence is checked at launch "
            "time by the tool, not here, so importing Settings never fails on a "
            "machine that does not have Screaming Frog installed."
        ),
    )
    screaming_frog_template_dir: Path = Field(
        default=REPO_ROOT / "templates" / "screaming_frog",
        description=(
            "Pre-authored .seospiderconfig files, operator-selected by name "
            "(ADR 0013 condition 5). Nothing in this engine can create one: a "
            "config is a Java ObjectInputStream-serialised file, producible only "
            "by the real Screaming Frog GUI's File > Configuration > Save As."
        ),
    )
    screaming_frog_max_runtime_s: float = Field(
        default=7200.0,
        gt=0.0,
        description=(
            "Wall-clock ceiling before ScreamingFrogControlTool terminates its "
            "own supervised process rather than trusting the CLI to exit."
        ),
    )
    process_supervisor_ledger_path: Path = Field(
        default=REPO_ROOT / ".process_ledger.json",
        description=(
            "Independent PID + process-start-time ledger `launch_supervised()` "
            "writes before a Job Object exists (ADR 0013 condition 2). Never "
            "DiskJobStore's `.jobs/` directory — that store answers 'which job "
            "record was left RUNNING', this one answers 'which OS process is "
            "still alive', and the two must not be conflated."
        ),
    )
    screaming_frog_trace_log_path: Path = Field(
        default_factory=lambda: Path.home() / ".ScreamingFrogSEOSpider" / "trace.txt",
        description=(
            "Screaming Frog's own rolling log file, read offset-scoped (never "
            "from the start) for the 'Licence Status:' line (ADR 0013 condition "
            "6). Confirmed live against a real 19.4 install; Screaming Frog "
            "exposes no CLI flag to redirect it, and it is shared across every "
            "invocation on this workstation, which is why the 'seo.screaming_frog' "
            "facet's max_concurrent=1 cap matters for reading it correctly."
        ),
    )

    # -- Multi-tenant organization configs -----------------------------------
    org_config_path: Path = Field(
        default=REPO_ROOT / ".orgs",
        description=(
            "Directory holding org_configs.json. Created if absent, initialized "
            "with a default org if empty. `.orgs` rather than `.jobs` because "
            "that is where the API has been writing org GSC accounts since the "
            "feature shipped; one location, or an account added in the UI is "
            "invisible to the crawl that wants to use it."
        ),
    )

    # -- API authentication (ADR 0016) ---------------------------------------
    auth_session_secret: SecretStr | None = Field(
        default=None,
        description=(
            "HMAC-SHA256 signing key for session tokens (ADR 0016). Required in "
            "production (`model_post_init` refuses to boot without it). Left "
            "unset elsewhere, `Settings.session_secret` generates one random key "
            "per process and caches it, so a restart invalidates every "
            "outstanding session rather than trusting a default nobody chose."
        ),
    )
    auth_session_ttl_s: int = Field(
        default=43_200,
        gt=0,
        description=(
            "Session token lifetime in seconds (12h default). Short enough that "
            "deactivating an operator takes effect on a human timescale — the "
            "token is self-contained (ADR 0016 condition 6) and is not checked "
            "against the operator store again before this expiry — long enough "
            "that an operator is not asked to log in again mid-session."
        ),
    )
    auth_operator_store_path: Path = Field(
        default=REPO_ROOT / ".operators",
        description=(
            "Directory holding operators.json (ADR 0016). Created if absent. "
            "Never auto-seeded the way `.orgs` is: there is no safe default "
            "password, so an empty store stays empty until "
            "`scripts/create_operator.py` or `AUTH_BOOTSTRAP_OPERATOR_*` "
            "creates the first operator."
        ),
    )
    auth_bootstrap_operator_id: str | None = Field(
        default=None,
        description=(
            "If set alongside AUTH_BOOTSTRAP_OPERATOR_PASSWORD and the operator "
            "store is empty, create_app() seeds exactly one operator at "
            "startup — the only way to log in before any operator exists "
            "without leaving a network-reachable, unauthenticated "
            "operator-creation endpoint for the same problem to reappear on."
        ),
    )
    auth_bootstrap_operator_password: SecretStr | None = None
    auth_bootstrap_operator_org_id: str = Field(
        default=DEFAULT_ORG_ID,
        description="Org the bootstrap operator belongs to. Defaults to 'default'.",
    )

    # -- Worker daemon dispatch (ADR 0015) ------------------------------------
    worker_store_backend: WorkerStoreBackend = Field(
        default=WorkerStoreBackend.DISK,
        description=(
            "Where registered desktop workers live. 'disk' is workers.json "
            "under WORKER_STORE_PATH — correct for the ADR 0004 local "
            "workstation. 'postgres' is the `workers` table from alembic "
            "revision 003 and is REQUIRED on any container host: a "
            "container filesystem is rebuilt on every deploy, so 'disk' "
            "there destroys every registration on every redeploy. Switching "
            "to 'postgres' requires re-registering each worker once; there "
            "is no data migration, because the file it would have read is "
            "already gone (see the 0003 migration's docstring)."
        ),
    )
    worker_store_path: Path = Field(
        default=REPO_ROOT / ".workers",
        description=(
            "Directory holding workers.json, used when WORKER_STORE_BACKEND "
            "is 'disk'. Same single-process caveat as "
            "`auth_operator_store_path`."
        ),
    )
    worker_offline_after_s: float = Field(
        default=60.0,
        gt=0.0,
        description=(
            "How long after a worker's last poll or heartbeat the dashboard "
            "should call it offline, and after which a dispatch confirm is "
            "refused rather than queued into a void. Four times the default "
            "WORKER_POLL_INTERVAL_S, so one dropped poll (or one slow "
            "retry) does not flip a healthy desktop offline; raise this in "
            "step with the poll interval, never below it."
        ),
    )
    worker_dispatch_timeout_s: float = Field(
        default=10_800.0,
        gt=0.0,
        description=(
            "How long a job may sit in DISPATCHED before it is swept to "
            "FAILED. A daemon that dies after claiming a job would "
            "otherwise leave it DISPATCHED forever, and its own single-use "
            "ledger stops it re-running. Default is "
            "SCREAMING_FROG_MAX_RUNTIME_S (7200s) plus an hour of upload "
            "and retry slack, so a legitimately long crawl is never swept "
            "out from under itself."
        ),
    )
    worker_dispatch_signing_secret: SecretStr | None = Field(
        default=None,
        description=(
            "HMAC-SHA256 key shared by the cloud API and every worker "
            "daemon to sign/verify dispatch assignment artifacts (ADR 0015 "
            "conditions 3(b) and 4). Required in production. Unset "
            "elsewhere generates one random per-process key, matching "
            "`auth_session_secret`'s own posture — a restart invalidates "
            "any artifact minted before it."
        ),
    )
    worker_bundle_encryption_secret: SecretStr | None = Field(
        default=None,
        description=(
            "Symmetric key for at-rest encryption of uploaded Screaming "
            "Frog bundles (ADR 0015 condition 11; see "
            "`src.core.worker_bundle_crypto`). Required in production."
        ),
    )
    worker_dispatch_assignment_ttl_s: float = Field(
        default=300.0,
        gt=0.0,
        description=(
            "How long a signed dispatch assignment (ADR 0015 condition "
            "3(b)) stays valid after a worker claims a job — long enough "
            "to receive the poll response and start the tool, short enough "
            "to bound a leaked artifact's replay window."
        ),
    )
    worker_dispatch_preview_ttl_s: float = Field(
        default=120.0,
        gt=0.0,
        description="Cloud-side gate (a) preview token lifetime (ADR 0015 condition 3(a)).",
    )
    worker_id: str | None = Field(
        default=None,
        description=(
            "This desktop worker's own registered identity (ADR 0015 "
            "condition 2). Set on the worker daemon's own machine, never "
            "on the cloud API process."
        ),
    )
    worker_org_id: str | None = Field(
        default=None,
        description=(
            "This worker's own org, provisioned out of band alongside "
            "worker_id/worker_credential when the worker was registered. "
            "Verified independently against a claimed dispatch assignment's "
            "`org_id` (condition 3(b)) so the worker's identity-binding "
            "check does not rely solely on a value the cloud process "
            "itself asserts — defense in depth against condition 4's own "
            "named limit (signing does not defend a compromised signer)."
        ),
    )
    worker_credential: SecretStr | None = Field(
        default=None,
        description=(
            "This worker's long-lived bearer credential, minted once by "
            "`POST /workers` and provisioned here out of band (ADR 0015 "
            "condition 2). Read only by the worker daemon, never by the "
            "cloud API, which stores only a hash."
        ),
    )
    worker_cloud_api_base_url: str | None = Field(
        default=None,
        description="Base URL of the cloud API this worker daemon polls, e.g. https://api.example.com.",
    )
    worker_poll_interval_s: float = Field(
        default=15.0,
        gt=0.0,
        description=(
            "Steady-state delay between poll calls when idle (ADR 0015 "
            "§2's own '10-15s while idle' example). Bounded exponential "
            "backoff (condition 10) grows this on a poll/dispatch/upload "
            "failure; this is the floor it resets to on success."
        ),
    )
    worker_poll_max_backoff_s: float = Field(
        default=300.0,
        gt=0.0,
        description="Ceiling for condition 10's bounded exponential backoff on repeated failures.",
    )
    worker_upload_max_bytes: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
        description=(
            "Size cap on one uploaded bundle (ADR 0015 condition 9), 100 MB "
            "by default. Enforced on the server before the body is buffered "
            "— a declared Content-Length over the cap is refused outright, "
            "and a chunked body is abandoned the moment it crosses it — and "
            "again on the worker before it ever starts the upload."
        ),
    )
    worker_bundle_retention_days: int = Field(
        default=30,
        ge=1,
        description="Automatic-expiry retention window for uploaded bundles (ADR 0015 §11).",
    )
    worker_consumed_jobs_path: Path = Field(
        default=REPO_ROOT / ".worker_consumed_jobs.json",
        description=(
            "The worker daemon's own local record of job ids it has already "
            "run, checked before honouring a dispatch assignment a second "
            "time — the worker-side half of ADR 0015 Step 5 answer 4's "
            "idempotency requirement, and part of what makes gate (b) "
            "(condition 3(b)) 'single-use' in practice across a daemon "
            "restart, not merely within one process's lifetime."
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
        if self.environment is Environment.PRODUCTION:
            if not self.guardrails_enabled:
                msg = "GUARDRAILS_ENABLED=false is not permitted in production."
                raise ConfigurationError(msg)
            # Enforce that policy overrides cannot loosen WRITE and FINANCIAL approvals
            if not self.require_approval_for_writes:
                msg = (
                    "REQUIRE_APPROVAL_FOR_WRITES=false is not permitted in production. "
                    "Policy overrides cannot loosen WRITE guardrails (CLAUDE.md §7 ruling 10)."
                )
                raise ConfigurationError(msg)
            if not self.require_approval_for_spend:
                msg = (
                    "REQUIRE_APPROVAL_FOR_SPEND=false is not permitted in production. "
                    "Policy overrides cannot loosen FINANCIAL guardrails (CLAUDE.md §7 ruling 10)."
                )
                raise ConfigurationError(msg)
            if self.auth_session_secret is None:
                msg = (
                    "AUTH_SESSION_SECRET must be set in production (ADR 0016). A "
                    "process-local random key is permitted only outside production, "
                    "where invalidating every session on restart is an acceptable cost."
                )
                raise ConfigurationError(msg)
            if self.worker_dispatch_signing_secret is None:
                msg = (
                    "WORKER_DISPATCH_SIGNING_SECRET must be set in production (ADR "
                    "0015 condition 4). A process-local random key is permitted only "
                    "outside production, where invalidating outstanding dispatch "
                    "assignments on restart is an acceptable cost."
                )
                raise ConfigurationError(msg)
            if self.worker_bundle_encryption_secret is None:
                msg = (
                    "WORKER_BUNDLE_ENCRYPTION_SECRET must be set in production (ADR "
                    "0015 condition 11). A process-local random key is permitted only "
                    "outside production, where uploaded bundles becoming unreadable "
                    "across a restart is an acceptable cost."
                )
                raise ConfigurationError(msg)
        self._org_config_store: OrgConfigStore | None = None
        self._operator_store: OperatorStore | None = None
        self._worker_store: WorkerStore | None = None
        self._session_secret: SecretStr | None = None
        self._dispatch_signing_secret: SecretStr | None = None
        self._bundle_encryption_secret: SecretStr | None = None

    def gsc_account_names(self) -> tuple[str, ...]:
        """Profile names from `.env.local` only, sorted. Names, never secrets.

        Kept Settings-only on purpose: it answers "what does the environment
        declare". What a *crawl* may select is the wider question answered by
        `gsc_account_names_for_org`.
        """
        return tuple(sorted(self.gsc_accounts))

    def _org_gsc_accounts(
        self,
        org_id: str | None,
        org_store: OrgConfigStore | None,
    ) -> dict[str, GscAccountCredential]:
        """The org's stored GSC accounts, or empty if the org or store is absent.

        Fail-soft by design. An unreadable or missing org store means "this
        deployment has no org-level accounts", which degrades to the `.env.local`
        profiles that predate them — never to an exception on a path whose real
        job is to resolve a credential.

        Args:
            org_id: Organization to read. `None` means `DEFAULT_ORG_ID`.
            org_store: Store to read. `None` means `self.org_config_store`.
        """
        try:
            store = org_store if org_store is not None else self.org_config_store
            return dict(store.get(org_id or DEFAULT_ORG_ID).gsc_accounts)
        except (KeyError, OSError, ValueError):
            # Unknown org, unreadable file, unparseable contents. Named rather
            # than a bare `except`, so a bug in the store still surfaces. Not
            # logged: `logger` imports this module, so this one cannot log
            # without a cycle — the caller reports the outcome instead, as
            # "Unknown GSC account" or a list that omits the org's entries.
            return {}

    def gsc_account_names_for_org(
        self,
        org_id: str | None = None,
        *,
        org_store: OrgConfigStore | None = None,
    ) -> tuple[str, ...]:
        """Every profile name a crawl in this org may select, sorted.

        The union of the org store and `.env.local`, because both are real
        sources and a picker that showed only one would hide accounts the engine
        will happily accept. Names only, as with `gsc_account_names`.

        Args:
            org_id: Organization to read. `None` means `DEFAULT_ORG_ID`.
            org_store: Store to read. `None` means `self.org_config_store`.
        """
        org_names = self._org_gsc_accounts(org_id, org_store)
        return tuple(sorted(set(org_names) | set(self.gsc_accounts)))

    def resolve_gsc_account(
        self,
        name: str | None,
        *,
        org_id: str | None = None,
        org_store: OrgConfigStore | None = None,
    ) -> ResolvedGscCredentials:
        """Produce the credential triple for a profile, or for the default.

        Deliberately the only place the inheritance rule lives, so the token
        manager and any future Google connector agree on what "default" means.

        Two sources hold profiles: the org store, written by the API when an
        operator adds an account in the UI, and the `.env.local` table that
        predates it. The org store is consulted first — an operator who re-enters
        an account in the UI means the credential they just typed, not the stale
        one in the file — and `.env.local` answers every name the org does not
        carry, so accounts that only ever existed there keep working untouched.

        Args:
            name: A profile name, or `None` for the flat `GOOGLE_OAUTH_*` triple.
                `None` never consults the org store; the flat triple is an
                environment fact with no org dimension.
            org_id: Organization whose stored accounts to search. `None` means
                `DEFAULT_ORG_ID`, which is the org the API uses for a request
                carrying no `X-Org-Id`.
            org_store: Store to read, for a caller that holds one already. `None`
                means `self.org_config_store`.

        Returns:
            Complete credentials with the account name attached.

        Raises:
            ConfigurationError: If the profile exists in neither source — no
                fallback to the default, because silently querying the wrong
                client's Search Console is worse than a failed crawl — or if
                whatever is selected is incomplete.
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
        org_accounts = self._org_gsc_accounts(org_id, org_store)
        # Both sources yield the same three optional/required fields, so one
        # inheritance rule covers both: the profile's own OAuth client if it
        # declared one, otherwise the shared GOOGLE_OAUTH_* client.
        profile: GscAccountCredential | GscAccountProfile | None = org_accounts.get(key)
        source = "org"
        if profile is None:
            profile = self.gsc_accounts.get(key)
            source = "env"
        if profile is None:
            known = (
                ", ".join(self.gsc_account_names_for_org(org_id, org_store=org_store))
                or "none configured"
            )
            msg = f"Unknown GSC account '{name}'. Configured accounts: {known}."
            raise ConfigurationError(msg)

        client_id = profile.client_id or self.google_oauth_client_id
        client_secret = profile.client_secret or self.google_oauth_client_secret
        if not client_id or client_secret is None:
            where = (
                f"add a client id and secret to account '{key}' for organization "
                f"'{org_id or DEFAULT_ORG_ID}'"
                if source == "org"
                else (
                    f"or GSC_ACCOUNTS__{key.upper()}__CLIENT_ID and "
                    f"GSC_ACCOUNTS__{key.upper()}__CLIENT_SECRET for this account"
                )
            )
            msg = (
                f"GSC account '{key}' has no OAuth client. Set GOOGLE_OAUTH_CLIENT_ID and "
                f"GOOGLE_OAUTH_CLIENT_SECRET (shared), {where}."
            )
            raise ConfigurationError(msg)
        return ResolvedGscCredentials(
            account=key,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=profile.refresh_token,
        )

    @property
    def org_config_store(self) -> OrgConfigStore:
        """Get the organization configuration store, creating it on first access.

        Returns:
            The `OrgConfigStore` for this deployment.
        """
        if self._org_config_store is None:
            from src.core.state_store import DiskOrgConfigStore

            self._org_config_store = DiskOrgConfigStore(self.org_config_path)
        return self._org_config_store

    @property
    def operator_store(self) -> OperatorStore:
        """Get the operator identity store, creating it on first access (ADR 0016).

        Returns:
            The `OperatorStore` for this deployment.
        """
        if self._operator_store is None:
            from src.core.auth import DiskOperatorStore

            self._operator_store = DiskOperatorStore(self.auth_operator_store_path)
        return self._operator_store

    @property
    def worker_store(self) -> WorkerStore:
        """Get the worker daemon identity store, creating it on first access (ADR 0015).

        The one place `worker_store_backend` is read. Deliberately not a
        try-Postgres-then-fall-back-to-disk arrangement: a silent fallback
        would answer `401 invalid worker credential` to a fleet of correctly
        configured daemons the moment Postgres hiccuped, which is precisely
        the confusing failure this setting was added to end.

        Returns:
            The `WorkerStore` for this deployment.
        """
        if self._worker_store is None:
            if self.worker_store_backend is WorkerStoreBackend.POSTGRES:
                from src.core.postgres_worker_store import PostgresWorkerStore

                self._worker_store = PostgresWorkerStore()
            else:
                from src.core.worker_auth import DiskWorkerStore

                self._worker_store = DiskWorkerStore(self.worker_store_path)
        return self._worker_store

    @property
    def dispatch_signing_secret(self) -> SecretStr:
        """The shared HMAC key for ADR 0015 dispatch assignment artifacts.

        Required in production (`model_post_init` already refuses to boot
        without one there). Elsewhere, generated once per process and
        cached, matching `session_secret`'s own reasoning exactly: every
        artifact a process issues (or, on the worker side, verifies) must
        stay checkable for as long as that process runs.
        """
        if self._dispatch_signing_secret is not None:
            return self._dispatch_signing_secret
        if self.worker_dispatch_signing_secret is not None:
            self._dispatch_signing_secret = self.worker_dispatch_signing_secret
            return self._dispatch_signing_secret
        if self.environment is Environment.PRODUCTION:
            msg = "WORKER_DISPATCH_SIGNING_SECRET must be set in production (ADR 0015)."
            raise ConfigurationError(msg)
        self._dispatch_signing_secret = SecretStr(secrets.token_hex(32))
        return self._dispatch_signing_secret

    @property
    def bundle_encryption_secret(self) -> SecretStr:
        """The symmetric key for ADR 0015 condition 11's at-rest encryption.

        Same generate-once-and-cache posture as `dispatch_signing_secret`.
        """
        if self._bundle_encryption_secret is not None:
            return self._bundle_encryption_secret
        if self.worker_bundle_encryption_secret is not None:
            self._bundle_encryption_secret = self.worker_bundle_encryption_secret
            return self._bundle_encryption_secret
        if self.environment is Environment.PRODUCTION:
            msg = "WORKER_BUNDLE_ENCRYPTION_SECRET must be set in production (ADR 0015)."
            raise ConfigurationError(msg)
        self._bundle_encryption_secret = SecretStr(secrets.token_hex(32))
        return self._bundle_encryption_secret

    @property
    def session_secret(self) -> SecretStr:
        """The HMAC signing key for ADR 0016 session tokens.

        Required in production (`model_post_init` already refuses to boot
        without one there). Elsewhere, an unset key is generated once per
        process and cached on this instance rather than regenerated per
        call — every token a process issues must stay verifiable by that same
        process for as long as it runs, and a fresh key per call would make
        the very first request's own token fail its own verification.

        Not logged here even on the generated path: `logger.py` imports this
        module (`get_settings`), so logging from here would be an import
        cycle — the same constraint `_org_gsc_accounts` documents above.
        """
        if self._session_secret is not None:
            return self._session_secret
        if self.auth_session_secret is not None:
            self._session_secret = self.auth_session_secret
            return self._session_secret
        if self.environment is Environment.PRODUCTION:
            # Reachable if `environment` is reassigned after construction —
            # `model_post_init` already refuses to boot in the normal path.
            msg = "AUTH_SESSION_SECRET must be set in production (ADR 0016)."
            raise ConfigurationError(msg)
        self._session_secret = SecretStr(secrets.token_hex(32))
        return self._session_secret

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
