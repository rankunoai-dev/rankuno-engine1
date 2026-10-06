"""Single-use, short-lived sign-in link for the local launcher (ADR 0033).

`scripts/run_local.ps1` opens the browser already signed in: it generates one
random token per start, hands it to the server in the environment, and opens
`http://127.0.0.1:<port>/#autosignin=<token>`. This module is the server's half
of that exchange, kept free of HTTP so its one hard property can be tested
directly: the token is accepted **at most once**, only within five minutes of
startup, and never after five wrong guesses.

Design stance:

* Only `sha256(token)` is held, never the token. A heap dump or a `repr` of
  the gate shows a digest of a value that is single-use anyway.
* Check, compare and consume happen in one critical section, so two racing
  requests carrying the right token cannot both succeed.
* Every way to fail is terminal or counted. Success and expiry clear the
  digest; five mismatches disarm the gate for the life of the process. A
  restart (a new launch) is the only way to get a new link.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections.abc import Callable
from enum import StrEnum

from pydantic import SecretStr

__all__ = ["DEFAULT_LINK_TTL_S", "MAX_FAILURES", "LocalSigninGate", "SigninOutcome"]

DEFAULT_LINK_TTL_S = 300.0
"""Five minutes from startup: long enough for the launcher's health poll and a
slow browser start, short enough that a link copied out of a process list is
stale before anyone could use it."""

MAX_FAILURES = 5
"""Mismatches before the gate disarms for good. The token has 256 bits, so this
is not about brute force; it stops a misbehaving client from hammering it."""


class SigninOutcome(StrEnum):
    """Why `redeem` accepted or refused. Values double as log categories."""

    OK = "ok"
    MISMATCH = "mismatch"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    LOCKED = "locked"


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class LocalSigninGate:
    """Holds one sign-in link's digest and redeems it at most once."""

    def __init__(
        self,
        token: SecretStr,
        *,
        ttl_s: float = DEFAULT_LINK_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Arm the gate. The clock starts now, at app construction.

        Args:
            token: The launcher's token. Hashed here and not retained.
            ttl_s: Seconds from construction until the link expires.
            clock: Monotonic clock; injectable so tests need not sleep.
        """
        self._clock = clock
        self._digest: bytes | None = _digest(token.get_secret_value())
        self._expires_at = clock() + ttl_s
        self._failures = 0
        self._consumed = False
        self._lock = threading.Lock()

    def redeem(self, presented: str) -> SigninOutcome:
        """Accept `presented` if it is the armed token, and disarm either way it ends.

        Args:
            presented: The token the browser posted.

        Returns:
            `OK` exactly once per gate; otherwise the reason it was refused.
        """
        presented_digest = _digest(presented)
        with self._lock:
            if self._consumed:
                return SigninOutcome.CONSUMED
            if self._failures >= MAX_FAILURES:
                return SigninOutcome.LOCKED
            if self._digest is None or self._clock() >= self._expires_at:
                self._digest = None
                return SigninOutcome.EXPIRED
            if not hmac.compare_digest(presented_digest, self._digest):
                self._failures += 1
                if self._failures >= MAX_FAILURES:
                    self._digest = None
                return SigninOutcome.MISMATCH
            self._consumed = True
            self._digest = None
            return SigninOutcome.OK
