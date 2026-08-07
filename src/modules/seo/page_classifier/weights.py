"""Signal weight profiles and the site-profile selection seam.

Architecture is client-agnostic; **calibration is not**. The weights in
`schemas.SIGNAL_WEIGHTS` came from a specification, not from measurement, and a
single global vector is wrong in two directions at once:

* On Shopify, a `/products.json` hit is near-certain evidence. Weighting
  `CMS_API_ENDPOINT` at 0.30 *undersells* it.
* On a headless React site that endpoint does not exist at all, so the same 0.30
  is dead weight that should redistribute to ARIA and Schema.org.

This module is the **seam** that lets weights vary by detected site profile
without the consensus engine knowing anything about CMS families.

Status: the seam is live, the adaptation is not. `get_weight_profile()` returns
the default vector unconditionally until a golden corpus exists to calibrate
against — see `ADAPTIVE_WEIGHTS_ENABLED`. The non-default profiles are declared
so their shape is fixed and reviewable, but their numbers are **informed
guesses, not measurements**, and must not be switched on until fitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import Field

from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.schemas import SIGNAL_WEIGHTS, SignalSource

__all__ = [
    "ADAPTIVE_WEIGHTS_ENABLED",
    "DEFAULT_PROFILE",
    "WEIGHT_PROFILES",
    "CmsFamily",
    "SiteProfile",
    "WeightProfileReport",
    "get_weight_profile",
    "resolve_profile_name",
]

ADAPTIVE_WEIGHTS_ENABLED = False
"""Whether `get_weight_profile()` may return a non-default vector.

Deliberately off. Switching this on before the profiles are fitted against a
golden corpus would replace one set of unmeasured numbers with four, which is
strictly worse — it would look like tuning while being guesswork. Flipping this
requires the corpus and an ADR."""

DEFAULT_PROFILE = "default"


class CmsFamily(StrEnum):
    """Content platform detected for a site.

    Determined once per crawl job by a handful of probe requests, never per
    page. Agencies onboard sites they have never seen, so this is discovered at
    runtime rather than configured per client.
    """

    WORDPRESS = "WORDPRESS"
    """Exposes `/wp-json/wp/v2/`. Parent IDs resolve flat URLs definitively."""

    SHOPIFY = "SHOPIFY"
    """Exposes `/products.json` and `/collections.json`."""

    HEADLESS = "HEADLESS"
    """Client-rendered with no public content API. Structural signals only."""

    UNKNOWN = "UNKNOWN"
    """Nothing recognised. Falls back to the default weight vector."""


class SiteProfile(StrictModel):
    """What one probe pass discovered about a site.

    Produced once per crawl job. Cheap by construction: a handful of requests
    against a crawl of tens of thousands of pages.

    Attributes:
        cms_family: Detected content platform.
        renders_client_side: Static HTML lacks real content, so a headless
            browser is required to see the DOM.
        has_catalogue: A product/collection catalogue was detected, implying
            faceted filters and SKU variants are likely.
        locale_prefixes: Locale path prefixes observed, e.g. `("de", "en-gb")`.
    """

    cms_family: CmsFamily = CmsFamily.UNKNOWN
    renders_client_side: bool = False
    has_catalogue: bool = False
    locale_prefixes: tuple[str, ...] = ()

    @property
    def weight_profile_name(self) -> str:
        """Name of the weight vector this site should be scored with."""
        return resolve_profile_name(self)


def _profile(**weights: float) -> Mapping[SignalSource, float]:
    """Build an immutable weight vector keyed by signal source."""
    return MappingProxyType({SignalSource[name]: value for name, value in weights.items()})


WEIGHT_PROFILES: Mapping[str, Mapping[SignalSource, float]] = MappingProxyType(
    {
        # The specified baseline (CLAUDE_HANDOFF_DIRECTIVE §5.3). The only
        # profile currently reachable, and the only one derived from the
        # approved blueprint rather than reasoning about a platform.
        DEFAULT_PROFILE: SIGNAL_WEIGHTS,
        # WordPress exposes parent IDs through /wp-json/wp/v2/pages, which
        # settles hierarchy outright for flat URLs. Sitemaps are also reliably
        # grouped by post type, so both rise; link centrality matters less when
        # the database will simply tell you the answer.
        "wordpress": _profile(
            CMS_API_ENDPOINT=0.38,
            ARIA_NAV_TREE=0.20,
            SITEMAP_INDEX=0.24,
            SCHEMA_JSONLD=0.12,
            LINK_IN_DEGREE=0.06,
        ),
        # Shopify's /products.json and /collections.json are effectively
        # authoritative, and its Schema.org Product markup is generated rather
        # than hand-written, so it is unusually trustworthy.
        "shopify": _profile(
            CMS_API_ENDPOINT=0.42,
            ARIA_NAV_TREE=0.15,
            SITEMAP_INDEX=0.18,
            SCHEMA_JSONLD=0.20,
            LINK_IN_DEGREE=0.05,
        ),
        # No content API at all, so CMS_API_ENDPOINT contributes nothing and its
        # weight must go somewhere useful. Rendered ARIA structure and JSON-LD
        # become the primary evidence.
        "headless": _profile(
            CMS_API_ENDPOINT=0.0,
            ARIA_NAV_TREE=0.40,
            SITEMAP_INDEX=0.26,
            SCHEMA_JSONLD=0.22,
            LINK_IN_DEGREE=0.12,
        ),
    }
)
"""Named weight vectors. Every profile sums to 1.0 — enforced by test.

