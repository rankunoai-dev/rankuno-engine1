"""Create one operator who may log in to the local API server (ADR 0016).

The only supported way to provision an operator. Deliberately offline and
interactive rather than an HTTP endpoint: an operator-creation route would
itself need authentication, which is exactly the chicken-and-egg problem this
script avoids by running on the operator's own workstation instead of over
the network `src/api/server.py` serves.

Usage:
    python scripts/create_operator.py --operator-id alice --org-id acme
        --display-name "Alice Operator"

The password is never a command-line argument — it would then sit in shell
history and process listings — it is always read from a masked prompt.
"""

from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

# Make `src` importable when this is run directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.auth import Operator, hash_password  # noqa: E402
from src.core.config import get_settings  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="create_operator",
        description="Provision one operator who may log in to the local API server.",
    )
    parser.add_argument("--operator-id", required=True, help="Login id, e.g. 'alice'")
    parser.add_argument("--org-id", required=True, help="Organization this operator acts for")
    parser.add_argument("--display-name", default="", help="Defaults to --operator-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        return 1
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1

    store = get_settings().operator_store
    operator = Operator(
        operator_id=args.operator_id,
        org_id=args.org_id,
        display_name=args.display_name or args.operator_id,
        password_hash=hash_password(password),
    )
    try:
        store.create(operator)
    except ValueError as exc:
        print(f"Could not create operator: {exc}", file=sys.stderr)
        return 1

    print(f"Created operator '{operator.operator_id}' for org '{operator.org_id}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
