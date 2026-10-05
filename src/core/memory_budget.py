"""A process-wide byte budget shared by concurrent crawls (ADR 0031).

Every crawl retains the HTML of every page it fetches until its job ends, and
the server runs several crawls at once. Nothing bounded the sum, so a container
reaching its memory limit was SIGKILLed mid-crawl and every running job came
back `FAILED`, "interrupted by a server restart". This module is the safety net:
it counts what the crawls retain and asks one of them to stop *cleanly*, while
there is still memory to classify what it has, so the job ends partial instead
of dead.

Design stance
-------------
* **Counted, not measured.** Bytes are charged by the caller, one charge per
  retained body (`sys.getsizeof`, O(1)). The process RSS is never read: a
  syscall per page is the cost this avoids, and RSS cannot say *which* crawl to
  stop. The measured ratio of RSS growth to counted bytes was 1.005-1.03
  (ADR 0031), so the count is a faithful proxy for the HTML it covers.
* **Fair share first, then largest.** Each live crawl is guaranteed
  `budget // fair_share_slots`. When the projected total reaches the budget,
  only crawls *over* that share are candidates, the largest first, the latest
  started on a tie. A crawl at or under its share is never stopped by another
  tenant's load, and a crawl running alone may use the whole budget.
* **Stopping is a request, not an action.** Choosing a victim sets its flag and
  nothing else. The crawl honours it at its own safe points, so this module
  never touches a job's status, slot or cancel flag.
* **Not an OOM guarantee.** Only what callers charge is counted. Anything that
  allocates without charging — sitemaps, result reads, workbook builds — sits
  outside the budget, which is why the default leaves headroom for it.
"""

from __future__ import annotations

import itertools
import threading
from typing import Final

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel

__all__ = [
    "MEMORY_BUDGET_REASON",
    "MIB",
    "MemoryAccount",
    "MemoryBudget",
    "MemoryBudgetSnapshot",
]

_logger = get_logger(__name__)

MIB: Final = 1024 * 1024

MEMORY_BUDGET_REASON: Final = "memory budget reached"
"""The tenant-visible stop reason. Fixed and numberless on purpose.

A job's `error` is shown to its tenant. Byte counts, the share, and which other
jobs were running describe *other* tenants' load, so they go to the server log
and never into this string."""


class MemoryBudgetSnapshot(StrictModel):
    """A consistent read of the budget, for logs and tests."""

    budget_bytes: int = Field(ge=1)
    fair_share_bytes: int = Field(ge=0)
    projected_bytes: int = Field(ge=0)
    """Charged bytes plus every account's in-flight reserve."""
    accounts: int = Field(ge=0)
    stopped: int = Field(ge=0)


class MemoryAccount:
    """One crawl's share of a `MemoryBudget`.

    A live object rather than a model: it carries a `threading.Event` and
    mutable counters guarded by the budget's lock, and it crosses the
    server-to-tool boundary the way `cancel_event` does — as the caller's
    control primitive, never as serialised request data.
    """

    def __init__(
        self, budget: MemoryBudget, account_id: str, sequence: int, in_flight_ceiling: int
    ) -> None:
        """Build an account. Use `MemoryBudget.open`, which registers it.

        Args:
            budget: The budget this account draws on.
            account_id: The job id. Logged server-side, never shown to a tenant.
            sequence: Start order; the tie-break that stops the newest crawl.
            in_flight_ceiling: Most bodies this crawl can have in flight. They
                exist in memory before they can be charged, so each is reserved
                at the crawl's mean page size.
        """
        self._budget = budget
        self.account_id = account_id
        self.sequence = sequence
        self.in_flight_ceiling = max(1, in_flight_ceiling)
        self.charged_bytes = 0
        self.pages = 0
        self.fetches_skipped = 0
        """Fetches not made because of the stop. Touched only on the crawl's own
        event-loop thread, so it needs no lock; the crawl reads it to tell a
        crawl the budget cut short from one that finished as the stop landed."""
        self._stop = threading.Event()

    @property
    def stop_requested(self) -> bool:
        """Whether this crawl has been chosen to stop."""
        return self._stop.is_set()

    @property
    def projected_bytes(self) -> int:
        """Charged bytes plus a reserve for the bodies that may be in flight.

        The reserve is zero until the first page lands, which is harmless: an
        account with no pages can never be chosen as a victim anyway.
        """
        mean = self.charged_bytes // self.pages if self.pages else 0
        return self.charged_bytes + self.in_flight_ceiling * mean

    def charge(self, nbytes: int) -> None:
        """Count one retained page body against the budget."""
        self._budget.charge(self, nbytes)

    def record_skip(self) -> None:
        """Note a fetch that was not made because of the stop."""
        self.fetches_skipped += 1

    def request_stop(self) -> None:
        """Flag this account to stop. Called under the budget's lock."""
        self._stop.set()


