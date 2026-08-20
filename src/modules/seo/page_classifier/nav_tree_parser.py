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
from src.modules.seo.page_classifier.breadcrumb_parser import is_breadcrumb_container
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

ROOT_LEVEL_ATTRS: dict[str, int] = {
    # Vendor attributes, 0-based: level 0 is a top-level tab.
    "data-menu-level": 0,
    "data-level": 0,
    # WAI-ARIA, 1-based by specification: `aria-level="1"` is a top-level item.
    # Getting this wrong is not a cosmetic error — reading a compliant site's
    # "1" as depth 1 would demote every top tab to a child of whatever preceded
    # it, inverting the menu on exactly the sites that mark it up correctly.
    "aria-level": 1,
}
"""Attributes by which markup can declare an item's own menu depth, and the
value each uses for the top level.

Read only to answer one question — *is this a top-level tab?* — never to
override depth generally. Measured on the gep.com homepage: 26 of 609 anchors
carry `data-menu-level`, and **none** of the 126 content links do. Only section
labels declare a depth, so treating the attribute as the depth would put 4% of
anchors on one scale and 96% on another and then compare them against each
other in `_build_tree`.

Why the signal is needed at all: gep.com renders its top tabs as
`<div title="Careers">` and `<a data-bs-toggle="pill">` — neither is a link, and
its hamburger menu is 52 sibling `<ul class="site-map-menu">` lists rather than
one tree. No amount of DOM nesting can say those ten anchors are siblings. The
attribute is the only place the site states it."""
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

_FRAGMENT_HREF = re.compile(r"^#([A-Za-z][\w:.-]*)$")
"""A pure-fragment href, which on a mega-menu names the panel the tab opens.

Anchored at both ends deliberately. `#` alone is a placeholder used by menus
that wire themselves up in JavaScript and addresses nothing; `/a#b` is a link to
another page that happens to carry a fragment. Only `#id` is the disclosure
pattern this reads."""

