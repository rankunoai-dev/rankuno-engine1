"""The 3-path merged discovery pipeline.

Produces `PageEvidence` — the contract every signal parser consumes and which,
until this module existed, nothing produced. This is the last structural gap
before an end-to-end crawl.

Why three paths
---------------
`docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md` is the empirical case. A sitemap audit
of highradius.com returned 3,145 URLs. A one-second DOM crawl of the homepage
alone surfaced pages absent from every sitemap: `/anti-corruption-and-bribery-policy/`,
`/code-of-ethics/`, `/human-rights-policy/`, `/glossary/`, `/finsider/`.

Sitemaps miss URLs systematically, not occasionally — orphaned campaign pages,
faceted filters generated client-side, and CMS drift where a plugin failed to
update `sitemap.xml`. Any one path alone under-reports.

    Path A  XML sitemaps    → what the webmaster published
    Path B  DOM link graph  → what is actually reachable
    Path C  CMS REST API    → what the database contains
                            ↓
              merged graph G = (V, E), with orphans flagged

An **orphan** is a page that exists in the sitemap or the CMS but has zero
inbound internal links. That is a genuine SEO finding, not a crawl artefact:
nothing on the site points at it, so neither users nor crawlers reach it.

Budget
------
Discovery is bounded by `max_pages` (ADR 0001: build for 20k–500k). The ceiling
is enforced and **reported**, never silently applied — a truncated crawl that
looks complete is worse than one that says it stopped.
"""

from __future__ import annotations

from collections import deque

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.integrations.http_fetcher import HttpFetcher
from src.modules.seo.page_classifier.discovery_parsers import (
    extract_page_links,
    parse_shopify_records,
    parse_sitemap,
    parse_wordpress_records,
)
from src.modules.seo.page_classifier.signal_parsers import CmsRecord, PageEvidence
from src.modules.seo.page_classifier.url_rules import is_faceted_filter, normalize_url
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

__all__ = [
    "DEFAULT_MAX_PAGES",
    "DiscoveredNode",
    "DiscoveryReport",
    "DiscoverySource",
    "SiteGraph",
    "discover_site",
]

_logger = get_logger("modules.seo.discovery")

DEFAULT_MAX_PAGES = 20_000
"""Node ceiling for one crawl job. ADR 0001 targets 20k–500k; beyond that the
in-memory implementations need replacing with the Bloom-filter path."""

_WORDPRESS_ENDPOINTS = (
    ("/wp-json/wp/v2/pages?per_page=100", "page"),
    ("/wp-json/wp/v2/posts?per_page=100", "post"),
)
_SHOPIFY_ENDPOINTS = (
    ("/products.json?limit=250", "products"),
    ("/collections.json?limit=250", "collections"),
)


class DiscoverySource(StrictModel):
    """Which paths surfaced a URL.

    Kept as flags rather than a single winner, because agreement between paths
    is itself information: a URL found by all three is certainly real, while one
    found only by a DOM link may be a generated artefact.

    Attributes:
        sitemap: Listed in an XML sitemap.
        dom_link: Reached by following a link from another page.
        cms_api: Present in the CMS database.
    """

    sitemap: bool = False
    dom_link: bool = False
    cms_api: bool = False

    @property
    def count(self) -> int:
        """How many independent paths surfaced this URL."""
        return sum((self.sitemap, self.dom_link, self.cms_api))


class DiscoveredNode(StrictModel):
    """One URL in the site graph, with everything discovery learned about it.

    Attributes:
        url: Absolute URL, as first seen.
        normalized: Canonical dedup key from `url_rules.normalize_url`.
        sources: Which paths surfaced it.
        sitemap_source: Grouped sitemap filename, if it came from one.
        cms_record: CMS record, if Path C found one.
        inbound_links: Internal links pointing at it.
        outbound_links: Internal links it emits.
        depth: Link distance from the crawl root, `None` if never linked.
    """

    url: str = Field(min_length=1)
    normalized: str = Field(min_length=1)
    sources: DiscoverySource = DiscoverySource()
    sitemap_source: str | None = None
    cms_record: CmsRecord | None = None
    inbound_links: int = Field(default=0, ge=0)
    outbound_links: int = Field(default=0, ge=0)
    depth: int | None = None

    @property
    def is_orphan(self) -> bool:
        """Whether nothing on the site links here.

        A real SEO finding. A page in the sitemap that no page links to is
        invisible to link-based discovery and accrues no internal authority.
        """
        return self.inbound_links == 0