class MemoryBudget:
    """The registry every concurrent crawl in this process charges.

    Thread-safe: each crawl runs `asyncio.run` on its own worker thread, so
    charges arrive from several threads at once and are serialised by one lock.
    The victim scan is O(accounts), and accounts are bounded by the crawl
    concurrency cap plus any cancelled crawls still draining.
    """

    def __init__(self, budget_bytes: int, fair_share_slots: int) -> None:
        """Build a budget.

        Args:
            budget_bytes: Projected bytes at which a victim is chosen.
            fair_share_slots: How many crawls the budget is shared between —
                the crawl concurrency cap. Each is guaranteed
                `budget_bytes // fair_share_slots`.

        Raises:
            ValueError: If either value is not positive.
        """
        if budget_bytes < 1 or fair_share_slots < 1:
            raise ValueError("budget_bytes and fair_share_slots must both be positive")
        self.budget_bytes = budget_bytes
        self.fair_share_bytes = budget_bytes // fair_share_slots
        self._lock = threading.Lock()
        self._accounts: dict[int, MemoryAccount] = {}
        self._sequence = itertools.count()
        self._overrun_logged = False

    def open(self, account_id: str, *, in_flight_ceiling: int = 1) -> MemoryAccount:
        """Register a crawl. Pair with `close` in a `finally`.

        Args:
            account_id: The job id.
            in_flight_ceiling: The crawl's concurrency ceiling.

        Returns:
            The crawl's account.
        """
        with self._lock:
            account = MemoryAccount(self, account_id, next(self._sequence), in_flight_ceiling)
            self._accounts[account.sequence] = account
        return account

    def close(self, account: MemoryAccount) -> None:
        """Deregister a crawl and release everything it charged. Idempotent.

        Must run when the crawl's thread really ends — not when its slot is
        released. A cancelled crawl keeps running, and keeps its HTML, until
        its in-flight work drains, so it stays counted until then.
        """
        with self._lock:
            self._accounts.pop(account.sequence, None)
            if self._projected_locked() < self.budget_bytes:
                self._overrun_logged = False

    def charge(self, account: MemoryAccount, nbytes: int) -> None:
        """Count one retained body and choose a victim if the budget is reached.

        Args:
            account: The crawl that retained it.
            nbytes: Its size in memory.

        Raises:
            ValueError: If `nbytes` is negative.
        """
        if nbytes < 0:
            raise ValueError("nbytes must not be negative")
        with self._lock:
            account.charged_bytes += nbytes
            account.pages += 1
            if account.sequence not in self._accounts:
                return
            projected = self._projected_locked()
            if projected < self.budget_bytes:
                self._overrun_logged = False
                return
            victim = self._choose_victim_locked()
            if victim is not None:
                victim.request_stop()
                victim_bytes = victim.projected_bytes
            elif self._overrun_logged:
                return
            else:
                self._overrun_logged = True

        # Logged outside the lock. Job ids and byte counts are server-side only.
        if victim is not None:
            _logger.warning(
                "crawl_memory_budget_victim",
                extra={
                    "victim_job_id": victim.account_id,
                    "victim_bytes": victim_bytes,
                    "trigger_job_id": account.account_id,
                    "projected_bytes": projected,
                    "budget_bytes": self.budget_bytes,
                    "fair_share_bytes": self.fair_share_bytes,
                },
            )
        else:
            _logger.warning(
                "crawl_memory_budget_overrun_no_victim",
                extra={"projected_bytes": projected, "budget_bytes": self.budget_bytes},
            )

    def snapshot(self) -> MemoryBudgetSnapshot:
        """Read the budget's state consistently."""
        with self._lock:
            return MemoryBudgetSnapshot(
                budget_bytes=self.budget_bytes,
                fair_share_bytes=self.fair_share_bytes,
                projected_bytes=self._projected_locked(),
                accounts=len(self._accounts),
                stopped=sum(1 for a in self._accounts.values() if a.stop_requested),
            )

    def _projected_locked(self) -> int:
        return sum(account.projected_bytes for account in self._accounts.values())

    def _choose_victim_locked(self) -> MemoryAccount | None:
        """The largest crawl over its fair share, newest first on a tie.

        An account with no pages is never chosen: a crawl stopped before its
        first page retrieves nothing, and `retrieved_nothing` fails the job —
        the outcome this module exists to prevent.
        """
        candidates = [
            account
            for account in self._accounts.values()
            if account.pages > 0
            and not account.stop_requested
            and account.projected_bytes > self.fair_share_bytes
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda a: (a.projected_bytes, a.sequence))
