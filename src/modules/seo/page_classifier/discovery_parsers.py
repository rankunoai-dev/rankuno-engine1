"""Payload parsing for the three discovery paths.

Pure functions over already-fetched text, mirroring the split in
`signal_parsers.py`: parsing here, I/O in `discovery.py`. That separation is
what lets hostile-input handling be tested exhaustively offline.

XML safety
----------
Sitemaps come from arbitrary third-party hosts, which makes them untrusted
input. Python's `xml.etree.ElementTree` does not resolve *external* entities,
but it does expand *internal* ones, so a "billion laughs" document is a live
denial-of-service vector against a crawler.

A sitemap has no legitimate use for a DTD, so any document containing a
`<!DOCTYPE` declaration is rejected outright before parsing. That closes both
entity-expansion and XXE without adding a dependency, and it cannot reject a
well-formed sitemap because well-formed sitemaps never carry one.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.signal_parsers import CmsRecord

__all__ = [
    "MAX_SITEMAP_ENTRIES",
    "SitemapDocument",
    "SitemapKind",
    "extract_page_links",
    "parse_shopify_records",
    "parse_sitemap",
    "parse_wordpress_records",
]

_logger = get_logger("modules.seo.discovery_parsers")

MAX_SITEMAP_ENTRIES = 50_000
"""Per the sitemap protocol. A file claiming more is malformed or hostile."""

_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)

_SKIP_LINK_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "data:", "sms:")

# Extensions that are never HTML pages. Following them wastes crawl budget and
# pollutes the graph with nodes that can never be classified.
_NON_PAGE_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".bmp",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".rss",
    ".atom",
    ".zip",
    ".gz",
    ".tar",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".wav",
    ".webm",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".exe",
    ".dmg",
    ".pkg",
)


class SitemapKind(StrEnum):
    """Whether a sitemap document lists other sitemaps or actual pages."""

    INDEX = "INDEX"
    """A `<sitemapindex>`: its entries are further sitemaps to fetch."""

    URLSET = "URLSET"
    """A `<urlset>`: its entries are pages."""

    UNKNOWN = "UNKNOWN"
    """Unparseable, or a root element that is neither."""


class SitemapDocument(StrictModel):
    """One parsed sitemap file.

    Attributes:
        kind: Index or urlset.
        locations: `<loc>` values, de-duplicated and order-preserved.
        source_name: Filename this came from, e.g. `product-sitemap.xml`. This
            is what feeds `PageEvidence.sitemap_source`, which Signal 3 reads —
            a grouped sitemap is the webmaster declaring what those URLs are.
        truncated: Whether the entry ceiling was hit.
    """

    kind: SitemapKind = SitemapKind.UNKNOWN
    locations: tuple[str, ...] = ()
    source_name: str = ""
    truncated: bool = False

    @property
    def is_index(self) -> bool:
        """True when the entries are further sitemaps rather than pages."""
        return self.kind is SitemapKind.INDEX


def _local_name(tag: str) -> str:
    """Strip an XML namespace, so parsing does not depend on the declared one."""
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(xml_text: str, source_name: str = "") -> SitemapDocument:
    """Parse a sitemap index or urlset.

    Malformed XML yields an empty document rather than raising: one broken
    sitemap among a dozen must not abort discovery for the whole site.

    Args:
        xml_text: Raw sitemap XML.
        source_name: Filename it came from, carried through to signal parsing.

    Returns:
        The parsed document. `SitemapKind.UNKNOWN` with no locations when the
        input could not be parsed.
    """
    if not xml_text.strip():
        return SitemapDocument(source_name=source_name)

    if _DOCTYPE_RE.search(xml_text):
        # No legitimate sitemap carries a DTD; one that does is an
        # entity-expansion attempt. Refuse before handing it to the parser.
        _logger.warning("sitemap_doctype_rejected", extra={"source": source_name})
        return SitemapDocument(source_name=source_name)

    try:
        root = ElementTree.fromstring(xml_text)  # noqa: S314 - DOCTYPE rejected above
    except ElementTree.ParseError as exc:
        _logger.info("sitemap_unparseable", extra={"source": source_name, "error": str(exc)})
        return SitemapDocument(source_name=source_name)

    root_name = _local_name(root.tag)
    if root_name == "sitemapindex":
        kind = SitemapKind.INDEX
    elif root_name == "urlset":
        kind = SitemapKind.URLSET
    else:
        return SitemapDocument(source_name=source_name)

    seen: dict[str, None] = {}
    truncated = False
    for element in root.iter():
        if _local_name(element.tag) != "loc":
            continue
        value = (element.text or "").strip()
        if not value:
            continue
        if len(seen) >= MAX_SITEMAP_ENTRIES:
            truncated = True
            _logger.warning("sitemap_truncated", extra={"source": source_name})
            break
        seen[value] = None

    return SitemapDocument(
        kind=kind,
        locations=tuple(seen),
        source_name=source_name,
        truncated=truncated,
    )


class _AnchorCollector(HTMLParser):
    """Collect every `<a href>` in a document, navigation or otherwise."""

    def __init__(self) -> None:
        """Start with no links collected."""
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record anchor targets."""
        if tag != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value.strip())
                return


