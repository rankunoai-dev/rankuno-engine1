"""Shared profile and result builders for the "All URLs" column tests.

Kept apart from the test modules so the derivation tests and the workbook/PDF
tests build their pages the same way, and so each test file stays under the
400-line limit. Every helper defaults to a page the crawl fetched successfully
and sitemap- or link-discovered; a test overrides only the fields it is about.
"""

from __future__ import annotations

import base64
import re
import zlib

from src.modules.seo.page_classifier.discovery import OUTCOME_OK, DiscoveryReport
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    DiscoverySource,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import CrawlSummary, PageClassificationOutput
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

BASE_URL = "https://e.com/"


def make_page(url: str = "https://e.com/p/", **fields: object) -> FullPageIntelligenceProfile:
    """A validly classified page the crawl fetched, with any overrides applied."""
    base: dict[str, object] = {
        "url": url,
        "canonical_url": url,
        "normalized_path": url,
        "hierarchy_level": HierarchyLevel.L3_LEAF_PAGE,
        "primary_page_type": PrimaryPageType.BLOG_ARTICLE,
        "depth_from_l0": 1,
        "search_intent": SearchIntent.INFORMATIONAL,
        "signals_evaluated": (
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.9,
            ),
        ),
        "final_confidence_score": 0.9,
        "consensus_method": ConsensusMethod.LAYER1_STRUCTURAL,
        "final_url": url,
        "http_status": 200,
        "fetch_outcome": OUTCOME_OK,
        "discovery_sources": DiscoverySource(dom_link=True),
    }
    base.update(fields)
    return FullPageIntelligenceProfile.model_validate(base)


def legacy_page(url: str = "https://e.com/old/") -> FullPageIntelligenceProfile:
    """A profile as stored before any fetch or discovery fact was recorded."""
    return make_page(
        url,
        http_status=None,
        fetch_outcome=None,
        final_url="",
        discovery_sources=DiscoverySource(),
    )


def make_result(*pages: FullPageIntelligenceProfile) -> PageClassificationOutput:
    """A crawl result wrapping the given pages, with empty site-level context."""
    return PageClassificationOutput(
        base_url=BASE_URL,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(base_url=BASE_URL),
        summary=CrawlSummary(pages_classified=len(pages)),
        pages=pages,
    )


def pdf_text(pdf_bytes: bytes) -> bytes:
    """Decode the content streams of a `generate_pdf` PDF to raw bytes.

    The same decoder the server tests use: the ASCII85-over-Flate chain that
    `SimpleDocTemplate` writes. It is enough to see which header words reached
    the rendered page, not a general PDF text extractor. Headers wrap onto two
    lines in the PDF, so callers join them across `Tj T*` before matching.
    """
    chunks: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL):
        raw = match.group(1).rstrip(b"\r\n")
        if raw.endswith(b"~>"):
            raw = raw[:-2]
        try:
            chunks.append(zlib.decompress(base64.a85decode(raw, adobe=False)))
        except (ValueError, zlib.error):
            continue
    return b"".join(chunks)
