"""The five structural consensus signals.

Every parser here is a **pure function over already-fetched content**. Nothing
in this module opens a socket: fetching belongs to a connector in
`src.integrations`, which is what makes the exclusion and classification rules
exhaustively testable offline and keeps `UrlSafetyPolicy` and `robots` on the
one code path that does reach the network.

The sixth signal, `LLM_ZERO_SHOT`, is not here. It is an escalation performed by
`cascading_pipeline` through `LLMClient`, not a parser over local evidence.

HTML parsing note
-----------------
`TECH_STACK_SPECIFICATION.md` selects `selectolax` for DOM parsing, and it will
be the right choice at crawl scale. It is deliberately *not* imported here: it
lives in the optional `seo` extra, CI installs only `[dev]`, and a module-level
import would break the build for a performance benefit that does not exist
until a crawler is actually running. The ARIA parser below uses the standard
library behind the same signature, so substituting `selectolax` later is a
change inside one function.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from html.parser import HTMLParser

from pydantic import Field

from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.schemas import (
    DiscoverySource,
    HierarchyLevel,
    PrimaryPageType,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.url_rules import normalize_path, strip_locale_prefix

__all__ = [
    "L1_HUB_INBOUND_LINK_THRESHOLD",
    "CmsRecord",
    "NavLink",
    "PageEvidence",
    "SignalParser",
    "collect_structural_signals",
    "extract_nav_links",
    "parse_aria_nav_signal",
    "parse_cms_endpoint_signal",
    "parse_jsonld_signal",
    "parse_link_indegree_signal",
    "parse_sitemap_signal",
]

SignalParser = Callable[["PageEvidence"], "SignalScore | None"]
"""A structural signal extractor: pure evidence in, optional opinion out.

Returning `None` means "this signal has nothing to say about this page", which
is materially different from a low-confidence opinion and must stay
distinguishable — an absent signal should not drag the consensus down."""

L1_HUB_INBOUND_LINK_THRESHOLD = 1_000
"""Inbound internal links above which a page is site-wide navigation.

