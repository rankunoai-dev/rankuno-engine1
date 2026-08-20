"""Phase 1 data contracts — the decoupled page classification taxonomy.

`FullPageIntelligenceProfile` is the canonical output of the classification
engine, per `docs/adr/0002-canonical-phase1-output-contract.md`. The retired
`SiteNodeIntelligence` model's graph-topology fields are absorbed here rather
than discarded, because Signal 5 (link in-degree) and the tree visualizer both
need them.

The core idea is **decoupling**: where a page sits in the site graph
(`HierarchyLevel`) is a separate question from what the page is for
(`PrimaryPageType`). Legacy crawlers conflate the two, which is why a blog post
linked from the homepage gets filed alongside a top-level category hub. Keeping
them orthogonal is what lets a flat URL such as `site.com/capsules` be a
`L2_SUB_NAV_HUB` holding a `PRODUCT_CATEGORY_HUB`.

Every enum here is UPPER_SNAKE per the ruling in `CLAUDE.md` §7. Governance
enums in `src.core.schemas` are lowercase; domain taxonomy enums are not. The
two conventions come from different source documents and both are now fixed.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from src.core.schemas import StrictModel

__all__ = [
    "LLM_FALLBACK_CONFIDENCE_THRESHOLD",
    "MAX_CRAWL_DEPTH",
    "SIGNAL_WEIGHTS",
    "ConsensusMethod",
    "ConversionRole",
    "DiscoverySource",
    "FullPageIntelligenceProfile",
    "HierarchyLevel",
    "PrimaryPageType",
    "SearchIntent",
    "SignalScore",
    "SignalSource",
    "TrailSource",
    "is_valid_taxonomy_pair",
]

TrailSource = Literal["menu", "breadcrumb", "none"]
"""Which source placed a page in the tree.

A `Literal` rather than a `StrEnum` deliberately. Ruling 3 in `CLAUDE.md` splits
enum casing by kind — governance lowercase, domain taxonomy UPPER — and this is
neither. It is provenance metadata about the engine's own reasoning, it is only
ever read as a string by the UI, and giving it an enum would force a casing
choice that the ruling does not cover.
"""

LLM_FALLBACK_CONFIDENCE_THRESHOLD = 0.85
"""Below this combined confidence, Layer 3 escalates to the governed LLM.

