"""Provider-agnostic LLM connector with per-call spend metering.

Two requirements shape this module, both from
`docs/adr/0005-llm-provider-strategy-and-cost-metering.md`:

1. **Multi-provider is mandatory, not aspirational.** Phase 7 Signal 1 queries
   eight different answer engines. The classification cascade's Layer 3 is
   therefore one caller of a shared abstraction, not a bespoke integration.
2. **Cost is variable and must be metered where it is incurred.** A tool's
   static `estimated_cost_usd` cannot describe a crawl that makes between zero
   and several hundred fallback calls. Spend is checked before each call and
   charged after it, against a `CostLedger` the caller owns.

Structured output, not prompt-and-parse
---------------------------------------
`complete()` takes a `StrictModel` subclass and returns an instance of it. The
provider is expected to constrain generation to the model's JSON Schema, so an
unparseable or half-populated response is a provider bug rather than an everyday
occurrence the pipeline must code around. Validation happens here regardless, so
a provider without schema enforcement still cannot leak a malformed object into
the classifier.

No concrete provider is implemented yet: that needs a live credential and
network access. `docs/adr/0005` selects Claude Haiku 4.5 as the Layer 3 default.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from enum import StrEnum
from typing import ClassVar, Generic, TypeVar

from pydantic import Field

from src.core.config import Settings
from src.core.errors import BudgetExceededError, IntegrationError
from src.core.logger import get_logger
from src.core.rate_limiter import CostLedger
from src.core.schemas import StrictModel
from src.integrations.base_client import BaseAPIClient

__all__ = [
    "LLMClient",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMRole",
    "LLMUsage",
    "TokenPricing",
    "estimate_tokens",
]

_logger = get_logger("integrations.llm_client")

_CHARS_PER_TOKEN = 3.5
"""Conservative characters-per-token ratio used for pre-flight cost estimates.

Deliberately below the ~4.0 typical of English prose: the estimate gates spend,
so over-counting fails safe. Exact accounting always uses the provider's
reported `LLMUsage`, never this.
"""

_USD_PER_MTOK = 1_000_000.0


class LLMRole(StrEnum):
    """Who authored a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(StrictModel):
    """One turn of a conversation.

    Attributes:
        role: Message author.
        content: Message text. Scraped page content placed here is untrusted —
            callers MUST sanitise it for prompt injection before constructing
            the message (Phase 1 Master Blueprint §6).
    """

    role: LLMRole
    content: str = Field(min_length=1)


class TokenPricing(StrictModel):
    """Per-million-token rates for one model.

    Held in configuration rather than hard-coded so a price change is not a code
    change. Rates are per million tokens, matching how providers publish them.

    Attributes:
        input_usd_per_mtok: Cost per million input tokens.
        output_usd_per_mtok: Cost per million output tokens.
        cache_read_usd_per_mtok: Cost per million cached-prefix input tokens.
        batch_discount: Multiplier applied when a request is submitted as part
            of a batch. `0.5` means 50% off.
    """

    input_usd_per_mtok: float = Field(ge=0.0)
    output_usd_per_mtok: float = Field(ge=0.0)
    cache_read_usd_per_mtok: float = Field(default=0.0, ge=0.0)
    batch_discount: float = Field(default=1.0, gt=0.0, le=1.0)


class LLMUsage(StrictModel):
    """Token counts as reported by the provider.

    Attributes:
        input_tokens: Uncached input tokens billed at the full input rate.
        output_tokens: Generated tokens.
        cached_input_tokens: Input tokens served from a cached prefix.
    """

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)

    def cost_usd(self, pricing: TokenPricing, *, batch: bool = False) -> float:
        """Compute the billed cost of this usage.

        Args:
            pricing: Rates for the model that produced it.
            batch: Whether the request was submitted through a batch endpoint.

        Returns:
            Cost in USD.
        """
        total = (
            self.input_tokens * pricing.input_usd_per_mtok
            + self.output_tokens * pricing.output_usd_per_mtok
            + self.cached_input_tokens * pricing.cache_read_usd_per_mtok
        ) / _USD_PER_MTOK
        return total * (pricing.batch_discount if batch else 1.0)


class LLMRequest(StrictModel):
    """One structured-output completion request.

    Attributes:
        messages: Conversation turns, in order.
        max_output_tokens: Hard ceiling on generation. Required, because output
            tokens dominate cost and an unbounded response is an unbounded bill.
        temperature: Sampling temperature. Defaults to 0.0 — classification is a
            decision, not a creative task, and determinism makes accuracy
            regressions reproducible.
        batch: Submit through the provider's batch endpoint when available.
    """

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    max_output_tokens: int = Field(gt=0, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    batch: bool = False

    def estimated_input_tokens(self) -> int:
        """Approximate the input token count without calling a tokenizer."""
        return sum(estimate_tokens(message.content) for message in self.messages)


ResponseT = TypeVar("ResponseT", bound=StrictModel)


class LLMResponse(StrictModel, Generic[ResponseT]):
    """A validated structured completion.

    Attributes:
        model: Provider model id that produced it.
        parsed: The response, already validated against the caller's model.
        usage: Token counts reported by the provider.
        cost_usd: Actual billed cost, charged to the ledger.
    """

    model: str
    parsed: ResponseT
    usage: LLMUsage
    cost_usd: float = Field(default=0.0, ge=0.0)


def estimate_tokens(text: str) -> int:
    """Approximate the token count of `text`.

    Used only for pre-flight spend estimates. Rounds up and assumes a low
    characters-per-token ratio so the estimate errs toward refusing a call
    rather than overshooting a budget.

    Args:
        text: The text to measure.

    Returns:
        An approximate, deliberately conservative token count.
    """
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN) + 1)


