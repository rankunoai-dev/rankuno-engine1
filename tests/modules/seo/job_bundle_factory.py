"""Builders for valid job-import bundles, shared by the module, API and CLI tests.

Every URL-bearing field family the URL audit walks is populated, so a test that
poisons one field proves that field is walked rather than passing because the
field was empty.
"""

from __future__ import annotations

import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.nav_tree_parser import NavigationTree, NavNode
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    DiscoverySource,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    Indexability,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import (
    CrawlSummary,
    PageClassificationInput,
    PageClassificationOutput,
)
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

BASE = "https://example.com/"
SOURCE_JOB_ID = "0123456789abcdef0123456789abcdef"
INSTANCE_ID = "li-test-instance-0001"
STARTED = datetime(2026, 10, 6, 17, 34, tzinfo=UTC)
FINISHED = STARTED + timedelta(minutes=38)


def profile(url: str, **overrides: Any) -> FullPageIntelligenceProfile:
    """A minimal valid page profile."""
    fields: dict[str, Any] = {
        "url": url,
        "canonical_url": url,
        "normalized_path": url,
        "hierarchy_level": HierarchyLevel.L3_LEAF_PAGE,
        "primary_page_type": PrimaryPageType.UNKNOWN,
        "depth_from_l0": 1,
        "search_intent": SearchIntent.INFORMATIONAL,
        "signals_evaluated": (
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.UNKNOWN,
                confidence=0.5,
            ),
        ),
        "final_confidence_score": 0.5,
        "consensus_method": ConsensusMethod.LAYER1_STRUCTURAL,
        "discovery_sources": DiscoverySource(sitemap=True, dom_link=True),
        "indexability": Indexability.INDEXABLE,
    }
    fields.update(overrides)
    return FullPageIntelligenceProfile(**fields)


def crawl_output(page_count: int = 2) -> PageClassificationOutput:
    """A result exercising every walked URL field."""
    pages = [
        profile(
            f"{BASE}page-{i}",
            final_url=f"{BASE}page-{i}/",
            redirect_chain=(f"{BASE}page-{i}", f"{BASE}page-{i}/"),
            nav_parent_url=BASE,
        )
        for i in range(page_count)
    ]
    return PageClassificationOutput(
        base_url=BASE,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(base_url=BASE, total_urls=page_count, pages_fetched=page_count),
        summary=CrawlSummary(pages_classified=page_count),
        pages=tuple(pages),
        navigation=NavigationTree(
            roots=(
                NavNode(
                    label="Services",
                    url=f"{BASE}services",
                    children=(NavNode(label="Lawn", url=f"{BASE}services/lawn", depth=1),),
                ),
            )
        ),
    )


def bundle_dict(**overrides: Any) -> dict[str, Any]:
    """A valid bundle as a JSON-ready dict. Overrides replace top-level keys."""
    request = PageClassificationInput(
        base_url=BASE, seed_urls=(f"{BASE}seed",), exclude_urls=(f"{BASE}excluded",)
    )
    bundle: dict[str, Any] = {
        "format": "rankuno.job-bundle",
        "version": 1,
        "source": {"source_instance_id": INSTANCE_ID, "source_job_id": SOURCE_JOB_ID},
        "status": "succeeded",
        "label": BASE,
        "error": None,
        "started_at": STARTED.isoformat(),
        "finished_at": FINISHED.isoformat(),
        "request": request.model_dump(mode="json"),
        "result": crawl_output().model_dump(mode="json"),
        "homepage_html": "<html><nav><a href='/services'>Services</a></nav></html>",
    }
    bundle.update(overrides)
    return copy.deepcopy(bundle)


def gz(bundle: dict[str, Any] | bytes) -> bytes:
    """Gzip a bundle dict (or raw bytes) the way the CLI does: `mtime=0`."""
    raw = bundle if isinstance(bundle, bytes) else json.dumps(bundle).encode("utf-8")
    return gzip.compress(raw, mtime=0)
