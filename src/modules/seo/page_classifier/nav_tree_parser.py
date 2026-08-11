"""Extract a site's header navigation menu as a tree.

Why this exists
---------------
Grouping a site by URL path answers "where does this file live?". It does not
answer "where would a visitor find this?", and those diverge badly on modern
sites. A flat-URL architecture puts every page at depth 1, so a path tree of
`vitaquest.com` is a single flat list regardless of how the site is actually
organised. The header menu is the structure the site's own designers published.

What this module does **not** do
--------------------------------
It does not classify anything. `PrimaryPageType`, `SearchIntent` and
`HierarchyLevel` are produced by the cascading pipeline from page evidence, and
none of them are affected by what is parsed here. This produces an *additional*
grouping axis, not a replacement for classification.

That distinction matters for expectations: on gep.com the header menu holds 168
unique internal URLs against 4,427 in the sitemap — **3.8%**. The menu can never
account for most of a large site on its own. `logical_hierarchy.py` closes that
gap by treating nav URLs as path prefixes that descendants inherit.

Scope of the parse
------------------
Only the header. Footer navigation is excluded, because a footer is a link dump
rather than a hierarchy: gep.com publishes seven `<nav>` elements and most are
not the header menu. Including them would put "Privacy Policy" beside "Solutions"
as a top-level section.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import safe_split

__all__ = [
    "MAX_NAV_DEPTH",
    "NavNode",
    "NavSource",
    "NavigationTree",
    "parse_navigation",
]

_logger = get_logger("modules.seo.nav_tree_parser")

MAX_NAV_DEPTH = 3
"""Menu levels kept, counting the top tab as 0.

Mega-menus occasionally nest four or five deep, but past three levels the
grouping stops being something a person recognises from looking at the site.
Deeper items are attached to their nearest kept ancestor rather than dropped.
"""

MAX_NAV_NODES = 2_000
"""Ceiling on nodes taken from one document.

A malformed page can nest lists indefinitely, and a header menu with thousands
of entries is a parse failure, not a menu.
"""

_NAV_TAGS = frozenset({"nav", "header"})
_LIST_TAGS = frozenset({"ul", "ol", "dl"})

_HEADING_TAGS = frozenset({"span", "strong", "h2", "h3", "h4", "h5", "h6"})
"""Tags that carry an unlinked mega-menu section heading.

Only honoured inside a list item and outside an anchor. Unrestricted, this would
also capture the logo text and the icon `<span>`s that live inside menu links —
the list constraint is what keeps it to menu structure."""
_SKIP_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "data:", "sms:")

_WHITESPACE = re.compile(r"\s+")

_HAS_WORD = re.compile(r"\w", re.UNICODE)
"""A label must contain at least one word character to be a label.

Menus are full of decorative anchors: chevrons (`›`), bullets, and icon-only
links whose text is empty. Observed live on gep.com, these produced top-level
sections named `''` and `'›'`."""


class NavSource(StrictModel):
    """Where a navigation tree came from, and how much it found.

    Recorded because an empty menu and a menu that was never looked for are
    different failures, and the UI has to be able to say which happened.

    Attributes:
        strategy: `dom` (a `<nav>`/`<header>` element), `jsonld`
            (`SiteNavigationElement` markup), or `none`.
        containers: Navigation containers examined.
        link_count: Unique internal URLs found.
    """

    strategy: str = "none"
    containers: int = Field(default=0, ge=0)
    link_count: int = Field(default=0, ge=0)


class NavNode(StrictModel):
    """One entry in the header menu.

    Attributes:
        label: Visible link text, whitespace-collapsed.
        url: Absolute destination, or `None` for a heading that is not a link.
            Mega-menu section headings are frequently unlinked, and dropping them
            would flatten the two levels beneath into one.
        depth: 0 for a top tab, 1 for a mega-menu heading, 2 for a dropdown item.
        children: Entries nested beneath this one.
    """

    label: str = ""
    url: str | None = None
    depth: int = Field(default=0, ge=0)
    children: tuple[NavNode, ...] = ()

    def walk(self) -> list[NavNode]:
        """This node and every descendant, depth-first."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


class NavigationTree(StrictModel):
    """A parsed header menu.

    Attributes:
        roots: Top-level tabs.
        source: How it was obtained and how much it covered.
    """

    roots: tuple[NavNode, ...] = ()
    source: NavSource = NavSource()

    @property
    def is_empty(self) -> bool:
        """Whether nothing usable was found.

        Callers must branch on this rather than assuming a tree exists. A
        client-rendered menu leaves the served HTML with no links at all, and
        presenting that as "this site has no navigation" would be wrong.
        """
        return not self.roots

    def linked_nodes(self) -> list[NavNode]:
        """Every node that actually points somewhere, depth-first."""
        return [node for root in self.roots for node in root.walk() if node.url]


