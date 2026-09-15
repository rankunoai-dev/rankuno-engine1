"""The preview -> confirm token exchange that supplies HITL approval.

ADR 0013 condition 8, and its own "open question": `GuardrailEngine.
authorize()`'s `ApprovalProvider.request_approval()` call inside
`BaseTool.run()` is synchronous and blocking, and no tool before this one has
ever needed a real answer to what supplies it. This module is the chosen
answer — approval is supplied *before* `run()` is ever called, not by
blocking inside it:

1. `POST .../preview` validates the seed URL and template, then mints a
   short-lived, single-use token bound to the exact
   `(org_id, seed_url, template_name)` triple the UI shows in a confirmation
   modal. Nothing runs yet.
2. `POST .../jobs` hands that token back. It is never trusted as a bare
   `confirmed: true` boolean; the API route builds a
   `CallbackApprovalProvider` (`src/core/guardrails.py`) whose callback is
   the only thing that can mark the token used, and it does so at the moment
   `GuardrailEngine.authorize()` actually calls it inside `tool.run()` — not
   earlier, so a job that is later refused for an unrelated reason (capacity,
   unknown org) never burns the operator's approval before the tool asked
   for it.

`AutoApproveProvider` is never wired here or anywhere in production per
CLAUDE.md §3 — this callback is a real, falsifiable check (token identity,
expiry, exact-match binding, single use), not an unconditional `True`.

In-process only, like `RateLimiterRegistry`/`CostLedger` (CLAUDE.md §8): a
multi-worker deployment would need a shared store. Out of scope for a single
Windows workstation (ADR 0004; ADR 0013's own consequences section repeats
this for the whole capability).
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.core.logger import get_logger
from src.core.schemas import ToolMetadata

__all__ = ["DEFAULT_TOKEN_TTL_S", "PreviewToken", "PreviewTokenStore", "make_approval_callback"]

_logger = get_logger(__name__)

DEFAULT_TOKEN_TTL_S = 120.0
"""~2 minutes: long enough for an operator to read the confirmation modal,
short enough that a leaked token is a narrow window (ADR 0013 Step 3 design)."""


@dataclass(frozen=True)
class PreviewToken:
    """One minted, not-yet-consumed approval token."""

    token: str
    org_id: str
    seed_url: str
    template_name: str | None
    expires_at: datetime


class PreviewTokenStore:
    """Mints and consumes preview tokens. One instance per running server."""

    def __init__(self, *, ttl_s: float = DEFAULT_TOKEN_TTL_S) -> None:
        """Build an empty store.

        Args:
            ttl_s: Token lifetime in seconds from `mint()`.
        """
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._tokens: dict[str, PreviewToken] = {}

    def mint(self, *, org_id: str, seed_url: str, template_name: str | None) -> PreviewToken:
        """Create a new token bound to this exact triple."""
        record = PreviewToken(
            token=secrets.token_urlsafe(32),
            org_id=org_id,
            seed_url=seed_url,
            template_name=template_name,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_s),
        )
        with self._lock:
            self._prune_expired()
            self._tokens[record.token] = record
        return record

    def peek(self, token: str, *, org_id: str, seed_url: str, template_name: str | None) -> bool:
        """Non-consuming validity check, for a fast admission-time rejection.

        Never the authoritative approval decision — `consume()`, called from
        inside the guardrail callback, is. A token that passes `peek` and
        then loses a race to a concurrent confirm request correctly fails
        the later `consume()`.
        """
        with self._lock:
            return self._is_valid(
                token, org_id=org_id, seed_url=seed_url, template_name=template_name
            )

    def consume(self, token: str, *, org_id: str, seed_url: str, template_name: str | None) -> bool:
        """Atomically validate and burn a token. The real HITL decision.

        Bound into a `CallbackApprovalProvider` so this runs exactly once, at
        the moment `GuardrailEngine.authorize()` asks for approval.
        """
        with self._lock:
            if not self._is_valid(
                token, org_id=org_id, seed_url=seed_url, template_name=template_name
            ):
                return False
            del self._tokens[token]
            return True

    def _is_valid(
        self, token: str, *, org_id: str, seed_url: str, template_name: str | None
    ) -> bool:
        record = self._tokens.get(token)
        if record is None:
            return False
        if datetime.now(UTC) >= record.expires_at:
            del self._tokens[token]
            return False
        return (
            record.org_id == org_id
            and record.seed_url == seed_url
            and record.template_name == template_name
        )

    def _prune_expired(self) -> None:
        """Drop expired entries. Called under `self._lock` only."""
        now = datetime.now(UTC)
        expired = [token for token, record in self._tokens.items() if now >= record.expires_at]
        for token in expired:
            del self._tokens[token]


def make_approval_callback(
    store: PreviewTokenStore,
    *,
    token: str,
    org_id: str,
    seed_url: str,
    template_name: str | None,
) -> Callable[[ToolMetadata, str], bool]:
    """Build the `(ToolMetadata, str) -> bool` callable `CallbackApprovalProvider` wants.

    Closes over one confirm request's already-known triple so the callback
    itself takes no caller-supplied argument that could be spoofed; the only
    thing `GuardrailEngine` hands it back is the tool's own metadata and a
    human-readable description, neither of which this callback trusts for
    the approval decision.
    """

    def _callback(metadata: ToolMetadata, _context: str) -> bool:
        approved = store.consume(
            token, org_id=org_id, seed_url=seed_url, template_name=template_name
        )
        _logger.info(
            "sf_preview_token_consumed",
            extra={"tool": metadata.name, "org": org_id, "approved": approved},
        )
        return approved

    return _callback