class DiscoveryReport(StrictModel):
    """Summary of one discovery pass.

    Attributes:
        base_url: Crawl root.
        total_urls: Nodes in the merged graph.
        from_sitemap: Count surfaced by Path A.
        from_dom: Count surfaced by Path B.
        from_cms: Count surfaced by Path C.
        sitemap_only: Present in a sitemap but never linked — orphan candidates.
        dom_only: Reachable by link but absent from every sitemap. These are the
            pages a sitemap-only audit would miss entirely.
        orphans: Nodes with zero inbound internal links.
        sitemaps_fetched: Sitemap files successfully parsed.
        pages_fetched: Pages actually retrieved during the DOM crawl.
        truncated: Whether the page ceiling stopped discovery early.
    """

    base_url: str
    total_urls: int = Field(default=0, ge=0)
    from_sitemap: int = Field(default=0, ge=0)
    from_dom: int = Field(default=0, ge=0)
    from_cms: int = Field(default=0, ge=0)
    sitemap_only: int = Field(default=0, ge=0)
    dom_only: int = Field(default=0, ge=0)
    orphans: int = Field(default=0, ge=0)
    sitemaps_fetched: int = Field(default=0, ge=0)
    pages_fetched: int = Field(default=0, ge=0)
    truncated: bool = False


