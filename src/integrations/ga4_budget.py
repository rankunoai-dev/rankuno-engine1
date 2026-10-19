"""Per-organisation daily GA4 crawl budget, counted in process (ADR 0038).

GA4 requests are free of CostLedger charges (CLAUDE.md §8, C10: READ, zero recorded
spend), so this budget is a request-volume guard, not a spend guard. It stops
one organisation's crawls from consuming the shared GA4 quota every day.

Design stance, matching the rate limiter and the cost ledger: **in-process
only**. A multi-worker deployment multiplies the allowance by the worker count,
which is recorded as a known gap in the ADR, not hidden.

Counts are per UTC day. Yesterday's buckets are dropped on the first spend of
today, so the table cannot grow without bound.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime

__all__ = ["DAILY_BUDGET", "Ga4DailyBudget"]


class Ga4DailyBudget:
    """Counts crawls that reach GA4, per (organisation, UTC day), and refuses past a limit.

    One crawl is one charge, whatever its page count: the GA4 request is one host
    report per crawl (ADR 0038), so the crawl is the unit a daily allowance means.
    """

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, date], int] = {}

    def try_spend(self, org_id: str, *, limit: int, today: date | None = None) -> bool:
        """Record one crawl if the organisation is under `limit` for the day.

        Args:
            org_id: The organisation whose crawl is asking.
            limit: Crawls permitted per UTC day. Zero refuses every crawl.
            today: The day to count against. `None` means the current UTC day.

        Returns:
            `True` if the crawl is recorded and may reach GA4, `False` if the
            organisation has used its allowance for the day.
        """
        day = today or datetime.now(UTC).date()
        with self._lock:
            self._counts = {key: n for key, n in self._counts.items() if key[1] == day}
            used = self._counts.get((org_id, day), 0)
            if used >= limit:
                return False
            self._counts[(org_id, day)] = used + 1
            return True

    def spent(self, org_id: str, *, today: date | None = None) -> int:
        """Crawls recorded for the organisation on the day."""
        day = today or datetime.now(UTC).date()
        with self._lock:
            return self._counts.get((org_id, day), 0)


DAILY_BUDGET = Ga4DailyBudget()
"""The process-wide budget every GA4 caller shares."""
