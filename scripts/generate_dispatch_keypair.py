"""Generate the Ed25519 keypair that signs ADR 0015 dispatch assignments (ADR 0028).

Prints two values and writes nothing to disk:

* the PRIVATE key — secret; paste it into the cloud API's
  `WORKER_DISPATCH_SIGNING_PRIVATE_KEY` (Railway variables) and nowhere else;
* the PUBLIC verify key and its `kid` — not secret; workers fetch it
  automatically via `scripts/register_worker.py`, or it can be set by hand as
  `WORKER_DISPATCH_VERIFY_KEY`.

The private key is never written to a file: a key file left in a
checkout or a Downloads folder is exactly the copy this change exists to stop
existing. Run it once per rotation, copy the private key straight into
Railway, and clear the terminal.

Usage:
    python scripts/generate_dispatch_keypair.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.worker_dispatch_keys import DispatchSigningKey  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="generate_dispatch_keypair",
        description="Generate the Ed25519 dispatch signing keypair (ADR 0028). Writes no files.",
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    key = DispatchSigningKey.generate()

    print("=" * 72)
    print("SECRET - cloud API only. Set as a Railway variable; never on a worker,")
    print("never in git, never in chat. Anyone holding it can dispatch crawls.")
    print("=" * 72)
    print(f"WORKER_DISPATCH_SIGNING_PRIVATE_KEY={key.private_key_secret().get_secret_value()}")
    print()
    print("PUBLIC - not secret. Workers fetch this via scripts/register_worker.py.")
    print(f"WORKER_DISPATCH_VERIFY_KEY={key.public_key_b64}")
    print(f"kid={key.kid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
