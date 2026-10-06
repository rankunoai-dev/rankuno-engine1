"""The import CLI's one outbound connection: sign in, then upload a bundle (ADR 0034).

A `BaseAPIClient` like every other connector (CLAUDE.md §1.5), so the upload
gets the standard rate limit, retry and audit logging. It has its own quota key:
it shares nothing with the worker daemon's channel, and a burst of imports must
not starve a worker's polling.

What this client will not do
----------------------------
* **Follow a redirect.** `follow_redirects=False`, and any 3xx is a hard
  error. A redirect is the one way an https endpoint could silently hand the
  operator's password, or a bundle, to a different host.
* **Talk plain http to anything but loopback.** `require_secure_base_url`.
* **Keep a credential.** The password is passed straight to the login call
  and never stored; the session token lives on this object only, and `close()`
  drops it. Nothing here writes either anywhere, logs them, or puts them in
  an exception message.
* **Retry a refusal.** Only transport failures, `429` and `5xx` are retried,
  and a retry resends the identical bytes, which the server answers as a
  duplicate if the first attempt actually landed.

`UrlSafetyPolicy` is not applied to the base URL, for the reason
`worker_cloud_client` gives: it is a single operator-provisioned endpoint, not
crawl input.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import Settings
from src.core.errors import GuardrailViolationError, IntegrationError
from src.core.logger import get_logger
from src.integrations.base_client import BaseAPIClient
from src.integrations.worker_cloud_client import require_secure_base_url

__all__ = ["CloudImportRejectedError", "CloudImportResult", "RankunoCloudClient"]

_logger = get_logger("integrations.rankuno_cloud_client")

_TIMEOUT = httpx.Timeout(30.0, read=180.0)
"""Validating the largest local result took ~10 s on a workstation; leave room."""

_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


class CloudImportRejectedError(GuardrailViolationError):
    """The cloud refused the request, and retrying the same bytes will not help.

    A `GuardrailViolationError` for the reason `WorkerCredentialRejectedError`
    is one: `BaseAPIClient.call` passes those through unwrapped and
    `with_retries` does not treat them as transient. Anything else would be
    wrapped into an `IntegrationError` and retried.

    Attributes:
        status_code: The HTTP status, or 0 for a redirect refused locally.
        detail: The server's explanation, safe to show the operator.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        """Hold the refusal.

        Args:
            status_code: HTTP status.
            detail: Explanation for the operator.
        """
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class CloudImportResult:
    """What the cloud said about one import."""

    __slots__ = ("duplicate", "job_id", "label", "org_id", "pages", "status")

    def __init__(self, payload: dict[str, Any], org_id: str) -> None:
        """Read the response body.

        Args:
            payload: The `JobImportAccepted` JSON.
            org_id: The org the session authenticated for.
        """
        self.job_id = str(payload["id"])
        self.status = str(payload["status"])
        self.label = str(payload.get("label", ""))
        self.pages = int(payload.get("pages", 0))
        self.duplicate = bool(payload.get("duplicate", False))
        self.org_id = org_id


class RankunoCloudClient(BaseAPIClient):
    """Sign in to a Rankuno cloud API and import one job bundle."""

    service_name = "rankuno.cloud_import"
    rate_limit_key = "rankuno_cloud_import"
    requests_per_minute = 10
    """A CLI makes two calls per run. This only stops a runaway retry loop."""

    def __init__(
        self,
        base_url: str,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Build the client. Does not connect until first use.

        Args:
            base_url: The cloud API root, from `--cloud-url` or
                `Settings.cloud_import_base_url`.
            settings: Configuration override, primarily for tests.
            transport: Injectable transport (`httpx.MockTransport` in tests).

        Raises:
            ConfigurationError: Not https, and not http to a loopback host.
        """
        super().__init__(settings=settings)
        self.base_url = require_secure_base_url(base_url, setting_name="CLOUD_IMPORT_BASE_URL")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=_TIMEOUT,
            transport=transport,
            follow_redirects=False,
            verify=True,
        )
        self._token: str | None = None
        self.org_id: str | None = None

    def authenticate(self) -> None:
        """No stored credential exists to load; `login` is the only way in.

        Raises:
            CloudImportRejectedError: Always, if called before `login`.
        """
        if self._token is None:
            raise CloudImportRejectedError(401, "not signed in")

    def login(self, operator_id: str, password: str) -> str:
        """Exchange an operator id and password for a session token, kept in memory.

        Returns:
            The org the session belongs to.

        Raises:
            CloudImportRejectedError: Wrong credentials, or any other refusal.
            IntegrationError: The cloud could not be reached.
        """

        def _do() -> dict[str, Any]:
            response = self._send(
                "POST",
                "/api/v1/auth/login",
                json={"operator_id": operator_id, "password": password},
            )
            body: dict[str, Any] = response.json()
            return body

        body = self.call("login", _do)
        self._token = str(body["token"])
        self.org_id = str(body["org_id"])
        return self.org_id

    def import_bundle(self, bundle_gz: bytes) -> CloudImportResult:
        """Upload one gzip bundle. Retries resend these exact bytes.

        Raises:
            CloudImportRejectedError: The cloud refused it (409, 413, 415, 422 ...).
            IntegrationError: Still unreachable after retries.
        """
        self.authenticate()

        def _do() -> dict[str, Any]:
            response = self._send(
                "POST",
                "/api/v1/jobs/import",
                content=bundle_gz,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/gzip",
                },
            )
            body: dict[str, Any] = response.json()
            return body

        return CloudImportResult(self.call("import_bundle", _do), self.org_id or "")

    def close(self) -> None:
        """Drop the session token and close the connection pool."""
        self._token = None
        self._client.close()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:  # noqa: ANN401
        """One request, classified into success, retryable failure or refusal."""
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            # Class name only: an httpx message can quote the request.
            raise IntegrationError(self.service_name, type(exc).__name__) from None
        if response.is_redirect or 300 <= response.status_code < 400:
            msg = "the cloud answered with a redirect; refusing to follow it"
            raise CloudImportRejectedError(response.status_code, msg)
        if response.status_code in _RETRYABLE_STATUSES or response.status_code >= 500:
            raise IntegrationError(self.service_name, f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CloudImportRejectedError(response.status_code, _detail(response))
        return response


def _detail(response: httpx.Response) -> str:
    """The server's `detail`, flattened for a terminal. Never the request."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.reason_phrase or "request refused"
    if isinstance(detail, dict):
        locations = ", ".join(str(item) for item in detail.get("locations", []))
        count = detail.get("error_count", "?")
        return f"{detail.get('error', 'refused')} ({count} problem(s): {locations})"
    return str(detail) if detail else (response.reason_phrase or "request refused")