class SiteGraph:
    """Mutable builder for the merged site graph.

    A plain class rather than a model: it is assembled incrementally across
    three paths, and `validate_assignment` on every edge insertion would cost
    more than the validation is worth at 20,000 nodes. The values it *emits*
    (`DiscoveredNode`, `PageEvidence`, `DiscoveryReport`) are all strict models.
    """

    def __init__(self, base_url: str, max_pages: int = DEFAULT_MAX_PAGES) -> None:
        """Create an empty graph rooted at `base_url`."""
        self.base_url = base_url
        self.max_pages = max_pages
        self._nodes: dict[str, DiscoveredNode] = {}
        self._html: dict[str, str] = {}
        self.truncated = False

    def __len__(self) -> int:
        """Node count."""
        return len(self._nodes)

    @property
    def nodes(self) -> tuple[DiscoveredNode, ...]:
        """Every node, in discovery order."""
        return tuple(self._nodes.values())

    def at_capacity(self) -> bool:
        """Whether the node ceiling has been reached."""
        return len(self._nodes) >= self.max_pages

    def add(
        self,
        url: str,
        *,
        sitemap: bool = False,
        dom_link: bool = False,
        cms_api: bool = False,
        sitemap_source: str | None = None,
        cms_record: CmsRecord | None = None,
        depth: int | None = None,
    ) -> DiscoveredNode | None:
        """Insert or update a node, merging discovery sources.

        Returns:
            The node, or `None` if the ceiling refused a new one. Existing nodes
            are always updatable, so a full graph still records new evidence
            about URLs it already holds.
        """
        key = normalize_url(url)
        existing = self._nodes.get(key)

        if existing is None:
            if self.at_capacity():
                self.truncated = True
                return None
            existing = DiscoveredNode(url=url, normalized=key)
            self._nodes[key] = existing

        merged = existing.sources
        existing.sources = DiscoverySource(
            sitemap=merged.sitemap or sitemap,
            dom_link=merged.dom_link or dom_link,
            cms_api=merged.cms_api or cms_api,
        )
        if sitemap_source and not existing.sitemap_source:
            existing.sitemap_source = sitemap_source
        if cms_record is not None and existing.cms_record is None:
            existing.cms_record = cms_record
        if depth is not None and (existing.depth is None or depth < existing.depth):
            existing.depth = depth
        return existing

    def record_links(self, from_url: str, to_urls: tuple[str, ...], depth: int) -> list[str]:
        """Record outbound links and return every target that entered the graph.

        Returns targets regardless of whether the node already existed. A URL
        already known from the sitemap still has to be *fetched* by the DOM
        crawl, and returning only graph-new URLs would silently skip every page
        the sitemap listed — producing a report full of discovered URLs and
        almost no captured HTML. Crawl-visited bookkeeping belongs to the
        caller's frontier, not to the graph.

        Args:
            from_url: The linking page.
            to_urls: Absolute link targets.
            depth: Link distance of the linking page.

        Returns:
            Targets successfully recorded, for the caller's frontier to filter.
        """
        source = self._nodes.get(normalize_url(from_url))
        if source is not None:
            source.outbound_links += len(to_urls)

        recorded: list[str] = []
        for target in to_urls:
            node = self.add(target, dom_link=True, depth=depth + 1)
            if node is None:
                continue  # Ceiling reached; the graph refused a new node.
            node.inbound_links += 1
            recorded.append(target)
        return recorded

    def store_html(self, url: str, html: str) -> None:
        """Retain a page's HTML for later evidence assembly."""
        self._html[normalize_url(url)] = html

    def to_page_evidence(self, total_pages: int | None = None) -> tuple[PageEvidence, ...]:
        """Project the graph into the contract the signal parsers consume.

        This is the join between discovery and classification, and the reason
        this module exists.

        Args:
            total_pages: Crawl size for in-degree scaling. Defaults to the node
                count.

        Returns:
            One `PageEvidence` per node.
        """
        size = total_pages if total_pages is not None else len(self._nodes)
        return tuple(
            PageEvidence(
                url=node.url,
                normalized_path=node.normalized,
                html=self._html.get(node.normalized),
                sitemap_source=node.sitemap_source,
                cms_record=node.cms_record,
                inbound_internal_links=node.inbound_links,
                outbound_internal_links=node.outbound_links,
                total_pages_in_crawl=size,
            )
            for node in self._nodes.values()
        )

    def report(self) -> DiscoveryReport:
        """Summarise what each path contributed."""
        nodes = self._nodes.values()
        return DiscoveryReport(
            base_url=self.base_url,
            total_urls=len(self._nodes),
            from_sitemap=sum(1 for n in nodes if n.sources.sitemap),
            from_dom=sum(1 for n in nodes if n.sources.dom_link),
            from_cms=sum(1 for n in nodes if n.sources.cms_api),
            sitemap_only=sum(1 for n in nodes if n.sources.sitemap and not n.sources.dom_link),
            dom_only=sum(1 for n in nodes if n.sources.dom_link and not n.sources.sitemap),
            orphans=sum(1 for n in nodes if n.is_orphan),
            truncated=self.truncated,
        )


def discover_site(
    fetcher: HttpFetcher,
    base_url: str,
    *,
    site_profile: SiteProfile | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = 5,
    crawl_dom: bool = True,
) -> tuple[SiteGraph, DiscoveryReport]:
    """Run all three discovery paths and merge them into one graph.

    Args:
        fetcher: Safety-wired fetcher. Every request inherits SSRF validation,
            robots compliance and per-host throttling from it.
        base_url: Site root.
        site_profile: Platform hints from the probe pass. Path C is skipped for
            an unrecognised platform rather than guessed at.
        max_pages: Node ceiling.
        max_depth: Link depth for the DOM crawl.
        crawl_dom: Disable to run sitemap and CMS discovery only — much cheaper,
            at the cost of missing exactly the pages Path B exists to find.

    Returns:
        The merged graph and its report.
    """
    graph = SiteGraph(base_url, max_pages=max_pages)

    sitemaps_fetched = _discover_from_sitemaps(fetcher, base_url, graph)
    _discover_from_cms(fetcher, base_url, graph, site_profile)
    pages_fetched = _crawl_dom(fetcher, base_url, graph, max_depth) if crawl_dom else 0

    report = graph.report().model_copy(
        update={"sitemaps_fetched": sitemaps_fetched, "pages_fetched": pages_fetched}
    )
    _logger.info("discovery_complete", extra=report.model_dump())
    return graph, report