_PANEL_TAGS = frozenset({"div", "section", "aside", "ul", "ol", "nav", "details"})
"""Elements that may be a dropdown panel.

Containers only. A fragment can legitimately point at a heading or an icon —
`<a href="#icon-1">` against `<span id="icon-1">` — and treating an inline
element as a panel would push a whole menu down a level for nothing."""

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
"""HTML elements with no closing tag. Counting them would desync the stack."""

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
        self.declared_root_hrefs: list[str] = []
        """Raw hrefs of anchors whose own markup calls them top-level.

        Collected beside the entries rather than folded into them: depth stays
        derived from nesting for every anchor, and this is consulted once, after
        the tree is built, to lift the few the site declares as tabs."""
        self.containers = 0
        self._nav_depth = 0
        self._footer_depth = 0
        self._crumb_depth = 0
        """Open breadcrumb containers.

        A breadcrumb is frequently marked `role="navigation"`, which made it
        indistinguishable from the site menu: allbirds.com publishes
        `<nav role='navigation' aria-label='breadcrumbs'>`, and its `Home` and
        `Men's Shoes` crumbs were parsed as top-level tabs beside the real
        ones. A breadcrumb describes one page's ancestry, not the site's menu,
        so it is excluded here and read by `breadcrumb_parser` instead."""
        self._list_depth = 0
        self._dropdown_depth = 0
        """Nested nav containers opened *inside* a list item.

        A dropdown panel is frequently its own `<nav>` inside the `<li>` of the
        tab that opens it, and its group headings then sit at the same list
        depth as the tabs themselves. Counting only navs opened inside a list is
        what separates the two: `<header><nav>` wraps the whole menu and opens
        before any list, so it must not shift every tab down a level."""
        self._crumb_tags: list[str] = []
        """Tag names of the open breadcrumb containers, to close the right one."""
        self._nav_stack: list[bool] = []
        """Whether each open `<nav>`/`<header>` counted as a dropdown.

        Only these two tags are tracked. An element carrying
        `role="navigation"` still gates parsing as before, but is not counted
        here: matching its close would need a full element stack, and getting
        that wrong would mis-depth an entire menu."""
        self._panel_ids: set[str] = set()
        """Fragment targets named by tab anchors seen so far.

        Kinsta states the tab-to-panel relationship outright — the tab is
        `<a href="#megamenu-item-0__child">` and the panel is
        `<div id="megamenu-item-0__child">`. That is the ARIA disclosure
        pattern, and it is authored intent rather than a class-name guess, which
        is what makes acting on it safe.

        Without it the panel is invisible to the depth model: `_dropdown_depth`
        counts only `<nav>`/`<header>`, so a `<div>` panel left the column
        headings inside it at the same depth as the tabs. `Platform` was then
        closed with no children by the first `<h6>` and pruned as an unlinked
        leaf, and its column titles — `Product`, `Features`, `Extensions` — were
        promoted to top-level tabs in its place."""
        self._elements: list[str] = []
        """Open non-void elements inside the header, for closing panels.

        Needed because a panel is a `<div>` among many nested `<div>`s, so
        matching on tag name alone would close it at the first inner `</div>`.
        Depth in this stack is the only reliable marker of where it ends."""
        self._panel_levels: list[int] = []
        """Stack depth at which each open panel began."""
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
        return self._nav_depth > 0 and self._footer_depth == 0 and self._crumb_depth == 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track nav/footer/list nesting and open anchors."""
        mapping = {key: value or "" for key, value in attrs}

        if tag == "footer" or mapping.get("role") == "contentinfo":
            self._footer_depth += 1
            return

        if is_breadcrumb_container(mapping):
            self._crumb_depth += 1
            self._crumb_tags.append(tag)
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

        # Element stack first, so a panel's own opening tag is on it before its
        # level is recorded.
        if tag not in _VOID_TAGS:
            self._elements.append(tag)
            element_id = mapping.get("id", "").strip()
            if tag in _PANEL_TAGS and element_id and element_id in self._panel_ids:
                self._panel_levels.append(len(self._elements))
                self._dropdown_depth += 1

        if tag in _LIST_TAGS:
            self._list_depth += 1
        elif tag == "a":
            self._finish_anchor()
            href = mapping.get("href") or None
            if href and (match := _FRAGMENT_HREF.match(href.strip())):
                # Recorded before the panel is reached: the tab always precedes
                # the panel it opens.
                self._panel_ids.add(match.group(1))
            if href and _declares_root(mapping):
                self.declared_root_hrefs.append(href)
            self._open(href)
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
        if self._crumb_tags and self._crumb_tags[-1] == tag:
            self._crumb_tags.pop()
            self._crumb_depth = max(0, self._crumb_depth - 1)
            return
        if tag in _NAV_TAGS:
            self._finish_anchor()
            self._nav_depth = max(0, self._nav_depth - 1)
            if self._nav_stack and self._nav_stack.pop():
                self._dropdown_depth = max(0, self._dropdown_depth - 1)
            return
        if not self._inside_header_nav:
            return

        if tag not in _VOID_TAGS and tag in self._elements:
            # Pop to the match rather than popping once. Menus routinely omit
            # `</li>`, and a stack that only ever popped its top would drift by
            # one per item until the panel boundary was meaningless.
            while self._elements:
                popped = self._elements.pop()
                while self._panel_levels and self._panel_levels[-1] > len(self._elements):
                    self._panel_levels.pop()
                    self._dropdown_depth = max(0, self._dropdown_depth - 1)
                if popped == tag:
                    break

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

    Gaps in the incoming depths are closed by *rank*, not by clamping against
    the stack height. A mega-menu opens its panel in a wrapper the collector
    counts, so rankuno.com's Our Expertise arrives as `0, 2, 3, 3, 2, 2, 3` — the
    tab, a column heading, its items, then the next heading. Clamping each entry
    to `len(stack)` closed that 0→2 jump for the first heading only: it dropped
    to 1, and every heading after it kept depth 2 and became a *child* of the
    first instead of its sibling. The whole dropdown collapsed into one chain,
    with `SEO` beside `Digital Channels` rather than under it and `Perspective`
    given a parent it does not have on the site.

    Comparing raw depths against each other keeps entries at the same incoming
    depth at the same outgoing depth, however wide the jump that preceded them.
    """
    roots: list[NavNode] = []
    # Each stack slot holds the node at that depth and its accumulating children.
    stack: list[tuple[NavNode, list[NavNode]]] = []
    # The raw depth of each open slot, so a later entry can be ranked against it.
    open_raw: list[int] = []

    def collapse(to_depth: int) -> None:
        while len(stack) > to_depth:
            node, children = stack.pop()
            open_raw.pop()
            finished = node.model_copy(update={"children": tuple(children)})
            if stack:
                stack[-1][1].append(finished)
            else:
                roots.append(finished)

    for raw_depth, label, url in entries:
        # Close every open level at or below this entry's own depth; what is
        # left open is its ancestry, and its rank among them is its depth.
        rank = len(open_raw)
        while rank > 0 and open_raw[rank - 1] >= raw_depth:
            rank -= 1
        depth = min(rank, MAX_NAV_DEPTH - 1)
        collapse(depth)
        stack.append((NavNode(label=label, url=url, depth=depth), []))
        # The raw depth is recorded, not the clamped one. Past MAX_NAV_DEPTH
        # several raw levels share one slot, and ranking on the clamped value
        # would make a deeper entry look like a sibling of its own parent.
        open_raw.append(raw_depth)

    collapse(0)
    return tuple(roots)