Raising this figure raises accuracy and cost together. ADR 0005 shows the cost
target needs the escalation rate at or below 0.5%, so this constant is the
single most expensive number in the engine."""

MAX_CRAWL_DEPTH = 15
"""Hard depth ceiling. URLs deeper than this are crawl traps, not content
(Amazon-scale specification, Rule 4)."""


class HierarchyLevel(StrEnum):
    """Structural position in the site graph, independent of page purpose."""

    L0_HOMEPAGE = "L0_HOMEPAGE"
    """Root entry point."""

    L1_PRIMARY_NAV_HUB = "L1_PRIMARY_NAV_HUB"
    """Primary section hub reachable from global navigation."""

    L2_SUB_NAV_HUB = "L2_SUB_NAV_HUB"
    """Intermediate sub-category hub. Absorbs arbitrary nesting depths; the
    precise depth is carried separately in `depth_from_l0`."""

    L3_LEAF_PAGE = "L3_LEAF_PAGE"
    """Terminal content node: a SKU, an article, a service detail page."""

    UTILITY_PAGE = "UTILITY_PAGE"
    """Supporting infrastructure: legal pages, search results, faceted filters."""


class PrimaryPageType(StrEnum):
    """Functional purpose of a page, independent of structural position.

    Fourteen members, per the ruling in `CLAUDE.md` §7 — the Phase 1 blueprint
    lists twelve, but `CASE_STUDY` and `TOOL_APPLICATION` are both referenced by
    the tree visualizer specification and observed in the HighRadius audit.
    """

    HOMEPAGE = "HOMEPAGE"
    SERVICE_CATEGORY_HUB = "SERVICE_CATEGORY_HUB"
    SERVICE_DETAIL_PAGE = "SERVICE_DETAIL_PAGE"
    PRODUCT_CATEGORY_HUB = "PRODUCT_CATEGORY_HUB"
    PRODUCT_DETAIL_PAGE = "PRODUCT_DETAIL_PAGE"
    BLOG_HUB = "BLOG_HUB"
    BLOG_ARTICLE = "BLOG_ARTICLE"
    COMPANY_ABOUT = "COMPANY_ABOUT"
    COMMERCIAL_LEAD_GEN = "COMMERCIAL_LEAD_GEN"
    FACETED_FILTER = "FACETED_FILTER"
    UTILITY_LEGAL = "UTILITY_LEGAL"
    CASE_STUDY = "CASE_STUDY"
    TOOL_APPLICATION = "TOOL_APPLICATION"
    UNKNOWN = "UNKNOWN"
    """Escape hatch. Phase 1's stated goal is zero of these in a finished run,
    so its presence in a result set is a defect signal, not a normal outcome."""


class SearchIntent(StrEnum):
    """What a searcher landing on this page is trying to accomplish."""

    INFORMATIONAL = "INFORMATIONAL"
    COMMERCIAL_INVESTIGATION = "COMMERCIAL_INVESTIGATION"
    TRANSACTIONAL = "TRANSACTIONAL"
    NAVIGATIONAL = "NAVIGATIONAL"


class ConversionRole(StrEnum):
    """The page's role in the conversion funnel.

    The source blueprint typed this as a bare `str`. An enum is substituted
    deliberately: an untyped label cannot be aggregated across a 20,000-page
    crawl, which is the only thing this field is useful for.
    """

    DIRECT_SALE = "DIRECT_SALE"
    LEAD_GENERATION = "LEAD_GENERATION"
    BRAND_AWARENESS = "BRAND_AWARENESS"
    INFORMATIONAL_SUPPORT = "INFORMATIONAL_SUPPORT"
    NONE = "NONE"


class SignalSource(StrEnum):
    """Which of the six consensus signals produced a suggestion."""

    ARIA_NAV_TREE = "ARIA_NAV_TREE"
    CMS_API_ENDPOINT = "CMS_API_ENDPOINT"
    SITEMAP_INDEX = "SITEMAP_INDEX"
    SCHEMA_JSONLD = "SCHEMA_JSONLD"
    LINK_IN_DEGREE = "LINK_IN_DEGREE"
    LLM_ZERO_SHOT = "LLM_ZERO_SHOT"


class ConsensusMethod(StrEnum):
    """Which cascade layer settled the classification.

    Recorded per page so the escalation rate — the dominant cost driver in
    ADR 0005 — is measurable directly from a result set rather than estimated.
    """

    LAYER0_FAST_PATH = "LAYER0_FAST_PATH"
    LAYER1_STRUCTURAL = "LAYER1_STRUCTURAL"
    LAYER2_LOCAL_ML = "LAYER2_LOCAL_ML"
    LAYER3_LLM_FALLBACK = "LAYER3_LLM_FALLBACK"
    WEIGHTED_CONSENSUS = "WEIGHTED_CONSENSUS"


SIGNAL_WEIGHTS: Mapping[SignalSource, float] = MappingProxyType(
    {
        SignalSource.CMS_API_ENDPOINT: 0.30,
        SignalSource.ARIA_NAV_TREE: 0.25,
        SignalSource.SITEMAP_INDEX: 0.20,
        SignalSource.SCHEMA_JSONLD: 0.15,
        SignalSource.LINK_IN_DEGREE: 0.10,
    }
)
"""Consensus weights from `CLAUDE_HANDOFF_DIRECTIVE` §5.3. Sums to 1.0.

