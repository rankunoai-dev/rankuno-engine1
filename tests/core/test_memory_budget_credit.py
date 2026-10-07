"""Credits on the process-wide crawl memory budget (ADR 0035).

A crawl that releases each body once the page is read charges the body when it
lands and credits it back when it is released. These pin the rules the P4
security review made binding: a credit is clamped against outstanding *body*
bytes and logged when it overshoots, it never chooses a victim, it never makes a
page un-fetched, and the fair-share guarantee of ADR 0031 survives it.
"""

from __future__ import annotations

import threading

import pytest
from src.core import memory_budget as memory_budget_module
from src.core.memory_budget import LEAN_PAGE_BYTES, MemoryBudget

KB = 1000


def test_a_negative_credit_is_refused():
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    account.charge(10 * KB)
    with pytest.raises(ValueError, match="negative"):
        account.credit(-1)


def test_a_negative_overhead_is_refused():
    budget = MemoryBudget(1000 * KB, 5)
    with pytest.raises(ValueError, match="negative"):
        budget.open("a").charge(1, overhead_bytes=-1)


def test_a_credit_returns_exactly_the_body_and_never_the_overhead():
    budget = MemoryBudget(10_000 * KB, 5)
    account = budget.open("a")
    account.charge(100 * KB, overhead_bytes=LEAN_PAGE_BYTES)
    account.credit(100 * KB)
    assert account.charged_bytes == LEAN_PAGE_BYTES
    assert account.landed_body_bytes == 100 * KB
    assert account.credited_body_bytes == 100 * KB
    assert account.pages == 1, "a credit never makes a page un-fetched"


def test_an_over_credit_is_clamped_to_outstanding_body_bytes_and_logged(
    monkeypatch, allow_over_credit
):
    errors: list[dict[str, object]] = []
    monkeypatch.setattr(
        memory_budget_module._logger,
        "error",
        lambda event, extra: errors.append({"event": event, **extra}),
    )
    budget = MemoryBudget(10_000 * KB, 5)
    account = budget.open("job-7")
    account.charge(100 * KB, overhead_bytes=LEAN_PAGE_BYTES)
    account.credit(150 * KB)
    assert account.credited_body_bytes == 100 * KB, "never more than landed"
    assert account.charged_bytes == LEAN_PAGE_BYTES, "the overhead is not credited away"
    assert errors == [
        {
            "event": "crawl_memory_budget_over_credit",
            "job_id": "job-7",
            "requested_bytes": 150 * KB,
            "outstanding_body_bytes": 100 * KB,
        }
    ], "job id and counts only"


def test_a_credit_never_selects_a_victim():
    """With the budget still reached and an eligible candidate waiting, only a charge picks."""
    budget = MemoryBudget(1000 * KB, 5)  # share 200 KB
    mid = budget.open("mid")
    mid.charge(300 * KB)  # projected 600 KB, total under budget: nobody chosen
    big = budget.open("big")
    big.charge(900 * KB)  # total 2.4 MB: the largest, big, is chosen; one victim per charge
    assert big.stop_requested
    assert not mid.stop_requested, "eligible, over share, and still waiting"

    big.credit(100 * KB)  # total still over budget
    assert not mid.stop_requested, "a credit chose nobody"

    mid.charge(0)
    assert mid.stop_requested, "the next charge does"


def test_the_overrun_log_is_rearmed_only_when_projected_falls_below_the_budget():
    budget = MemoryBudget(1000 * KB, 2)  # share 500 KB
    crawls = [budget.open(f"c{i}") for i in range(3)]
    for crawl in crawls:
        crawl.charge(200 * KB)  # 400 KB projected each, all under share: no victim
    assert budget._overrun_logged
    assert not any(crawl.stop_requested for crawl in crawls)

    crawls[0].credit(50 * KB)  # projected 1.15 MB: still over
    assert budget._overrun_logged, "not re-armed while still over"

    for crawl in crawls:
        crawl.credit(150 * KB)  # projected 0.6 MB
    assert not budget._overrun_logged, "re-armed once under"


def test_the_in_flight_reserve_uses_landed_bodies_not_what_is_left():
    """A released body still says how large the next one in flight will be."""
    budget = MemoryBudget(10**12, 5)
    account = budget.open("a", in_flight_ceiling=10)
    account.charge(100 * KB, overhead_bytes=LEAN_PAGE_BYTES)
    account.credit(100 * KB)
    assert account.projected_bytes == LEAN_PAGE_BYTES + 10 * 100 * KB


def test_charge_and_credit_from_two_threads_stay_consistent():
    budget = MemoryBudget(10**12, 5)
    accounts = [budget.open("x"), budget.open("y")]
    rounds = 2000

    def work(account: memory_budget_module.MemoryAccount) -> None:
        for _ in range(rounds):
            account.charge(5 * KB, overhead_bytes=LEAN_PAGE_BYTES)
            account.credit(5 * KB)

    threads = [threading.Thread(target=work, args=(account,)) for account in accounts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for account in accounts:
        assert account.pages == rounds
        assert account.landed_body_bytes == account.credited_body_bytes == rounds * 5 * KB
        assert account.charged_bytes == account.overhead_bytes == rounds * LEAN_PAGE_BYTES
        assert not account.stop_requested, "both under share: neither may be chosen"


def test_a_crawl_under_its_share_is_spared_when_a_lean_charged_crawl_fills_the_budget():
    """ADR 0031's guarantee with bodies released: small pages reach a share on LEAN alone."""
    budget = MemoryBudget(100 * LEAN_PAGE_BYTES, 5)  # share: 20 pages' worth of LEAN
    small = budget.open("small-pages", in_flight_ceiling=1)
    steady = budget.open("other-org", in_flight_ceiling=1)
    steady.charge(1 * KB, overhead_bytes=LEAN_PAGE_BYTES)
    steady.credit(1 * KB)
    for _ in range(200):
        small.charge(1 * KB, overhead_bytes=LEAN_PAGE_BYTES)
        small.credit(1 * KB)
        if small.stop_requested:
            break
    assert small.stop_requested, "lean charges alone carry a crawl past the budget"
    assert not steady.stop_requested


def test_a_zero_page_account_is_never_a_victim_and_a_stop_stays_sticky(allow_over_credit):
    budget = MemoryBudget(1000 * KB, 5)
    idle = budget.open("idle")
    idle.credit(10 * KB)  # an over-credit on nothing: clamped to zero
    assert idle.pages == 0
    assert idle.charged_bytes == 0
    hog = budget.open("hog")
    hog.charge(2000 * KB)
    assert hog.stop_requested
    assert not idle.stop_requested
    hog.credit(2000 * KB)
    assert hog.stop_requested, "a credit never lifts a stop"


def test_charge_and_credit_after_close_are_harmless():
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    account.charge(100 * KB)
    budget.close(account)
    account.charge(5000 * KB)
    account.credit(5000 * KB)
    assert not account.stop_requested
    assert budget.snapshot().accounts == 0
    assert budget.snapshot().projected_bytes == 0