def _is_page_link(url: str) -> bool:
    """Whether a URL plausibly points at an HTML page."""
    path = urlsplit(url).path.lower()
    return not path.endswith(_NON_PAGE_SUFFIXES)


def extract_page_links(html: str, base_url: str, *, same_host_only: bool = True) -> tuple[str, ...]:
    """Extract outbound page links from a document.

    This is Path B's primitive: the DOM link graph is what finds the pages a
    sitemap omits. On HighRadius that included the entire corporate governance
    section — `/anti-corruption-and-bribery-policy/`, `/code-of-ethics/`,
    `/human-rights-policy/` — none of which appeared in any sitemap.

    Args:
        html: Raw page HTML.
        base_url: Absolute URL of the page, used to resolve relative links.
        same_host_only: Drop links leaving the host. External links are not part
            of the site graph and following them would be an unbounded crawl.

    Returns:
        Absolute URLs, de-duplicated and order-preserved.
    """
    if not html:
        return ()

    collector = _AnchorCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup must not abort a crawl
        # Whatever the parser managed before choking is still usable, and a
        # broken page is far more common than a broken parser.
        _logger.debug("link_extraction_partial", extra={"url": base_url, "error": str(exc)})

    base_host = urlsplit(base_url).netloc.lower()
    found: dict[str, None] = {}

    for href in collector.hrefs:
        if href.startswith(_SKIP_LINK_PREFIXES):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in {"http", "https"}:
            continue
        if same_host_only and parts.netloc.lower() != base_host:
            continue
        if not _is_page_link(absolute):
            continue
        found[absolute.split("#", 1)[0]] = None

    return tuple(found)


class CmsPage(StrictModel):
    """One record from a CMS listing, before URL resolution.

    Attributes:
        record_id: Platform's own identifier.
        url: Canonical URL the platform reports.
        parent_id: Parent identifier, `None` at top level.
    """

    record_id: int = Field(ge=0)
    url: str = Field(min_length=1)
    parent_id: int | None = None


def _load_json(payload: str) -> Any:
    """Parse JSON, returning `None` rather than raising on malformed input."""
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None


def parse_wordpress_records(payload: str, record_type: str = "page") -> dict[str, CmsRecord]:
    """Parse a WordPress REST listing into records keyed by URL.

    This is Path C's payoff and the reason Signal 2 carries the heaviest weight:
    WordPress states parent IDs outright, so a flat URL such as
    `site.com/capsules` is placed in the hierarchy by the database rather than
    inferred from a slug that carries no depth information.

    Args:
        payload: Raw JSON from `/wp-json/wp/v2/pages` or `/posts`.
        record_type: Type label to record, e.g. `page` or `post`.

    Returns:
        `CmsRecord` per URL, with parents resolved to URLs where possible.
    """
    data = _load_json(payload)
    if not isinstance(data, list):
        return {}

    pages: list[CmsPage] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        identifier = item.get("id")
        if not isinstance(link, str) or not link or not isinstance(identifier, int):
            continue
        raw_parent = item.get("parent")
        parent = raw_parent if isinstance(raw_parent, int) and raw_parent > 0 else None
        pages.append(CmsPage(record_id=identifier, url=link, parent_id=parent))

    by_id = {page.record_id: page.url for page in pages}
    parents_with_children = {page.parent_id for page in pages if page.parent_id is not None}

    return {
        page.url: CmsRecord(
            record_type=record_type,
            parent_id=page.parent_id,
            parent_url=by_id.get(page.parent_id) if page.parent_id else None,
            has_children=page.record_id in parents_with_children,
        )
        for page in pages
    }


def parse_shopify_records(
    payload: str, base_url: str, *, collection: str = "products"
) -> dict[str, CmsRecord]:
    """Parse a Shopify listing into records keyed by URL.

    Args:
        payload: Raw JSON from `/products.json` or `/collections.json`.
        base_url: Site root, used to build handle URLs.
        collection: Either `products` or `collections`.

    Returns:
        `CmsRecord` per URL.
    """
    data = _load_json(payload)
    if not isinstance(data, dict):
        return {}

    items = data.get(collection)
    if not isinstance(items, list):
        return {}

    record_type = "product" if collection == "products" else "collection"
    root = base_url.rstrip("/")
    records: dict[str, CmsRecord] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str) or not handle:
            continue
        records[f"{root}/{collection}/{handle}"] = CmsRecord(
            record_type=record_type,
            # Shopify collections are flat; a product's collection membership is
            # many-to-many, so no single parent can be asserted here.
            parent_id=None,
            has_children=collection == "collections",
        )

    return records
