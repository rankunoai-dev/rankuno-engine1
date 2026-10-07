"""Every value read from a body and kept after it is released has a bound.

Extract-at-fetch (ADR 0035) releases page bodies, and the memory budget then
charges a page a flat amount plus what it measurably keeps. That is only safe if
what a page keeps cannot be made arbitrarily large by the page itself. These are
the adversarial cases from the P4 security review: a multi-megabyte breadcrumb
label, a type repeated 100,000 times, a 200,000-character canonical, a
redirect to an over-long address, and 300,000 distinct links.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from src.core.errors import UnsafeUrlError
from src.integrations.http_fetcher import MAX_FETCH_URL_LENGTH
from src.modules.seo.contracts.audit import MAX_URL_LENGTH
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import (
    MAX_BREADCRUMB_LABEL_CHARS,
    MAX_LINKS_PER_PAGE,
    SiteGraph,
    discover_site,
)
from src.modules.seo.page_classifier.signal_parsers import (
    MAX_SCHEMA_TYPE_CHARS,
    MAX_SCHEMA_TYPES,
    PageEvidence,
    extract_canonical_url,
    extract_schema_types,
    parse_jsonld_signal,
)

from tests.modules.seo.golden_site_factory import BASE, Route, build_fetcher, golden_settings

ROBOTS = Route(200, "text/plain", "User-agent: *\nDisallow:\n")


def jsonld(document: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(document)}</script>'


def stored_types(html: str) -> tuple[str, ...]:
    graph = SiteGraph(BASE)
    graph.add(f"{BASE}/p/", dom_link=True)
    graph.store_html(f"{BASE}/p/", html)
    return graph._jsonld_types.get(f"{BASE}/p/", ())


def signals_agree(html: str) -> None:
    """The homepage path (body) and every other page (stored types) must agree."""
    with_body = PageEvidence(url=f"{BASE}/", normalized_path="/", html=html)
    without = PageEvidence(url=f"{BASE}/p/", normalized_path="/p/", jsonld_types=stored_types(html))
    assert parse_jsonld_signal(with_body) == parse_jsonld_signal(without)


class TestBreadcrumbLabels:
    def test_a_multi_megabyte_label_is_truncated(self):
        label = "中" * (3 * 1024 * 1024 // 2)  # CJK: two bytes a character, 3 MiB
        html = (
            f'<nav aria-label="breadcrumb"><ol><li><a href="/shop/">{label}</a></li>'
            "<li>Here</li></ol></nav>"
        )
        graph = SiteGraph(BASE)
        graph.add(f"{BASE}/p/", dom_link=True)
        graph.store_html(f"{BASE}/p/", html)
        (kept,) = graph._breadcrumbs[f"{BASE}/p/"]
        assert kept == label[:MAX_BREADCRUMB_LABEL_CHARS]


class TestSchemaTypes:
    def test_a_type_repeated_100k_times_is_kept_once(self):
        html = jsonld({"@graph": [{"@type": "Product"}] * 100_000})
        assert extract_schema_types(html) == ("Product",)
        signals_agree(html)

    def test_at_most_eight_distinct_types_are_kept_and_the_first_still_wins(self):
        names = ["Article", "Product", "Service", "AboutPage", "ContactPage", "Blog",
                 "FAQPage", "ItemPage", "CollectionPage", "WebApplication"]  # fmt: skip
        html = jsonld({"@graph": [{"@type": name} for name in names]})
        assert extract_schema_types(html) == tuple(names[:MAX_SCHEMA_TYPES])
        signals_agree(html)

    def test_an_over_long_recognised_type_is_ignored_on_both_paths(self):
        long_type = "https://evil.example/" + "a" * MAX_SCHEMA_TYPE_CHARS + "/Product"
        html = jsonld({"@graph": [{"@type": long_type}, {"@type": "Article"}]})
        assert extract_schema_types(html) == ("Article",)
        signals_agree(html)
        signal = parse_jsonld_signal(PageEvidence(url=f"{BASE}/", normalized_path="/", html=html))
        assert signal is not None
        assert signal.notes == "schema.org @type 'Article'"


class TestCanonical:
    def test_a_200k_character_canonical_is_dropped(self):
        href = f"{BASE}/" + "c" * 200_000
        assert extract_canonical_url(f'<link rel="canonical" href="{href}">', f"{BASE}/") == ""

    def test_the_limit_is_the_audit_contracts(self):
        at_limit = f"{BASE}/" + "c" * (MAX_URL_LENGTH - len(BASE) - 1)
        over = at_limit + "c"
        assert len(at_limit) == MAX_URL_LENGTH
        assert extract_canonical_url(f'<link rel="canonical" href="{at_limit}">', BASE) == at_limit
        assert extract_canonical_url(f'<link rel="canonical" href="{over}">', BASE) == ""


class TestRedirectHops:
    def test_the_fetcher_limit_is_the_audit_contracts(self):
        assert MAX_FETCH_URL_LENGTH == MAX_URL_LENGTH

    def test_a_redirect_to_an_over_long_url_is_refused_without_retry(self, tmp_path):
        target = "/" + "r" * MAX_URL_LENGTH
        site = {"/robots.txt": ROBOTS, "/go/": Route(301, "text/html", "", target)}
        fetcher = build_fetcher(golden_settings(tmp_path), site)
        with pytest.raises(UnsafeUrlError):
            fetcher.fetch(f"{BASE}/go/")

    @pytest.mark.parametrize("use_async", [False, True], ids=["serial", "async"])
    def test_the_crawl_records_it_as_a_guardrail_refusal(self, tmp_path, use_async):
        site = {
            "/robots.txt": ROBOTS,
            "/": Route(200, "text/html", '<a href="/go/">go</a>'),
            "/go/": Route(301, "text/html", "", "/" + "r" * MAX_URL_LENGTH),
        }
        fetcher = build_fetcher(golden_settings(tmp_path), site, seed=1 if use_async else None)
        if use_async:

            async def scenario() -> tuple[SiteGraph, object]:
                async with fetcher:
                    return await adiscover_site(fetcher, BASE)

            graph, report = asyncio.run(scenario())
        else:
            graph, report = discover_site(fetcher, BASE)
        assert report.fetch_outcomes.get("guardrail_refused") == 1
        assert f"{BASE}/go/" in graph.unfetched_urls()


class TestLinks:
    def test_300k_distinct_links_are_capped_in_document_order(self):
        graph = SiteGraph(BASE)
        links = tuple(f"{BASE}/{i}/" for i in range(300_000))
        kept = graph.cap_links(f"{BASE}/", links)
        assert kept == links[:MAX_LINKS_PER_PAGE]
        assert graph.links_capped == 300_000 - MAX_LINKS_PER_PAGE

    def test_a_second_reading_of_the_same_page_is_not_counted_twice(self):
        graph = SiteGraph(BASE)
        links = tuple(f"{BASE}/{i}/" for i in range(MAX_LINKS_PER_PAGE + 10))
        graph.cap_links(f"{BASE}/", links)
        graph.cap_links(f"{BASE}/", links, count=False)
        assert graph.links_capped == 10

    @pytest.mark.parametrize(
        ("use_async", "total"),
        [(False, MAX_LINKS_PER_PAGE + 7), (True, 300_000)],
        ids=["serial", "async-300k"],
    )
    def test_both_crawl_paths_apply_the_cap(self, tmp_path, use_async, total):
        """Up to 300,000 distinct links, compact enough to fit the 5 MiB body cap."""
        extra = total - MAX_LINKS_PER_PAGE
        body = "".join(f"<a href=/{i}/>" for i in range(total))
        assert len(body.encode()) < 5 * 1024 * 1024
        site = {"/robots.txt": ROBOTS, "/": Route(200, "text/html", body)}
        fetcher = build_fetcher(golden_settings(tmp_path), site, seed=1 if use_async else None)
        if use_async:

            async def scenario() -> SiteGraph:
                async with fetcher:
                    return (await adiscover_site(fetcher, BASE, max_pages=50))[0]

            graph = asyncio.run(scenario())
        else:
            graph = discover_site(fetcher, BASE, max_pages=50)[0]
        assert graph.links_capped == extra
        (home,) = (node for node in graph.nodes if node.url == BASE)
        assert home.outbound_links == MAX_LINKS_PER_PAGE
