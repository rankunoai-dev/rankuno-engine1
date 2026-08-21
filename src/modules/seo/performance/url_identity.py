"""Tie a Google-reported URL to the page the crawler actually holds.

The problem
-----------
Search Console reports the URL *it* chose as canonical. GA4 reports whatever
path its tag saw in the address bar, with no host at all. The crawler holds the
address a link pointed at. On a real site these three disagree constantly:

* the crawl found `/about/csr-policy/`, which 301s — Google reports the
  destination;
* the page declares `<link rel="canonical">` to a URL that is neither;
* GA4 reports `/about/csr-policy/?utm_source=nl`, and drops the host;
* an editor linked `/About/CSR-Policy` with no trailing slash.

A dashboard that joins on the raw string attributes four pages' worth of traffic
to nothing, reports the section as having no demand, and gives no sign that
anything went wrong. **The silence is the defect** — everything in this module
exists to convert that silence into a countable number.

How it resolves
---------------
An alias index is built from every address each crawled page is known by, in
descending order of evidence: the crawled URL, the redirect destination, then
the declared canonical. A stronger tier is never overwritten by a weaker one.

Ambiguity is refused, not guessed
---------------------------------
Canonical tags are many-to-one by design — that is what they are for. So the
same alias routinely names several crawled pages, and picking one would move
real traffic into the wrong section while looking exactly like a correct answer.
Any alias claimed by two different pages at the tier that would decide it is
marked ambiguous and resolves to `MatchFailure.AMBIGUOUS`.

The same rule is what makes the host question safe. The path maps are keyed on
path alone, because GA4 supplies no host; if a crawl spans two hosts and both
serve `/pricing/`, that path is claimed twice and is refused rather than
attributed to whichever host happened to be indexed first.

Pure domain logic: no I/O, no settings, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import SplitResult, parse_qsl, urlencode

from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.page_classifier.url_rules import (
    is_tracking_param,
    normalize_path,
    normalize_url,
    safe_split,
    site_host,
)
from src.modules.seo.performance.schemas import (
    RELIABLE_MATCH_RATE,
    MatchFailure,
    MatchTier,
    ResolutionOutcome,
    UrlFailure,
    UrlMatch,
)

__all__ = ["UrlResolutionIndex"]

# Alias sources in descending order of evidence. Order is load-bearing: the
# merge below stops at the first tier that names an owner, so a canonical tag
# can never overrule the address a page was actually crawled at.
_SOURCES: tuple[tuple[str, MatchTier], ...] = (
    ("url", MatchTier.CRAWLED_URL),
    ("final_url", MatchTier.REDIRECT_TARGET),
    ("canonical_url", MatchTier.CANONICAL_TAG),
)

_Owner = tuple[str, MatchTier]
_Tier = tuple[dict[str, str], set[str], MatchTier]
_Index = tuple[dict[str, _Owner], set[str]]


def _query_key(parts: SplitResult) -> str:
    """Render the non-tracking query in a stable order.

    Same rule as `normalize_url`, applied on its own because the path maps need
    a query string without a host in front of it.
    """
    kept = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if not is_tracking_param(name)
    ]
    return urlencode(sorted(kept))


def _path_key(parts: SplitResult) -> str:
    """Path plus surviving query — the host-free identity of an address."""
    query = _query_key(parts)
    path = normalize_path(parts.path or "/")
    return f"{path}?{query}" if query else path


def _tier_index(aliases: Iterable[tuple[str, str]], tier: MatchTier) -> _Tier:
    """Index one tier's aliases, recording clashes instead of resolving them.

    Args:
        aliases: `(alias, owner)` pairs from a single evidence tier.
        tier: The evidence tier these aliases came from.

    Returns:
        The alias-to-owner map, the set of aliases claimed by more than one
        owner, and the tier. A clashed alias is left in the map so the merge can
        see that this tier had an opinion and refuse, rather than falling
        through to a weaker tier that would answer more confidently on less
        evidence.
    """
    owners: dict[str, str] = {}
    clashed: set[str] = set()
    for alias, owner in aliases:
        # A second claim is always a *different* page: the caller deduplicates
        # profiles by dedup key before building any tier, so one owner
        # contributes at most one pair here.
        if alias in owners:
            clashed.add(alias)
        else:
            owners[alias] = owner
    return owners, clashed, tier


def _merge(tiers: Iterable[_Tier]) -> _Index:
    """Collapse per-tier indexes into one, strongest tier winning."""
    merged: dict[str, _Owner] = {}
    ambiguous: set[str] = set()
    for owners, clashed, tier in tiers:
        for alias, owner in owners.items():
            if alias in merged or alias in ambiguous:
                continue
            if alias in clashed:
                ambiguous.add(alias)
            else:
                merged[alias] = (owner, tier)
    return merged, ambiguous


class UrlResolutionIndex:
    """Resolves Search Console and GA4 addresses onto crawled page URLs.

    Built once per crawl and queried per export row. Construction is O(pages)
    and lookup is O(1); nothing here re-parses the site.

    The value a lookup returns is `FullPageIntelligenceProfile.url` — the key the
    site graph already uses. A new page identity is deliberately not invented:
    two halves of a dashboard that disagree about what a page is will eventually
    disagree about how many there are.
    """

    def __init__(self, profiles: Iterable[FullPageIntelligenceProfile]) -> None:
        """Build the index from one crawl's classified pages.

        Args:
            profiles: Every page the crawl produced a profile for. Consumed
                once; order is irrelevant, since clashes are recorded rather
                than resolved by arrival.
        """
        # Collapse profiles the engine's own dedup key already calls one page.
        # Measured across 70 stored crawls, results contain rows whose
        # `normalized_path` is identical — 20 in a fresh 12,807-page highradius
        # crawl, 863 in an older 33,439-page one. Two shapes produce them:
        #
        #     /en-gb/whats-new/?ref=navbar   vs   /en-gb/whats-new/
        #     /value-creation//konica-…/     vs   /value-creation/konica-…/
        #
        # Refusing those as ambiguous would be the wrong kind of honest: they
        # are not two pages competing for one address, they are one page the
        # crawl emitted twice, and treating them as a conflict would drop up to
        # 7% of an export for a defect the analyst cannot see or fix. Keying on
        # `normalize_url` rather than the stored `normalized_path` means this
        # holds even on crawls stored before that field settled.
        #
        # The duplicates are an upstream defect and are counted, not hidden —
        # see `duplicate_profiles`.
        by_key: dict[str, FullPageIntelligenceProfile] = {}
        duplicates = 0
        for page in profiles:
            key = normalize_url(page.url)
            if key in by_key:
                duplicates += 1
            else:
                by_key[key] = page
        pages = tuple(by_key.values())
        self.duplicate_profiles = duplicates
        """Profiles dropped as re-emissions of a page already held.

        Non-zero means the crawl that produced these profiles reported the same
        address more than once, which inflates every page count downstream of
        it. Surfaced here because this is the first thing in the engine that
        recomputes the dedup key over a whole result and can therefore see it.
        """
        self._hosts = frozenset(self._host_of(page.url) for page in pages) - {""}

        absolute: list[_Tier] = []
        with_query: list[_Tier] = []
        bare: list[_Tier] = []

        for field, tier in _SOURCES:
            urls: list[tuple[str, str]] = [(getattr(page, field), page.url) for page in pages]
            live = [(alias, owner) for alias, owner in urls if alias]
            absolute.append(_tier_index(((normalize_url(a), o) for a, o in live), tier))

            split = [(safe_split(alias), owner) for alias, owner in live]
            parsed = [(parts, owner) for parts, owner in split if parts is not None]
            with_query.append(_tier_index(((_path_key(p), o) for p, o in parsed), tier))
            bare.append(_tier_index(((normalize_path(p.path or "/"), o) for p, o in parsed), tier))

        self._absolute, self._absolute_clash = _merge(absolute)
        self._path, self._path_clash = _merge(with_query)
        self._bare, self._bare_clash = _merge(bare)

    @staticmethod
    def _host_of(url: str) -> str:
        parts = safe_split(url)
        return site_host(parts.netloc) if parts is not None else ""

    @property
    def page_count(self) -> int:
        """Distinct crawled pages the index can resolve to."""
        return len({owner for owner, _ in self._absolute.values()})

    def resolve(self, google_url: str) -> UrlMatch | UrlFailure:
        """Resolve one Google-reported address, with its evidence or its reason.

        Args:
            google_url: An absolute URL (Search Console) or a rooted path
                (GA4 `pagePath`). Query strings and tracking parameters are
                handled; neither needs stripping first.

        Returns:
            A `UrlMatch` naming the crawled page and the tier that decided it,
            or a `UrlFailure` naming why no page could be named.
        """
        parts = safe_split(google_url)
        if parts is None or not (parts.netloc or parts.path.startswith("/")):
            return UrlFailure(google_url=google_url, reason=MatchFailure.UNPARSEABLE)

        if parts.netloc:
            key = normalize_url(google_url)
            if key in self._absolute_clash:
                return UrlFailure(google_url=google_url, reason=MatchFailure.AMBIGUOUS)
            found = self._absolute.get(key)
            if found is not None:
                return UrlMatch(google_url=google_url, page_url=found[0], via=found[1])
            # Only now is the host worth checking. Doing it first would reject a
            # cross-domain canonical — a page that names another property as its
            # canonical is exactly the case where Google reports the other host,
            # and it is already in the index under that address.
            if self._host_of(google_url) not in self._hosts:
                return UrlFailure(google_url=google_url, reason=MatchFailure.OFF_SITE)

        return self._by_path(google_url, parts)

    def _by_path(self, google_url: str, parts: SplitResult) -> UrlMatch | UrlFailure:
        """Host-free resolution: path with query first, then path alone."""
        exact = _path_key(parts)
        if exact in self._path_clash:
            return UrlFailure(google_url=google_url, reason=MatchFailure.AMBIGUOUS)
        found = self._path.get(exact)
        if found is not None:
            return UrlMatch(google_url=google_url, page_url=found[0], via=found[1])

        # Last resort: drop the query entirely. GA4 property filters routinely
        # strip parameters the crawl kept, so `/search/` arrives for a page held
        # as `/search/?q=…`. Accepted only when exactly one crawled page has the
        # path, and reported under its own tier so the count is visible rather
        # than blended into the honest matches.
        loose = normalize_path(parts.path or "/")
        if loose in self._bare_clash:
            return UrlFailure(google_url=google_url, reason=MatchFailure.AMBIGUOUS)
        owner = self._bare.get(loose)
        if owner is not None:
            return UrlMatch(google_url=google_url, page_url=owner[0], via=MatchTier.BARE_PATH)

        return UrlFailure(google_url=google_url, reason=MatchFailure.NOT_CRAWLED)

    def resolve_url(self, google_url: str) -> str | None:
        """Resolve to a crawled page URL, or `None` if it cannot be resolved.

        The convenience form. Callers deciding what to *tell* the analyst should
        use `resolve` instead — `None` collapses four different diagnoses into
        one, and the difference between "we failed to crawl it" and "the site
        deleted it" is the whole finding.
        """
        outcome = self.resolve(google_url)
        return outcome.page_url if isinstance(outcome, UrlMatch) else None

    def build_resolution_report(
        self, google_urls: Iterable[str], *, threshold_pct: float = RELIABLE_MATCH_RATE
    ) -> ResolutionOutcome:
        """Resolve a whole export and report how much of it landed.

        Every input is counted once, including duplicates: the denominator is
        the export as uploaded, so the rate answers "how much of my file did you
        understand" rather than a question about a set the analyst never saw.

        Args:
            google_urls: URLs or paths, one per export row.
            threshold_pct: Match rate at or above which rollups are considered
                trustworthy.

        Returns:
            The outcome, carrying every match with its tier and every failure
            with its reason.
        """
        matches: list[UrlMatch] = []
        failures: list[UrlFailure] = []
        total = 0
        for url in google_urls:
            total += 1
            outcome = self.resolve(url)
            if isinstance(outcome, UrlMatch):
                matches.append(outcome)
            else:
                failures.append(outcome)
        return ResolutionOutcome(
            total=total,
            matches=tuple(matches),
            failures=tuple(failures),
            threshold_pct=threshold_pct,
        )
