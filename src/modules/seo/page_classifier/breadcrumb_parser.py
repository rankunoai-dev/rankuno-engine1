"""Extract a page's own breadcrumb trail.

Why this exists
---------------
The header menu answers "where would a visitor look for this?" for the site as a
whole. A breadcrumb answers it for **this page**, published by the site itself.
That makes it the stronger evidence where both exist, and the only evidence on a
flat-URL site whose menu could not be parsed.

Without it, a page such as `openai.com/contact-sales` has one path segment and
lands at path depth 0 — indistinguishable from the homepage in a path tree, on a
site where 1,569 of 1,575 pages are leaves.

Two extractors, both required
-----------------------------
Measured across six live sites, one extractor covers roughly half of them:

* `BreadcrumbList` JSON-LD — highradius (Yoast), gep, infosys (AEM).
* DOM markup — caeliusconsulting (React/Tailwind), allbirds (Shopify).

Neither is a superset. A JSON-LD-only implementation is blind to Shopify and to
most modern component frameworks, which publish an accessible `<nav
aria-label="breadcrumb">` and no structured data at all.

Schema variance is the hard part
--------------------------------
Every JSON-LD site in the sample used a different shape, and all three are valid:

* Yoast:  ``{"name": "Home", "item": "https://…/"}`` — `item` is a string.
* AEM:    ``{"item": {"@id": "https://…", "name": "Services"}}`` — `item` is an
  object and `name` lives *inside* it.
* GEP:    URL-escaped slashes in ``item``, and upper-cased names.

Reading only one shape returns an empty trail for the others, and an empty trail
is indistinguishable from "this site publishes no breadcrumbs". Both shapes are
read, and neither is assumed.

Labels are stored exactly as published. GEP emits `HOME` and `CAREERS AT GEP`;
retitling those would put words in a client's mouth in a report they will read.
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import normalize_url, safe_split

__all__ = [
    "MAX_BREADCRUMB_STEPS",
    "BreadcrumbStep",
    "BreadcrumbTrail",
    "extract_breadcrumb",
    "is_breadcrumb_container",
]

_logger = get_logger("modules.seo.breadcrumb_parser")

MAX_BREADCRUMB_STEPS = 12
"""Ceiling on trail length.

A real breadcrumb is three to six steps. Beyond this the markup is either
malformed or hostile, and a 500-step trail would become 500 tree levels."""

_LD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

_BREADCRUMB_WORD = re.compile(r"breadcrumb", re.IGNORECASE)
"""Matches `breadcrumb` and `breadcrumbs` alike.

