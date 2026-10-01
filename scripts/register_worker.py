"""Interactively register this PC as a worker daemon and write `.env.local`.

Connects to the API (local or cloud on Railway), logs in as an operator, fetches
the cloud's public dispatch verify key, registers a new worker for your
organization, and writes `.env.local` so `run_worker_daemon.py` /
`rankuno-worker` can start immediately.

No signing secret is ever requested or written (ADR 0028). The worker receives
only the cloud's Ed25519 *public* key, which can verify a dispatch but never
create one, so a copied `.env.local` no longer lets anyone forge jobs. The only
secret written is this worker's own credential.

The cloud URL must be `https://`; plain `http://` is accepted only for
localhost / 127.0.0.1 / ::1, because the operator password and the worker
credential both travel over this connection. Error responses are reported by
status code only — a server's raw error body is never echoed to the terminal.

Usage:
    python scripts/register_worker.py
"""

from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path
from typing import Any

# Make `src` importable when this script is run from repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from src.core.errors import ConfigurationError  # noqa: E402
from src.core.worker_dispatch_keys import DispatchVerifyKey  # noqa: E402
from src.integrations.worker_cloud_client import require_secure_base_url  # noqa: E402

VERIFY_KEY_PATH = "/api/v1/workers/dispatch-verify-key"

_STATUS_HINTS = {
    401: "the server did not accept the credentials or session.",
    403: "this operator is not allowed to do that.",
    503: "the server is not ready for this (see the message above, or the API logs).",
}


class RegistrationError(Exception):
    """A step failed; the message is safe to print and names the next action."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="register_worker",
        description="Register this PC as a Screaming Frog worker daemon and generate .env.local.",
    )
    parser.add_argument(
        "--cloud-url",
        default="https://rankuno-engine1-production.up.railway.app",
        help="Base URL of the Rankuno API server (default: https://rankuno-engine1-production.up.railway.app)",
    )
    parser.add_argument(
        "--display-name",
        default="My Windows PC",
        help="Display name for this worker (default: 'My Windows PC')",
    )
    return parser


def _fail(step: str, response: httpx.Response) -> RegistrationError:
    """Describe a failed response by status only — never by its body."""
    hint = _STATUS_HINTS.get(response.status_code, "see the API server logs for details.")
    return RegistrationError(f"{step} failed (HTTP {response.status_code}): {hint}")


def _fetch_verify_key(client: httpx.Client, cloud_url: str, headers: dict[str, str]) -> str:
    """Fetch the cloud's public verify key and check it against its own `kid`."""
    resp = client.get(f"{cloud_url}{VERIFY_KEY_PATH}", headers=headers)
    if resp.status_code == 503:
        msg = (
            "The cloud API does not sign dispatches with Ed25519 yet "
            "(WORKER_DISPATCH_SIGNING_PRIVATE_KEY is not set there, ADR 0028). "
            "Ask the operator to configure it, then run this again."
        )
        raise RegistrationError(msg)
    if resp.status_code != 200:
        raise _fail("Fetching the dispatch verify key", resp)
    body: dict[str, Any] = resp.json()
    try:
        key = DispatchVerifyKey.from_base64(str(body.get("public_key", "")))
    except ConfigurationError as exc:
        raise RegistrationError("The server returned a malformed dispatch verify key.") from exc
    if body.get("kid") != key.kid:
        raise RegistrationError("The server's verify key does not match its own key id.")
    print(f"Fetched dispatch verify key (kid {key.kid}).")
    return key.public_key_b64


def _register(
    cloud_url: str, display_name: str, transport: httpx.BaseTransport | None
) -> dict[str, str]:
    operator_id = input("Operator ID (e.g. admin or alice): ").strip()
    if not operator_id:
        raise RegistrationError("Operator ID is required.")
    password = getpass("Operator Password: ")
    if not password:
        raise RegistrationError("Password is required.")

    print(f"\nLogging in to {cloud_url}...")
    with httpx.Client(timeout=15.0, transport=transport) as client:
        resp = client.post(
            f"{cloud_url}/api/v1/auth/login",
            json={"operator_id": operator_id, "password": password},
        )
        if resp.status_code != 200:
            raise _fail("Login", resp)
        login_data: dict[str, Any] = resp.json()
        token = login_data.get("token")
        org_id = str(login_data.get("org_id", "default"))
        if not token:
            raise RegistrationError("Server returned an empty session token.")
        print(f"Logged in successfully as '{operator_id}' for org '{org_id}'.")
        headers = {"Authorization": f"Bearer {token}"}

        # Before registering: a worker whose one-time credential was issued
        # but never written anywhere is an orphan nobody can use.
        verify_key = _fetch_verify_key(client, cloud_url, headers)

        print(f"Registering worker '{display_name}'...")
        reg_resp = client.post(
            f"{cloud_url}/api/v1/workers", json={"display_name": display_name}, headers=headers
        )
        if reg_resp.status_code != 201:
            raise _fail("Worker registration", reg_resp)
        reg_data: dict[str, Any] = reg_resp.json()
        print(f"Worker registered! ID: {reg_data['worker_id']}")
        return {
            "WORKER_CLOUD_API_BASE_URL": cloud_url,
            "WORKER_ID": str(reg_data["worker_id"]),
            "WORKER_ORG_ID": str(reg_data.get("org_id", org_id)),
            "WORKER_CREDENTIAL": str(reg_data["worker_secret"]),
            "WORKER_DISPATCH_VERIFY_KEY": verify_key,
        }


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    env_path: Path | None = None,
) -> int:
    args = build_parser().parse_args(argv)

    cloud_url = args.cloud_url.rstrip("/")
    if "://" not in cloud_url:
        cloud_url = f"https://{cloud_url}"
    try:
        require_secure_base_url(cloud_url, setting_name="--cloud-url")
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("=== Rankuno Worker Registration ===")
    print(f"Connecting to: {cloud_url}\n")
    try:
        values = _register(cloud_url, args.display_name, transport)
    except RegistrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(
            f"Could not complete registration with {cloud_url} ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    target = env_path or REPO_ROOT / ".env.local"
    lines = ["# Rankuno Worker Configuration", *(f"{k}={v}" for k, v in values.items())]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote configuration to: {target}")
    print("\n=== SUCCESS ===")
    print("Your PC is now registered and configured!")
    print("You can now start the daemon anytime by running:")
    print("  python scripts/run_worker_daemon.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