From the blueprint. A page linked from every page of a large site is in the
header or footer, which makes it a primary hub by definition rather than by
inference. Scaled against site size below, since 1,000 links on a 200-page site
is impossible and on a 50,000-page site is unremarkable."""

# Schema.org @type values mapped onto the taxonomy. Only unambiguous types are
# listed; `WebPage` and `Thing` tell us nothing and are deliberately absent.
_SCHEMA_TYPE_MAP: dict[str, tuple[HierarchyLevel, PrimaryPageType]] = {
    "product": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.PRODUCT_DETAIL_PAGE),
    "itempage": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.PRODUCT_DETAIL_PAGE),
    "service": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.SERVICE_DETAIL_PAGE),
    "article": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    "blogposting": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    "newsarticle": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    "techarticle": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    "collectionpage": (HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.PRODUCT_CATEGORY_HUB),
    "aboutpage": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.COMPANY_ABOUT),
    "contactpage": (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.COMMERCIAL_LEAD_GEN),
    "faqpage": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    "blog": (HierarchyLevel.L1_PRIMARY_NAV_HUB, PrimaryPageType.BLOG_HUB),
    "softwareapplication": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.TOOL_APPLICATION),
    "webapplication": (HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.TOOL_APPLICATION),
}

# Sitemap filename fragments mapped onto the taxonomy. Grouped sitemaps are a
# webmaster's own declaration of what a URL is, which makes them high-value.
_SITEMAP_HINTS: tuple[tuple[str, HierarchyLevel, PrimaryPageType], ...] = (
    ("product", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.PRODUCT_DETAIL_PAGE),
    ("collection", HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.PRODUCT_CATEGORY_HUB),
    ("categor", HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.PRODUCT_CATEGORY_HUB),
    ("case-stud", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.CASE_STUDY),
    ("case_stud", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.CASE_STUDY),
    ("blog", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    ("post", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    ("news", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    ("resource", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.BLOG_ARTICLE),
    ("service", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.SERVICE_DETAIL_PAGE),
    ("software", HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.SERVICE_DETAIL_PAGE),
    ("global-page", HierarchyLevel.L1_PRIMARY_NAV_HUB, PrimaryPageType.COMPANY_ABOUT),
    ("page", HierarchyLevel.L1_PRIMARY_NAV_HUB, PrimaryPageType.SERVICE_CATEGORY_HUB),
)

_JSONLD_BLOCK_RE = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class NavLink(StrictModel):
    """One link found inside a navigation landmark.

    Attributes:
        href: The link target, as written in the markup.
        text: Visible anchor text, whitespace-collapsed.
        nav_depth: Nesting depth within the nav tree. 0 is a top-level item.
    """

    href: str
    text: str = ""
    nav_depth: int = Field(default=0, ge=0)


class CmsRecord(StrictModel):
    """A content record retrieved from a CMS API.

    The decisive signal for flat URLs: `site.com/capsules` has no path depth to
    read, but WordPress will state its parent ID outright and Shopify will say
    whether the handle is a product or a collection.

    Attributes:
        record_type: Platform's own type, e.g. `page`, `post`, `product`.
        parent_id: Parent record id. `0` or `None` means top level.
        parent_url: Resolved parent URL, if the crawler could map the id.
        has_children: Whether other records declare this one as parent.
    """

    record_type: str = Field(min_length=1)
    parent_id: int | None = None
    parent_url: str | None = None
    has_children: bool = False


class PageEvidence(StrictModel):
    """Everything known about one page before classification.

    Assembled by the crawler; consumed by the signal parsers. Modelled as a
    single contract so a parser cannot quietly acquire a new input without the
    change being visible at the boundary.

    Attributes:
        url: Absolute URL.
        normalized_path: Canonical dedup path from `url_rules.normalize_url`.
        html: Raw HTML, if fetched. Absent for URLs resolved before fetching.
        nav_links: Links extracted from the site's navigation landmarks. Site
            level, not page level — the same tree for every page on the site.
        discovery_sources: Which paths surfaced this URL. Carried through the
            classification so the finished profile can say whether a page with
            no inbound links is a published-but-unlinked sitemap entry or a CMS
            record nothing ever linked. No signal reads it — it is provenance
            travelling with the evidence, not evidence itself.
        sitemap_source: Filename of the grouped sitemap that listed this URL.
        cms_record: Parsed CMS API record for this URL, if one was found.
        inbound_internal_links: Count of internal links pointing here.
        outbound_internal_links: Count of internal links emitted.
        total_pages_in_crawl: Crawl size, used to scale the in-degree threshold.
        breadcrumb_path: Breadcrumb trail if one was extracted.
    """

    url: str = Field(min_length=1)
    normalized_path: str = Field(min_length=1)
    html: str | None = None
    nav_links: tuple[NavLink, ...] = ()
    discovery_sources: DiscoverySource = DiscoverySource()
    sitemap_source: str | None = None
    cms_record: CmsRecord | None = None
    inbound_internal_links: int = Field(default=0, ge=0)
    outbound_internal_links: int = Field(default=0, ge=0)
    total_pages_in_crawl: int = Field(default=0, ge=0)
    breadcrumb_path: tuple[str, ...] = ()


class _NavLinkExtractor(HTMLParser):
    """Collect anchors inside navigation landmarks, with nesting depth.

    Solves the hidden-hamburger problem directly: this reads the DOM, so
    `display: none` is irrelevant. A mobile menu collapsed by CSS is fully
    visible here, which is the entire reason Signal 1 outranks visual scraping.
    """

    def __init__(self) -> None:
        """Start with no navigation context open."""
        super().__init__(convert_charrefs=True)
        self.links: list[NavLink] = []
        self._nav_depth = 0
        self._list_depth = 0
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track navigation landmarks, list nesting, and open anchors."""
        attributes = {k.lower(): (v or "") for k, v in attrs}

        if tag == "nav" or attributes.get("role", "").lower() == "navigation":
            self._nav_depth += 1
            return

        if self._nav_depth == 0:
            return

        if tag in {"ul", "ol"}:
            self._list_depth += 1
        elif tag == "a":
            href = attributes.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self._current_href = href
                self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        """Close landmarks, lists and anchors, emitting completed links."""
        if tag == "nav" and self._nav_depth > 0:
            self._nav_depth -= 1
            self._list_depth = 0
            return

        if self._nav_depth == 0:
            return

        if tag in {"ul", "ol"} and self._list_depth > 0:
            self._list_depth -= 1
        elif tag == "a" and self._current_href is not None:
            self.links.append(
                NavLink(
                    href=self._current_href,
                    text=" ".join("".join(self._current_text).split()),
                    # One list level is the menu itself; nesting beyond that is
                    # a dropdown, which is what distinguishes L1 from L2.
                    nav_depth=max(0, self._list_depth - 1),
                )
            )
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        """Accumulate anchor text."""
        if self._current_href is not None:
            self._current_text.append(data)


