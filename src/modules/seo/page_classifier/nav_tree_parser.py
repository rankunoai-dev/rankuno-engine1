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

_HEADING_TAGS = frozenset(
    {"span", "strong", "h2", "h3", "h4", "h5", "h6", "div", "button", "summary"}
)
"""Tags that can carry an unlinked mega-menu section heading.

Only honoured inside a list and outside an anchor. Unrestricted, this would also
capture the logo text and the icon `<span>`s that live inside menu links — the
list constraint is what keeps it to menu structure.

`div` and `button` are here because a top tab that opens a dropdown is very
often not a link at all. Anthropic's `Commitments` tab is
`<div class="w-dropdown-toggle"><div>Commitments</div></div>` — no anchor, no
`role`, no `aria-haspopup`. Without a node for it, `_build_tree` attached its
whole dropdown to the previous tab, which is how `Transparency` came to sit
under `Policy`.

Admitting `div` is only safe alongside two other rules in this module: an inner
candidate replaces an outer one, so the innermost text-bearing element wins
rather than a wrapper swallowing the entire dropdown; and unlinked leaves are
pruned, so the CTA and placeholder text that this inevitably also catches does
not survive as a section."""
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
        self._dropdown_depth = 0
        """Nested nav containers opened *inside* a list item.

        A dropdown panel is frequently its own `<nav>` inside the `<li>` of the
        tab that opens it, and its group headings then sit at the same list
        depth as the tabs themselves. Counting only navs opened inside a list is
        what separates the two: `<header><nav>` wraps the whole menu and opens
        before any list, so it must not shift every tab down a level."""
        self._nav_stack: list[bool] = []
        """Whether each open `<nav>`/`<header>` counted as a dropdown.

        Only these two tags are tracked. An element carrying
        `role="navigation"` still gates parsing as before, but is not counted
        here: matching its close would need a full element stack, and getting
        that wrong would mis-depth an entire menu."""
        self._current: list[str] | None = None
        self._current_href: str | None = None
        self._current_depth = 0
        self._anchor_open = False
        """Whether the open candidate is an `<a>`.

        Tracked separately because an unlinked candidate may be replaced by a
        nested one and an anchor may not: `<a><div>Research</div></a>` must
        record the anchor with its href, not a bare `div` that has lost it."""

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
            if tag in _NAV_TAGS:
                counted = self._inside_header_nav and self._list_depth > 0
                self._nav_stack.append(counted)
                if counted:
                    # A dropdown panel. Everything inside it belongs under the
                    # tab that opens it, not beside that tab.
                    self._dropdown_depth += 1
            self._nav_depth += 1
            return

        if not self._inside_header_nav:
            return

        if tag in _LIST_TAGS:
            self._list_depth += 1
        elif tag == "a":
            self._finish_anchor()
            self._open(mapping.get("href") or None)
            self._anchor_open = True
        elif tag in _HEADING_TAGS and not self._anchor_open and self._list_depth > 0:
            # Replaces any open *unlinked* candidate rather than being ignored.
            # A dropdown toggle is commonly three nested wrappers deep
            # (`w-dropdown` > `w-dropdown-toggle` > text), and keeping the
            # outermost would swallow the entire dropdown into one label —
            # "Commitments Initiatives Claude's Constitution …". The innermost
            # text-bearing element is the one that holds the tab name.
            self._open(None)

    def handle_endtag(self, tag: str) -> None:
        """Close the matching nesting level."""
        if tag == "footer":
            self._footer_depth = max(0, self._footer_depth - 1)
            return
        if tag in _NAV_TAGS:
            self._finish_anchor()
            self._nav_depth = max(0, self._nav_depth - 1)
            if self._nav_stack and self._nav_stack.pop():
                self._dropdown_depth = max(0, self._dropdown_depth - 1)
            return
        if not self._inside_header_nav:
            return
        if tag in _LIST_TAGS:
            self._list_depth = max(0, self._list_depth - 1)
        elif tag == "a":
            self._finish_anchor()
        elif tag in _HEADING_TAGS and not self._anchor_open:
            # Guarded: `</div>` inside an open anchor must not close the anchor
            # early and strip its href.
            self._finish_anchor()

    def handle_data(self, data: str) -> None:
        """Accumulate the visible text of the open anchor."""
        if self._current is not None:
            self._current.append(data)

    def _open(self, href: str | None) -> None:
        """Begin capturing a menu entry at the current list depth."""
        self._current = []
        self._current_href = href
        self._current_depth = self._dropdown_depth + max(0, self._list_depth - 1)

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
        self._anchor_open = False


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


def _prune_unlinked_leaves(nodes: tuple[NavNode, ...]) -> tuple[NavNode, ...]:
    """Drop nodes that neither link anywhere nor group anything.

    An unlinked node earns its place by being a *heading*: it names the section
    its children sit in. One with no children names nothing and reaches nothing,
    so it is noise however it was produced.

    This is what makes accepting `<div>` and `<button>` labels safe. A header
    carries far more unlinked text than menu structure, and on anthropic.com the
    rejected set is instructive: `Try Claude`, `Log in to Claude` and
    `Download app` are call-to-action buttons pointing off-host, and `This is
    some text inside of a div block.` is an unfilled Webflow locale-switcher
    placeholder behind `href="#"`. Every one of them was surfacing as a
    top-level section.

    It also removes the mobile menu's duplicate tabs for free. A site that
    renders its menu twice has its second copy's links dropped by URL
    de-duplication, which leaves those headings childless.

    Bottom-up, so a heading whose only children were themselves pruned is pruned
    in the same pass.
    """
    kept: list[NavNode] = []
    for node in nodes:
        children = _prune_unlinked_leaves(node.children)
        if node.url is None and not children:
            continue
        kept.append(node.model_copy(update={"children": children}))
    return tuple(kept)


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

    roots = _prune_unlinked_leaves(_build_tree(resolved)) if resolved else ()
    if roots:
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
