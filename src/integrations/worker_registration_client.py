"""The three operator calls that turn a PC into a registered worker (ADR 0030).

`rankuno-worker setup` signs in once as an operator, fetches the cloud's public
dispatch verify key, and registers this machine. Those calls leave the machine,
so they go through `BaseAPIClient` (CLAUDE.md §1.5) rather than a bare `httpx`
call in the CLI — `WorkerCloudClient` cannot host them, because it
authenticates *as a worker* from `Settings`, and at setup time no worker exists
yet.

Two properties carried over from `scripts/register_worker.py` and Phase 1:

* **Verify key before registration.** `POST /api/v1/workers` mints a one-time
  credential the server never shows again. Fetching the key first means a
  cloud that cannot sign with Ed25519 stops setup before anything is minted.
* **Nothing from a response body reaches the operator.** Failures are named by
  HTTP status with a fixed hint; a server's raw error text is never echoed.

No step is retried. `WorkerRegistrationError` is not in `TRANSIENT_ERRORS`, and
`httpx` transport errors are not either, so `BaseAPIClient.call()` makes one
attempt — which matters for registration: retrying a `POST /workers` whose
response was lost would mint a second worker nobody holds the credential for.

The operator password is held as `SecretStr` and unwrapped only into the login
request body. It is never stored on this object, logged, or written anywhere.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from src.core.config import Settings
from src.core.errors import ConfigurationError, RankunoError
from src.core.schemas import StrictModel
from src.core.worker_dispatch_keys import DispatchVerifyKey
from src.integrations.base_client import BaseAPIClient
from src.integrations.worker_cloud_client import require_secure_base_url

__all__ = [
    "DEFAULT_CLOUD_URL",
    "VERIFY_KEY_PATH",
    "OperatorSession",
    "WorkerRegistration",
    "WorkerRegistrationClient",
    "WorkerRegistrationError",
]

DEFAULT_CLOUD_URL = "https://rankuno-engine1-production.up.railway.app"
"""The production cloud, shared with `scripts/register_worker.py`."""

LOGIN_PATH = "/api/v1/auth/login"
VERIFY_KEY_PATH = "/api/v1/workers/dispatch-verify-key"
WORKERS_PATH = "/api/v1/workers"

_TIMEOUT_S = 15.0

_STATUS_HINTS = {
    401: "the server did not accept the operator ID or password.",
    403: "this operator is not allowed to register workers.",
    503: "the server is not ready for this; ask an administrator to check the API logs.",
}


class WorkerRegistrationError(RankunoError):
    """A setup call failed. The message is safe to show and names the next action."""


class OperatorSession(StrictModel):
    """A signed-in operator, for the duration of one setup run."""

    token: SecretStr
    org_id: str


class WorkerRegistration(StrictModel):
    """What `POST /api/v1/workers` returned: the new identity and its one-time secret."""

    worker_id: str
    org_id: str
    credential: SecretStr


def _failure(step: str, response: httpx.Response) -> WorkerRegistrationError:
    hint = _STATUS_HINTS.get(response.status_code, "ask an administrator to check the API logs.")
    return WorkerRegistrationError(f"{step} failed (HTTP {response.status_code}): {hint}")


class WorkerRegistrationClient(BaseAPIClient):
    """Operator sign-in, verify-key fetch and worker registration."""

    service_name = "rankuno.worker_registration"
    rate_limit_key = "worker.registration"
    requests_per_minute = 30

    def __init__(
        self,
        base_url: str,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Build the client against an operator-typed URL.

        Args:
            base_url: The Rankuno URL the operator entered.
            settings: Configuration override, primarily for tests.
            transport: `httpx.MockTransport` in tests.

        Raises:
            ConfigurationError: `base_url` is not `https://` (loopback
                `http://` excepted) — the password travels on this connection.
        """
        super().__init__(settings=settings)
        require_secure_base_url(base_url, setting_name="The Rankuno URL")
        self._client = httpx.Client(base_url=base_url, timeout=_TIMEOUT_S, transport=transport)

    def authenticate(self) -> None:
        """Nothing to do: the operator's password is supplied per `login` call.

        Deliberately not read from `Settings` — the packaged worker must never
        hold an operator password anywhere a later process could find it.
        """

    def login(self, operator_id: str, password: SecretStr) -> OperatorSession:
        """Sign in as an operator. One attempt; a wrong password is not transient."""

        def _do() -> OperatorSession:
            response = self._client.post(
                LOGIN_PATH,
                json={"operator_id": operator_id, "password": password.get_secret_value()},
            )
            if response.status_code != 200:
                raise _failure("Sign-in", response)
            body: dict[str, Any] = response.json()
            token = body.get("token")
            if not token:
                raise WorkerRegistrationError("Sign-in failed: the server returned no session.")
            return OperatorSession(token=SecretStr(str(token)), org_id=str(body.get("org_id", "")))

        return self.call("login", _do)

    def fetch_verify_key(self, session: OperatorSession) -> DispatchVerifyKey:
        """Fetch the cloud's Ed25519 public key and check it against its own `kid`."""

        def _do() -> DispatchVerifyKey:
            response = self._client.get(VERIFY_KEY_PATH, headers=_bearer(session))
            if response.status_code == 503:
                msg = (
                    "The Rankuno server does not sign crawl dispatches yet "
                    "(WORKER_DISPATCH_SIGNING_PRIVATE_KEY is not set there, ADR 0028). "
                    "Ask an administrator to configure it, then run setup again."
                )
                raise WorkerRegistrationError(msg)
            if response.status_code != 200:
                raise _failure("Fetching the dispatch verify key", response)
            body: dict[str, Any] = response.json()
            try:
                key = DispatchVerifyKey.from_base64(str(body.get("public_key", "")))
            except ConfigurationError as exc:
                msg = "The server returned a malformed dispatch verify key."
                raise WorkerRegistrationError(msg) from exc
            if body.get("kid") != key.kid:
                msg = "The server's dispatch verify key does not match its own key id."
                raise WorkerRegistrationError(msg)
            return key

        return self.call("fetch_verify_key", _do)

    def register_worker(self, session: OperatorSession, display_name: str) -> WorkerRegistration:
        """Register this machine. Never retried — see the module docstring."""

        def _do() -> WorkerRegistration:
            response = self._client.post(
                WORKERS_PATH, json={"display_name": display_name}, headers=_bearer(session)
            )
            if response.status_code != 201:
                raise _failure("Worker registration", response)
            body: dict[str, Any] = response.json()
            try:
                return WorkerRegistration(
                    worker_id=str(body["worker_id"]),
                    org_id=str(body.get("org_id") or session.org_id),
                    credential=SecretStr(str(body["worker_secret"])),
                )
            except KeyError as exc:
                msg = "Worker registration returned an incomplete response."
                raise WorkerRegistrationError(msg) from exc

        return self.call("register_worker", _do)

    def close(self) -> None:
        """Release the connection pool."""
        self._client.close()

    def __enter__(self) -> WorkerRegistrationClient:
        """Support `with WorkerRegistrationClient(url) as client: ...`."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close on exit, success or failure alike."""
        self.close()


def _bearer(session: OperatorSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {session.token.get_secret_value()}"}