def _discover_from_sitemaps(fetcher: HttpFetcher, base_url: str, graph: SiteGraph) -> int:
    """Path A — walk the sitemap index and every child sitemap."""
    root = base_url.rstrip("/")
    pending = deque([f"{root}/sitemap_index.xml", f"{root}/sitemap.xml"])
    visited: set[str] = set()
    parsed_count = 0

    while pending:
        sitemap_url = pending.popleft()
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        body = _safe_body(fetcher, sitemap_url)
        if body is None:
            continue

        document = parse_sitemap(body, source_name=sitemap_url.rsplit("/", 1)[-1])
        if document.kind.name == "UNKNOWN":
            continue
        parsed_count += 1

        if document.is_index:
            pending.extend(loc for loc in document.locations if loc not in visited)
            continue

        for location in document.locations:
            graph.add(location, sitemap=True, sitemap_source=document.source_name)

    return parsed_count


def _discover_from_cms(
    fetcher: HttpFetcher,
    base_url: str,
    graph: SiteGraph,
    site_profile: SiteProfile | None,
) -> None:
    """Path C — read the CMS database directly.

    Skipped entirely for an unrecognised platform. Probing endpoints that are
    not there wastes requests and, on a sensitive host, looks like scanning.
    """
    if site_profile is None or site_profile.cms_family is CmsFamily.UNKNOWN:
        return

    root = base_url.rstrip("/")

    if site_profile.cms_family is CmsFamily.WORDPRESS:
        for path, record_type in _WORDPRESS_ENDPOINTS:
            body = _safe_body(fetcher, f"{root}{path}")
            if body is None:
                continue
            for url, record in parse_wordpress_records(body, record_type).items():
                graph.add(url, cms_api=True, cms_record=record)

    elif site_profile.cms_family is CmsFamily.SHOPIFY:
        for path, collection in _SHOPIFY_ENDPOINTS:
            body = _safe_body(fetcher, f"{root}{path}")
            if body is None:
                continue
            for url, record in parse_shopify_records(body, root, collection=collection).items():
                graph.add(url, cms_api=True, cms_record=record)


def _crawl_dom(fetcher: HttpFetcher, base_url: str, graph: SiteGraph, max_depth: int) -> int:
    """Path B — breadth-first link traversal from the root.

    Breadth-first rather than depth-first so that when the ceiling is hit, what
    was captured is the shallow, structurally important part of the site rather
    than one arbitrarily deep branch.
    """
    graph.add(base_url, dom_link=True, depth=0)
    frontier: deque[tuple[str, int]] = deque([(base_url, 0)])
    seen: set[str] = {normalize_url(base_url)}
    fetched = 0

    while frontier:
        url, depth = frontier.popleft()
        if depth > max_depth or graph.at_capacity():
            continue

        # Filter permutations are classified from the URL alone; fetching them
        # is the combinatorial trap the Amazon-scale rules exist to avoid.
        if is_faceted_filter(url):
            continue

        result = _safe_fetch_html(fetcher, url)
        if result is None:
            continue
        fetched += 1
        graph.store_html(url, result)

        links = extract_page_links(result, url)
        for target in graph.record_links(url, links, depth):
            key = normalize_url(target)
            if key not in seen:
                seen.add(key)
                frontier.append((target, depth + 1))

    return fetched


def _safe_body(fetcher: HttpFetcher, url: str) -> str | None:
    """Fetch a URL, returning `None` for any failure or non-2xx."""
    try:
        result = fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("discovery_fetch_failed", extra={"url": url, "error": str(exc)})
        return None
    return result.body if result.ok else None


def _safe_fetch_html(fetcher: HttpFetcher, url: str) -> str | None:
    """Fetch a URL, returning its body only when it is HTML."""
    try:
        result = fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop discovery
        _logger.debug("discovery_fetch_failed", extra={"url": url, "error": str(exc)})
        return None
    return result.body if result.ok and result.is_html else None
