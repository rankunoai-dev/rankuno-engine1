"""Placeholder for Theme-Based Classification (unimplemented in Phase 1).

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

__all__ = [
    "ThemeClassificationInput",
    "ThemeClassificationOutput",
    "ThemeClassificationTool",
    "register_tools",
]


class ThemeClassificationInput(StrictModel):
    """Input for theme classification (placeholder).

    Attributes:
        base_url: Site root to analyze.
    """

    base_url: str = Field(min_length=1)


class ThemeClassificationOutput(StrictModel):
    """Output of theme classification (placeholder).

    Attributes:
        base_url: Analyzed site.
        message: Placeholder message explaining tool is unimplemented.
    """

    base_url: str
    message: str


class ThemeClassificationTool(BaseTool[ThemeClassificationInput, ThemeClassificationOutput]):
    """Placeholder for theme-based page classification.

    Raises NotImplementedError on execute(). Use to test facet isolation
    infrastructure; actual theme classification is Phase 1.5+.
    """

    metadata: ClassVar[ToolMetadata] = ToolMetadata(
        name="seo.theme_classification",
        version="0.1.0",
        summary="(Unimplemented) Classify pages by visual design theme and content patterns.",
        risk_class=RiskClass.READ,
        facet_id="seo.theme_classification",
        rate_limit_key="web.crawl",
        estimated_cost_usd=0.0,
    )
    input_model: ClassVar[type[StrictModel]] = ThemeClassificationInput
    output_model: ClassVar[type[StrictModel]] = ThemeClassificationOutput

    def execute(self, payload: ThemeClassificationInput) -> ThemeClassificationOutput:
        """Raise NotImplementedError — tool not yet implemented.

        Args:
            payload: Input (unused, raises immediately).

        Raises:
            NotImplementedError: Always. This tool exists for infrastructure only.
        """
        msg = (
            "Theme Classification is not yet implemented. "
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
        registry.register(ThemeClassificationTool)
