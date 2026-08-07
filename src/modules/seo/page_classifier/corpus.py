"""Golden corpus — labelled ground truth, organised by site archetype.

Two open questions block on this, both raised by the first live run:

* **Signal weight calibration** (ADR 0006). The four weight profiles are
  declared but only `default` is derived from anything, and that from a
  specification rather than data. Nothing can be fitted without labels.
* **Escalation rate** (build-log 0007 §4.2). The observed rate was 98% against
  ADR 0005's assumed 2% — a ~50x miss that makes the cost model untrustworthy.
  Choosing a defensible confidence threshold needs labelled examples.

Archetypes, not sites
---------------------
Entries are grouped by `SiteArchetype` because Rankuno is an agency: every
engagement is a site nobody has seen, so what matters is coverage of *kinds* of
site, not of particular ones. A corpus of ten B2B SaaS sites is one data point
repeated ten times.

Accuracy must therefore be reported **per archetype**. A blended 98% that is
100% on B2B SaaS and 70% on e-commerce is a broken engine wearing a good score,
and `evaluation.py` refuses to report a single number without the breakdown.

Honesty about size
------------------
This module is a **harness with seed data**, not a corpus that can validate the
≥98% accuracy claim. `CoverageReport` exists to make that unmistakable: it
reports how far each archetype falls short of a usable sample, so nobody mistakes
a passing evaluation over 8 labels for evidence about 20,000 pages.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from pydantic import Field, ValidationError

from src.core.errors import ConfigurationError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.schemas import HierarchyLevel, PrimaryPageType

__all__ = [
    "MIN_ENTRIES_PER_ARCHETYPE",
    "ArchetypeCoverage",
    "CorpusEntry",
    "CorpusSite",
    "CoverageReport",
    "GoldenCorpus",
    "SiteArchetype",
    "load_corpus",
    "load_corpus_dir",
    "summarise_gaps",
]

_logger = get_logger("modules.seo.corpus")

MIN_ENTRIES_PER_ARCHETYPE = 50
"""Labels below which an archetype's accuracy figure is not worth quoting.

