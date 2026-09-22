"""Interactively register this PC as a worker daemon and write `.env.local`.

Connects to the API (local or cloud on Railway), logs in as an operator, registers
a new worker for your organization, and populates `.env.local` with the required
worker credentials so `run_worker_daemon.py` / `rankuno-worker` can start immediately.

Usage:
    python scripts/register_worker.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path

# Make `src` importable when this script is run from repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cloud_url = args.cloud_url.rstrip("/")
    if not cloud_url.startswith("http://") and not cloud_url.startswith("https://"):
        cloud_url = f"https://{cloud_url}"

    print(f"=== Rankuno Worker Registration ===")
    print(f"Connecting to: {cloud_url}\n")

    # Step 1: Prompt for operator login
    operator_id = input("Operator ID (e.g. admin or alice): ").strip()
    if not operator_id:
        print("Operator ID is required.", file=sys.stderr)
        return 1

    password = getpass("Operator Password: ")
    if not password:
        print("Password is required.", file=sys.stderr)
        return 1

    # Step 2: Log in to obtain session token
    login_url = f"{cloud_url}/api/v1/auth/login"
    print(f"\nLogging in to {cloud_url}...")

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(login_url, json={"operator_id": operator_id, "password": password})
            if resp.status_code != 200:
                print(f"Login failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
                return 1
            login_data = resp.json()
            token = login_data.get("token")
            org_id = login_data.get("org_id", "default")

            if not token:
                print("Server returned empty session token.", file=sys.stderr)
                return 1

            print(f"Logged in successfully as '{operator_id}' for org '{org_id}'.")

            # Step 3: Register worker
            register_url = f"{cloud_url}/api/v1/workers"
            headers = {"Authorization": f"Bearer {token}"}
            print(f"Registering worker '{args.display_name}'...")

            reg_resp = client.post(
                register_url,
                json={"display_name": args.display_name},
                headers=headers,
            )

            if reg_resp.status_code != 201:
                print(
                    f"Worker registration failed (HTTP {reg_resp.status_code}): {reg_resp.text}",
                    file=sys.stderr,
                )
                return 1

            reg_data = reg_resp.json()
            worker_id = reg_data["worker_id"]
            worker_secret = reg_data["worker_secret"]
            worker_org_id = reg_data.get("org_id", org_id)

            print(f"Worker registered! ID: {worker_id}")

    except Exception as exc:
        print(f"Network error connecting to {cloud_url}: {exc}", file=sys.stderr)
        return 1

    # Step 4: Prompt for signing secret
    print("\n--- Signing Secret Configuration ---")
    signing_secret = getpass(
        "Enter WORKER_DISPATCH_SIGNING_SECRET (same secret set in Railway variables): "
    ).strip()

    if not signing_secret:
        print("Signing secret cannot be empty.", file=sys.stderr)
        return 1

    # Step 5: Write to .env.local
    env_local_path = REPO_ROOT / ".env.local"
    env_content = (
        f"# Rankuno Worker Configuration\n"
        f"WORKER_CLOUD_API_BASE_URL={cloud_url}\n"
        f"WORKER_ID={worker_id}\n"
        f"WORKER_ORG_ID={worker_org_id}\n"
        f"WORKER_CREDENTIAL={worker_secret}\n"
        f"WORKER_DISPATCH_SIGNING_SECRET={signing_secret}\n"
    )

    env_local_path.write_text(env_content, encoding="utf-8")
    print(f"\nWrote configuration to: {env_local_path}")
    print("\n=== SUCCESS ===")
    print("Your PC is now registered and configured!")
    print("You can now start the daemon anytime by running:")
    print("  python scripts/run_worker_daemon.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
