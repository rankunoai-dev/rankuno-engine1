"""The async DOM crawl honours the process-wide memory budget (ADR 0031).

Kept apart from `test_async_discovery.py`, which is already past a thousand
lines. Every fetch goes through a real `HttpFetcher` over `httpx.MockTransport`;
nothing touches the network.
"""

from __future__ import annotations

import asyncio
import sys
import threading

import httpx
from src.core.memory_budget import MEMORY_BUDGET_REASON, MemoryAccount, MemoryBudget
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import _gather_bounded, adiscover_site
from src.modules.seo.page_classifier.discovery import DiscoveryReport, SiteGraph

PUBLIC_IP = "93.184.216.34"
ROBOTS = "User-agent: *\nAllow: /\n"
PAD = "<p>" + "x" * 49_990 + "</p>"
"""About 50 KB of ASCII per page: big enough to dominate, small enough to be fast."""
CHILDREN = 20


def _page(links: str, extra: str = "") -> str:
    return f"<html><body>{links}{extra}{PAD}</body></html>"


HOME = _page("".join(f'<a href="/p{i}/">P{i}</a>' for i in range(CHILDREN)))


def _site(home: str = HOME) -> dict[str, str]:
    routes = {"/": home}
    for i in range(CHILDREN):
        routes[f"/p{i}/"] = _page("")
    return routes


def _fetcher(settings, routes: dict[str, str], calls: list[str] | None = None) -> HttpFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        body = routes.get(path)
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    return HttpFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
    )


def _run(
    settings,
    account: MemoryAccount | None,
    routes: dict[str, str] | None = None,
    **kwargs: object,
) -> tuple[SiteGraph, DiscoveryReport]:
    fetcher = _fetcher(settings, routes if routes is not None else _site())

    async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
        async with fetcher:
            return await adiscover_site(
                fetcher,
                "https://e.com",
                concurrency=1,
                memory_account=account,
                **kwargs,  # type: ignore[arg-type]
            )

    return asyncio.run(asyncio.wait_for(scenario(), timeout=30.0))


def test_a_stopped_account_skips_queued_fetches_without_calling_them():
    """The `_gather_bounded` half: checked before a task claims a slot."""
    account = MemoryBudget(1000, 1).open("a")
    account.request_stop()
    calls = 0

    async def poison() -> str:
        nonlocal calls
        calls += 1
        return "must never run"

    async def scenario() -> list[str | None]:
        return await _gather_bounded(
            [lambda: poison(), lambda: poison()], concurrency=2, memory_account=account
        )

    assert asyncio.run(scenario()) == [None, None]
    assert calls == 0
    assert account.fetches_skipped == 2


def test_a_small_budget_ends_the_crawl_partial_with_the_memory_reason(settings):
    """Home plus four children fit; the fifth charge reaches the budget."""
    account = MemoryBudget(300_000, 5).open("job", in_flight_ceiling=1)

    graph, report = _run(settings, account)

    assert report.stopped_reason == MEMORY_BUDGET_REASON
    assert report.truncated is False, "truncated means the page ceiling, not memory"
    assert 1 < report.pages_fetched < CHILDREN + 1
    assert account.fetches_skipped > 0
    assert graph.html_for("https://e.com/") is not None, "fetched pages keep their HTML"
    assert not report.retrieved_nothing


def test_a_budget_smaller_than_the_homepage_still_fetches_the_homepage(settings):
    """C6: stopping before the first page would fail the job as retrieved-nothing."""
    account = MemoryBudget(1_000, 5).open("job")

    graph, report = _run(settings, account)

    assert report.pages_fetched == 1
    assert report.stopped_reason == MEMORY_BUDGET_REASON
    assert graph.html_for("https://e.com/") is not None
    assert not report.retrieved_nothing


def test_operator_cancel_wins_when_both_stops_land(settings):
    """C4: the operator's label must not be replaced by the budget's."""
    account = MemoryBudget(1_000, 5).open("job")
    cancel_event = threading.Event()

    def on_progress(done: int, _total: int, _recent: tuple[str, ...]) -> None:
        if done >= 1:
            cancel_event.set()

    _, report = _run(settings, account, cancel_event=cancel_event, on_progress=on_progress)

    assert account.stop_requested
    assert report.stopped_reason == "cancelled by operator"


def test_a_crawl_that_finished_as_the_stop_landed_is_not_labelled_partial(settings):
    """The last page reaching the budget skipped nothing, so nothing is missing."""
    leaf = _page("")
    routes = {"/": _page('<a href="/only/">Only</a>'), "/only/": leaf}
    budget = MemoryBudget(2 * sys.getsizeof(leaf) + sys.getsizeof(leaf) // 2, 5)
    account = budget.open("job", in_flight_ceiling=1)

    _, report = _run(settings, account, routes=routes)

    assert account.stop_requested, "the leaf's charge reached the budget"
    assert account.fetches_skipped == 0
    assert report.stopped_reason is None
    assert report.pages_fetched == 2


def test_the_charge_is_the_retained_size_including_pep_393_width(settings):
    """One curly apostrophe makes a page two bytes per character."""
    home = _page("", extra="It’s")
    account = MemoryBudget(10**9, 5).open("job")

    _run(settings, account, routes={"/": home})

    assert account.pages == 1
    assert account.charged_bytes == sys.getsizeof(home)
    assert account.charged_bytes > 2 * len(home)


def test_no_account_means_no_budget(settings):
    """Every caller without a server — direct `execute()`, most tests — is unaffected."""
    _, report = _run(settings, None)
    assert report.stopped_reason is None
    assert report.pages_fetched == CHILDREN + 1
