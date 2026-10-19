"""Print the Google consent URL that grants this engine GA4 read access (ADR 0038).

The operator-run half of GA4 authorisation. The in-app consent flow is not
built (C1), so a person grants the scope on Google's own page and copies the
resulting refresh token into the GSC account form's GA4 section.

What this script does, and does not do:

* It reads the shared OAuth client id from `Settings` and builds one URL with the
  GA4 read scope, offline access and forced consent, so a refresh token is issued.
* It prints the URL and the remaining steps. It makes **no network call**, and
  it never prints the client secret.
* It does not exchange the authorisation code. That step needs the client
  secret and a redirect the operator controls, so it is done by the operator,
  for example in Google's OAuth Playground configured with this client.

Usage:
    python scripts/ga4_consent_url.py
    python scripts/ga4_consent_url.py --redirect-uri https://developers.google.com/oauthplayground
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.config import get_settings  # noqa: E402
from src.integrations.ga4_client import GA4_READONLY_SCOPE  # noqa: E402

__all__ = ["build_consent_url", "main"]

GOOGLE_AUTHORIZE_URI = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_REDIRECT_URI = "https://developers.google.com/oauthplayground"


def build_consent_url(client_id: str, redirect_uri: str) -> str:
    """The authorisation URL for the GA4 read scope.

    `access_type=offline` and `prompt=consent` together make Google issue a
    refresh token on every grant, which the store needs. Neither value is a
    secret, so the URL is safe to show.
    """
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GA4_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"{GOOGLE_AUTHORIZE_URI}?{query}"


def main(argv: list[str] | None = None) -> int:
    """Print the URL and the steps. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help="Where Google sends the authorisation code. Default: the OAuth Playground.",
    )
    args = parser.parse_args(argv)
    client_id = get_settings().google_oauth_client_id
    if not client_id:
        sys.stderr.write("GOOGLE_OAUTH_CLIENT_ID is not set; nothing to authorise against.\n")
        return 1
    print(build_consent_url(client_id, args.redirect_uri))
    print()
    print(
        "1. Open the URL above and grant access with the Google account that owns the GA4 property."
    )
    print("2. Exchange the returned code for a refresh token with the same OAuth client.")
    print("3. In the GSC account form, paste that refresh token into the GA4 section, then")
    print("   pick a property from the list it can see. Nothing is stored until both steps pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
