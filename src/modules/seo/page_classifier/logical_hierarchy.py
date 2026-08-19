"""Place every discovered URL under the section a visitor would find it in.

The problem this solves
-----------------------
A URL-path tree answers "where does this file live?". The header menu answers
"where would a visitor look for this?". They diverge, and the second question is
the one an SEO audit is actually asking.

Why exact matching is not enough
--------------------------------
Measured on gep.com: the header menu holds 168 unique internal URLs; the sitemap
holds 4,427. Assigning only URLs that appear *in* the menu would leave **96.2%**
of the site in `OTHERS`, and a bucket holding 96% of the pages has organised
nothing.

So a menu entry is treated as a **path prefix its descendants inherit**.
`/company/culture/diversity` is a menu item, so `/company/culture/diversity/2024`
belongs to it even though no menu links there. The longest matching prefix wins,
which puts a page under the most specific section that contains it.

What lands in OTHERS, and why that is useful
--------------------------------------------
Whatever no menu section contains: campaign landing pages, press releases,
orphaned content. That is not a dumping ground — it is the finding. A page no
navigation path reaches is a page users cannot browse to, which is exactly what
an audit is looking for. Inside `OTHERS` the pages are sub-grouped by
`PrimaryPageType` so the bucket stays readable at thousands of URLs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.nav_tree_parser import NavigationTree, NavNode
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    PrimaryPageType,
)
from src.modules.seo.page_classifier.url_rules import normalize_url

__all__ = [
    "OTHERS_LABEL",
    "NavAssignment",
    "NavCoverageReport",
    "assign_navigation",
    "recount_placements",
]

_logger = get_logger("modules.seo.logical_hierarchy")

OTHERS_LABEL = "OTHERS"
"""Root group for URLs no navigation section contains.

