"""Outbound links are charged while their level is in flight (ADR 0035, review R2).

A page's link tuples live from the moment it lands until its BFS level has been
recorded, and a hostile page can make them far larger than its own body. They
are charged as the page lands and credited by the level loop once recorded. A
level abandoned before it is recorded never credits: the safe over-count.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest
from src.core import memory_budget
from src.core.memory_budget import MEMORY_BUDGET_REASON, MemoryAccount, MemoryBudget
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier import async_discovery
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import DiscoveryReport, SiteGraph
from src.modules.seo.page_classifier.discovery_parsers import extract_page_links

from tests.modules.seo.golden_site_factory import (
    BASE,
    PUBLIC_IP,
    GoldenFetcher,
    Route,
    build_fetcher,
    build_site,
    golden_settings,
)

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")


def sizeof_links(links: tuple[str, ...]) -> int:
    return sys.getsizeof(links) + sum(sys.getsizeof(link) for link in links)


def crawl(
    tmp_path: Path, site: dict[str, Route], account: MemoryAccount, **kwargs: Any
) -> tuple[SiteGraph, DiscoveryReport]:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=1)

    async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
        async with fetcher:
            return await adiscover_site(fetcher, BASE, memory_account=account, **kwargs)

    return asyncio.run(scenario())


@pytest.fixture
def link_charges(monkeypatch) -> list[int]:
    seen: list[int] = []
    real = MemoryBudget.charge_links

    def spy(self: MemoryBudget, account: MemoryAccount, nbytes: int) -> None:
        seen.append(nbytes)
        real(self, account, nbytes)

    monkeypatch.setattr(MemoryBudget, "charge_links", spy)
    return seen


@pytest.mark.parametrize("release", [True, False], ids=["release-on", "release-off"])
def test_every_link_charge_is_credited_once_its_level_is_recorded(tmp_path, release):
    account = MemoryBudget(10**12, 5).open("job")
    crawl(tmp_path, build_site(), account, release_bodies=release)
    assert account.links_charged_bytes > 0
    assert account.links_credited_bytes == account.links_charged_bytes


def test_a_redirected_page_is_charged_for_both_readings_of_its_links(tmp_path, link_charges):
    body = '<a href="child/">c</a><a href="../up/">u</a>'
    site = {
        "/robots.txt": ROBOTS,
        "/": Route(200, "text/html", '<a href="/moved/">m</a>'),
        "/moved/": Route(301, "text/html", "", "/deep/landing/"),
        "/deep/landing/": Route(200, "text/html", body),
    }
    account = MemoryBudget(10**12, 5).open("job")
    crawl(tmp_path, site, account)
    landed = extract_page_links(body, f"{BASE}/moved/", document_url=f"{BASE}/deep/landing/")
    requested = extract_page_links(body, f"{BASE}/moved/", document_url=f"{BASE}/moved/")
    assert landed != requested
    assert sizeof_links(landed) + sizeof_links(requested) in link_charges


def test_an_abandoned_level_keeps_its_link_charge(tmp_path, monkeypatch, link_charges):
    """Build-log 0137 §4.2: completed pages are kept, their links never recorded."""
    monkeypatch.setattr(async_discovery, "STALL_TIMEOUT_S", 0.3)
    site = {"/": "<a href='/fast/'>f</a><a href='/slow/'>s</a>", "/fast/": "<a href='/x/'>x</a>"}
    never = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        body = site.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="nf")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    async def ahandler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/slow/":
            await never.wait()
        return handler(request)

    fetcher = GoldenFetcher(
        settings=golden_settings(tmp_path),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(ahandler),
    )
    account = MemoryBudget(10**12, 5).open("job")

    async def scenario() -> DiscoveryReport:
        async with fetcher:
            return (await adiscover_site(fetcher, BASE, memory_account=account))[1]

    report = asyncio.run(scenario())
    assert report.abandoned_in_flight == 1
    fast_links = sizeof_links((f"{BASE}/x/",))
    outstanding = account.links_charged_bytes - account.links_credited_bytes
    assert outstanding == fast_links, "the abandoned level's charge stays: a safe over-count"


def test_link_charges_alone_can_stop_a_crawl(tmp_path):
    """Thousands of long same-site links are real memory, and the budget sees them."""
    base = f"{BASE}/" + "p" * 2_000 + "/"
    anchors = "".join(f'<a href="?{i}">{i}</a>' for i in range(3_000))
    site = {
        "/robots.txt": ROBOTS,
        "/": Route(200, "text/html", f'<base href="{base}">{anchors}'),
    }
    account = MemoryBudget(4 * 1024 * 1024, 5).open("job", in_flight_ceiling=1)
    _, report = crawl(tmp_path, site, account)
    assert account.links_charged_bytes > 4 * 1024 * 1024
    assert account.stop_requested
    assert report.stopped_reason == MEMORY_BUDGET_REASON


class TestCreditLinks:
    def test_a_negative_count_is_refused(self):
        account = MemoryBudget(10**9, 5).open("a")
        with pytest.raises(ValueError, match="negative"):
            account.charge_links(-1)
        with pytest.raises(ValueError, match="negative"):
            account.credit_links(-1)

    def test_an_over_credit_is_clamped_and_logged(self, monkeypatch, allow_over_credit):
        errors: list[dict[str, object]] = []
        monkeypatch.setattr(
            memory_budget._logger,
            "error",
            lambda event, extra: errors.append({"event": event, **extra}),
        )
        account = MemoryBudget(10**9, 5).open("job-9")
        account.charge(1000)
        account.charge_links(300)
        account.credit_links(500)
        assert account.links_credited_bytes == 300
        assert account.charged_bytes == 1000, "the body charge is untouched"
        assert errors == [
            {
                "event": "crawl_memory_budget_over_credit",
                "job_id": "job-9",
                "requested_bytes": 500,
                "outstanding_link_bytes": 300,
            }
        ]

    def test_a_link_credit_never_selects_a_victim(self):
        budget = MemoryBudget(1000, 5)  # share 200
        mid = budget.open("mid")
        mid.charge(300)  # projected 600, under budget
        big = budget.open("big")
        big.charge(100)
        big.charge_links(800)  # total over budget: the largest, big, is chosen
        assert big.stop_requested
        assert not mid.stop_requested
        big.credit_links(100)
        assert not mid.stop_requested, "a credit chose nobody"


def test_no_await_from_the_body_charge_to_the_body_credit_and_none_in_the_recording_loop():
    landing = ast.parse(textwrap.dedent(inspect.getsource(async_discovery._ahtml)))
    calls = {
        node.func.attr: node.lineno
        for node in ast.walk(landing)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"charge", "charge_links", "credit"}
    }
    assert calls["charge"] < calls["charge_links"] < calls["credit"]
    awaits = [node.lineno for node in ast.walk(landing) if isinstance(node, ast.Await)]
    assert not [line for line in awaits if calls["charge"] <= line <= calls["credit"]]

    crawl_tree = ast.parse(textwrap.dedent(inspect.getsource(async_discovery._acrawl)))
    (loop,) = (
        node
        for node in ast.walk(crawl_tree)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "results"
    )
    assert not any(isinstance(node, ast.Await) for node in ast.walk(loop))
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "credit_links"
        for node in ast.walk(loop)
    )
