"""Produce the UI's fixture datasets.

Two kinds, and the distinction is load-bearing:

* **Real** — the serialised output of an actual crawl. Small, honest, and the
  only data that reflects what the engine genuinely produces: the confidence
  distribution, the orphan counts, the `UNKNOWN` pages. A UI tuned only against
  synthetic data will look wrong the first time it meets a real crawl.
* **Synthetic** — generated at target scale to exercise virtualisation. No real
  crawl available here reaches 20,000 URLs, and waiting for one would mean
  building the tree at 250 nodes and discovering the freeze in production.

Every synthetic file is stamped `"synthetic": true` and uses an `example.com`
host, so it can never be mistaken for crawl output or quoted as evidence about
the engine. That is the same rule the golden corpus enforces, applied to
fixtures.

Usage:
    python scripts/export_ui_fixtures.py --synthetic 20000
    python scripts/export_ui_fixtures.py --crawl https://www.highradius.com --max-pages 300
"""

from __future__ import annotations

# ruff: noqa: S311 - `random` here shapes test fixtures from a fixed seed. It
# guards nothing and protects nothing; swapping in `secrets` would make the
# output non-reproducible, which is the one property these fixtures need.
import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.schemas import ExecutionStatus  # noqa: E402
from src.modules.seo.page_classifier.schemas import (  # noqa: E402
    ConsensusMethod,
    ConversionRole,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
)

FIXTURES_DIR = REPO_ROOT / "rankuno-ui" / "src" / "data"

# Section shapes lifted from the structure of real B2B and catalogue sites, so
# the synthetic tree has realistic branching rather than a uniform fan-out. A
# balanced tree hides exactly the layout problems deep narrow branches cause.
_SECTIONS = (
    ("software", PrimaryPageType.PRODUCT_CATEGORY_HUB, PrimaryPageType.PRODUCT_DETAIL_PAGE),
    ("solutions", PrimaryPageType.SERVICE_CATEGORY_HUB, PrimaryPageType.SERVICE_DETAIL_PAGE),
    ("resources", PrimaryPageType.BLOG_HUB, PrimaryPageType.BLOG_ARTICLE),
    ("case-studies", PrimaryPageType.SERVICE_CATEGORY_HUB, PrimaryPageType.CASE_STUDY),
    ("products", PrimaryPageType.PRODUCT_CATEGORY_HUB, PrimaryPageType.PRODUCT_DETAIL_PAGE),
    ("company", PrimaryPageType.SERVICE_CATEGORY_HUB, PrimaryPageType.COMPANY_ABOUT),
    ("tools", PrimaryPageType.SERVICE_CATEGORY_HUB, PrimaryPageType.TOOL_APPLICATION),
)

_LEGAL = (
    "privacy-policy",
    "terms-of-service",
    "cookie-policy",
    "accessibility",
    "code-of-ethics",
)

_INTENT_BY_TYPE = {
    PrimaryPageType.PRODUCT_DETAIL_PAGE: SearchIntent.TRANSACTIONAL,
    PrimaryPageType.COMMERCIAL_LEAD_GEN: SearchIntent.TRANSACTIONAL,
    PrimaryPageType.PRODUCT_CATEGORY_HUB: SearchIntent.COMMERCIAL_INVESTIGATION,
    PrimaryPageType.SERVICE_CATEGORY_HUB: SearchIntent.COMMERCIAL_INVESTIGATION,
    PrimaryPageType.SERVICE_DETAIL_PAGE: SearchIntent.COMMERCIAL_INVESTIGATION,
    PrimaryPageType.CASE_STUDY: SearchIntent.COMMERCIAL_INVESTIGATION,
    PrimaryPageType.TOOL_APPLICATION: SearchIntent.COMMERCIAL_INVESTIGATION,
    PrimaryPageType.HOMEPAGE: SearchIntent.NAVIGATIONAL,
    PrimaryPageType.COMPANY_ABOUT: SearchIntent.NAVIGATIONAL,
    PrimaryPageType.UTILITY_LEGAL: SearchIntent.NAVIGATIONAL,
}

