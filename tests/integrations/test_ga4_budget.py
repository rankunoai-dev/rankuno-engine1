"""`Ga4DailyBudget`: a per-organisation, per-UTC-day call allowance, in process (ADR 0038)."""

from __future__ import annotations

from datetime import date, timedelta

from src.integrations.ga4_budget import Ga4DailyBudget

DAY = date(2026, 10, 19)


def test_allows_up_to_the_limit_then_refuses() -> None:
    budget = Ga4DailyBudget()
    assert [budget.try_spend("acme", limit=2, today=DAY) for _ in range(3)] == [True, True, False]
    assert budget.spent("acme", today=DAY) == 2


def test_each_organisation_has_its_own_allowance() -> None:
    budget = Ga4DailyBudget()
    assert budget.try_spend("acme", limit=1, today=DAY) is True
    assert budget.try_spend("acme", limit=1, today=DAY) is False
    assert budget.try_spend("globex", limit=1, today=DAY) is True


def test_a_zero_limit_refuses_every_call() -> None:
    assert Ga4DailyBudget().try_spend("acme", limit=0, today=DAY) is False


def test_the_allowance_renews_on_the_next_utc_day() -> None:
    budget = Ga4DailyBudget()
    assert budget.try_spend("acme", limit=1, today=DAY) is True
    assert budget.try_spend("acme", limit=1, today=DAY) is False
    assert budget.try_spend("acme", limit=1, today=DAY + timedelta(days=1)) is True


def test_yesterdays_buckets_are_dropped_on_the_first_spend_of_today() -> None:
    budget = Ga4DailyBudget()
    budget.try_spend("acme", limit=5, today=DAY)
    budget.try_spend("globex", limit=5, today=DAY)
    budget.try_spend("acme", limit=5, today=DAY + timedelta(days=1))
    assert budget.spent("globex", today=DAY) == 0
    assert set(budget._counts) == {("acme", DAY + timedelta(days=1))}