class _NavCollector(HTMLParser):
    """Collect anchors inside header navigation, with their nesting depth.

    Depth comes from list nesting (`<ul>`/`<ol>`/`<dl>`) rather than from the
    anchors' order, because that is how menus are actually marked up and it is
    the only structure present in the HTML. A menu built purely from `<div>`s
    yields a flat list, which is the honest result rather than an invented
    hierarchy.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[int, str, str | None]] = []
        self.containers = 0
        self._nav_depth = 0
        self._footer_depth = 0
        self._list_depth = 0
        self._current: list[str] | None = None
        self._current_href: str | None = None
        self._current_depth = 0

    @property
    def _inside_header_nav(self) -> bool:
        return self._nav_depth > 0 and self._footer_depth == 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track nav/footer/list nesting and open anchors."""
        mapping = {key: value or "" for key, value in attrs}

        if tag == "footer" or mapping.get("role") == "contentinfo":
            self._footer_depth += 1
            return

        if tag in _NAV_TAGS or mapping.get("role") == "navigation":
            if self._nav_depth == 0 and self._footer_depth == 0:
                self.containers += 1
            self._nav_depth += 1
            return

        if not self._inside_header_nav:
            return

        if tag in _LIST_TAGS:
            self._list_depth += 1
        elif tag == "a":
            self._finish_anchor()
            self._open(mapping.get("href") or None)
        elif tag in _HEADING_TAGS and self._current is None and self._list_depth > 0:
            self._open(None)

    def handle_endtag(self, tag: str) -> None:
        """Close the matching nesting level."""
        if tag == "footer":
            self._footer_depth = max(0, self._footer_depth - 1)
            return
        if tag in _NAV_TAGS:
            self._nav_depth = max(0, self._nav_depth - 1)
            return
        if not self._inside_header_nav:
            return
        if tag in _LIST_TAGS:
            self._list_depth = max(0, self._list_depth - 1)
        elif tag == "a" or tag in _HEADING_TAGS:
            self._finish_anchor()

    def handle_data(self, data: str) -> None:
        """Accumulate the visible text of the open anchor."""
        if self._current is not None:
            self._current.append(data)

    def _open(self, href: str | None) -> None:
        """Begin capturing a menu entry at the current list depth."""
        self._current = []
        self._current_href = href
        self._current_depth = max(0, self._list_depth - 1)

    def _finish_anchor(self) -> None:
        if self._current is None:
            return
        label = _WHITESPACE.sub(" ", "".join(self._current)).strip()
        if not _HAS_WORD.search(label):
            # Decorative, not a section name. Kept only if it links somewhere, in
            # which case `parse_navigation` derives a name from the URL.
            label = ""
        if label or self._current_href:
            self.entries.append((self._current_depth, label, self._current_href))
        self._current = None
        self._current_href = None


def _label_from_url(url: str) -> str:
    """Derive a readable name for an icon-only link from its path.

    `https://e.com/login` becomes `Login`. Without this, an anchor whose only
    content is an SVG icon produces a section with a blank name.
    """
    parts = safe_split(url)
    path = parts.path.strip("/") if parts else ""
    if not path:
        return "Home"
    return path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip().title()


def _usable_href(href: str | None, base_url: str, base_host: str) -> str | None:
    """Resolve an href to an absolute same-host URL, or reject it.

    Off-host links are dropped: a menu that links to a careers portal on another
    domain is not part of this site's structure, and following it would start an
    unbounded crawl.
    """
    if not href:
        return None
    candidate = href.strip()
    if not candidate or candidate.lower().startswith(_SKIP_HREF_PREFIXES):
        return None

    try:
        absolute = urljoin(base_url, candidate)
    except ValueError:
        return None
    split = safe_split(absolute)
    if split is None or split.scheme not in {"http", "https"}:
        return None
    if split.netloc.lower() != base_host:
        return None
    # A fragment addresses a position on a page already in the menu, not a
    # separate destination. `/contact-us#rfp` and `/contact-us` are one page.
    return absolute.split("#", 1)[0]