_ROLE_BY_TYPE = {
    PrimaryPageType.PRODUCT_DETAIL_PAGE: ConversionRole.DIRECT_SALE,
    PrimaryPageType.COMMERCIAL_LEAD_GEN: ConversionRole.LEAD_GENERATION,
    PrimaryPageType.SERVICE_DETAIL_PAGE: ConversionRole.LEAD_GENERATION,
    PrimaryPageType.TOOL_APPLICATION: ConversionRole.LEAD_GENERATION,
    PrimaryPageType.CASE_STUDY: ConversionRole.BRAND_AWARENESS,
    PrimaryPageType.COMPANY_ABOUT: ConversionRole.BRAND_AWARENESS,
    PrimaryPageType.BLOG_ARTICLE: ConversionRole.INFORMATIONAL_SUPPORT,
    PrimaryPageType.BLOG_HUB: ConversionRole.INFORMATIONAL_SUPPORT,
}


def _profile(
    *,
    path: str,
    level: HierarchyLevel,
    page_type: PrimaryPageType,
    depth: int,
    inbound: int,
    outbound: int,
    confidence: float,
    method: ConsensusMethod,
    sources: tuple[SignalSource, ...],
    host: str,
) -> FullPageIntelligenceProfile:
    """Build one synthetic profile."""
    url = f"https://{host}{path}"
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=level,
        primary_page_type=page_type,
        depth_from_l0=min(depth, 15),
        search_intent=_INTENT_BY_TYPE.get(page_type, SearchIntent.INFORMATIONAL),
        conversion_role=_ROLE_BY_TYPE.get(page_type, ConversionRole.NONE),
        inbound_internal_links_count=inbound,
        outbound_internal_links_count=outbound,
        signals_evaluated=tuple(
            SignalScore(
                source=source,
                suggested_level=level,
                suggested_page_type=page_type,
                # Clamped both ends: jitter on a 0.0-confidence UNKNOWN page
                # would otherwise go negative and fail model validation.
                confidence=round(min(1.0, max(0.0, confidence + random.uniform(-0.08, 0.08))), 3),
                notes=f"synthetic {source.value.lower()} evidence",
            )
            for source in sources
        ),
        final_confidence_score=round(confidence, 3),
        consensus_method=method,
    )


