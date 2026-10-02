"""`rankuno-worker setup`: sign in once, and this PC is a worker (ADR 0030).

The packaged worker is for teammates who will never clone the repository or
edit a `.env` file. Setup asks four questions — Rankuno URL, operator ID,
password, a name for this PC — and does the rest:

1. Checks the credential store is usable *before* any network call, so a
   machine that cannot hold a credential never mints one.
2. Signs in, fetches the cloud's public verify key, then registers — key
   first, so a cloud that cannot sign with Ed25519 stops setup before a
   one-time credential exists (ADR 0028's ordering).
3. Puts the worker credential in Windows Credential Manager, then writes the
   **non-secret** configuration (URL, worker id, org id, verify key) to
   `worker.env` in the worker's profile directory.

The operator password is read with `getpass`, held as `SecretStr`, sent once
in the login body, and dropped. It is never logged, echoed or written. Setup on
a machine that is already configured asks before replacing anything, and tells
the operator to revoke the old registration — this client cannot, because
revoking is an administrator action in the dashboard (ADR 0029).
"""

from __future__ import annotations

import os
import platform
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from getpass import getpass
from pathlib import Path

from pydantic import SecretStr

from src.core.app_paths import WORKER_CONFIG_FILENAME, ensure_private_dir
from src.core.credential_vault import (
    CredentialVault,
    CredentialVaultError,
    worker_credential_target,
)
from src.core.errors import ConfigurationError, IntegrationError
from src.core.logger import get_logger
from src.integrations.worker_cloud_client import require_secure_base_url
from src.integrations.worker_registration_client import (
    DEFAULT_CLOUD_URL,
    WorkerRegistrationClient,
    WorkerRegistrationError,
)

__all__ = ["SetupConsole", "normalise_cloud_url", "read_configured_worker_id", "run_setup"]

_logger = get_logger(__name__)


def _say(message: str) -> None:
    print(message)  # noqa: T201 - an interactive CLI talking to its operator


@dataclass
class SetupConsole:
    """The operator's terminal. Injectable so tests answer the prompts."""

    ask: Callable[[str], str] = input
    ask_secret: Callable[[str], str] = getpass
    say: Callable[[str], None] = field(default=_say)


def normalise_cloud_url(raw: str) -> str:
    """Trim, default to `https://` for a bare host, and drop a trailing slash."""
    url = raw.strip().rstrip("/") or DEFAULT_CLOUD_URL
    return url if "://" in url else f"https://{url}"


def read_configured_worker_id(config_file: Path) -> str | None:
    """The `WORKER_ID` already in `config_file`, or `None` when unconfigured."""
    if not config_file.is_file():
        return None
    for line in config_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "WORKER_ID":
            return value.strip() or None
    return None


def _write_config(config_file: Path, values: dict[str, str], kid: str) -> None:
    """Atomically replace `config_file`, so a crash leaves the old one or the new one."""
    ensure_private_dir(config_file.parent)
    lines = [
        "# Rankuno worker configuration, written by `rankuno-worker setup`.",
        "# Contains no secret: the worker credential is in Windows Credential Manager.",
        f"# Dispatch verify key id: {kid}",
        *(f"{key}={value}" for key, value in values.items()),
    ]
    fd, tmp = tempfile.mkstemp(dir=config_file.parent, prefix=".worker.env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        Path(tmp).replace(config_file)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _safe_reason(exc: IntegrationError) -> str:
    """A setup failure's operator-facing text: our own message, or the error type."""
    cause = exc.__cause__
    if isinstance(cause, WorkerRegistrationError):
        return str(cause)
    return f"Could not reach the Rankuno server ({type(cause or exc).__name__})."


def run_setup(
    root: Path,
    *,
    console: SetupConsole,
    vault_factory: Callable[[], CredentialVault],
    client_factory: Callable[[str], WorkerRegistrationClient] = WorkerRegistrationClient,
) -> bool:
    """Interactively register this PC and store its configuration under `root`.

    Args:
        root: The worker's data directory (`config.user_data_root()`).
        console: Prompts and output.
        vault_factory: The credential store; called first, before any prompt.
        client_factory: Builds the registration client for the entered URL.

    Returns:
        `True` when this PC is now configured; `False` when setup stopped,
        with the reason already shown to the operator.
    """
    config_file = root / WORKER_CONFIG_FILENAME
    try:
        vault = vault_factory()
    except CredentialVaultError as exc:
        console.say(str(exc))
        return False

    previous_worker = read_configured_worker_id(config_file)
    if previous_worker is not None:
        answer = console.ask(
            f"This PC is already set up as worker '{previous_worker}'. "
            "Replace it with a new registration? [y/N]: "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            console.say("Setup cancelled; the existing configuration is unchanged.")
            return False

    url = normalise_cloud_url(console.ask(f"Rankuno URL [{DEFAULT_CLOUD_URL}]: "))
    try:
        # Before the password prompt: it must never be typed for an http:// URL.
        require_secure_base_url(url, setting_name="The Rankuno URL")
    except ConfigurationError as exc:
        console.say(str(exc))
        return False
    operator_id = console.ask("Operator ID: ").strip()
    password = SecretStr(console.ask_secret("Password: "))
    default_name = platform.node() or "Rankuno worker"
    display_name = console.ask(f"Name for this PC [{default_name}]: ").strip() or default_name
    if not operator_id or not password.get_secret_value():
        console.say("Operator ID and password are both required.")
        return False

    try:
        with client_factory(url) as client:
            session = client.login(operator_id, password)
            verify_key = client.fetch_verify_key(session)
            registration = client.register_worker(session, display_name)
    except ConfigurationError as exc:
        console.say(str(exc))
        return False
    except IntegrationError as exc:
        console.say(_safe_reason(exc))
        return False

    try:
        vault.write(
            worker_credential_target(registration.worker_id),
            username=registration.worker_id,
            secret=registration.credential,
        )
    except CredentialVaultError as exc:
        console.say(
            f"{exc} Worker '{registration.worker_id}' was registered but its credential "
            "could not be saved; ask an administrator to revoke it, then run setup again."
        )
        return False

    _write_config(
        config_file,
        {
            "WORKER_CLOUD_API_BASE_URL": url,
            "WORKER_ID": registration.worker_id,
            "WORKER_ORG_ID": registration.org_id,
            "WORKER_DISPATCH_VERIFY_KEY": verify_key.public_key_b64,
        },
        verify_key.kid,
    )
    if previous_worker is not None and previous_worker != registration.worker_id:
        vault.delete(worker_credential_target(previous_worker))
        console.say(
            f"Ask an administrator to revoke the old worker '{previous_worker}' in the dashboard."
        )
    _logger.info(
        "worker_setup_completed",
        extra={"worker_id": registration.worker_id, "org": registration.org_id},
    )
    console.say(f"This PC is registered as worker '{registration.worker_id}'.")
    return True