`LLM_ZERO_SHOT` is deliberately absent: it is an escalation that *replaces* the
structural consensus, not another vote inside it. Changing these weights is an
architectural decision and requires an ADR."""


# Page types that are only meaningful at one structural level. Everything not
# listed here is permitted anywhere, which is the point of decoupling the two
# axes — a PRODUCT_CATEGORY_HUB is legitimately an L1 on one site and an L2 on
# another.
_TYPE_RESTRICTED_TO_LEVELS: Mapping[PrimaryPageType, frozenset[HierarchyLevel]] = MappingProxyType(
    {
        PrimaryPageType.HOMEPAGE: frozenset({HierarchyLevel.L0_HOMEPAGE}),
        PrimaryPageType.FACETED_FILTER: frozenset({HierarchyLevel.UTILITY_PAGE}),
        PrimaryPageType.UTILITY_LEGAL: frozenset({HierarchyLevel.UTILITY_PAGE}),
    }
)


def is_valid_taxonomy_pair(level: HierarchyLevel, page_type: PrimaryPageType) -> bool:
    """Report whether a level/type combination is coherent.

    Most combinations are legal by design. The few that are not would indicate a
    consensus bug rather than an unusual site — a page cannot be the homepage
    and simultaneously sit three levels down.

    Args:
        level: Structural position.
        page_type: Functional purpose.

    Returns:
        True when the pair is permitted.
    """
    allowed = _TYPE_RESTRICTED_TO_LEVELS.get(page_type)
    if allowed is not None and level not in allowed:
        return False
    # The constraint also runs the other way: the root entry point is the
    # homepage and nothing else.
    return not (level is HierarchyLevel.L0_HOMEPAGE and page_type is not PrimaryPageType.HOMEPAGE)


class SignalScore(StrictModel):
    """One signal's independent opinion about a page.

    Retained on the final profile so a classification can be audited without a
    separate log lookup — the reason a page was called an `L1_PRIMARY_NAV_HUB`
    should be visible in the output itself.

    Attributes:
        source: Which signal produced this.
        suggested_level: The level this signal argues for.
        suggested_page_type: The page type this signal argues for.
        confidence: How strongly, in `[0.0, 1.0]`.
        notes: Short evidence string, e.g. the matched sitemap filename. Bounded
            in length: this is diagnostic metadata, not prose.
    """

    source: SignalSource
    suggested_level: HierarchyLevel
    suggested_page_type: PrimaryPageType
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = Field(default="", max_length=500)

    @property
    def weight(self) -> float:
        """This signal's consensus weight. Zero for the LLM escalation."""
        return SIGNAL_WEIGHTS.get(self.source, 0.0)

    @property
    def weighted_confidence(self) -> float:
        """Contribution this signal makes to the combined confidence score."""
        return self.confidence * self.weight


class DiscoverySource(StrictModel):
    """Which paths surfaced a URL.

    Kept as flags rather than a single winner, because agreement between paths
    is itself information: a URL found by all three is certainly real, while one
    found only by a DOM link may be a generated artefact.

    Lives here rather than in `discovery` because it is no longer private to the
    crawl. `FullPageIntelligenceProfile` carries it to the UI, and an orphan
    that only a sitemap knows about is a different finding from one only the CMS
    knows about — a distinction the consumer cannot draw without these flags.

    Attributes:
        sitemap: Listed in an XML sitemap.
        dom_link: Reached by following a link from another page.
        cms_api: Present in the CMS database.
    """

    sitemap: bool = False
    dom_link: bool = False
    cms_api: bool = False

    @property
    def count(self) -> int:
        """How many independent paths surfaced this URL."""
        return sum((self.sitemap, self.dom_link, self.cms_api))