def extract_nav_links(html: str) -> tuple[NavLink, ...]:
    """Extract navigation links and their nesting depth from HTML.

    Args:
        html: Raw page HTML.

    Returns:
        Links found inside `<nav>` or `role="navigation"` landmarks. Empty when
        the markup has no navigation landmark — which is itself informative, and
        typically means a client-rendered site.
    """
    parser = _NavLinkExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not abort a crawl
        return tuple(parser.links)
    return tuple(parser.links)


def _path_key(href: str) -> str:
    """Reduce a link href to a comparable normalised path."""
    without_scheme = re.sub(r"^[a-z][a-z0-9+.-]*://[^/]+", "", href.strip(), flags=re.IGNORECASE)
    path = without_scheme.split("?", 1)[0].split("#", 1)[0]
    stripped, _ = strip_locale_prefix(path or "/")
    return normalize_path(stripped)


def parse_aria_nav_signal(evidence: PageEvidence) -> SignalScore | None:
    """Signal 1 — position within the site's ARIA navigation tree.

    A page appearing at the top level of the main menu is a primary hub; one
    appearing only inside a dropdown is a sub-hub. Reading the DOM rather than
    the rendered layout means a hamburger-collapsed menu classifies identically
    to a desktop one.

    Args:
        evidence: Page evidence carrying the site's nav tree.

    Returns:
        A scored suggestion, or `None` if this page is not in the navigation.
    """
    if not evidence.nav_links:
        return None

    target = _path_key(evidence.normalized_path)
    matches = [link for link in evidence.nav_links if _path_key(link.href) == target]
    if not matches:
        return None

    depth = min(link.nav_depth for link in matches)
    if depth == 0:
        level, page_type = HierarchyLevel.L1_PRIMARY_NAV_HUB, PrimaryPageType.SERVICE_CATEGORY_HUB
        confidence = 0.90
    elif depth == 1:
        level, page_type = HierarchyLevel.L2_SUB_NAV_HUB, PrimaryPageType.SERVICE_CATEGORY_HUB
        confidence = 0.82
    else:
        level, page_type = HierarchyLevel.L3_LEAF_PAGE, PrimaryPageType.SERVICE_DETAIL_PAGE
        confidence = 0.70

    return SignalScore(
        source=SignalSource.ARIA_NAV_TREE,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=confidence,
        notes=f"nav depth {depth}, {len(matches)} nav occurrence(s)",
    )


def parse_cms_endpoint_signal(evidence: PageEvidence) -> SignalScore | None:
    """Signal 2 — the CMS's own record for this URL.

    The highest-weighted structural signal, because it is the only one that
    reads the site's database rather than inferring from presentation. This is
    what resolves a flat URL such as `site.com/capsules`, where path depth
    carries no information at all.

    Args:
        evidence: Page evidence carrying the CMS record.

    Returns:
        A scored suggestion, or `None` if no CMS record was retrieved.
    """
    record = evidence.cms_record
    if record is None:
        return None

    kind = record.record_type.lower()
    is_root = not record.parent_id

    if kind in {"product", "products"}:
        level = HierarchyLevel.L3_LEAF_PAGE
        page_type = PrimaryPageType.PRODUCT_DETAIL_PAGE
    elif kind in {"collection", "collections", "product_category", "category"}:
        level = HierarchyLevel.L1_PRIMARY_NAV_HUB if is_root else HierarchyLevel.L2_SUB_NAV_HUB
        page_type = PrimaryPageType.PRODUCT_CATEGORY_HUB
    elif kind in {"post", "posts"}:
        level = HierarchyLevel.L3_LEAF_PAGE
        page_type = PrimaryPageType.BLOG_ARTICLE
    elif record.has_children:
        level = HierarchyLevel.L1_PRIMARY_NAV_HUB if is_root else HierarchyLevel.L2_SUB_NAV_HUB
        page_type = PrimaryPageType.SERVICE_CATEGORY_HUB
    else:
        level = HierarchyLevel.L3_LEAF_PAGE
        page_type = PrimaryPageType.SERVICE_DETAIL_PAGE

    # A resolved parent means the hierarchy is stated rather than inferred.
    confidence = 0.95 if record.parent_url or is_root else 0.88
    return SignalScore(
        source=SignalSource.CMS_API_ENDPOINT,
        suggested_level=level,
        suggested_page_type=page_type,
        confidence=confidence,
        notes=f"cms type '{record.record_type}', parent={record.parent_id or 'root'}",
    )