Not a statistical derivation — a floor chosen so that a single misclassification
moves the number by no more than two percentage points. Under it, the measured
accuracy says more about which pages happened to be labelled than about the
engine."""


class SiteArchetype(StrEnum):
    """A *kind* of site, chosen so each exercises signals the others cannot.

    The set is deliberately small. Each member must justify itself by the code
    path it reaches; adding one that overlaps an existing member gains coverage
    on paper and none in fact.
    """

    B2B_SAAS = "B2B_SAAS"
    """WordPress-shaped marketing site: grouped sitemaps, ARIA nav, blog and
    case-study types. Exercises Signals 1, 3 and 4."""

    ECOMMERCE = "ECOMMERCE"
    """Catalogue with `/products.json`, SKU variants and faceted filters.
    The only archetype that reaches Shopify's Path C or the parameter
    normaliser in anger."""

    FLAT_URL = "FLAT_URL"
    """Pages hanging directly off root (`site.com/capsules`). Path depth carries
    no information, so Signal 2's CMS parent lookup is the *only* thing that can
    resolve hierarchy. The headline failure case for legacy crawlers."""

    HEADLESS_SPA = "HEADLESS_SPA"
    """Client-rendered. No content API and an empty hydration root, so
    `CMS_API_ENDPOINT` contributes nothing and its weight must redistribute."""

    MULTI_REGION = "MULTI_REGION"
    """Locale-prefixed routing (`/de/`, `/en-gb/`). Exercises locale folding and
    the dedup key — where the `/dp/` bug lived."""

    LARGE_CATALOGUE = "LARGE_CATALOGUE"
    """100k+ URLs, pagination traps, parameter matrices. Exercises the crawl
    budget, the depth ceiling and the DOM reserve (ADR 0007)."""


class CorpusEntry(StrictModel):
    """One hand-labelled URL.

    Attributes:
        url: Absolute URL as it appears on the site.
        expected_level: Correct `HierarchyLevel`.
        expected_page_type: Correct `PrimaryPageType`.
        source: Where the label came from — a document, a person, a date. A
            label with no provenance cannot be re-checked when it is disputed,
            and disputed labels are the normal case in classification work.
        notes: Why this entry is interesting. Most valuable on the hard ones.
    """

    url: str = Field(min_length=1)
    expected_level: HierarchyLevel
    expected_page_type: PrimaryPageType
    source: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=500)


class CorpusSite(StrictModel):
    """Labelled entries for one site.

    Attributes:
        name: Short identifier, e.g. `highradius`.
        base_url: Site root.
        archetype: Which kind of site this is.
        labelled_by: Who or what produced the labels.
        entries: The labelled URLs.
        notes: Anything a future labeller needs to know.
    """

    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    archetype: SiteArchetype
    labelled_by: str = Field(default="", max_length=200)
    entries: tuple[CorpusEntry, ...] = ()
    notes: str = Field(default="", max_length=1000)


class ArchetypeCoverage(StrictModel):
    """How well one archetype is represented.

    Attributes:
        archetype: The archetype.
        sites: Distinct sites contributing labels.
        entries: Labelled URLs.
        sufficient: Whether `entries` reaches `MIN_ENTRIES_PER_ARCHETYPE`.
        shortfall: Labels still needed. Zero when sufficient.
    """

    archetype: SiteArchetype
    sites: int = Field(default=0, ge=0)
    entries: int = Field(default=0, ge=0)
    sufficient: bool = False
    shortfall: int = Field(default=0, ge=0)


class CoverageReport(StrictModel):
    """What the corpus can and cannot support conclusions about.

    Exists to prevent the most likely misuse of this module: quoting an accuracy
    figure computed over a handful of labels as though it described the engine.

    Attributes:
        total_entries: Labels across every archetype.
        total_sites: Distinct sites.
        per_archetype: Coverage for every archetype, including empty ones —
            an archetype with zero labels is the most important thing to show.
        usable_archetypes: Archetypes with enough labels to quote.
        is_publishable: Whether *every* archetype has enough labels. Until this
            is true, no overall accuracy figure should leave the team.
    """

    total_entries: int = Field(default=0, ge=0)
    total_sites: int = Field(default=0, ge=0)
    per_archetype: tuple[ArchetypeCoverage, ...] = ()
    usable_archetypes: tuple[SiteArchetype, ...] = ()
    is_publishable: bool = False

    def summary_line(self) -> str:
        """One-line status suitable for a log or a CLI header."""
        usable = len(self.usable_archetypes)
        total = len(SiteArchetype)
        verdict = "publishable" if self.is_publishable else "NOT publishable"
        return (
            f"{self.total_entries} labels across {self.total_sites} sites; "
            f"{usable}/{total} archetypes usable — {verdict}"
        )


class GoldenCorpus(StrictModel):
    """The labelled ground truth, across every site.

    Attributes:
        sites: Labelled sites.
    """

    sites: tuple[CorpusSite, ...] = ()

    def entries(self) -> tuple[CorpusEntry, ...]:
        """Every labelled entry, across every site."""
        return tuple(entry for site in self.sites for entry in site.entries)

    def by_archetype(self, archetype: SiteArchetype) -> tuple[CorpusEntry, ...]:
        """Entries belonging to one archetype."""
        return tuple(
            entry for site in self.sites if site.archetype is archetype for entry in site.entries
        )

    def archetype_of(self) -> Mapping[str, SiteArchetype]:
        """Map every labelled URL to its archetype.

        The join `evaluation.py` needs: predictions arrive keyed by URL and must
        be bucketed by archetype before any accuracy figure is computed.
        """
        return MappingProxyType(
            {entry.url: site.archetype for site in self.sites for entry in site.entries}
        )

    def expected(self) -> Mapping[str, CorpusEntry]:
        """Map every labelled URL to its entry."""
        return MappingProxyType({entry.url: entry for site in self.sites for entry in site.entries})

    def coverage(self) -> CoverageReport:
        """Report what this corpus can support conclusions about."""
        per_archetype: list[ArchetypeCoverage] = []
        usable: list[SiteArchetype] = []

        for archetype in SiteArchetype:
            sites = [site for site in self.sites if site.archetype is archetype]
            count = sum(len(site.entries) for site in sites)
            sufficient = count >= MIN_ENTRIES_PER_ARCHETYPE
            if sufficient:
                usable.append(archetype)
            per_archetype.append(
                ArchetypeCoverage(
                    archetype=archetype,
                    sites=len(sites),
                    entries=count,
                    sufficient=sufficient,
                    shortfall=max(0, MIN_ENTRIES_PER_ARCHETYPE - count),
                )
            )

        return CoverageReport(
            total_entries=len(self.entries()),
            total_sites=len(self.sites),
            per_archetype=tuple(per_archetype),
            usable_archetypes=tuple(usable),
            is_publishable=len(usable) == len(SiteArchetype),
        )

    def merged_with(self, other: GoldenCorpus) -> GoldenCorpus:
        """Combine two corpora, later sites winning on a name collision."""
        by_name = {site.name: site for site in self.sites}
        by_name.update({site.name: site for site in other.sites})
        return GoldenCorpus(sites=tuple(by_name.values()))


def load_corpus(path: Path | str) -> GoldenCorpus:
    """Load one corpus file.

    Args:
        path: JSON file holding either a single site object or a list of them.

    Returns:
        The parsed corpus.

    Raises:
        ConfigurationError: If the file is missing, unreadable, not valid JSON,
            or does not satisfy the schema. Corpus data is the yardstick the
            engine is measured against, so a malformed label file is a hard
            failure rather than something to skip past.
    """
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Corpus file '{source}' could not be read: {exc}"
        raise ConfigurationError(msg) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Corpus file '{source}' is not valid JSON: {exc}"
        raise ConfigurationError(msg) from exc

    documents = payload if isinstance(payload, list) else [payload]
    try:
        sites = tuple(CorpusSite.model_validate(document) for document in documents)
    except ValidationError as exc:
        msg = f"Corpus file '{source}' does not match the schema: {exc}"
        raise ConfigurationError(msg) from exc

    _logger.debug(
        "corpus_loaded",
        extra={
            "path": str(source),
            "sites": len(sites),
            "entries": sum(len(s.entries) for s in sites),
        },
    )
    return GoldenCorpus(sites=sites)


def load_corpus_dir(directory: Path | str, pattern: str = "*.json") -> GoldenCorpus:
    """Load and merge every corpus file in a directory.

    Args:
        directory: Directory to scan.
        pattern: Glob for corpus files.

    Returns:
        The merged corpus. Empty if the directory holds no matching files —
        an empty corpus is a valid state that `coverage()` will report on,
        whereas raising here would make the harness unusable before the first
        site is labelled.

    Raises:
        ConfigurationError: If the directory does not exist, or any file in it
            is malformed.
    """
    root = Path(directory)
    if not root.is_dir():
        msg = f"Corpus directory '{root}' does not exist."
        raise ConfigurationError(msg)

    merged = GoldenCorpus()
    for file in sorted(root.glob(pattern)):
        merged = merged.merged_with(load_corpus(file))
    return merged


def summarise_gaps(coverage: CoverageReport) -> tuple[str, ...]:
    """Render the corpus's gaps as actionable lines.

    Args:
        coverage: A coverage report.

    Returns:
        One line per under-represented archetype, worst first. Empty when the
        corpus is publishable.
    """
    gaps: Iterable[ArchetypeCoverage] = sorted(
        (item for item in coverage.per_archetype if not item.sufficient),
        key=lambda item: item.shortfall,
        reverse=True,
    )
    return tuple(
        f"{item.archetype}: {item.entries}/{MIN_ENTRIES_PER_ARCHETYPE} labels "
        f"({item.shortfall} more needed)"
        for item in gaps
    )