def build_synthetic(
    count: int, host: str = "example.com", seed: int = 20260807
) -> dict[str, object]:
    """Generate a crawl-shaped payload of `count` pages.

    The distribution deliberately mirrors what live crawls actually produced
    rather than an idealised one: most pages low-confidence, a visible tail of
    orphans, and a couple of `UNKNOWN`. A fixture where everything is confident
    and well-linked would let the UI ship without ever rendering the states an
    auditor most needs to see.

    Args:
        count: Number of pages.
        host: Hostname. Kept as `example.com` so synthetic data cannot be
            mistaken for a real site's crawl.
        seed: Fixed, so the fixture is reproducible and diffs stay meaningful.

    Returns:
        A JSON-ready payload matching `PageClassificationOutput` plus a
        `synthetic` marker.
    """
    random.seed(seed)
    pages: list[FullPageIntelligenceProfile] = [
        _profile(
            path="/",
            level=HierarchyLevel.L0_HOMEPAGE,
            page_type=PrimaryPageType.HOMEPAGE,
            depth=0,
            inbound=count,
            outbound=60,
            confidence=0.97,
            method=ConsensusMethod.LAYER0_FAST_PATH,
            sources=(SignalSource.ARIA_NAV_TREE,),
            host=host,
        )
    ]

    for slug in _LEGAL:
        pages.append(
            _profile(
                path=f"/{slug}/",
                level=HierarchyLevel.UTILITY_PAGE,
                page_type=PrimaryPageType.UTILITY_LEGAL,
                depth=1,
                inbound=random.randint(0, 4),
                outbound=3,
                confidence=0.97,
                method=ConsensusMethod.LAYER0_FAST_PATH,
                sources=(SignalSource.SITEMAP_INDEX,),
                host=host,
            )
        )

    # One deliberately deep, narrow chain, emitted *before* the wide sections so
    # the final truncation cannot cut it off. The sections produce very wide
    # sibling lists, which stress virtualisation; a deep chain stresses the
    # swimlane layout and the expand-to-level controls instead. A fixture with
    # only one of the two shapes lets half the layout bugs through.
    chain = "/deep"
    for tier in range(1, 9):
        chain = f"{chain}/tier-{tier}"
        pages.append(
            _profile(
                path=f"{chain}/",
                level=(
                    HierarchyLevel.L1_PRIMARY_NAV_HUB
                    if tier == 1
                    else HierarchyLevel.L2_SUB_NAV_HUB
                    if tier < 8
                    else HierarchyLevel.L3_LEAF_PAGE
                ),
                page_type=(
                    PrimaryPageType.SERVICE_CATEGORY_HUB
                    if tier < 8
                    else PrimaryPageType.SERVICE_DETAIL_PAGE
                ),
                depth=tier,
                inbound=random.randint(1, 30),
                outbound=4,
                confidence=round(random.uniform(0.6, 0.9), 3),
                method=ConsensusMethod.WEIGHTED_CONSENSUS,
                sources=(SignalSource.ARIA_NAV_TREE,),
                host=host,
            )
        )

    remaining = max(0, count - len(pages))
    per_section = max(1, remaining // len(_SECTIONS))

    for section, hub_type, leaf_type in _SECTIONS:
        pages.append(
            _profile(
                path=f"/{section}/",
                level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
                page_type=hub_type,
                depth=1,
                inbound=random.randint(800, 2000),
                outbound=40,
                confidence=round(random.uniform(0.86, 0.95), 3),
                method=ConsensusMethod.WEIGHTED_CONSENSUS,
                sources=(SignalSource.ARIA_NAV_TREE, SignalSource.LINK_IN_DEGREE),
                host=host,
            )
        )

        # Branching is uneven on purpose: a balanced tree hides the layout
        # problems that deep, narrow branches cause in a swimlane graph.
        sub_hubs = random.randint(3, 9)
        leaves_left = per_section - sub_hubs

        for sub in range(sub_hubs):
            sub_slug = f"{section}-area-{sub + 1}"
            pages.append(
                _profile(
                    path=f"/{section}/{sub_slug}/",
                    level=HierarchyLevel.L2_SUB_NAV_HUB,
                    page_type=hub_type,
                    depth=2,
                    inbound=random.randint(20, 300),
                    outbound=25,
                    confidence=round(random.uniform(0.7, 0.92), 3),
                    method=ConsensusMethod.WEIGHTED_CONSENSUS,
                    sources=(SignalSource.SITEMAP_INDEX, SignalSource.ARIA_NAV_TREE),
                    host=host,
                )
            )

            share = max(0, leaves_left // sub_hubs)
            for leaf in range(share):
                orphan = random.random() < 0.18
                unknown = random.random() < 0.004
                confidence = 0.0 if unknown else round(random.uniform(0.45, 0.95), 3)
                pages.append(
                    _profile(
                        path=f"/{section}/{sub_slug}/item-{leaf + 1}/",
                        level=HierarchyLevel.L3_LEAF_PAGE,
                        page_type=PrimaryPageType.UNKNOWN if unknown else leaf_type,
                        depth=3,
                        inbound=0 if orphan else random.randint(1, 12),
                        outbound=random.randint(2, 18),
                        confidence=confidence,
                        method=(
                            ConsensusMethod.LAYER3_LLM_FALLBACK
                            if unknown
                            else ConsensusMethod.WEIGHTED_CONSENSUS
                        ),
                        sources=(SignalSource.SITEMAP_INDEX,)
                        if confidence < 0.8
                        else (SignalSource.SITEMAP_INDEX, SignalSource.SCHEMA_JSONLD),
                        host=host,
                    )
                )

    pages = pages[:count]
    orphans = sum(1 for page in pages if page.inbound_internal_links_count == 0)
    escalated = sum(1 for page in pages if page.escalated_to_llm)

    return {
        "synthetic": True,
        "label": f"Synthetic site ({len(pages):,} pages)",
        "base_url": f"https://{host}",
        "site_profile": {
            "cms_family": "WORDPRESS",
            "renders_client_side": False,
            "has_catalogue": True,
            "locale_prefixes": [],
        },
        "weight_profile": {
            "profile_name": "default",
            "adaptive_enabled": False,
            "detected_profile_name": "wordpress",
        },
        "discovery": {
            "base_url": f"https://{host}",
            "total_urls": len(pages),
            "from_sitemap": int(len(pages) * 0.72),
            "from_dom": int(len(pages) * 0.61),
            "from_cms": int(len(pages) * 0.34),
            "sitemap_only": int(len(pages) * 0.21),
            "dom_only": int(len(pages) * 0.14),
            "orphans": orphans,
            "sitemaps_fetched": 18,
            "pages_fetched": int(len(pages) * 0.58),
            "truncated": True,
            "dom_reserve": int(len(pages) * 0.2),
            "dom_reserve_used": int(len(pages) * 0.14),
        },
        "summary": {
            "pages_classified": len(pages),
            "escalated_to_llm": escalated,
            "escalation_rate": round(escalated / len(pages), 5) if pages else 0.0,
            "unknown_pages": sum(
                1 for page in pages if page.primary_page_type is PrimaryPageType.UNKNOWN
            ),
            "low_confidence_pages": sum(1 for page in pages if not page.is_confidently_classified),
            "orphan_pages": orphans,
            "llm_spend_usd": 0.0,
        },
        "pages": [page.model_dump(mode="json") for page in pages],
    }


def build_from_crawl(url: str, max_pages: int, depth: int, reserve: float) -> dict[str, object]:
    """Crawl a real site and serialise the result as a fixture.

    Raises:
        RuntimeError: If the crawl does not succeed. A fixture built from a
            failed crawl would be indistinguishable from a real but empty site.
    """
    tool = PageClassificationTool()
    result = tool.run(
        PageClassificationInput(
            base_url=url,
            max_pages=max_pages,
            max_depth=depth,
            concurrency=5,
            dom_reserve_fraction=reserve,
        )
    )
    if result.status is not ExecutionStatus.SUCCESS or not isinstance(
        result.data, PageClassificationOutput
    ):
        msg = f"crawl of {url} failed: {result.status} {result.error}"
        raise RuntimeError(msg)

    payload = result.data.model_dump(mode="json")
    host = url.split("://")[-1].split("/")[0]
    payload["synthetic"] = False
    payload["label"] = f"{host} ({result.data.summary.pages_classified} pages, live crawl)"
    return payload


def _write(payload: dict[str, object], destination: Path) -> None:
    """Write a fixture, reporting its size."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=None, separators=(",", ":"))
    destination.write_text(text, encoding="utf-8")
    pages = len(payload.get("pages", []))  # type: ignore[arg-type]
    print(f"wrote {destination.relative_to(REPO_ROOT)}  {pages:,} pages  {len(text) / 1024:.0f} KB")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="export_ui_fixtures",
        description="Produce real and synthetic fixture datasets for the UI.",
    )
    parser.add_argument("--synthetic", type=int, default=0, help="Generate N synthetic pages")
    parser.add_argument("--crawl", default="", help="Crawl this URL for a real fixture")
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--dom-reserve", type=float, default=0.4)
    parser.add_argument("--out", default="", help="Output path override")
    args = parser.parse_args()

    if not args.synthetic and not args.crawl:
        parser.error("pass --synthetic N or --crawl URL")

    if args.synthetic:
        payload = build_synthetic(args.synthetic)
        name = args.out or f"synthetic-{args.synthetic}.json"
        _write(payload, FIXTURES_DIR / name if not args.out else Path(args.out))

    if args.crawl:
        print(f"Crawling {args.crawl}...")
        payload = build_from_crawl(args.crawl, args.max_pages, args.depth, args.dom_reserve)
        host = args.crawl.split("://")[-1].split("/")[0].replace(":", "_")
        name = args.out or f"{host}.json"
        _write(payload, FIXTURES_DIR / name if not args.out else Path(args.out))

    return 0


if __name__ == "__main__":
    sys.exit(main())
