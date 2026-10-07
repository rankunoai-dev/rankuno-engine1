"""A process-wide byte budget shared by concurrent crawls (ADR 0031, ADR 0035).

The server runs several crawls at once, and nothing bounded what they held
together, so a container reaching its memory limit was SIGKILLed mid-crawl and
every running job came back `FAILED`, "interrupted by a server restart". This
module is the safety net: it counts what the crawls hold and asks one of them to
stop *cleanly*, while there is still memory to classify what it has, so the job
ends partial instead of dead.

A crawl used to hold the HTML of every page it fetched until its job ended.
Since ADR 0035 it releases each body once the page has been read, keeping only
the homepage's, unless the operator turns that off
(`Settings.crawl_release_page_html`).

Design stance
-------------
* **Counted, not measured.** Bytes are charged by the caller (`sys.getsizeof`,
  O(1)): every body when it lands, and — when bodies are released — a flat
  `LEAN_PAGE_BYTES` plus the measured size of what the page keeps. A released
  body is credited back (`credit`). The process RSS is never read: a syscall
  per page is the cost this avoids, and RSS cannot say *which* crawl to stop.
  The measured ratio of RSS growth to counted bytes was 1.005-1.03 (ADR 0031)
  for retained HTML.
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
    "LEAN_PAGE_BYTES",
    "MEMORY_BUDGET_REASON",
    "MIB",
    "MemoryAccount",
    "MemoryBudget",
    "MemoryBudgetSnapshot",
]

_logger = get_logger(__name__)

MIB: Final = 1024 * 1024

LEAN_PAGE_BYTES: Final = 32 * 1024
"""Flat charge per fetched page once its body is released (ADR 0035).