class FullPageIntelligenceProfile(StrictModel):
    """The complete classification of a single URL.

    Canonical Phase 1 output contract (ADR 0002). Composed of a structural
    classification, a topical classification, a semantic-intent classification,
    and the graph topology needed to render the site tree.

    Attributes:
        url: Absolute URL as crawled.
        canonical_url: Value of `<link rel="canonical">`, or the URL itself.
            Drives SKU variant clustering on large catalogues.
        normalized_path: Path after locale-prefix and tracking-parameter
            stripping. The join key for deduplication.
        hierarchy_level: Structural position.
        primary_page_type: Functional purpose.
        depth_from_l0: Graph distance from the homepage. Distinct from
            `hierarchy_level`: a blog post linked on the homepage is depth 1 but
            still an `L3_LEAF_PAGE`. This is the click-depth fallacy the engine
            exists to avoid.
        nav_parent_url: Parent in the navigation tree, if one was resolved.
        breadcrumb_path: The trail this page is placed under, outermost first.
            Despite the name it is not always the page's own breadcrumb —
            `_better_trail` overwrites it with the header-menu path when the
            menu places the page more specifically. `trail_source` says which
            one it is.
        own_breadcrumb: The trail **this page published about itself**, before
            any contest with the header menu. Kept separately because
            `breadcrumb_path` is overwritten when the menu wins, which destroys
            the only record of what the page actually said — and with it any
            chance of recomputing placement later without re-fetching the site.
            Empty when the page published no breadcrumb.
        trail_source: Where `breadcrumb_path` came from. `menu` is the parsed
            header navigation, `breadcrumb` is markup the page published about
            itself, `none` means neither placed it and the page sits in OTHERS.
            Recorded because the two are evidence of different strength and a
            report that presents them identically cannot be checked: a menu path
            is one global structure read once from the homepage, while a
            breadcrumb is a per-page assertion that can contradict its
            neighbours.
        topical_category: Top-level topical silo.
        sub_topic: Narrower topic within the silo.
        search_intent: What a searcher wants here.
        conversion_role: Role in the funnel.
        is_cross_silo_link: Whether this page links outside its own topical silo.
        inbound_internal_links_count: Signal 5 input. A page in a site-wide
            header accrues one per page on the site.
        outbound_internal_links_count: Internal links emitted.
        discovery_sources: Which of the three discovery paths surfaced this URL.
            Carried onto the profile so a consumer can separate a page the site
            publishes but never links — a sitemap entry with no inbound link —
            from one only the CMS database knows about. Both have zero inbound
            links and they are not the same finding.
        sitemap_source: Filename of the grouped sitemap that listed this URL,
            when one did. `resource-pages-sitemap.xml` and `blog-pages-sitemap.xml`
            are how an analyst tells which content team owns a page.
        signals_evaluated: Every signal that produced an opinion.
        final_confidence_score: Combined confidence after consensus.
        consensus_method: Which cascade layer settled it.
    """

    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    normalized_path: str = Field(min_length=1)

    hierarchy_level: HierarchyLevel
    primary_page_type: PrimaryPageType
    depth_from_l0: int = Field(ge=0, le=MAX_CRAWL_DEPTH)

    nav_parent_url: str | None = None
    breadcrumb_path: tuple[str, ...] = ()
    own_breadcrumb: tuple[str, ...] = ()
    # Defaults to `none` so a profile built outside the navigation pass — the
    # cascade's own output, and every fixture — makes no claim it cannot support.
    trail_source: TrailSource = "none"

    topical_category: str = Field(default="", max_length=200)
    sub_topic: str | None = Field(default=None, max_length=200)
    search_intent: SearchIntent
    conversion_role: ConversionRole = ConversionRole.NONE

    is_cross_silo_link: bool = False
    inbound_internal_links_count: int = Field(default=0, ge=0)
    outbound_internal_links_count: int = Field(default=0, ge=0)

    discovery_sources: DiscoverySource = DiscoverySource()
    sitemap_source: str | None = Field(default=None, max_length=200)

    signals_evaluated: tuple[SignalScore, ...] = Field(min_length=1)
    final_confidence_score: float = Field(ge=0.0, le=1.0)
    consensus_method: ConsensusMethod

    @model_validator(mode="after")
    def _check_taxonomy_pair(self) -> FullPageIntelligenceProfile:
        """Reject incoherent level/type combinations at construction time.

        Catching this here rather than in a report means a consensus bug fails
        loudly on the page that triggered it, instead of quietly producing a
        site tree with a second homepage three levels down.
        """
        if not is_valid_taxonomy_pair(self.hierarchy_level, self.primary_page_type):
            msg = (
                f"'{self.primary_page_type}' is not a valid page type at "
                f"'{self.hierarchy_level}' (url: {self.url})."
            )
            raise ValueError(msg)
        return self

    @property
    def escalated_to_llm(self) -> bool:
        """Whether this page consumed a paid Layer 3 call.

        Aggregate over a result set to get the true escalation rate, which is
        the dominant term in the cost model.
        """
        return self.consensus_method is ConsensusMethod.LAYER3_LLM_FALLBACK

    @property
    def is_confidently_classified(self) -> bool:
        """Whether the result cleared the escalation threshold."""
        return (
            self.final_confidence_score >= LLM_FALLBACK_CONFIDENCE_THRESHOLD
            and self.primary_page_type is not PrimaryPageType.UNKNOWN
        )
