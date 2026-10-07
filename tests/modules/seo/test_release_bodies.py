"""Page bodies are released once read, and the memory budget follows them (ADR 0035).

Numbers refer to the required tests of the P4 security review. Every crawl here
runs through a real `HttpFetcher` over `httpx.MockTransport`.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from src.core.config import reset_settings_cache
from src.core.memory_budget import LEAN_PAGE_BYTES, MemoryAccount, MemoryBudget
from src.integrations.http_fetcher import FetchResult
from src.modules.seo.page_classifier import async_discovery
from src.modules.seo.page_classifier import tool as tool_module
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import (
    MAX_BREADCRUMB_LABEL_CHARS,
    DiscoveryReport,
    SiteGraph,
)
from src.modules.seo.page_classifier.signal_parsers import MAX_SCHEMA_TYPE_CHARS, MAX_SCHEMA_TYPES
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool

from tests.modules.seo.golden_site_factory import (
    BASE,
    Route,
    build_fetcher,
    build_site,
    golden_settings,
)

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")
HOME = (
    "<html><head><title>Home</title></head><body><header><nav><ul>"
    '<li><a href="/a/">A</a></li><li><a href="/b/">B</a></li></ul></nav></header>'
    '<a href="/moved/">m</a></body></html>'
)
CRUMB = '<nav aria-label="breadcrumb"><ol><li><a href="/a/">A</a></li><li>Here</li></ol></nav>'
TYPED = '<script type="application/ld+json">{"@type": "Product"}</script>'


def small_site(homepage: Route | None = None) -> dict[str, Route]:
    return {
        "/robots.txt": ROBOTS,
        "/": homepage or Route(301, "text/html", "", "/home/"),
        "/home/": Route(200, "text/html", HOME),
        "/a/": Route(200, "text/html", f"<title>A</title>{TYPED}<a href='/a/1/'>1</a>"),
        "/a/1/": Route(200, "text/html", f"{CRUMB}<h1>One</h1>"),
        "/b/": Route(200, "text/html", "<p>b — wide</p>"),
        "/moved/": Route(301, "text/html", "", "/landing/"),
        "/landing/": Route(200, "text/html", f'<link rel="canonical" href="{BASE}/x/">'),
    }


def crawl(
    tmp_path: Path,
    site: dict[str, Route],
    *,
    release: bool,
    account: MemoryAccount | None = None,
    base: str = BASE,
    seed: int = 1,
    **kwargs: Any,
) -> tuple[SiteGraph, DiscoveryReport]:
    fetcher = build_fetcher(golden_settings(tmp_path), site, seed=seed)

    async def scenario() -> tuple[SiteGraph, DiscoveryReport]:
        async with fetcher:
            return await adiscover_site(
                fetcher, base, memory_account=account, release_bodies=release, **kwargs
            )

    return asyncio.run(scenario())


def body_bytes(site: dict[str, Route], path: str) -> int:
    return sys.getsizeof(site[path].body)


@pytest.fixture
def ledger(monkeypatch) -> dict[str, list[Any]]:
    """Every charge and credit, in order, with the projected total after each."""
    seen: dict[str, list[Any]] = {"charges": [], "credits": [], "stores": []}
    charge, credit, store = MemoryBudget.charge, MemoryBudget.credit, SiteGraph.store_html

    def spy_charge(self, account, nbytes, *, overhead_bytes=0) -> None:
        charge(self, account, nbytes, overhead_bytes=overhead_bytes)
        seen["charges"].append(
            (
                nbytes,
                overhead_bytes,
                account.projected_bytes,
                account.charged_bytes,
                account.landed_body_bytes,
            )
        )

    def spy_credit(self, account, nbytes) -> None:
        credit(self, account, nbytes)
        seen["credits"].append(nbytes)

    def spy_store(self, url, html) -> bool:
        released = store(self, url, html)
        seen["stores"].append((url, sys.getsizeof(html), released))
        return released

    monkeypatch.setattr(MemoryBudget, "charge", spy_charge)
    monkeypatch.setattr(MemoryBudget, "credit", spy_credit)
    monkeypatch.setattr(SiteGraph, "store_html", spy_store)
    return seen


def test_1_release_off_charges_exactly_as_adr_0031(tmp_path, ledger):
    """One charge per body as it lands, no overhead, no credit, the 0031 projection."""
    account = MemoryBudget(10**12, 5).open("job", in_flight_ceiling=10)
    graph, _ = crawl(tmp_path, build_site(), release=False, account=account)
    assert ledger["credits"] == []
    assert [c[0] for c in ledger["charges"]] == [s[1] for s in ledger["stores"]]
    for index, (_nbytes, overhead, projected, charged, landed) in enumerate(ledger["charges"]):
        assert overhead == 0
        assert charged == landed, "nothing but bodies, as in ADR 0031"
        assert projected == charged + 10 * (charged // (index + 1))
    assert not any(released for *_, released in ledger["stores"])
    assert graph.loop_urls_skipped > 0, "evictions happened and charged nothing back"


def test_2_release_on_charges_lean_plus_kept_and_credits_all_but_the_homepage(tmp_path):
    site = small_site()
    account = MemoryBudget(10**12, 5).open("job")
    graph, _ = crawl(tmp_path, site, release=True, account=account)
    fetched = [node.url for node in graph.nodes if node.url not in graph.unfetched_urls()]
    kept = sum(graph.retained_page_bytes(url) for url in fetched)
    homepage = body_bytes(site, "/home/")
    assert account.pages == len(fetched) == 5  # `/landing/` is a destination, not a node
    assert account.charged_bytes == account.pages * LEAN_PAGE_BYTES + kept + homepage
    assert account.credited_body_bytes == account.landed_body_bytes - homepage
    assert kept > 0, "the canonical, title, breadcrumb and type are charged"


@pytest.mark.parametrize("base", ["https://e.com", "https://e.com/", "https://E.COM/"])
def test_3_the_homepage_is_kept_through_a_redirect_and_any_spelling_of_the_root(tmp_path, base):
    graph, _ = crawl(tmp_path, small_site(), release=True, base=base)
    assert list(graph._html) == [f"{BASE}/"], "exactly one body is held"
    assert graph.html_for(base) == HOME

    tool = PageClassificationTool(fetcher=build_fetcher(golden_settings(tmp_path), small_site()))
    result = tool.run(PageClassificationInput(base_url=base))
    assert result.data is not None
    assert result.data.nav_coverage.nav_entries == 2, "the menu was read after release"


@pytest.mark.parametrize(
    ("root", "stored_as"),
    [
        ("https://E.COM", "https://e.com/"),
        ("https://e.com/", "https://e.com"),
        ("https://e.com", "https://E.com/"),
    ],
)
def test_3_the_homepage_is_recognised_by_normalised_key_not_spelling(root, stored_as):
    """In a crawl the root is always requested as given; the key rule is the guarantee."""
    graph = SiteGraph(root, release_bodies=True)
    assert graph.store_html(stored_as, HOME) is False
    assert graph.html_for(root) == HOME
    assert graph.store_html(f"{BASE}/other/", "<p>x</p>") is True


def test_4_seeds_that_normalise_to_the_homepage_are_fetched_and_credited_once(tmp_path, ledger):
    site = small_site(Route(200, "text/html", HOME))
    account = MemoryBudget(10**12, 5).open("job")
    seeds = ("https://e.com/", "https://E.COM", "https://e.com")
    crawl(tmp_path, site, release=True, account=account, seed_urls=seeds)
    home_stores = [s for s in ledger["stores"] if s[0].lower().rstrip("/") == BASE]
    assert len(home_stores) == 1
    assert account.credited_body_bytes == account.landed_body_bytes - body_bytes(site, "/")


def test_5_an_extraction_error_never_credits_and_aborts_as_before(tmp_path, monkeypatch, ledger):
    real = async_discovery.extract_page_links

    def failing(html: str, base_url: str, **kwargs: Any) -> tuple[str, ...]:
        if base_url.endswith("/b/"):
            raise RuntimeError("boom")
        return real(html, base_url, **kwargs)

    monkeypatch.setattr(async_discovery, "extract_page_links", failing)
    site = small_site()
    account = MemoryBudget(10**12, 5).open("job")
    graph, report = crawl(tmp_path, site, release=True, account=account)
    assert report.stopped_reason == "RuntimeError: boom"
    released = [size for _url, size, was in ledger["stores"] if was]
    b_body = body_bytes(site, "/b/")
    assert sum(ledger["credits"]) == sum(released) - b_body, "the failing page's body stays charged"
    assert f"{BASE}/b/" not in graph.unfetched_urls()


def test_12_what_a_hostile_page_keeps_is_bounded_and_charged(tmp_path):
    """A page at every cap at once, built from multi-megabyte inputs."""
    wide = "\U0001f600"
    labels = "".join(f'<li><a href="/s{i}/">{"中" * 1_000_000}{i}</a></li>' for i in range(30))
    types = [
        {"@type": f"https://t{i}.example/{'a' * 200}/Product"} for i in range(MAX_SCHEMA_TYPES * 3)
    ]
    canonical = f"{BASE}/" + "é" * 2040
    html = (
        f"<html><head><title>{wide * 2000}</title>"
        f'<meta name="description" content="{wide * 2000}">'
        f'<link rel="canonical" href="{canonical}">'
        f'<script type="application/ld+json">{json.dumps({"@graph": types})}</script>'
        f'</head><body><nav aria-label="breadcrumb"><ol>{labels}</ol></nav>'
        f"<h1>{wide * 5000}</h1></body></html>"
    )
    hops = tuple(f"{BASE}/{i}" + "h" * 2040 for i in range(5))
    url = f"{BASE}/p/"
    graph = SiteGraph(BASE, release_bodies=True)
    graph.add(url, dom_link=True)
    graph.record_fetch(
        url,
        FetchResult(
            requested_url=url,
            final_url=hops[-1],
            status_code=200,
            content_type="text/html",
            body=html,
            redirect_chain=hops[:-1],
        ),
    )
    assert graph.store_html(url, html) is True
    kept = graph.retained_page_bytes(url)

    def worst(chars: int) -> int:
        return sys.getsizeof(wide * chars)

    bound = (
        worst(500) * 2
        + worst(1000)  # title, meta, H1 (content_signals caps)
        + worst(2048) * 2
        + worst(2048 + 200)  # canonical, final URL, verdict quoting it
        + sys.getsizeof(hops)
        + worst(2048) * 5  # five redirect hops
        + sys.getsizeof(tuple(range(12)))
        + worst(MAX_BREADCRUMB_LABEL_CHARS) * 12
        + sys.getsizeof(tuple(range(8)))
        + worst(MAX_SCHEMA_TYPE_CHARS) * MAX_SCHEMA_TYPES
    )
    assert len(html) > 30_000_000
    assert kept <= bound <= 128 * 1024, (kept, bound)


def test_13_the_flag_is_operator_configuration_read_once_per_crawl(tmp_path, monkeypatch):
    with pytest.raises(ValidationError):
        PageClassificationInput(base_url=BASE, crawl_release_page_html=False)  # type: ignore[call-arg]

    constructed: list[bool] = []
    real_init = SiteGraph.__init__

    def spy_init(self, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        constructed.append(self.release_bodies)

    reads: list[int] = []
    real_get = tool_module.get_settings

    def counting_get() -> Any:
        reads.append(1)
        return real_get()

    monkeypatch.setattr(SiteGraph, "__init__", spy_init)
    monkeypatch.setattr(tool_module, "get_settings", counting_get)
    for value, expected in (("false", False), ("true", True)):
        monkeypatch.setenv("CRAWL_RELEASE_PAGE_HTML", value)
        reset_settings_cache()
        constructed.clear()
        reads.clear()
        tool = PageClassificationTool(
            fetcher=build_fetcher(golden_settings(tmp_path), small_site())
        )
        tool.run(PageClassificationInput(base_url=BASE))
        assert constructed == [expected]
        assert len(reads) == 1, "read once per crawl"


@pytest.mark.parametrize("release", [True, False], ids=["release-on", "release-off"])
def test_14_eviction_never_credits(tmp_path, ledger, release):
    account = MemoryBudget(10**12, 5).open("job")
    graph, _ = crawl(tmp_path, build_site(), release=release, account=account)
    assert graph.loop_urls_skipped > 0
    released = [size for _url, size, was in ledger["stores"] if was]
    assert ledger["credits"] == released, "one credit per release, at land, and no others"
    if not release:
        assert ledger["credits"] == []


def test_c8_no_await_between_charge_and_credit():
    tree = ast.parse(textwrap.dedent(inspect.getsource(async_discovery._ahtml)))
    calls = {
        node.func.attr: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"charge", "credit"}
    }
    awaits = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Await)]
    assert set(calls) == {"charge", "credit"}
    assert not [line for line in awaits if calls["charge"] <= line <= calls["credit"]]