class LLMClient(BaseAPIClient):
    """Base class for every LLM provider connector.

    Subclasses implement `_invoke()` (transport) and `authenticate()`, and set
    the `BaseAPIClient` class variables plus `model_id` and `pricing`. Everything
    cross-cutting — quota, retry, budget checks, cost accounting, audit
    logging — is handled here so providers stay thin and comparable.
    """

    model_id: ClassVar[str]
    pricing: ClassVar[TokenPricing]

    def __init__(self, ledger: CostLedger, settings: Settings | None = None) -> None:
        """Build a client bound to a spend ledger.

        Args:
            ledger: Ledger charged for every call. Required — an LLM client with
                no budget attached is how a runaway agent loop burns a month's
                spend in an afternoon.
            settings: Configuration override, primarily for tests.

        Raises:
            TypeError: If the subclass omits `model_id` or `pricing`.
        """
        super().__init__(settings)

        for attr in ("model_id", "pricing"):
            if not getattr(type(self), attr, None):
                msg = f"{type(self).__name__} must declare a class-level '{attr}'."
                raise TypeError(msg)

        self._ledger = ledger

    @abstractmethod
    def _invoke(
        self, request: LLMRequest, response_model: type[ResponseT]
    ) -> tuple[ResponseT, LLMUsage]:
        """Perform the provider call and return the parsed result plus usage.

        Called only after the budget check has passed. Implementations should
        pass `response_model.model_json_schema()` to the provider's structured
        output mechanism, and raise on failure — `complete()` wraps exceptions.

        Args:
            request: The validated request.
            response_model: Model the response must satisfy.

        Returns:
            The parsed response and the provider's reported token usage.
        """
        raise NotImplementedError

    def complete(
        self, request: LLMRequest, response_model: type[ResponseT]
    ) -> LLMResponse[ResponseT]:
        """Run one completion under quota, retry and budget protection.

        The spend cap is enforced by refusing a call whose worst case would not
        fit in the remaining budget, then charging the actual cost afterwards.
        Precision is therefore one worst-case call: the ledger can be undershot,
        never meaningfully overshot.

        Args:
            request: What to ask.
            response_model: Model the response must validate against.

        Returns:
            The validated response, with actual cost attached.

        Raises:
            BudgetExceededError: If the call could exceed the remaining budget.
                Callers should treat this as a signal to degrade gracefully —
                for Layer 3, keep the best structural guess rather than failing
                the crawl.
            IntegrationError: If the provider call fails after retries.
        """
        worst_case = self.estimate_worst_case_usd(request)
        remaining = self._ledger.remaining_usd
        if worst_case > remaining:
            _logger.warning(
                "llm_call_refused_budget",
                extra={
                    "model": type(self).model_id,
                    "worst_case_usd": round(worst_case, 6),
                    "remaining_usd": round(remaining, 6),
                },
            )
            spent = self._ledger.spent_usd
            raise BudgetExceededError(worst_case, spent, spent + remaining)

        parsed, usage = self.call(
            "complete",
            lambda: self._invoke(request, response_model),
        )

        cost = usage.cost_usd(type(self).pricing, batch=request.batch)
        self._ledger.charge(cost)

        _logger.info(
            "llm_call_completed",
            extra={
                "model": type(self).model_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "batch": request.batch,
                "cost_usd": round(cost, 6),
            },
        )

        # Parameterise explicitly: an unparameterised generic would validate
        # `parsed` against the TypeVar bound (`StrictModel`) and silently drop
        # every subclass field. Pydantic caches parametrised classes, so this is
        # a dict lookup after the first call for a given response model.
        envelope: type[LLMResponse[ResponseT]] = LLMResponse[response_model]  # type: ignore[valid-type]
        return envelope(
            model=type(self).model_id,
            parsed=parsed,
            usage=usage,
            cost_usd=cost,
        )

    def estimate_worst_case_usd(self, request: LLMRequest) -> float:
        """Cost of `request` if generation runs to `max_output_tokens`.

        Assumes no cache hits and a full-length response, because a budget gate
        that assumes the best case is not a gate.

        Args:
            request: The request to price.

        Returns:
            Worst-case cost in USD.
        """
        usage = LLMUsage(
            input_tokens=request.estimated_input_tokens(),
            output_tokens=request.max_output_tokens,
        )
        return usage.cost_usd(type(self).pricing, batch=request.batch)

    @staticmethod
    def parse_structured(payload: str, response_model: type[ResponseT]) -> ResponseT:
        """Validate a raw JSON string against `response_model`.

        Helper for provider implementations whose SDK returns text rather than a
        parsed object. Any failure becomes an `IntegrationError` so a malformed
        completion is reported as an upstream fault, not a crash.

        Args:
            payload: Raw JSON text from the provider.
            response_model: Model to validate against.

        Returns:
            The validated model instance.

        Raises:
            IntegrationError: If the payload is not valid JSON, or does not
                satisfy the schema.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IntegrationError("llm", f"response was not valid JSON: {exc}") from exc

        try:
            return response_model.model_validate(data)
        except ValueError as exc:
            raise IntegrationError("llm", f"response did not match schema: {exc}") from exc
