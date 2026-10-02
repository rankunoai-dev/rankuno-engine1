"""The worker credential lives in Windows Credential Manager, not a file (ADR 0030).

A checkout keeps `WORKER_CREDENTIAL` in `.env.local`, readable by anything that
can read the repository. The packaged worker runs on a teammate's own PC, where
a plaintext file in the profile is one backup, sync client or support zip away
from leaking a long-lived bearer secret. Credential Manager stores it encrypted
under the user's DPAPI key, per user and per machine, and is what Windows
itself uses for the same job.

Precedence, in one place (`resolve_worker_credential`):

1. **Packaged (frozen):** Credential Manager only, under
   `Rankuno Worker/<worker_id>`. `WORKER_CREDENTIAL` in any env file is
   ignored, with a warning, so a plaintext copy can never quietly win. Off
   Windows this is an error, never a fallback.
2. **Checkout with `WORKER_CREDENTIAL_STORE=credential_manager`:** Credential
   Manager first; `WORKER_CREDENTIAL` only if the vault has no entry.
3. **Checkout, default:** `WORKER_CREDENTIAL`, exactly as before.

Why pywin32's `win32cred` and not the `keyring` package: pywin32 is already the
worker's Windows dependency (process supervision), `keyring` is a new
dependency whose backend is chosen at runtime by entry points — awkward to
freeze and, on a misconfigured machine, able to fall back to a less safe store
without saying so. Every real `win32cred` call is in `WindowsCredentialVault`;
everything else depends on the `CredentialVault` protocol, so tests use an
in-memory fake.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from src.core.app_paths import is_frozen
from src.core.config import Settings, WorkerCredentialStore
from src.core.errors import ConfigurationError
from src.core.logger import get_logger

__all__ = [
    "CredentialVault",
    "CredentialVaultError",
    "WindowsCredentialVault",
    "default_vault",
    "effective_credential_store",
    "resolve_worker_credential",
    "worker_credential_target",
]

_logger = get_logger(__name__)

_TARGET_PREFIX = "Rankuno Worker/"
_ERROR_NOT_FOUND = 1168
"""`ERROR_NOT_FOUND`: `CredRead`/`CredDelete` on a target that has no entry."""


class CredentialVaultError(ConfigurationError):
    """The OS credential store refused, or is not available on this platform.

    A `ConfigurationError` so the worker CLI reports it with its
    "a human must fix something" exit code rather than restarting.
    """


class CredentialVault(Protocol):
    """A per-user secret store addressed by target name."""

    def read(self, target: str) -> SecretStr | None:
        """The stored secret, or `None` when `target` has no entry."""
        ...

    def write(self, target: str, *, username: str, secret: SecretStr) -> None:
        """Create or replace `target`."""
        ...

    def delete(self, target: str) -> None:
        """Remove `target`. Deleting an absent entry is not an error."""
        ...


def worker_credential_target(worker_id: str) -> str:
    """The Credential Manager target name for one worker identity.

    Keyed by worker id so re-running setup cannot overwrite the credential of
    a worker that is still registered, and so the entry is recognisable to an
    operator browsing Credential Manager.
    """
    return f"{_TARGET_PREFIX}{worker_id}"


class WindowsCredentialVault:
    """Windows Credential Manager via pywin32. The only `win32cred` caller.

    Generic credentials, `CRED_PERSIST_LOCAL_MACHINE`: survives logoff and
    reboot, stays on this machine for this user, never roams with the profile.
    pywin32 is imported per call, matching `_win32_bindings.load_win32()`, so
    importing this module never requires Windows.
    """

    @staticmethod
    def _modules() -> tuple[Any, Any]:
        try:
            import pywintypes
            import win32cred
        except ImportError as exc:  # pragma: no cover - only where pywin32 is absent
            msg = (
                "pywin32 is required to store the worker credential in Windows "
                'Credential Manager; install with `pip install -e ".[pywin32]"`.'
            )
            raise CredentialVaultError(msg) from exc
        return win32cred, pywintypes

    def read(self, target: str) -> SecretStr | None:
        """Read `target`, decoding the UTF-16-LE blob pywin32 stores."""
        win32cred, pywintypes = self._modules()
        try:
            entry = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC)
        except pywintypes.error as exc:
            if exc.winerror == _ERROR_NOT_FOUND:
                return None
            raise CredentialVaultError(_os_error("read", exc.winerror)) from exc
        blob: bytes = entry["CredentialBlob"]
        return SecretStr(blob.decode("utf-16-le"))

    def write(self, target: str, *, username: str, secret: SecretStr) -> None:
        """Create or replace `target`. pywin32 accepts the blob only as `str`."""
        win32cred, pywintypes = self._modules()
        credential = {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": username,
            "CredentialBlob": secret.get_secret_value(),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }
        try:
            win32cred.CredWrite(credential, 0)
        except pywintypes.error as exc:
            raise CredentialVaultError(_os_error("write", exc.winerror)) from exc

    def delete(self, target: str) -> None:
        """Remove `target`; an absent entry is already the desired state."""
        win32cred, pywintypes = self._modules()
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC)
        except pywintypes.error as exc:
            if exc.winerror != _ERROR_NOT_FOUND:
                raise CredentialVaultError(_os_error("delete", exc.winerror)) from exc


def _os_error(operation: str, code: int) -> str:
    """Name the failure by Windows error code only — never by target content."""
    return f"Windows Credential Manager could not {operation} the worker credential (error {code})."


def default_vault() -> CredentialVault:
    """The platform credential store.

    Raises:
        CredentialVaultError: Not Windows. There is deliberately no plaintext
            fallback: a packaged worker that cannot protect its credential
            must stop, not degrade.
    """
    if sys.platform != "win32":
        msg = (
            "The packaged Rankuno worker stores its credential in Windows "
            "Credential Manager and runs on Windows only."
        )
        raise CredentialVaultError(msg)
    return WindowsCredentialVault()


def effective_credential_store(settings: Settings, *, frozen: bool) -> WorkerCredentialStore:
    """Credential Manager when packaged, otherwise whatever a checkout configured."""
    if frozen:
        return WorkerCredentialStore.CREDENTIAL_MANAGER
    return settings.worker_credential_store or WorkerCredentialStore.ENV


def resolve_worker_credential(
    settings: Settings,
    *,
    vault_factory: Callable[[], CredentialVault] = default_vault,
    frozen: bool | None = None,
) -> SecretStr | None:
    """The worker credential under the precedence in the module docstring.

    Args:
        settings: Supplies `worker_id` (the vault key) and the env value.
        vault_factory: Builds the vault, only when one is needed — so a
            checkout on the default path never touches Credential Manager.
        frozen: Defaults to `app_paths.is_frozen()`; explicit for tests.

    Returns:
        The credential, or `None` when none is available — which the CLI
        reports as `WORKER_CREDENTIAL` missing.

    Raises:
        CredentialVaultError: The vault was needed and could not be used.
    """
    frozen = is_frozen() if frozen is None else frozen
    if effective_credential_store(settings, frozen=frozen) is WorkerCredentialStore.ENV:
        return settings.worker_credential
    if frozen and settings.worker_credential is not None:
        _logger.warning(
            "worker_credential_env_ignored",
            extra={"reason": "packaged worker reads Windows Credential Manager only"},
        )
    if settings.worker_id is None:
        return None
    secret = vault_factory().read(worker_credential_target(settings.worker_id))
    if secret is not None or frozen:
        return secret
    return settings.worker_credential
