"""Shared ADR 0016 session-token helpers for every `tests/api/` module.

Authentication became mandatory on almost every route in `src/api/server.py`
in the same change that closed the GSC-account IDOR (ADR 0016). Every test
file under here that builds a `TestClient` needs a way to hand it a valid
bearer token without going through `POST /auth/login` for every single test
— minting one directly with `issue_session_token` is exactly what condition
6's self-contained verification buys a test suite: no operator store, no
network, just a signature check against the same secret the app under test
was built with.

`TEST_SESSION_SECRET` is fixed, not random per run: nothing here needs
unpredictability, only that every `create_app(..., session_secret=...)` call
in this test tree and every `mint_token`/`auth_headers` call sign against the
same value. Passing it explicitly, rather than letting `ApiState` fall back
to `Settings.session_secret`, is deliberate too — that property is itself
process-cache-order-dependent and gets monkeypatched by some fixtures in this
tree (`get_settings` overrides in `test_gsc_accounts_endpoint.py`), and a
token that silently stopped verifying because of fixture ordering would be a
confusing way for one of these tests to fail.
"""

from __future__ import annotations

from pydantic import SecretStr
from src.core.auth import Operator, issue_session_token

__all__ = ["TEST_SESSION_SECRET", "auth_headers", "mint_token"]

TEST_SESSION_SECRET = SecretStr("test-only-session-signing-secret-do-not-use-outside-tests")

DEFAULT_TEST_OPERATOR_ID = "test-operator"


def mint_token(org_id: str = "default", operator_id: str = DEFAULT_TEST_OPERATOR_ID) -> str:
    """A valid, signed session token claiming `org_id`.

    Builds a throwaway `Operator` rather than reading one from a store:
    verification is self-contained (ADR 0016 condition 6), so nothing a test
    calls ever looks the operator up again — only the token's own signature
    and claims matter once it is minted.
    """
    operator = Operator(
        operator_id=operator_id,
        org_id=org_id,
        display_name=operator_id,
        password_hash="unused-in-tests",  # noqa: S106 - a placeholder, never checked
    )
    return issue_session_token(operator, secret=TEST_SESSION_SECRET, ttl_s=3600).token


def auth_headers(
    org_id: str = "default", operator_id: str = DEFAULT_TEST_OPERATOR_ID
) -> dict[str, str]:
    """The `Authorization` header for a valid session claiming `org_id`."""
    return {"Authorization": f"Bearer {mint_token(org_id, operator_id)}"}
