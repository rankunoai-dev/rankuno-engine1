"""Placeholder for the Health Analyze Engine (unimplemented in Phase 1).

This tool is registered but raises NotImplementedError when executed. It exists
to establish the facet and concurrency isolation infrastructure. Implementation
is deferred to Phase 1.5.

See Phase 1 cloud-readiness ADR (cycle 0081) for details.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from src.core.base_tool import BaseTool
from src.core.schemas import RiskClass, StrictModel, ToolMetadata

__all__ = ["HealthAnalyzeInput", "HealthAnalyzeOutput", "HealthAnalyzeTool", "register_tools"]


class HealthAnalyzeInput(StrictModel):
    """Input for the health engine (placeholder).

    Attributes:
        base_url: Site root to analyze.
    """

    base_url: str = Field(min_length=1)


class HealthAnalyzeOutput(StrictModel):
    """Output of the health engine (placeholder).

    Attributes:
        base_url: Analyzed site.
        message: Placeholder message explaining tool is unimplemented.
    """

    base_url: str
    message: str


class HealthAnalyzeTool(BaseTool[HealthAnalyzeInput, HealthAnalyzeOutput]):
    """Placeholder for site health analysis.

    Raises NotImplementedError on execute(). Use to test facet isolation
    infrastructure; actual health scoring is Phase 1.5+.
    """

    metadata: ClassVar[ToolMetadata] = ToolMetadata(
        name="seo.health_engine",
        version="0.1.0",
        summary="(Unimplemented) Analyze site health and provide recommendations.",
        risk_class=RiskClass.READ,
        facet_id="seo.health_engine",
        rate_limit_key="web.crawl",
        estimated_cost_usd=0.0,
    )
    input_model: ClassVar[type[StrictModel]] = HealthAnalyzeInput
    output_model: ClassVar[type[StrictModel]] = HealthAnalyzeOutput

    def execute(self, payload: HealthAnalyzeInput) -> HealthAnalyzeOutput:
        """Raise NotImplementedError — tool not yet implemented.

        Args:
            payload: Input (unused, raises immediately).

        Raises:
            NotImplementedError: Always. This tool exists for infrastructure only.
        """
        msg = (
            "Health Analyze Engine is not yet implemented. "
            "See Phase 1 cloud-readiness build-log (cycle 0081) for details."
        )
        raise NotImplementedError(msg)


def register_tools() -> None:
    """Register this module's tools with the global registry.

    Called at bootstrap; does nothing if already registered (tests may call
    multiple times).
    """
    import contextlib

    from src.core.registry import registry

    with contextlib.suppress(ValueError):
        registry.register(HealthAnalyzeTool)