Not a failure bucket. A page outside every navigation path is unreachable by
browsing, which is a real finding rather than a gap in the analysis.
"""


class NavAssignment(StrictModel):
    """Where one URL sits in the navigation tree.

    Attributes:
        url: The page.
        nav_path: Section labels from the top tab down, e.g.
            `("Company", "Culture", "Diversity")`. Empty for `OTHERS` members.
        nav_parent_url: URL of the menu entry it was matched to, `None` when
            unmatched.
        matched_exactly: True when this URL *is* a menu entry, false when it
            inherited from an ancestor prefix. The difference matters: an exact
            match is a page the site links to directly, an inherited one is only
            reachable by digging.
        group: Top-level group for display — the first nav label, or `OTHERS`.
    """

    url: str = Field(min_length=1)
    nav_path: tuple[str, ...] = ()
    nav_parent_url: str | None = None
    matched_exactly: bool = False
    group: str = OTHERS_LABEL


class NavCoverageReport(StrictModel):
    """How much of the site has a published navigational position, and from where.

    Reported rather than assumed. Coverage varies enormously between sites, and a
    caller presenting a nav tree needs to know whether it describes the site or a
    corner of it.

    Two sources, counted apart
    --------------------------
    A page can be placed by the **header menu** or by its **own published
    breadcrumb**, and the two fail differently: a menu path is wrong for the
    whole site at once, a breadcrumb is wrong one page at a time. They are
    therefore counted separately and summed only by `placed`.

    Until cycle 0022 this model counted the menu alone, so every
    breadcrumb-placed page landed in `unmatched` — 22,869 of kinsta.com's 27,656
    pages, reported under the words "no navigation path reaches these" while the
    tree on the same screen placed all of them correctly. `unmatched` now means
    what it says: nothing on the site places this URL.

    Attributes:
        total_urls: URLs considered.
        exact_matches: URLs that are themselves menu entries.
        inherited_matches: URLs placed under an ancestor menu entry.
        breadcrumb_matches: URLs placed by their own published breadcrumb, the
            menu having not reached them. Defaults to 0, which is also what every
            result stored before this field existed will deserialize to — those
            keep the old menu-only reading until they are reparsed.
        unmatched: URLs no source places, i.e. `OTHERS`.
        nav_entries: Linked entries in the menu.
        groups: Top-level group names, in menu order, `OTHERS` last if present.
    """

    total_urls: int = Field(default=0, ge=0)
    exact_matches: int = Field(default=0, ge=0)
    inherited_matches: int = Field(default=0, ge=0)
    breadcrumb_matches: int = Field(default=0, ge=0)
    unmatched: int = Field(default=0, ge=0)
    nav_entries: int = Field(default=0, ge=0)
    groups: tuple[str, ...] = ()

    @property
    def menu_matches(self) -> int:
        """URLs the header menu reaches, exactly or by inheritance."""
        return self.exact_matches + self.inherited_matches

    @property
    def placed(self) -> int:
        """URLs with a published position, from either source."""
        return self.menu_matches + self.breadcrumb_matches

    @property
    def coverage(self) -> float:
        """Fraction of URLs with any published position, 0.0–1.0.

        Widened from menu-only in cycle 0022. `menu_coverage` is the previous
        meaning, kept because the two are genuinely different questions and the
        gap between them is itself a finding about the site.
        """
        if not self.total_urls:
            return 0.0
        return self.placed / self.total_urls

    @property
    def menu_coverage(self) -> float:
        """Fraction of URLs the header menu alone accounts for, 0.0–1.0."""
        if not self.total_urls:
            return 0.0
        return self.menu_matches / self.total_urls


def recount_placements(
    report: NavCoverageReport,
    pages: Sequence[FullPageIntelligenceProfile],
) -> NavCoverageReport:
    """Restate a menu-only coverage report against what finally placed each page.

    `assign_navigation` runs *before* `_better_trail` decides between the menu
    and a page's own breadcrumb, so the report it returns can only know about the
    menu. This closes that gap by re-reading `trail_source`, which is the record
    of which source actually won.

    Counted from `trail_source` rather than from a non-empty `breadcrumb_path`,
    because a page in `OTHERS` carries the trail `(OTHERS, <page type>)` — a
    non-empty path that places nothing. Counting paths would report every
    unplaced page as placed, which is the inverse of the bug this fixes.

    The menu counts are carried through untouched: they came from prefix matching
    against the parsed tree and re-deriving them here would give a second
    definition of "exact match" to disagree with the first.

    Args:
        report: The menu-derived report from `assign_navigation`.
        pages: The profiles *after* placement, carrying final `trail_source`.

    Returns:
        A new report. `total_urls` is taken from `pages`, so a caller that
        filtered between the two calls gets a coherent total rather than a
        stale one.
    """
    breadcrumb = sum(1 for page in pages if page.trail_source == "breadcrumb")
    menu = sum(1 for page in pages if page.trail_source == "menu")

    # `menu` recomputed only to bound the carried-through split. When placement
    # demotes a menu page — `_better_trail` prefers a deeper breadcrumb — the
    # stored exact/inherited pair would otherwise exceed the pages that are still
    # menu-placed, and `unmatched` would go negative on a `ge=0` field.
    exact = min(report.exact_matches, menu)
    inherited = min(report.inherited_matches, menu - exact)

    return report.model_copy(
        update={
            "total_urls": len(pages),
            "exact_matches": exact,
            "inherited_matches": inherited,
            "breadcrumb_matches": breadcrumb,
            "unmatched": len(pages) - exact - inherited - breadcrumb,
        }
    )


def _match_key(url: str) -> str:
    """Comparable path for prefix matching.

    Built from `normalize_url` so this agrees with the deduplication the rest of
    discovery already did — a nav entry and a sitemap entry for the same page
    must compare equal or the match silently fails.

    A trailing slash is added so prefixes cannot match across segment
    boundaries: without it `/services` would claim `/services-pricing`.
    """
    normalized = normalize_url(url)
    path = normalized.split("://", 1)[-1]
    cut = path.find("/")
    path = path[cut:] if cut != -1 else "/"
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = f"/{path}"
    return path if path.endswith("/") else f"{path}/"


def _nav_entries(tree: NavigationTree) -> list[tuple[str, tuple[str, ...], str]]:
    """Flatten the menu to `(match_key, label_path, url)`, deepest first.

    Sorted by key length descending so the first hit is the longest prefix, which
    is the most specific section containing the page.
    """
    entries: list[tuple[str, tuple[str, ...], str]] = []

    def walk(node: NavNode, ancestry: tuple[str, ...]) -> None:
        label = node.label or (node.url or "")
        path = (*ancestry, label) if label else ancestry
        if node.url:
            key = _match_key(node.url)
            # The site root is excluded as a match target. Almost every header
            # links the logo to `/`, whose key is `/` — a prefix of every URL on
            # the site. Left in, it silently absorbs everything that should have
            # gone to OTHERS, and coverage reads 100% on every site regardless of
            # how much the menu actually covers. Observed on gep.com: 0 unmatched
            # pages out of 600, which was the bug and not the achievement.
            if key != "/":
                entries.append((key, path, node.url))
        for child in node.children:
            walk(child, path)

    for root in tree.roots:
        walk(root, ())

    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def _group_order(tree: NavigationTree) -> list[str]:
    """Top-level group names in menu order, so the UI matches the site header."""
    order: list[str] = []
    for root in tree.roots:
        label = root.label or (root.url or "")
        if label and label not in order:
            order.append(label)
    return order


def assign_navigation(
    tree: NavigationTree,
    profiles: Sequence[FullPageIntelligenceProfile],
    *,
    page_types: Mapping[str, PrimaryPageType] | None = None,
) -> tuple[dict[str, NavAssignment], NavCoverageReport]:
    """Place every profile under a navigation section, or under `OTHERS`.

    Args:
        tree: The parsed header menu. An empty tree puts everything in `OTHERS`,
            which is correct: with no menu there is no navigational structure to
            report, and inventing one from URL paths would misrepresent it as
            something the site published.
        profiles: Classified pages to place.
        page_types: Optional override of each URL's page type, used to sub-group
            `OTHERS`. Defaults to each profile's own `primary_page_type`.

    Returns:
        The assignments by URL, and a coverage report.
    """
    entries = _nav_entries(tree)
    assignments: dict[str, NavAssignment] = {}
    exact = 0
    inherited = 0

    for profile in profiles:
        key = _match_key(profile.url)
        assignment = _assign_one(profile, key, entries, page_types)
        assignments[profile.url] = assignment

        if assignment.matched_exactly:
            exact += 1
        elif assignment.nav_parent_url is not None:
            inherited += 1

    groups = _group_order(tree)
    if any(item.group == OTHERS_LABEL for item in assignments.values()):
        groups.append(OTHERS_LABEL)

    report = NavCoverageReport(
        total_urls=len(profiles),
        exact_matches=exact,
        inherited_matches=inherited,
        unmatched=len(profiles) - exact - inherited,
        nav_entries=len(entries),
        groups=tuple(groups),
    )
    _logger.info("nav_coverage", extra=report.model_dump(exclude={"groups"}))
    return assignments, report


def _assign_one(
    profile: FullPageIntelligenceProfile,
    key: str,
    entries: Iterable[tuple[str, tuple[str, ...], str]],
    page_types: Mapping[str, PrimaryPageType] | None,
) -> NavAssignment:
    """Match one URL against the menu, longest prefix first."""
    for entry_key, labels, entry_url in entries:
        if key == entry_key:
            return NavAssignment(
                url=profile.url,
                nav_path=labels,
                nav_parent_url=entry_url,
                matched_exactly=True,
                group=labels[0] if labels else OTHERS_LABEL,
            )
        if key.startswith(entry_key):
            return NavAssignment(
                url=profile.url,
                nav_path=labels,
                nav_parent_url=entry_url,
                matched_exactly=False,
                group=labels[0] if labels else OTHERS_LABEL,
            )

    # Unmatched. Sub-grouped by page type so `OTHERS` stays navigable: on a large
    # site this bucket holds thousands of URLs, and a flat list of them is not an
    # improvement on no grouping at all.
    page_type = (page_types or {}).get(profile.url, profile.primary_page_type)
    return NavAssignment(
        url=profile.url,
        nav_path=(OTHERS_LABEL, page_type.value),
        nav_parent_url=None,
        matched_exactly=False,
        group=OTHERS_LABEL,
    )