Allbirds publishes `aria-label='breadcrumbs'`, plural and single-quoted; an
exact match on `"breadcrumb"` finds neither."""

_HAS_WORD = re.compile(r"\w", re.UNICODE)
"""Separators — `/`, `›`, `»` — are elements too, and are not steps."""

_CONTAINER_TAGS = frozenset({"nav", "ol", "ul", "div", "section", "p", "span"})


class BreadcrumbStep(StrictModel):
    """One crumb.

    Attributes:
        label: Text as published. Not normalised — see the module docstring.
        url: Absolute destination, or `None`. The final crumb is the current
            page and is very often unlinked.
    """

    label: str = Field(min_length=1)
    url: str | None = None


class BreadcrumbTrail(StrictModel):
    """A page's breadcrumb, outermost first.

    Attributes:
        steps: Crumbs from the root down to and including the current page.
        source: `jsonld`, `dom`, or `none`. Recorded because "no breadcrumb on
            this page" and "we failed to read one" are different facts, and only
            the first is a statement about the site.
    """

    steps: tuple[BreadcrumbStep, ...] = ()
    source: str = "none"

    @property
    def labels(self) -> tuple[str, ...]:
        """Just the text, which is what the tree groups by."""
        return tuple(step.label for step in self.steps)

    @property
    def depth(self) -> int:
        """Levels below the root.

        The final crumb is the page itself, so a three-step trail
        `Home > Resources > This Page` puts the page at depth 2.
        """
        return max(0, len(self.steps) - 1)

    @property
    def is_empty(self) -> bool:
        """Whether nothing usable was found."""
        return not self.steps

    def section_labels(self, site_root: str, page_url: str | None = None) -> tuple[str, ...]:
        """Labels with a leading site-root crumb removed, and self-only trails dropped.

        Nearly every breadcrumb opens with a link to the homepage, and that
        crumb is not a section — it is the root the whole tree already hangs
        from. Keeping it collapsed 86% of highradius.com under a single `Home`
        branch and hid the real sections one level down: `Solutions` held 7
        pages while 13 of its own children sat under `Home > Solutions parent
        page`.

        Matched on the crumb's **URL**, never on its text. The label is
        translated — `Home`, `Accueil`, `Startseite` — and a word list would
        work in English and fail everywhere else, which is precisely the bug
        that produced three roots for one concept.

        An unlinked first crumb is left alone: without a URL there is no
        evidence it is the root, and guessing from the label is the thing this
        avoids.

        Crumbs naming **the page itself** are then dropped, however long the
        trail. A breadcrumb states where a page sits; the page is not its own
        ancestor, and the tree already renders it as a leaf. Kept, it becomes a
        level of its own — `linear.app/developers/aig` sat under a section named
        `Agent Interaction Guidelines (AIG)` that contained nothing but that one
        page. rankuno.com shows the degenerate case: `Home > <article title>` and
        nothing else, which made each of 38 pages its own top-level section and
        counted all 38 as reached by navigation when nothing in the menu points
        at them.

        Self-reference is proved, not assumed, and two different proofs are
        needed because sites publish the final crumb two ways:

        * **A crumb whose URL is this page's** — dropped wherever it appears.
        * **An unlinked crumb in final position** — the conventional "you are
          here" markup, dropped only there.

        Position matters for the second rule and the distinction is load-bearing.
        A *middle* unlinked crumb is not the page: `Agents` on linear.app has no
        href because it is a docs section with no page of its own, and it is the
        only ancestry those seven pages have. Dropping unlinked crumbs
        indiscriminately would delete exactly the label worth keeping.

        What survives is a real parent. A truncated trail such as
        `Home > Resources` on `/resources/foo/` keeps `Resources`: its URL is not
        this page's and it is linked, so neither rule fires. That is the only
        placement such a page has and losing it would trade one bug for another.

        Args:
            site_root: The crawl root, for recognising the leading Home crumb.
            page_url: The page this trail was extracted from. Optional only
                because a caller may not have it; without it a linked lone crumb
                is kept, since it cannot be shown to be self-referential.
        """
        if not self.steps:
            return ()
        first = self.steps[0]
        steps = self.steps[1:] if self._is_root_crumb(first, site_root) else self.steps

        target = normalize_url(page_url) if page_url is not None else None
        # Positions are read from the trail as published. Filtering first and
        # then asking "is this crumb last?" promotes a middle crumb into final
        # position and deletes it: on `Agents > AIG`, dropping the self-linked
        # `AIG` left `Agents` last and unlinked, and the trail emptied.
        final = len(steps) - 1

        kept: list[str] = []
        for index, step in enumerate(steps):
            if step.url is None:
                # Unlinked *and* last is the conventional "you are here" crumb.
                # Unlinked anywhere else is a section with no page of its own,
                # which is ancestry and the only ancestry some sites publish.
                if index == final:
                    continue
            elif target is not None and normalize_url(step.url) == target:
                continue
            kept.append(step.label)
        return tuple(kept)

    @staticmethod
    def _is_root_crumb(step: BreadcrumbStep, site_root: str) -> bool:
        return step.url is not None and normalize_url(step.url) == normalize_url(site_root)


def _as_list(value: object) -> list[object]:
    """Coerce a field that may legally be one item or many."""
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _type_names(node: dict[str, object]) -> set[str]:
    """`@type` may be a string or a list; both are valid JSON-LD."""
    return {str(t) for t in _as_list(node.get("@type"))}


def _iter_breadcrumb_lists(payload: object) -> list[dict[str, object]]:
    """Find every `BreadcrumbList`, however deeply nested.

    Yoast wraps everything in an `@graph` array, so the list is never at the top
    level on a WordPress site. Breadth-first to preserve document order, which
    is the tie-break when a page publishes several.
    """
    found: list[dict[str, object]] = []
    queue: list[object] = [payload]
    index = 0
    while index < len(queue):
        current = queue[index]
        index += 1
        if isinstance(current, list):
            queue.extend(current)
        elif isinstance(current, dict):
            if "BreadcrumbList" in _type_names(current):
                found.append(current)
            queue.extend(current.values())
    return found


def _step_from_list_item(item: dict[str, object], base_url: str) -> BreadcrumbStep | None:
    """Read one `ListItem`, accepting every shape observed in the wild.

    `item` is a URL string on Yoast and an object carrying `@id` and `name` on
    AEM — where the *name is inside it* and absent from the `ListItem`. Reading
    only one shape yields an empty trail on the other, silently.
    """
    raw_item = item.get("item")
    url: str | None = None
    name = item.get("name")

    if isinstance(raw_item, str):
        url = raw_item
    elif isinstance(raw_item, dict):
        for key in ("@id", "url", "id"):
            candidate = raw_item.get(key)
            if isinstance(candidate, str):
                url = candidate
                break
        if not isinstance(name, str) or not name.strip():
            name = raw_item.get("name")

    if not isinstance(name, str) or not name.strip():
        return None

    resolved: str | None = None
    if url:
        try:
            # Also normalises the `https:\/\/` escaping GEP publishes, which
            # survives `json.loads` as a literal backslash in some encoders.
            absolute = urljoin(base_url, url.replace("\\/", "/").strip())
        except ValueError:
            absolute = ""
        if safe_split(absolute) is not None and absolute:
            resolved = absolute

    # `html.unescape` because JSON-LD carries raw markup entities: highradius
    # publishes "Treasury &amp; AR Insights", which reached the tree, the report
    # and the PDF verbatim. The DOM extractor gets this free from HTMLParser's
    # `convert_charrefs`; this path had no equivalent.
    return BreadcrumbStep(label=" ".join(html.unescape(name).split()), url=resolved)


def _position_of(item: dict[str, object]) -> int | None:
    """`position` is optional and frequently wrong. Read it, do not trust it."""
    raw = item.get("position")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def _steps_from_list(node: dict[str, object], base_url: str) -> list[BreadcrumbStep]:
    """Project one `BreadcrumbList` into ordered steps.

    Sorted by `position` only when *every* element declares one. A partial set
    would interleave declared and document order, which is worse than either —
    it silently reorders a trail that was correct as written.
    """
    elements = [e for e in _as_list(node.get("itemListElement")) if isinstance(e, dict)]
    positions = [_position_of(e) for e in elements]
    if elements and all(p is not None for p in positions):
        order = sorted(range(len(elements)), key=lambda i: positions[i] or 0)
        elements = [elements[i] for i in order]

    steps: list[BreadcrumbStep] = []
    for element in elements[:MAX_BREADCRUMB_STEPS]:
        step = _step_from_list_item(element, base_url)
        if step is not None:
            steps.append(step)
    return steps


def _from_jsonld(html: str, base_url: str) -> list[BreadcrumbStep]:
    """Longest trail across every `BreadcrumbList` on the page.

    A product listed in several categories emits one list per category. The
    longest is the most specific, and specificity is the whole point.
    """
    best: list[BreadcrumbStep] = []
    for block in _LD_BLOCK.findall(html):
        try:
            payload = json.loads(block)
        except (ValueError, TypeError):
            # One malformed block among several must not lose the others.
            continue
        for node in _iter_breadcrumb_lists(payload):
            steps = _steps_from_list(node, base_url)
            if len(steps) > len(best):
                best = steps
    return best


def is_breadcrumb_container(attributes: dict[str, str]) -> bool:
    """Whether an element's attributes mark it as a breadcrumb.

    Exported because the *header menu* parser needs it too. A breadcrumb often
    carries `role="navigation"`, which made it indistinguishable from the site
    menu: allbirds' `Home / Mens / Shoes` were being parsed as top-level tabs
    beside the real ones.
    """
    for key in ("aria-label", "class", "id", "itemtype", "data-testid"):
        value = attributes.get(key)
        if value and _BREADCRUMB_WORD.search(value):
            return True
    return False


class _DomBreadcrumbCollector(HTMLParser):
    """Collect crumbs from an accessible breadcrumb element.

    The fallback for the sites that publish no structured data at all, which in
    the sample was every React and Shopify storefront. They are consistent about
    one thing — an `aria-label` naming the region — because it is what a screen
    reader needs, and that is the hook used here.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.steps: list[BreadcrumbStep] = []
        self._depth = 0
        """Open element depth inside the breadcrumb, 0 when outside it."""
        self._text: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter the container, then capture each crumb inside it."""
        mapping = {key.lower(): value or "" for key, value in attrs}

        if self._depth == 0:
            if tag in _CONTAINER_TAGS and is_breadcrumb_container(mapping):
                self._depth = 1
            return

        self._depth += 1
        if tag == "a":
            self._flush()
            self._text = []
            self._href = mapping.get("href") or None
        elif tag in {"span", "li"} and self._text is None:
            # The current page is usually the one unlinked crumb.
            self._text = []
            self._href = None

    def handle_endtag(self, tag: str) -> None:
        """Close a crumb, and leave the container at depth zero."""
        if self._depth == 0:
            return
        if tag in {"a", "span", "li"}:
            self._flush()
            # Re-open an empty buffer rather than stopping. The final crumb is
            # commonly bare text sitting *after* a separator element inside the
            # same `<li>` — `<li><span>/</span>Wool Runners</li>` — and closing
            # capture at `</span>` dropped it. Shopify's product name went
            # missing exactly this way. An empty buffer costs nothing: a flush
            # with no word characters is discarded.
            if self._depth > 1:
                self._text = []
                self._href = None
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        """Accumulate crumb text."""
        if self._text is not None:
            self._text.append(data)

    def _flush(self) -> None:
        if self._text is None:
            return
        label = " ".join("".join(self._text).split())
        # `/`, `›` and `»` are elements in their own right on most markup and
        # are not crumbs.
        if label and _HAS_WORD.search(label):
            self.steps.append(BreadcrumbStep(label=label, url=self._href))
        self._text = None
        self._href = None


def _from_dom(html: str, base_url: str) -> list[BreadcrumbStep]:
    """Read crumbs from accessible breadcrumb markup."""
    collector = _DomBreadcrumbCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup must not abort a crawl
        _logger.debug("breadcrumb_dom_partial", extra={"url": base_url, "error": str(exc)})

    resolved: list[BreadcrumbStep] = []
    seen: set[str] = set()
    for step in collector.steps[:MAX_BREADCRUMB_STEPS]:
        # A nested `<a><span>Home</span></a>` yields the crumb twice; the outer
        # anchor and inner span carry the same text.
        if step.label in seen:
            continue
        seen.add(step.label)
        url = step.url
        if url:
            try:
                url = urljoin(base_url, url.strip())
            except ValueError:
                url = None
            if url and safe_split(url) is None:
                url = None
        resolved.append(step.model_copy(update={"url": url}))
    return resolved


def extract_breadcrumb(html: str, base_url: str) -> BreadcrumbTrail:
    """Extract a page's breadcrumb trail.

    Structured data is tried first: it states the trail rather than implying it
    through styling, and it survives a redesign. DOM markup is the fallback, not
    the equal — a `class="breadcrumb"` element could be anything, while a
    `BreadcrumbList` is an assertion.

    Args:
        html: Raw page HTML.
        base_url: Absolute URL of that page, for resolving relative crumbs.

    Returns:
        The trail. Empty with `source="none"` when the page publishes none,
        which is a fact about the page and not a failure.
    """
    if not html.strip():
        return BreadcrumbTrail()

    steps = _from_jsonld(html, base_url)
    if steps:
        return BreadcrumbTrail(steps=tuple(steps), source="jsonld")

    steps = _from_dom(html, base_url)
    if steps:
        return BreadcrumbTrail(steps=tuple(steps), source="dom")

    return BreadcrumbTrail()
