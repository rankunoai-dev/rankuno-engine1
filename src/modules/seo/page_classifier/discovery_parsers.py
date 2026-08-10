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

The defence is to parse only the `<urlset>`/`<sitemapindex>` element, sliced out
of whatever the response body happens to be. A DTD can only appear in the
prolog, *before* the root element, so the slice cannot contain one. Any
`&entity;` reference surviving inside it is then an undefined entity, which
expat reports as a `ParseError` rather than expanding — entity expansion and
XXE are both closed structurally, with no dependency added.

This replaced a blanket rejection of any body containing `<!DOCTYPE`. That rule
was written on the assumption that only an attacker would send one, which is
false: Yoast and RankMath serve sitemaps wrapped in an XHTML skin so the file
renders as a styled page in a browser, and the wrapper carries a doctype. The
rule was discarding those sites' sitemaps in full. Slicing keeps the same
guarantee and stops throwing away legitimate documents to get it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
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
    "parse_link_header",
    "parse_shopify_records",
    "parse_sitemap",
    "parse_wordpress_records",
    "with_page_param",
    "wordpress_total_pages",
]

_logger = get_logger("modules.seo.discovery_parsers")

MAX_SITEMAP_ENTRIES = 50_000
"""Per the sitemap protocol. A file claiming more is malformed or hostile."""

_SITEMAP_ROOTS = ("sitemapindex", "urlset")

_ROOT_OPEN_RE = {
    name: re.compile(rf"<(?:[\w.\-]+:)?{name}(?=[\s/>])", re.IGNORECASE) for name in _SITEMAP_ROOTS
}
"""Opening tag of a sitemap root, with or without a namespace prefix."""

_ROOT_CLOSE_RE = {
    name: re.compile(rf"</(?:[\w.\-]+:)?{name}\s*>", re.IGNORECASE) for name in _SITEMAP_ROOTS
}

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
    # Markdown. Observed live: allbirds.com/agents.md entered the graph as a
    # page and was classified UNKNOWN at 0.0 confidence — crawl budget spent on
    # something that can never be classified (build-log 0010 §7).
    ".md",
    ".markdown",
)
"""Extensions that are never HTML pages.

`.txt` is deliberately **absent**. `llms.txt` and `llms-full.txt` are the AI
crawler manifests Phase 7's answer-readiness audit reads, so excluding `.txt`
would blind a later phase to files it specifically needs."""


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


def _extract_root_element(text: str) -> str | None:
    """Slice out the `<urlset>`/`<sitemapindex>` element, discarding any prolog.

    This is the safety boundary, not a convenience. XML permits a DTD only in
    the prolog, so a slice that begins at the root element's opening tag cannot
    carry an internal subset — and therefore cannot carry an entity declaration
    to expand. Whatever wrapped the element, XHTML skin or nothing at all, is
    dropped along with it.

    The last closing tag is used rather than the first: `<loc>` values are
    escaped, so a literal `</urlset>` cannot appear inside the element, and
    taking the last one survives trailing wrapper markup.

    Returns:
        The sliced element, or `None` if no sitemap root is present.
    """
    best: tuple[int, str] | None = None
    for name in _SITEMAP_ROOTS:
        opening = _ROOT_OPEN_RE[name].search(text)
        if opening is not None and (best is None or opening.start() < best[0]):
            best = (opening.start(), name)

    if best is None:
        return None

    start, name = best

    tag_end = _opening_tag_end(text, start)
    if tag_end is not None and text[tag_end - 2 : tag_end] == "/>":
        # `<urlset/>` — an empty sitemap, well-formed and with no closing tag.
        # Falling through would return the wrapper's trailing markup as well.
        return text[start:tag_end]

    closings = list(_ROOT_CLOSE_RE[name].finditer(text, start))
    if not closings:
        # Unterminated. Hand it over anyway so ElementTree reports the truncation
        # rather than this function silently deciding the document is empty.
        return text[start:]
    return text[start : closings[-1].end()]


def _opening_tag_end(text: str, start: int) -> int | None:
    """Index just past the `>` closing the tag that begins at `start`.

    Quote-aware, because an XML attribute value may legally contain `>` and a
    naive `find(">")` would cut the tag in half.
    """
    quote = ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == ">":
            return index + 1
    return None


def parse_sitemap(xml_text: str, source_name: str = "") -> SitemapDocument:
    """Parse a sitemap index or urlset.

    Malformed XML yields an empty document rather than raising: one broken
    sitemap among a dozen must not abort discovery for the whole site.

    The document is sliced to its root element before parsing, which both
    tolerates the XHTML wrapper WordPress SEO plugins emit and removes the
    entity-expansion surface. See the module docstring.

    Args:
        xml_text: Raw sitemap XML, optionally wrapped in other markup.
        source_name: Filename it came from, carried through to signal parsing.

    Returns:
        The parsed document. `SitemapKind.UNKNOWN` with no locations when the
        input could not be parsed.
    """
    if not xml_text.strip():
        return SitemapDocument(source_name=source_name)

    sliced = _extract_root_element(xml_text)
    if sliced is None:
        _logger.info("sitemap_no_root_element", extra={"source": source_name})
        return SitemapDocument(source_name=source_name)

    try:
        # Safe: `sliced` starts at the root tag, so no DTD can precede it.
        root = ElementTree.fromstring(sliced)  # noqa: S314
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


def parse_link_header(value: str) -> dict[str, str]:
    """Parse an RFC 8288 `Link` header into a rel-to-URL map.

    Shopify signals cursor pagination here and nowhere else — the response body
    gives no indication that more records exist, so a caller without this header
    has no way to know it stopped early. That is exactly how the Allbirds crawl
    read 35 of a much larger catalogue (build-log 0010 §4).

    Args:
        value: Raw `Link` header, possibly holding several comma-separated links.

    Returns:
        Map of `rel` value to URL. Empty when the header is absent or unparseable.
    """
    links: dict[str, str] = {}
    if not value:
        return links

    for part in value.split(","):
        segments = part.split(";")
        target = segments[0].strip()
        if not (target.startswith("<") and target.endswith(">")):
            continue
        url = target[1:-1].strip()
        for attribute in segments[1:]:
            name, _, raw = attribute.partition("=")
            if name.strip().lower() != "rel":
                continue
            rel = raw.strip().strip('"').strip("'").lower()
            if rel and url:
                links[rel] = url
    return links


def with_page_param(url: str, page: int) -> str:
    """Return `url` with its `page` query parameter set to `page`.

    Replaces an existing value rather than appending a second one, which would
    produce `?page=1&page=2` and let the server pick.

    Args:
        url: Endpoint URL, with or without an existing `page` parameter.
        page: Page number to request.

    Returns:
        The URL with `page` set.
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
    query.append(("page", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def wordpress_total_pages(headers: Mapping[str, str]) -> int | None:
    """Read WordPress's declared page count from response headers.

    WordPress states the total in `X-WP-TotalPages`, which lets pagination stop
    exactly rather than probing until it gets a 400. Requesting a page past the
    end returns `rest_post_invalid_page_number`, so probing works but wastes a
    request and logs an error on the client's server.

    Args:
        headers: Response headers, keys lower-cased.

    Returns:
        The page count, or `None` when the header is absent or malformed.
    """
    raw = headers.get("x-wp-totalpages", "").strip()
    if not raw:
        return None
    try:
        total = int(raw)
    except ValueError:
        return None
    return total if total > 0 else None


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