def _declares_root(attrs: dict[str, str]) -> bool:
    """Whether an anchor's own attributes call it a top-level tab.

    Each attribute is compared against its own base — 0 for the vendor ones, 1
    for `aria-level` — so a compliant site is not inverted by the convention a
    different one happens to use.

    A non-numeric or absent value is simply not a declaration. Templates emit
    `aria-level="{{level}}"` unrendered often enough that raising would turn a
    templating slip into a failed crawl.
    """
    for attribute, top in ROOT_LEVEL_ATTRS.items():
        raw = attrs.get(attribute)
        if raw is None:
            continue
        try:
            if int(raw.strip()) == top:
                return True
        except ValueError:
            continue
    return False


def _promote_declared_roots(
    nodes: tuple[NavNode, ...], declared: frozenset[str]
) -> tuple[NavNode, ...]:
    """Lift nodes the markup calls top-level out of wherever nesting put them.

    Applied after the tree is built rather than by forcing depth during the
    walk. Depth is a *position in a stream* to `_build_tree`: setting an entry
    to 0 mid-stream closes every open level above it, so promoting gep.com's
    `/careers` in place would have made the rest of the Company dropdown its
    siblings instead of Company's children. Rebuilding the branch afterwards
    moves one node and disturbs nothing else.

    A promoted node keeps its own children. Its former parent may be left
    childless, which `_prune_unlinked_leaves` removes on the next pass if it
    also links nowhere — the reason promotion runs first.

    Promoted nodes are appended after the roots nesting already found. Document
    order is not recoverable here and inventing one would be a guess; the tree
    is sorted for display by `dashboardModel` regardless.

    Args:
        nodes: The tree as nesting produced it.
        declared: Resolved URLs whose anchors declared themselves top-level.

    Returns:
        The tree with those nodes at the root, each appearing exactly once.
    """
    if not declared:
        # The overwhelmingly common case: no site in the corpus but gep.com
        # declares a depth, so this returns untouched for everything else.
        return nodes

    lifted: list[NavNode] = []

    def strip(branch: tuple[NavNode, ...], *, at_root: bool) -> tuple[NavNode, ...]:
        kept: list[NavNode] = []
        for node in branch:
            rebuilt = node.model_copy(update={"children": strip(node.children, at_root=False)})
            if not at_root and rebuilt.url is not None and rebuilt.url in declared:
                lifted.append(rebuilt.model_copy(update={"depth": 0}))
                continue
            kept.append(rebuilt)
        return tuple(kept)

    remaining = strip(nodes, at_root=True)
    return (*remaining, *lifted)


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

    # Resolved through the same helper the entries used, so a declaration and
    # its entry agree on what the URL is. A declared href the resolver refuses —
    # off-host, unusable — simply never joins the set.
    declared = frozenset(
        url
        for href in collector.declared_root_hrefs
        if (url := _usable_href(href, base_url, base_host)) is not None
    )
    roots = (
        _prune_unlinked_leaves(_promote_declared_roots(_build_tree(resolved), declared))
        if resolved
        else ()
    )
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
