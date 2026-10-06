"""A checkpoint taken mid-level must already know which pages were fetched.

The async crawl is level-synchronous: a whole BFS level is gathered before any
of it is processed. A checkpoint is offered after every page, so if "fetched"
were only recorded once the level ended, every checkpoint taken inside a level
would report that level as unfetched. A resumed crawl seeds everything at depth
0, which makes its entire run one level — so a resumed crawl that died recorded
nothing as fetched, and resuming it again re-downloaded the whole site
(groundsguys.com: "+7,238" died at 2,011 pages; its resume offered "+7,972").

Concurrency is pinned to 1 throughout. With one slot, the next fetch cannot
start until the previous page's checkpoint has run, so "the pages the server
has answered" is exactly "the fetches that have completed" at every snapshot,
and the invariant can be stated as an equality rather than a bound.
"""

from __future__ import annotations

import asyncio

import httpx
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import SiteGraph

PUBLIC_IP = "93.184.216.34"
BASE = "https://e.com"
LEAF = "<html><body><p>leaf</p></body></html>"

Route = tuple[int, str, str]
"""`(status, content-type, body)` for one path."""


def _html(body: str) -> Route:
    return 200, "text/html", body


class _Recorder:
    """Serves a route table and snapshots `unfetched_urls()` at every checkpoint."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.served: list[str] = []
        self.snapshots: list[tuple[frozenset[str], frozenset[str]]] = []
        """`(page paths answered so far, unfetched page paths)` per checkpoint."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        route = self.routes.get(path)
        if route is None:
            return httpx.Response(404, text="not found")
        self.served.append(path)
        status, content_type, body = route
        return httpx.Response(status, text=body, headers={"content-type": content_type})

    def sink(self, graph: SiteGraph) -> None:
        if not len(graph):
            # The pre-crawl checkpoint. Sitemap discovery has already requested
            # the homepage by then, looking for sitemap links, but that probe
            # is not a page fetch and the graph is still empty.
            return
        unfetched = {httpx.URL(url).path for url in graph.unfetched_urls()}
        self.snapshots.append((frozenset(self.served), frozenset(unfetched & set(self.routes))))

    def crawl(self, settings, **kwargs: object) -> SiteGraph:
        fetcher = HttpFetcher(
            settings=settings,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            transport=httpx.MockTransport(self.handler),
            async_transport=httpx.MockTransport(self.handler),
        )

        async def scenario() -> SiteGraph:
            async with fetcher:
                graph, _ = await adiscover_site(
                    fetcher, BASE, concurrency=1, on_checkpoint=self.sink, **kwargs
                )
                return graph

        return asyncio.run(scenario())


SEEDS = tuple(f"/s{n}/" for n in range(6))


class TestAMidLevelCheckpointKnowsWhatWasFetched:
    def test_level_zero_of_a_resumed_crawl(self, settings):
        """The production shape: every seed at depth 0, so the run is one level."""
        recorder = _Recorder({"/": _html(LEAF), **{seed: _html(LEAF) for seed in SEEDS}})
        recorder.crawl(settings, seed_urls=tuple(f"{BASE}{seed}" for seed in SEEDS))

        mid_level = [s for s in recorder.snapshots if s[0] and len(s[0]) < 1 + len(SEEDS)]
        assert mid_level, "no checkpoint was taken inside level 0"
        for served, unfetched in recorder.snapshots:
            assert not served & unfetched, f"fetched pages checkpointed as unfetched: {served}"

    def test_a_level_below_the_root(self, settings):
        """Depth > 0: the root's children, checkpointed while their level runs."""
        children = ("/a/", "/b/", "/c/", "/d/")
        home = "".join(f'<a href="{child}">x</a>' for child in children)
        recorder = _Recorder(
            {"/": _html(f"<html><body>{home}</body></html>"), **{c: _html(LEAF) for c in children}}
        )
        recorder.crawl(settings)

        mid_level_one = [
            s for s in recorder.snapshots if "/a/" in s[0] and not set(children) <= s[0]
        ]
        assert mid_level_one, "no checkpoint was taken inside level 1"
        for served, unfetched in mid_level_one:
            assert not served & unfetched, f"fetched pages checkpointed as unfetched: {served}"

    def test_a_fetch_not_yet_made_stays_unfetched(self, settings):
        """The other half of the equality: nothing is marked fetched early."""
        recorder = _Recorder({"/": _html(LEAF), **{seed: _html(LEAF) for seed in SEEDS}})
        recorder.crawl(settings, seed_urls=tuple(f"{BASE}{seed}" for seed in SEEDS))

        for served, unfetched in recorder.snapshots:
            assert unfetched == {"/", *SEEDS} - served


class TestAFetchThatYieldedNoPageStaysUnfetched:
    """Errors and non-HTML answers are not "fetched": no HTML was kept for them.

    An error is worth retrying on a resume — a 5xx or a timeout is frequently
    transient. A non-HTML 200 would be re-requested too; that is the price of
    keeping one definition of fetched (stored HTML) rather than two that could
    disagree, and media URLs never enter the graph to begin with.
    """

    def test_errors_and_non_html_remain_after_the_crawl(self, settings):
        home = '<a href="/ok/">ok</a><a href="/broken/">b</a><a href="/data/">d</a>'
        recorder = _Recorder(
            {
                "/": _html(f"<html><body>{home}</body></html>"),
                "/ok/": _html(LEAF),
                "/broken/": (500, "text/html", "boom"),
                "/data/": (200, "application/json", "{}"),
            }
        )
        graph = recorder.crawl(settings)

        unfetched = {httpx.URL(url).path for url in graph.unfetched_urls()}
        assert unfetched == {"/broken/", "/data/"}
        _, last = recorder.snapshots[-1]
        assert "/ok/" not in last
