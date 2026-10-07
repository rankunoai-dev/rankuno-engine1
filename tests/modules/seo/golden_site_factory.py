"""A deterministic ~500-page site, served in-process, for the golden-equivalence test.

Built for the extract-at-fetch work (crawls stop retaining every page body). That
change moves *when* page HTML is read, so the proof it needs is that nothing a
crawl produces moves with it. The site is shaped to exercise every consumer of a
body the investigation found, and every way a URL can end up unfetched:

* the homepage redirects (`/` -> `/home/`), and its header menu is read after
  the crawl from the body stored under the *requested* key;
* breadcrumbs in both published forms (DOM markup and `BreadcrumbList` JSON-LD);
* JSON-LD page types, including one deliberately broken block;
* a cross-directory redirect whose page links relatively (`/moved/` ->
  `/new/sub/`), so link resolution against the landed URL is covered;
* a linked 404, a PDF answering `200` at a suffix-less URL, and an HTML `200`
  with an empty body — which *is* fetched, and must stay so;
* a relative-href loop wide enough to be confirmed, so fetched nodes are
  evicted mid-crawl;
* sitemap-only orphans and non-ASCII pages.

It deliberately avoids the five places the serial and async paths are known to
differ (transport errors, stalls, depth caps, cancellation, memory budgets), so
the two must agree byte for byte.

Determinism: every random choice comes from `random.Random` seeded with a
*string*, which CPython hashes with SHA-512 — independent of `PYTHONHASHSEED`.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any, ClassVar, NamedTuple

import httpx
from src.core.config import Environment, Settings
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.http_fetcher import HttpFetcher

BASE = "https://e.com"
PUBLIC_IP = "93.184.216.34"
LOOP_TAIL = "tools/roi/calc/"
"""Emitted as a *relative* href on every resources page, at four depths."""

MAX_YIELDS = 64
"""Upper bound on event-loop yields a response is delayed by, per path."""


class Route(NamedTuple):
    """One canned response."""

    status: int
    content_type: str
    body: str
    location: str | None = None


def _html(route_body: str) -> Route:
    return Route(200, "text/html; charset=utf-8", route_body)


def _page(
    rng: random.Random,
    path: str,
    links: list[str],
    *,
    crumbs: list[tuple[str, str]] | None = None,
    crumb_style: str = "dom",
    schema_type: str | None = None,
    extra: str = "",
) -> str:
    """Render one page. Title, meta and H1 vary so content signals differ."""
    name = path.strip("/").replace("/", " ").replace("-", " ") or "home"
    title = f"<title>{name.title()} | Example</title>" if rng.random() > 0.05 else ""
    meta = f'<meta name="description" content="About {name}.">' if rng.random() > 0.15 else ""
    blocks: list[dict[str, object]] = []
    if crumbs and crumb_style == "jsonld":
        items = [
            {"@type": "ListItem", "position": i + 1, "name": label, "item": f"{BASE}{href}"}
            for i, (label, href) in enumerate(crumbs)
        ]
        blocks.append(
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
        )
    if schema_type:
        blocks.append({"@context": "https://schema.org", "@type": schema_type, "name": name})
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    if rng.random() < 0.03:
        scripts += '<script type="application/ld+json">{"@type": "Product",</script>'
    nav = ""
    if crumbs and crumb_style == "dom":
        steps = "".join(f'<li><a href="{href}">{label}</a></li>' for label, href in crumbs)
        nav = f'<nav aria-label="breadcrumb"><ol>{steps}<li>{name}</li></ol></nav>'
    h1 = f"<h1>{name.title()}</h1>" * (2 if rng.random() < 0.05 else 1)
    body_links = "".join(f'<a href="{href}">{href}</a> ' for href in links)
    footer = '<footer><a href="/">Home</a> <a href="/privacy-policy/">Privacy</a></footer>'
    return (
        f"<!doctype html><html><head>{title}{meta}{scripts}</head><body>{nav}{h1}"
        f"<main>{extra}{body_links}</main>{footer}</body></html>"
    )


def build_site() -> dict[str, Route]:
    """Return the whole site as `path -> Route`. Pure and deterministic."""
    rng = random.Random("golden-0")  # noqa: S311 - fixture data, not security
    site: dict[str, Route] = {"/": Route(301, "text/html", "", "/home/")}
    linked: list[str] = []

    def add(path: str, links: list[str], **kwargs: Any) -> None:
        site[path] = _html(_page(rng, path, links, **kwargs))
        linked.append(path)

    services = [f"/services/s{i}/" for i in range(8)]
    products = [f"/products/c{i}/" for i in range(8)]
    sections = ["/services/", "/products/", "/blog/", "/resources/", "/about/", "/careers/"]
    menu = "".join(f'<li><a href="{hub}">{hub.strip("/").title()}</a></li>' for hub in sections)
    site["/home/"] = _html(
        f"<!doctype html><html><head><title>Example Co</title></head><body>"
        f"<header><nav><ul>{menu}</ul></nav></header><h1>Welcome</h1>"
        f'<a href="/moved/">Moved</a> <a href="{services[0]}">Featured</a>'
        f'<a href="/terms/">Terms</a></body></html>'
    )

    add("/services/", services, schema_type="CollectionPage")
    for i, hub in enumerate(services):
        subs = [f"{hub}sub{j}/" for j in range(4)]
        add(
            hub,
            subs,
            crumbs=[("Home", "/"), ("Services", "/services/")],
            schema_type="Service" if i % 2 else None,
        )
        for sub in subs:
            add(sub, [], crumbs=[("Home", "/"), ("Services", "/services/"), (f"S{i}", hub)])

    add("/products/", products)
    for i, category in enumerate(products):
        items = [f"{category}p{j}/" for j in range(15)]
        add(
            category,
            items,
            schema_type="CollectionPage",
            crumbs=[("Home", "/"), ("Products", "/products/")],
            crumb_style="jsonld",
        )
        for item in items:
            add(
                item,
                [],
                schema_type="Product",
                crumb_style="jsonld",
                crumbs=[("Home", "/"), ("Products", "/products/"), (f"C{i}", category)],
            )

    posts = [f"/blog/post-{k}/" for k in range(210)]
    pages = [f"/blog/page/{n}/" for n in range(2, 22)]
    add("/blog/", [*posts[:10], pages[0]], schema_type="Blog")
    for n, listing in enumerate(pages):
        nxt = [pages[n + 1]] if n + 1 < len(pages) else []
        add(listing, [*posts[(n + 1) * 10 : (n + 2) * 10], *nxt])
    for k, post in enumerate(posts):
        kind = "FAQPage" if k % 7 == 0 else ("BlogPosting" if k % 3 else None)
        extra = "<p>Café — naïve résumé</p>" if k % 11 == 0 else ""
        add(post, [posts[(k + 1) % len(posts)]], schema_type=kind, extra=extra)

    # Every resources page renders `LOOP_TAIL` relatively, at path depths 1-4, so
    # its copies span four depths and more than `MIN_LOOP_URLS` parents.
    loop_href = f'<a href="{LOOP_TAIL}">ROI calculator</a>'
    level1 = [f"/resources/r{i}/" for i in range(6)]
    add("/resources/", [*level1, "/resources/whitepaper-download/"], extra=loop_href)
    for r1 in level1:
        level2 = [f"{r1}d{j}/" for j in range(3)]
        add(r1, level2, extra=loop_href)
        for r2 in level2:
            level3 = [f"{r2}e{k}/" for k in range(2)]
            add(r2, level3, extra=loop_href)
            for r3 in level3:
                add(r3, [], extra=loop_href)
    site["/resources/whitepaper-download/"] = Route(200, "application/pdf", "%PDF-1.4 binary")

    add("/about/", ["/about/team/", "/about/contact/", "/about/history/"], schema_type="AboutPage")
    add("/about/team/", [])
    add("/about/contact/", [], schema_type="ContactPage")
    add("/about/history/", [])

    jobs = [f"/careers/job-{i}/" for i in range(20)]
    add("/careers/", [*jobs, "/careers/empty/", "/careers/old-role/"])
    for job in jobs:
        add(job, [], crumbs=[("Home", "/"), ("Careers", "/careers/")])
    site["/careers/empty/"] = _html("")
    # `/careers/old-role/` is linked and deliberately absent: a 404.

    site["/moved/"] = Route(301, "text/html", "", "/new/sub/")
    add("/new/sub/", ["child/", "../sibling/"])
    add("/new/sub/child/", [])
    add("/new/sibling/", [])
    add("/privacy-policy/", [])
    add("/terms/", [])

    orphans = [f"/campaign/{i}/" for i in range(6)]
    for orphan in orphans:
        site[orphan] = _html(_page(rng, orphan, []))
    listed = [path for path in linked if rng.random() < 0.7] + orphans
    urls = "".join(f"<url><loc>{BASE}{path}</loc></url>" for path in listed)
    site["/sitemap.xml"] = Route(
        200,
        "application/xml",
        f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>",
    )
    site["/robots.txt"] = Route(200, "text/plain", "User-agent: *\nDisallow:\n")
    return site


def _respond(site: dict[str, Route], path: str) -> httpx.Response:
    route = site.get(path)
    if route is None and path.endswith(f"/{LOOP_TAIL}"):
        # The fabricated loop copies all answer, as the real site's did.
        route = _html(f'<html><body><a href="{LOOP_TAIL}">ROI</a></body></html>')
    if route is None:
        return httpx.Response(404, text="not found")
    headers = {"content-type": route.content_type}
    if route.location is not None:
        headers["location"] = route.location
    return httpx.Response(route.status, content=route.body.encode("utf-8"), headers=headers)


def golden_settings(tmp: Path) -> Settings:
    """Hermetic settings with throttling effectively off: the site is in-process."""
    return Settings(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        audit_log_path=tmp / "audit.jsonl",
        max_session_spend_usd=1.0,
        default_requests_per_minute=60_000_000,
        default_timeout_s=5.0,
    )


class GoldenFetcher(HttpFetcher):
    """An `HttpFetcher` with its own process-wide quota bucket.

    `BaseAPIClient` throttles every fetcher sharing a `rate_limit_key` through
    one process-wide bucket (600/min for `HttpFetcher`). A 500-page serial crawl
    drains it in the first run and then paces at 10/s — 45 s per run, for a
    site that is a Python dict. A key of its own leaves real fetchers untouched.
    """

    rate_limit_key: ClassVar[str] = "tests.golden_site"
    requests_per_minute: ClassVar[int] = 60_000_000


def build_fetcher(
    settings: Settings,
    site: dict[str, Route],
    *,
    seed: int | None = None,
    completions: list[str] | None = None,
) -> HttpFetcher:
    """A fetcher answering from `site` on both transports.

    `seed` shuffles async completion order deterministically: each response is
    held back by a per-path number of `asyncio.sleep(0)` yields. Yields, not
    timers, so the order depends only on the seed and never on wall-clock time.
    `completions` records the order async responses were handed back in.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return _respond(site, request.url.path)

    async def ahandler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seed is not None:
            delay = random.Random(f"{seed}:{path}").randrange(MAX_YIELDS)  # noqa: S311
            for _ in range(delay):
                await asyncio.sleep(0)
        if completions is not None:
            completions.append(path)
        return _respond(site, path)

    return GoldenFetcher(
        settings=settings,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(ahandler),
    )
