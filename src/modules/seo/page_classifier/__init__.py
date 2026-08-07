"""Phase 1: Page Classification & Intent Analysis Engine.

Classifies every URL in a site graph across three interfaces — structural
hierarchy, topical cluster, and semantic intent — using a four-layer cascading
pipeline that resolves the overwhelming majority of pages at zero API cost.

Implemented so far:

* `schemas.py` — the taxonomy and the `FullPageIntelligenceProfile` contract.
* `weights.py` — signal weight profiles and the site-profile selection seam.
* `url_rules.py` — Layer 0 normalisation and pre-fetch classification.
* `signal_parsers.py` — the five structural consensus signals.
* `cascading_pipeline.py` — the Layer 0-3 cascade and weighted consensus.

Planned, not yet written (do not describe these as working):

* `tool.py` — the `BaseTool` entry point. One invocation is one crawl job, per
  `docs/adr/0003-job-level-governance-and-async-internals.md`.
* `tree_visualizer.py` — standalone interactive HTML site tree.
* A Layer 2 `ZeroShotClassifier` implementation. The protocol exists; the local
  ONNX model behind it does not (`docs/adr/0004`).
"""

from src.modules.seo.page_classifier.cascading_pipeline import (
    ConsensusOutcome,
    ZeroShotClassifier,
    classify_page,
    needs_llm_escalation,
    resolve_consensus,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    ConversionRole,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import (
    CmsRecord,
    NavLink,
    PageEvidence,
    collect_structural_signals,
)
from src.modules.seo.page_classifier.url_rules import normalize_url, url_fast_path
from src.modules.seo.page_classifier.weights import (
    CmsFamily,
    SiteProfile,
    get_weight_profile,
)

__all__ = [
    "CmsFamily",
    "CmsRecord",
    "ConsensusMethod",
    "ConsensusOutcome",
    "ConversionRole",
    "FullPageIntelligenceProfile",
    "HierarchyLevel",
    "NavLink",
    "PageEvidence",
    "PrimaryPageType",
    "SearchIntent",
    "SignalScore",
    "SignalSource",
    "SiteProfile",
    "ZeroShotClassifier",
    "classify_page",
    "collect_structural_signals",
    "get_weight_profile",
    "needs_llm_escalation",
    "normalize_url",
    "resolve_consensus",
    "url_fast_path",
]