def _build_tree(entries: list[tuple[int, str, str | None]]) -> tuple[NavNode, ...]:
    """Assemble flat (depth, label, url) entries into a nesting.

    A stack rather than recursion: the input is already in document order, and a
    depth that jumps by more than one — common in hand-written menus — must
    attach to the nearest available parent instead of raising.
    """
    roots: list[NavNode] = []
    # Each stack slot holds the node at that depth and its accumulating children.
    stack: list[tuple[NavNode, list[NavNode]]] = []

    def collapse(to_depth: int) -> None:
        while len(stack) > to_depth:
            node, children = stack.pop()
            finished = node.model_copy(update={"children": tuple(children)})
            if stack:
                stack[-1][1].append(finished)
            else:
                roots.append(finished)

    for raw_depth, label, url in entries:
        depth = min(raw_depth, MAX_NAV_DEPTH - 1)
        depth = min(depth, len(stack))  # Cannot open a level with no parent.
        collapse(depth)
        stack.append((NavNode(label=label, url=url, depth=depth), []))

    collapse(0)
    return tuple(roots)


def _parse_jsonld_navigation(html: str, base_url: str, base_host: str) -> tuple[NavNode, ...]:
    """Fall back to `SiteNavigationElement` markup.

    The fallback for client-rendered menus, where the served HTML carries no
    anchors at all. It produces a flat list, not a hierarchy — the markup has no
    nesting to recover — which is why it is a fallback and not the primary path.
    """
    nodes: list[NavNode] = []
    seen: set[str] = set()

    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(block)
        except (ValueError, TypeError):
            continue

        for item in _iter_navigation_elements(payload):
            # JSON-LD is arbitrary third-party data: `url` can legitimately be a
            # list, a nested object, or absent. Anything that is not a string is
            # not a destination.
            raw_url = item.get("url")
            url = _usable_href(raw_url, base_url, base_host) if isinstance(raw_url, str) else None
            name = str(item.get("name") or "").strip()
            if url and url not in seen:
                seen.add(url)
                nodes.append(NavNode(label=name, url=url, depth=0))

    return tuple(nodes)


def _iter_navigation_elements(payload: object) -> list[dict[str, object]]:
    """Find every `SiteNavigationElement` in an arbitrarily nested JSON-LD blob."""
    found: list[dict[str, object]] = []
    # A queue, not a stack: menu order is meaningful and `pop()` would reverse it.
    queue: list[object] = [payload]
    index = 0

    while index < len(queue):
        current = queue[index]
        index += 1
        if isinstance(current, list):
            queue.extend(current)
        elif isinstance(current, dict):
            if current.get("@type") == "SiteNavigationElement":
                found.append(current)
            queue.extend(current.values())

    return found


def parse_navigation(html: str, base_url: str) -> NavigationTree:
    """Parse a page's header navigation menu.

    Args:
        html: Raw HTML, normally the homepage — the one page whose menu is
            guaranteed to be the global one.
        base_url: Absolute URL of that page, for resolving relative links.

    Returns:
        The tree. Empty when nothing usable was found, which callers must handle
        rather than treat as "the site has no navigation".
    """
    if not html.strip():
        return NavigationTree()

    collector = _NavCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup must not abort a crawl
        # Whatever parsed before the failure is still usable, and a broken page
        # is far more common than a broken parser.
        _logger.debug("nav_parse_partial", extra={"url": base_url, "error": str(exc)})

    base_split = safe_split(base_url)
    base_host = base_split.netloc.lower() if base_split else ""
    resolved: list[tuple[int, str, str | None]] = []
    seen_urls: set[str] = set()

    for depth, label, href in collector.entries[:MAX_NAV_NODES]:
        url = _usable_href(href, base_url, base_host)
        if url is not None:
            # The same destination appears in both a desktop and a mobile menu on
            # most sites. Keeping the first occurrence keeps the desktop
            # hierarchy, which is the one with real nesting.
            if url in seen_urls:
                continue
            seen_urls.add(url)
        elif not label:
            continue
        # An icon-only link still names a real destination; name it from the URL
        # rather than letting a blank label become a section heading.
        if not label and url:
            label = _label_from_url(url)
        resolved.append((depth, label, url))

    if resolved:
        roots = _build_tree(resolved)
        return NavigationTree(
            roots=roots,
            source=NavSource(
                strategy="dom", containers=collector.containers, link_count=len(seen_urls)
            ),
        )

    jsonld = _parse_jsonld_navigation(html, base_url, base_host)
    if jsonld:
        _logger.info("nav_from_jsonld", extra={"url": base_url, "items": len(jsonld)})
        return NavigationTree(
            roots=jsonld,
            source=NavSource(strategy="jsonld", containers=0, link_count=len(jsonld)),
        )

    _logger.info("nav_not_found", extra={"url": base_url})
    return NavigationTree(source=NavSource(strategy="none", containers=collector.containers))