def parse_sitemap_signal(evidence: PageEvidence) -> SignalScore | None:
    """Signal 3 — which grouped sitemap listed this URL.

    A webmaster who publishes `product-sitemap.xml` has declared what those URLs
    are. That is weaker than a database record but stronger than guessing from a
    slug.

    Args:
        evidence: Page evidence carrying the sitemap filename.

    Returns:
        A scored suggestion, or `None` for an ungrouped or absent sitemap.
    """
    source = evidence.sitemap_source
    if not source:
        return None

    name = source.lower()
    for fragment, level, page_type in _SITEMAP_HINTS:
        if fragment in name:
            return SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=level,
                suggested_page_type=page_type,
                confidence=0.75,
                notes=f"sitemap '{source}' matched '{fragment}'",
            )
    return None


def _iter_schema_types(node: object) -> Iterable[str]:
    """Yield every `@type` value in a JSON-LD document, however nested."""
    if isinstance(node, dict):
        raw = node.get("@type")
        if isinstance(raw, str):
            yield raw
        elif isinstance(raw, list):
            yield from (item for item in raw if isinstance(item, str))
        for value in node.values():
            yield from _iter_schema_types(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_schema_types(item)


def parse_jsonld_signal(evidence: PageEvidence) -> SignalScore | None:
    """Signal 4 — Schema.org `@type` declarations embedded in the page.

    Walks nested `@graph` structures, since real sites rarely put the
    interesting type at the top level.

    Args:
        evidence: Page evidence carrying HTML.

    Returns:
        A scored suggestion, or `None` when no recognised type is present.
    """
    if not evidence.html:
        return None

    for block in _JSONLD_BLOCK_RE.findall(evidence.html):
        try:
            document = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue  # A broken JSON-LD block is common and not worth failing on.

        for declared in _iter_schema_types(document):
            mapped = _SCHEMA_TYPE_MAP.get(declared.split("/")[-1].lower())
            if mapped is not None:
                level, page_type = mapped
                return SignalScore(
                    source=SignalSource.SCHEMA_JSONLD,
                    suggested_level=level,
                    suggested_page_type=page_type,
                    confidence=0.80,
                    notes=f"schema.org @type '{declared}'",
                )
    return None


def parse_link_indegree_signal(evidence: PageEvidence) -> SignalScore | None:
    """Signal 5 — internal link in-degree centrality.

    A page linked from most other pages sits in a site-wide header or footer,
    which makes it primary navigation. The threshold scales with crawl size:
    1,000 inbound links is impossible on a 200-page site and unremarkable on a
    50,000-page one, so a fixed number would misfire at both ends.

    Args:
        evidence: Page evidence carrying link counts.

    Returns:
        A scored suggestion, or `None` when in-degree is unremarkable.
    """
    inbound = evidence.inbound_internal_links
    total = evidence.total_pages_in_crawl

    if inbound <= 0:
        return None

    threshold = (
        min(L1_HUB_INBOUND_LINK_THRESHOLD, max(10, int(total * 0.5)))
        if total > 0
        else L1_HUB_INBOUND_LINK_THRESHOLD
    )

    if inbound >= threshold:
        return SignalScore(
            source=SignalSource.LINK_IN_DEGREE,
            suggested_level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
            suggested_page_type=PrimaryPageType.SERVICE_CATEGORY_HUB,
            confidence=0.72,
            notes=f"{inbound} inbound internal links (threshold {threshold})",
        )

    # An orphan is worth reporting: it is a real SEO finding, and it is weak
    # evidence of a leaf page since hubs are never orphans.
    if inbound <= 1 and total > 50:
        return SignalScore(
            source=SignalSource.LINK_IN_DEGREE,
            suggested_level=HierarchyLevel.L3_LEAF_PAGE,
            suggested_page_type=PrimaryPageType.UNKNOWN,
            confidence=0.35,
            notes=f"near-orphan: {inbound} inbound internal link(s)",
        )
    return None


def collect_structural_signals(evidence: PageEvidence) -> tuple[SignalScore, ...]:
    """Run every structural parser and return those that produced an opinion.

    Args:
        evidence: Page evidence.

    Returns:
        Scores from the parsers that had something to say, in signal order.
    """
    parsers: tuple[SignalParser, ...] = (
        parse_cms_endpoint_signal,
        parse_aria_nav_signal,
        parse_sitemap_signal,
        parse_jsonld_signal,
        parse_link_indegree_signal,
    )
    scores = [score for parser in parsers if (score := parser(evidence)) is not None]
    return tuple(scores)
