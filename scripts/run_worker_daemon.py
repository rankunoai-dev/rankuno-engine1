"""Start the Rankuno desktop worker daemon from a checkout (ADR 0015).

Equivalent to the `rankuno-worker` console script, for a machine where the
package has not been `pip install -e .`'d. All the behaviour, and the
reasoning behind it, lives in
`src.modules.seo.screaming_frog_control.worker_daemon_cli`; this file exists
only so the daemon is startable with nothing but a checkout and a venv.

Usage:
    python scripts/run_worker_daemon.py --check
    python scripts/run_worker_daemon.py

Configuration comes from `.env.local` (WORKER_CLOUD_API_BASE_URL, WORKER_ID,
WORKER_ORG_ID, WORKER_CREDENTIAL, WORKER_DISPATCH_SIGNING_SECRET). No secret
is ever passed as an argument.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src` importable when this is run directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.modules.seo.screaming_frog_control.worker_daemon_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