Only `default` is calibrated. The rest are declared structure awaiting a corpus.
"""

_CMS_TO_PROFILE: Mapping[CmsFamily, str] = MappingProxyType(
    {
        CmsFamily.WORDPRESS: "wordpress",
        CmsFamily.SHOPIFY: "shopify",
        CmsFamily.HEADLESS: "headless",
        CmsFamily.UNKNOWN: DEFAULT_PROFILE,
    }
)


def resolve_profile_name(site_profile: SiteProfile | None) -> str:
    """Map a site profile onto the name of the weight vector it should use.

    Client-side rendering dominates the CMS family: if the content API is
    unreachable, it does not matter what generated the markup — the signal is
    unavailable either way.

    Args:
        site_profile: Discovered site characteristics, or `None` if unprofiled.

    Returns:
        A key into `WEIGHT_PROFILES`.
    """
    if site_profile is None:
        return DEFAULT_PROFILE
    if site_profile.renders_client_side and site_profile.cms_family is CmsFamily.UNKNOWN:
        return "headless"
    return _CMS_TO_PROFILE.get(site_profile.cms_family, DEFAULT_PROFILE)


def get_weight_profile(site_profile: SiteProfile | None = None) -> Mapping[SignalSource, float]:
    """Return the signal weight vector to score a site with.

    **This is the seam.** The consensus engine calls this and never reasons
    about CMS families itself, so switching on adaptive weighting later is a
    change here rather than a rewrite of the pipeline.

    Until `ADAPTIVE_WEIGHTS_ENABLED` is set, this returns the default vector for
    every site. That is deliberate: an uncalibrated profile is a guess, and four
    guesses are worse than one specified baseline.

    Args:
        site_profile: Discovered site characteristics. Ignored while adaptive
            weighting is disabled.

    Returns:
        An immutable mapping of signal source to weight, summing to 1.0.
    """
    if not ADAPTIVE_WEIGHTS_ENABLED:
        return WEIGHT_PROFILES[DEFAULT_PROFILE]
    return WEIGHT_PROFILES.get(resolve_profile_name(site_profile), WEIGHT_PROFILES[DEFAULT_PROFILE])


class WeightProfileReport(StrictModel):
    """Which weight vector a crawl actually used, and why.

    Attached to a crawl summary so a reviewer can tell a genuine accuracy
    difference between two sites from an artefact of different weighting.

    Attributes:
        profile_name: The vector that was applied.
        adaptive_enabled: Whether adaptive selection was live for this run.
        detected_profile_name: What would have been selected had it been live.
    """

    profile_name: str = Field(min_length=1)
    adaptive_enabled: bool = ADAPTIVE_WEIGHTS_ENABLED
    detected_profile_name: str = Field(min_length=1)

    @classmethod
    def for_site(cls, site_profile: SiteProfile | None) -> WeightProfileReport:
        """Build a report describing the selection for `site_profile`."""
        detected = resolve_profile_name(site_profile)
        applied = detected if ADAPTIVE_WEIGHTS_ENABLED else DEFAULT_PROFILE
        return cls(
            profile_name=applied,
            adaptive_enabled=ADAPTIVE_WEIGHTS_ENABLED,
            detected_profile_name=detected,
        )
