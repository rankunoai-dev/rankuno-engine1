"""Phase 1: Page Classification & Intent Analysis Engine.

Classifies every URL in a site graph across three interfaces — structural
hierarchy, topical cluster, and semantic intent — using a four-layer cascading
pipeline that resolves the overwhelming majority of pages at zero API cost.

Implemented so far:

* `schemas.py` — the taxonomy and the `FullPageIntelligenceProfile` contract.

Planned, not yet written (do not describe these as working):

* `signals.py` — the six consensus signal extractors.
* `pipeline.py` — the Layer 0-3 cascade and weighted consensus.
* `tool.py` — the `BaseTool` entry point. One invocation is one crawl job, per
  `docs/adr/0003-job-level-governance-and-async-internals.md`.
* `tree_visualizer.py` — standalone interactive HTML site tree.
"""

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

__all__ = [
    "ConsensusMethod",
    "ConversionRole",
    "FullPageIntelligenceProfile",
    "HierarchyLevel",
    "PrimaryPageType",
    "SearchIntent",
    "SignalScore",
    "SignalSource",
]