Covers what a page costs that is not a body and not separately measured: its
graph node, its share of the loop watcher, and the evidence and profile built
for it after the crawl. Measured at about 17 KiB per page end to end on a
2,000-page crawl of small pages; the investigation measured 20-36 KiB with
three-segment URLs. 32 KiB is the upper end, rounded. What a page keeps that it
derived from its own body — title, canonical, redirect hops, breadcrumb, schema
types — is charged on top, measured, so a page cannot make this constant a lie
by being large."""

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
        """What this crawl is counted as holding now: bodies landed and not yet
        credited, plus every flat and derived per-page charge."""
        self.pages = 0
        self.landed_body_bytes = 0
        """Every body charged, ever. Monotonic, and the basis of the in-flight
        reserve: a released body still says how large the next one will be."""
        self.credited_body_bytes = 0
        """Bodies released and credited back. Monotonic, and never more than
        `landed_body_bytes`."""
        self.overhead_bytes = 0
        """Flat and derived per-page charges (`LEAN_PAGE_BYTES` plus what each
        page kept). Never credited: they live as long as the crawl."""
        self.links_charged_bytes = 0
        """Outbound-link tuples charged as a page lands. Monotonic. Links are
        held from then until their BFS level has been recorded, and a hostile
        page can make them far larger than its own body (ADR 0035)."""
        self.links_credited_bytes = 0
        """Link bytes credited back once the level recorded them. Monotonic, and
        never more than `links_charged_bytes`. A level abandoned before it is
        recorded never credits, which over-counts on the safe side."""
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
        mean = self.landed_body_bytes // self.pages if self.pages else 0
        return self.charged_bytes + self.in_flight_ceiling * mean

    def charge(self, nbytes: int, *, overhead_bytes: int = 0) -> None:
        """Count one landed body, and any per-page overhead, against the budget."""
        self._budget.charge(self, nbytes, overhead_bytes=overhead_bytes)

    def credit(self, nbytes: int) -> None:
        """Return the bytes of one released body. See `MemoryBudget.credit`."""
        self._budget.credit(self, nbytes)

    def charge_links(self, nbytes: int) -> None:
        """Count a landed page's outbound links. See `MemoryBudget.charge_links`."""
        self._budget.charge_links(self, nbytes)

    def credit_links(self, nbytes: int) -> None:
        """Return a recorded page's link bytes. See `MemoryBudget.credit_links`."""
        self._budget.credit_links(self, nbytes)

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

    def charge(self, account: MemoryAccount, nbytes: int, *, overhead_bytes: int = 0) -> None:
        """Count one landed body and choose a victim if the budget is reached.

        Args:
            account: The crawl that fetched it.
            nbytes: The body's size in memory.
            overhead_bytes: What the page costs beyond its body for the rest of
                the crawl — `LEAN_PAGE_BYTES` plus what it derived from the
                body — when bodies are released. `0` keeps the ADR 0031
                accounting exactly: one charge per retained body.

        Raises:
            ValueError: If either count is negative.
        """
        if nbytes < 0 or overhead_bytes < 0:
            raise ValueError("nbytes and overhead_bytes must not be negative")
        with self._lock:
            account.charged_bytes += nbytes + overhead_bytes
            account.landed_body_bytes += nbytes
            account.overhead_bytes += overhead_bytes
            account.pages += 1
            outcome = self._after_charge_locked(account)
        self._log_outcome(account, outcome)

    def charge_links(self, account: MemoryAccount, nbytes: int) -> None:
        """Count a landed page's outbound links until its level records them.

        A charge like any other — it can choose a victim — but not a page: the
        page was counted when its body was charged.

        Args:
            account: The crawl that extracted them.
            nbytes: `getsizeof` of the link tuple(s) and every string in them.

        Raises:
            ValueError: If `nbytes` is negative.
        """
        if nbytes < 0:
            raise ValueError("nbytes must not be negative")
        with self._lock:
            account.charged_bytes += nbytes
            account.links_charged_bytes += nbytes
            outcome = self._after_charge_locked(account)
        self._log_outcome(account, outcome)

    def credit_links(self, account: MemoryAccount, nbytes: int) -> None:
        """Return a page's link bytes once its level has recorded them.

        Clamped against outstanding *link* bytes and logged at ERROR on an
        over-credit, exactly like `credit` for bodies; never selects a victim.

        Args:
            account: The crawl that recorded them.
            nbytes: Exactly what `charge_links` was given for that page.

        Raises:
            ValueError: If `nbytes` is negative.
        """
        if nbytes < 0:
            raise ValueError("nbytes must not be negative")
        with self._lock:
            outstanding = account.links_charged_bytes - account.links_credited_bytes
            applied = min(nbytes, outstanding)
            account.links_credited_bytes += applied
            account.charged_bytes -= applied
            self._rearm_locked(account)
        if applied < nbytes:
            _logger.error(
                "crawl_memory_budget_over_credit",
                extra={
                    "job_id": account.account_id,
                    "requested_bytes": nbytes,
                    "outstanding_link_bytes": outstanding,
                },
            )

    def _after_charge_locked(
        self, account: MemoryAccount
    ) -> tuple[int, MemoryAccount | None, int] | None:
        """Choose a victim if the budget is reached. Returns what to log, if anything."""
        if account.sequence not in self._accounts:
            return None
        projected = self._projected_locked()
        if projected < self.budget_bytes:
            self._overrun_logged = False
            return None
        victim = self._choose_victim_locked()
        if victim is not None:
            victim.request_stop()
            return projected, victim, victim.projected_bytes
        if self._overrun_logged:
            return None
        self._overrun_logged = True
        return projected, None, 0

    def _rearm_locked(self, account: MemoryAccount) -> None:
        """Re-arm the overrun log once a credit takes the total below the budget."""
        if account.sequence in self._accounts and self._projected_locked() < self.budget_bytes:
            self._overrun_logged = False

    def _log_outcome(
        self, account: MemoryAccount, outcome: tuple[int, MemoryAccount | None, int] | None
    ) -> None:
        """Log a charge's outcome outside the lock."""
        if outcome is None:
            return
        projected, victim, victim_bytes = outcome
        # Job ids and byte counts are server-side only.
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

    def credit(self, account: MemoryAccount, nbytes: int) -> None:
        """Return a released body's bytes. Never selects a victim.

        Clamped against the account's outstanding *body* bytes — landed minus
        already credited — never against its total charge, so the flat and
        derived per-page charges can never be credited away. An over-credit is a
        bug in the caller (a body credited twice, or one never charged): it is
        clamped so the count stays an over-estimate, and logged at ERROR, which
        the test suite turns into a failure. `pages` is never decremented: a
        crawl that has landed a page has retrieved something, whatever it still
        holds, so it stays eligible as a victim exactly as before.

        Args:
            account: The crawl releasing the body.
            nbytes: Exactly what was charged for it.

        Raises:
            ValueError: If `nbytes` is negative.
        """
        if nbytes < 0:
            raise ValueError("nbytes must not be negative")
        with self._lock:
            outstanding = account.landed_body_bytes - account.credited_body_bytes
            applied = min(nbytes, outstanding)
            account.credited_body_bytes += applied
            account.charged_bytes -= applied
            self._rearm_locked(account)
        if applied < nbytes:
            # Job id and counts only: never a body, never page text.
            _logger.error(
                "crawl_memory_budget_over_credit",
                extra={
                    "job_id": account.account_id,
                    "requested_bytes": nbytes,
                    "outstanding_body_bytes": outstanding,
                },
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
