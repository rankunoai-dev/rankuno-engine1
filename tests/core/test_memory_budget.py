"""Tests for the process-wide crawl memory budget (ADR 0031).

The victim policy is a tenancy decision, so most of these pin *who* is stopped,
not merely *that* something is: a crawl under its fair share must never pay for
another organisation's load.
"""

from __future__ import annotations

import threading

import pytest
from src.core import memory_budget as memory_budget_module
from src.core.memory_budget import MEMORY_BUDGET_REASON, MemoryBudget

KB = 1000


def test_the_tenant_visible_reason_is_fixed_and_numberless():
    assert MEMORY_BUDGET_REASON == "memory budget reached"
    assert not any(ch.isdigit() for ch in MEMORY_BUDGET_REASON)


@pytest.mark.parametrize(("budget", "slots"), [(0, 5), (100, 0), (-1, 1)])
def test_non_positive_configuration_is_refused(budget, slots):
    with pytest.raises(ValueError, match="positive"):
        MemoryBudget(budget, slots)


def test_a_negative_charge_is_refused():
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    with pytest.raises(ValueError, match="negative"):
        account.charge(-1)


def test_under_budget_nothing_stops():
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    for _ in range(8):
        account.charge(100 * KB)  # 800 KB charged + one 100 KB in-flight reserve
    assert not account.stop_requested
    assert budget.snapshot().stopped == 0


def test_a_lone_crawl_may_use_the_whole_budget_not_just_its_share():
    """Share is 200 KB; the lone crawl runs well past it and stops only at 1 MB."""
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    for _ in range(5):
        account.charge(100 * KB)
    assert not account.stop_requested, "500 KB is over the share but under the budget"
    for _ in range(5):
        account.charge(100 * KB)
    assert account.stop_requested


def test_a_crawl_under_its_fair_share_is_never_stopped_by_another_orgs_load():
    """The C2 guarantee. Another tenant's large crawl is the one that pays."""
    budget = MemoryBudget(1000 * KB, 5)
    small = budget.open("org-a-job")
    large = budget.open("org-b-job")
    small.charge(90 * KB)  # 180 KB with its reserve: under the 200 KB share
    for _ in range(20):
        large.charge(100 * KB)
        assert not small.stop_requested
    # Charges made by the small crawl itself, while over budget, still never
    # select it: it is not over its share.
    small.charge(10 * KB)
    assert not small.stop_requested
    assert large.stop_requested


def test_the_largest_over_share_crawl_is_stopped_first():
    budget = MemoryBudget(2000 * KB, 5)  # share 400 KB
    medium = budget.open("medium")
    largest = budget.open("largest")
    largest.charge(800 * KB)  # projected 1.6 MB
    medium.charge(250 * KB)  # projected 500 KB, also over share; total 2.1 MB
    assert largest.stop_requested
    assert not medium.stop_requested


def test_a_tie_stops_the_latest_started_crawl():
    budget = MemoryBudget(1000 * KB, 5)
    first = budget.open("first")
    second = budget.open("second")
    first.charge(250 * KB)
    second.charge(250 * KB)  # 500 KB projected each: an exact tie at 1 MB
    assert second.stop_requested
    assert not first.stop_requested


def test_victims_accumulate_while_the_budget_stays_reached():
    """Stopping frees nothing until the job ends, so later charges pick again."""
    budget = MemoryBudget(1000 * KB, 2)  # share 500 KB
    a = budget.open("a")
    b = budget.open("b")
    a.charge(200 * KB)  # projected 400 KB, under share
    b.charge(400 * KB)  # projected 800 KB; total 1.2 MB
    assert b.stop_requested
    a.charge(50 * KB)  # still over budget, but `a` is still under its share
    assert not a.stop_requested
    a.charge(400 * KB)  # now over its share as well
    assert a.stop_requested


def test_a_crawl_with_no_pages_is_never_a_victim():
    """C6: a crawl stopped before its first page fails as retrieved-nothing."""
    budget = MemoryBudget(1000 * KB, 5)
    empty = budget.open("empty", in_flight_ceiling=200)
    large = budget.open("large")
    large.charge(2000 * KB)
    assert large.stop_requested
    assert not empty.stop_requested


def test_the_in_flight_reserve_is_counted():
    """Ten bodies may be in flight; each is reserved at the mean page size."""
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a", in_flight_ceiling=10)
    account.charge(100 * KB)  # 100 KB charged + 10 x 100 KB reserve
    assert account.projected_bytes == 1100 * KB
    assert account.stop_requested


def test_closing_releases_the_bytes_and_is_idempotent():
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("a")
    account.charge(300 * KB)
    assert budget.snapshot().projected_bytes == 600 * KB
    budget.close(account)
    budget.close(account)
    assert budget.snapshot().projected_bytes == 0
    assert budget.snapshot().accounts == 0


def test_a_charge_after_close_selects_no_victim():
    budget = MemoryBudget(100 * KB, 1)
    account = budget.open("a")
    budget.close(account)
    account.charge(500 * KB)
    assert not account.stop_requested


def test_a_zombie_still_counts_until_its_thread_closes_it():
    """A cancelled crawl keeps its HTML until it drains; its slot is irrelevant."""
    budget = MemoryBudget(1000 * KB, 2)
    zombie = budget.open("cancelled-but-running")
    zombie.charge(400 * KB)
    fresh = budget.open("fresh")
    fresh.charge(200 * KB)  # projected 1.2 MB: the zombie is the over-share victim
    assert zombie.stop_requested
    assert not fresh.stop_requested
    assert budget.snapshot().accounts == 2


def test_overrun_with_no_candidate_stops_nobody_and_logs_once(monkeypatch):
    """Only zombies can push under-share crawls past the budget together."""
    warnings: list[str] = []
    monkeypatch.setattr(
        memory_budget_module._logger, "warning", lambda event, **_kw: warnings.append(event)
    )
    budget = MemoryBudget(1000 * KB, 2)  # share 500 KB
    crawls = [budget.open(f"c{i}") for i in range(3)]
    for crawl in crawls:
        crawl.charge(200 * KB)  # 400 KB projected each, all under share
    crawls[0].charge(0)
    assert not any(crawl.stop_requested for crawl in crawls)
    assert warnings == ["crawl_memory_budget_overrun_no_victim"]


def test_the_victim_log_names_jobs_and_bytes_server_side(monkeypatch):
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        memory_budget_module._logger,
        "warning",
        lambda event, extra: captured.append({"event": event, **extra}),
    )
    budget = MemoryBudget(1000 * KB, 5)
    account = budget.open("job-123")
    account.charge(600 * KB)
    assert captured[0]["event"] == "crawl_memory_budget_victim"
    assert captured[0]["victim_job_id"] == "job-123"
    assert captured[0]["budget_bytes"] == 1000 * KB


def test_concurrent_charges_from_many_threads_are_all_counted():
    budget = MemoryBudget(10**12, 5)
    accounts = [budget.open(f"t{i}") for i in range(8)]

    def work(index: int) -> None:
        for _ in range(500):
            accounts[index].charge(1000)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(a.charged_bytes for a in accounts) == 8 * 500 * 1000
    assert all(a.pages == 500 for a in accounts)


def test_record_skip_counts_skipped_fetches():
    account = MemoryBudget(1000, 1).open("a")
    account.record_skip()
    account.record_skip()
    assert account.fetches_skipped == 2
