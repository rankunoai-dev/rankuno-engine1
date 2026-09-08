"""Turn a crawl's page profiles into an `AuditDataset(source="engine")`.

Plan P0-4 (`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4) under ADR 0011. This
is the engine's side of the seam: it reads `FullPageIntelligenceProfile` and
writes the shared contract, and it is the only file in `page_classifier` that
knows the contract exists. It never imports `deliverables`.

The governing stance is honesty of coverage. The profile carries a handful of
facts a deliverable can use - discovery flags, a redirect chain, an
indexability verdict, the raw URL - and nothing about titles, headers, links
or content. Sixteen issues are measured from those facts; the other
ninety-four are declared `NOT_MEASURED` with the reason in `notes`, so a
workbook renders "not measured by this crawl" rather than a clean bill of
health (ADR 0011 §5).

Two limits are worth knowing before reading the rules:

* Status codes do not survive onto the profile. The one trace is the prose
  `indexability_reason` written by `signal_parsers.indexability_of`, which
  starts `Answered NNN.` for an error response. `STATUS_RE` reads that, and a
  test binds the pattern to the function so a wording change fails loudly.
* A fetch that raises - transport failure, redirect ceiling, robots refusal -
  never reaches `record_fetch`, so the profile reads `UNKNOWN`, the same as a
  page nobody requested. No response, redirect loops and robots blocks are
  therefore unmeasurable here, not merely unmeasured.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit

from pydantic import ValidationError

from src.core.logger import get_logger
from src.modules.seo.contracts.audit import (
    AuditDataset,
    AuditPage,
    AuditSource,
    Coverage,
    IssueCategory,
    IssueId,
)
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile, Indexability
from src.modules.seo.page_classifier.url_rules import normalize_url

__all__ = [
    "LINKS_NOT_RETAINED_NOTE",
    "NOT_MEASURED_REASONS",
    "SITEMAP_LIMIT",
    "SITEMAP_NOT_READ_NOTE",
    "SITEMAP_TRUNCATION_NOTE",
    "STATUS_RE",
    "AuditExportError",
    "to_audit_dataset",
]

_logger = get_logger(__name__)

SITEMAP_LIMIT: Final[int] = 50_000
"""The sitemaps.org ceiling per file; Screaming Frog flags anything above it."""

STATUS_RE: Final[re.Pattern[str]] = re.compile(r"^Answered (\d{3})\.")
"""Reads the status `indexability_of` wrote into the reason for a 4xx/5xx page."""

LINKS_NOT_RETAINED_NOTE: Final[str] = (
    "links: edges not retained by the engine adapter (ADR 0011 D4 deferred)"
)
SITEMAP_NOT_READ_NOTE: Final[str] = (
    "sitemaps: no profile was discovered via a sitemap, so the SITEMAPS category is NOT_MEASURED"
)
SITEMAP_TRUNCATION_NOTE: Final[str] = (
    "sitemaps: the crawl page budget can truncate a sitemap below 50k URLs; "
    "an empty XML_SITEMAP_OVER_50K_URLS set is not proof"
)

_WWW: Final[str] = "www."

NOT_MEASURED_REASONS: Final[dict[IssueCategory, str]] = {
    IssueCategory.RESPONSE_CODES_INTERNAL: (
        "no response, redirect loops and robots blocks raise in the fetcher and never reach "
        "the profile, which reads UNKNOWN"
    ),
    IssueCategory.CANONICALS: (
        "the profile holds one resolved canonical URL, falling back to the page URL when none "
        "is declared; tag count, position and attributes are dropped at extraction"
    ),
    IssueCategory.DIRECTIVES: "nofollow is not folded into the indexability verdict",
    IssueCategory.PAGE_TITLES: "titles are not carried on the profile",
    IssueCategory.META_DESCRIPTION: "meta descriptions are not carried on the profile",
    IssueCategory.H1: "headings are not carried on the profile",
    IssueCategory.SECURITY: "response headers and mixed-content data are not on the profile",
    IssueCategory.PAGE_SPEED_CWV: "Core Web Vitals are not crawled",
    IssueCategory.STRUCTURED_DATA: "structured data is not parsed onto the profile",
    IssueCategory.INTERNAL_LINKS: "link edges are not retained (ADR 0011 D4)",
    IssueCategory.CONTENT_ISSUES: "page HTML is not retained on the profile",
    IssueCategory.CUSTOM_SEARCH: "tag presence is not extracted",
    IssueCategory.PAGINATION: "rel=prev/next is not carried on the profile",
    IssueCategory.HREFLANG_TAGS: "hreflang annotations are not extracted",
}
"""Per-category reason a workbook can show beside `NOT_MEASURED`. The four
partly-measured categories are listed too, because the note is about the
issues left unmeasured within them."""


class AuditExportError(ValueError):
    """The profiles cannot yield a valid dataset - empty input or no usable hostname."""


_Rule = Callable[[FullPageIntelligenceProfile], bool]
_NON_INDEXABLE: Final[frozenset[Indexability]] = frozenset(
    {Indexability.NOINDEX, Indexability.CANONICALISED_AWAY, Indexability.NOT_A_PAGE}
)


def _status(profile: FullPageIntelligenceProfile) -> int | None:
    """The status a `NOT_A_PAGE` verdict was based on, when the reason names one."""
    if profile.indexability is not Indexability.NOT_A_PAGE:
        return None
    match = STATUS_RE.match(profile.indexability_reason)
    return int(match.group(1)) if match else None


def _path_and_query(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.path, parts.query


def _has_uppercase(profile: FullPageIntelligenceProfile) -> bool:
    path, query = _path_and_query(profile.url)
    return any(ch.isupper() for ch in path + query)


def _repeats_a_segment(profile: FullPageIntelligenceProfile) -> bool:
    segments = [s.casefold() for s in _path_and_query(profile.url)[0].split("/") if s]
    return len(segments) != len(set(segments))


def _is_4xx(profile: FullPageIntelligenceProfile) -> bool:
    status = _status(profile)
    return status is not None and 400 <= status < 500


def _is_5xx(profile: FullPageIntelligenceProfile) -> bool:
    status = _status(profile)
    return status is not None and 500 <= status < 600


# Rules over one profile. Sitemap and status rules read the crawl's verdicts;
# URL rules read the *raw* URL, because `normalize_url` lowercases, collapses
# slashes and drops parameters - exactly the defects these rules exist to find.
_RULES: Final[dict[IssueId, _Rule]] = {
    IssueId.SITEMAPS_URLS_NOT_IN_SITEMAP: lambda p: (
        p.indexability is Indexability.INDEXABLE and not p.discovery_sources.sitemap
    ),
    IssueId.SITEMAPS_ORPHAN_URLS: lambda p: (
        p.discovery_sources.sitemap and not p.discovery_sources.dom_link
    ),
    IssueId.SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP: lambda p: (
        p.discovery_sources.sitemap and p.indexability in _NON_INDEXABLE
    ),
    IssueId.DIRECTIVES_NOINDEX: lambda p: p.indexability is Indexability.NOINDEX,
    IssueId.CANONICALS_CANONICALISED: lambda p: p.indexability is Indexability.CANONICALISED_AWAY,
    IssueId.RESPONSE_CODES_3XX_REDIRECTION: lambda p: len(p.redirect_chain) >= 1,
    IssueId.RESPONSE_CODES_INTERNAL_REDIRECT_CHAIN: lambda p: len(p.redirect_chain) >= 2,
    IssueId.RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX: _is_4xx,
    IssueId.RESPONSE_CODES_INTERNAL_SERVER_ERROR_5XX: _is_5xx,
    IssueId.URL_UPPERCASE: _has_uppercase,
    IssueId.URL_UNDERSCORES: lambda p: "_" in _path_and_query(p.url)[0],
    IssueId.URL_PARAMETERS: lambda p: bool(_path_and_query(p.url)[1]),
    IssueId.URL_MULTIPLE_SLASHES: lambda p: "//" in _path_and_query(p.url)[0],
    IssueId.URL_REPETITIVE_PATH: _repeats_a_segment,
    IssueId.URL_CONTAINS_SPACE: lambda p: " " in p.url or "%20" in p.url,
}

_SITEMAP_ISSUES: Final[frozenset[IssueId]] = frozenset(
    spec.id for spec in ISSUE_CATALOGUE if spec.category is IssueCategory.SITEMAPS
)


def _over_50k(profiles: Sequence[FullPageIntelligenceProfile]) -> frozenset[str]:
    """Keys of every URL whose grouped sitemap listed more than `SITEMAP_LIMIT` URLs.

    Counted across profiles rather than files because the profile is all this
    module sees; the truncation caveat in `SITEMAP_TRUNCATION_NOTE` follows.
    """
    per_source: Counter[str] = Counter(p.sitemap_source for p in profiles if p.sitemap_source)
    oversized = {name for name, count in per_source.items() if count > SITEMAP_LIMIT}
    if not oversized:
        return frozenset()
    return frozenset(normalize_url(p.url) for p in profiles if p.sitemap_source in oversized)


def _derive_site(keys: Iterable[str]) -> tuple[str, int]:
    """Majority hostname of the spine, `www.` and port stripped (matches the SF adapter)."""
    hosts: Counter[str] = Counter()
    for key in keys:
        host = urlsplit(key).hostname
        if host:
            hosts[host.removeprefix(_WWW)] += 1
    if not hosts:
        raise AuditExportError("no hostname could be derived from the profiles")
    site, _ = hosts.most_common(1)[0]
    return site, len(hosts)


def to_audit_dataset(
    profiles: Sequence[FullPageIntelligenceProfile],
    *,
    produced_at: datetime | None = None,
) -> AuditDataset:
    """Build the engine-sourced `AuditDataset` from one crawl's profiles.

    Pages are keyed by `normalize_url`, first occurrence winning, so the spine
    is a set (contract invariant 4). Rules run on every profile and their
    verdicts are unioned onto the key, so a duplicate raw URL carrying a defect
    the survivor lacks still registers.

    Args:
        profiles: Typically `PageClassificationOutput.pages`.
        produced_at: Timestamp for the dataset; defaults to now, UTC.

    Returns:
        A validated dataset with `source=ENGINE`, every `IssueId` covered,
        sixteen issues `MEASURED`, and `links` empty.

    Raises:
        AuditExportError: No profiles, or no hostname the contract accepts.
    """
    if not profiles:
        raise AuditExportError("no profiles to export")

    keyed = [(normalize_url(p.url), p) for p in profiles]
    spine = dict.fromkeys(key for key, _ in keyed)
    site, host_count = _derive_site(spine)

    sitemap_read = any(p.discovery_sources.sitemap for p in profiles)
    members: dict[IssueId, set[str]] = {issue: set() for issue in _RULES}
    for key, profile in keyed:
        for issue, rule in _RULES.items():
            if rule(profile):
                members[issue].add(key)

    issues: dict[IssueId, frozenset[str]] = {}
    coverage: dict[IssueId, Coverage] = {}
    for spec in ISSUE_CATALOGUE:
        measured = spec.id in _RULES or spec.id is IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS
        if spec.id in _SITEMAP_ISSUES and not sitemap_read:
            measured = False
        if not measured:
            coverage[spec.id] = Coverage.NOT_MEASURED
            issues[spec.id] = frozenset()
            continue
        coverage[spec.id] = Coverage.MEASURED
        if spec.id is IssueId.SITEMAPS_XML_SITEMAP_OVER_50K_URLS:
            issues[spec.id] = _over_50k(profiles)
        else:
            issues[spec.id] = frozenset(members[spec.id])

    notes = [LINKS_NOT_RETAINED_NOTE]
    notes.extend(f"not measured ({cat.value}): {why}" for cat, why in NOT_MEASURED_REASONS.items())
    notes.append(SITEMAP_TRUNCATION_NOTE if sitemap_read else SITEMAP_NOT_READ_NOTE)
    if host_count > 1:
        notes.append(f"site: {host_count} hostnames in spine; majority chosen")

    measured_count = sum(1 for value in coverage.values() if value is Coverage.MEASURED)
    _logger.info(
        "audit_export_built",
        extra={
            "pages": len(spine),
            "duplicates_dropped": len(keyed) - len(spine),
            "coverage_measured": measured_count,
            "coverage_not_measured": len(coverage) - measured_count,
        },
    )
    try:
        return AuditDataset(
            source=AuditSource.ENGINE,
            site=site,
            produced_at=produced_at or datetime.now(UTC),
            pages=tuple(AuditPage(url=key) for key in spine),
            issues=issues,
            coverage=coverage,
            notes=tuple(notes),
        )
    except ValidationError as exc:
        raise AuditExportError("profiles do not satisfy the audit contract") from exc
