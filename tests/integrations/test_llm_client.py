"""Tests for the provider-agnostic LLM connector.

No network. A fake provider returns canned responses and usage figures, which is
what lets the budget and cost-accounting logic be tested exhaustively.
"""

from __future__ import annotations

import pytest
from pydantic import Field
from src.core.config import Settings
from src.core.errors import BudgetExceededError, IntegrationError
from src.core.rate_limiter import CostLedger
from src.core.schemas import StrictModel
from src.integrations.llm_client import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMUsage,
    TokenPricing,
    estimate_tokens,
)

# Claude Haiku 4.5 rates, per docs/adr/0005.
HAIKU_PRICING = TokenPricing(
    input_usd_per_mtok=1.0,
    output_usd_per_mtok=5.0,
    cache_read_usd_per_mtok=0.1,
    batch_discount=0.5,
)


class Classification(StrictModel):
    """Stand-in for a Layer 3 classification result."""

    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class FakeLLMClient(LLMClient):
    """Provider stub that returns whatever it was primed with."""

    service_name = "test.llm"
    rate_limit_key = "test.llm"
    requests_per_minute = 6000
    model_id = "fake-model-1"
    pricing = HAIKU_PRICING

    def __init__(
        self,
        ledger: CostLedger,
        settings: Settings | None = None,
        usage: LLMUsage | None = None,
        result: Classification | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        """Prime the stub with the usage and result it should return."""
        super().__init__(ledger, settings)
        self._usage = usage or LLMUsage(input_tokens=1000, output_tokens=100)
        self._result = result or Classification(label="BLOG_ARTICLE", confidence=0.91)
        self._fail_with = fail_with
        self.calls = 0

    def authenticate(self) -> None:
        return None

    def _invoke(
        self, request: LLMRequest, response_model: type[StrictModel]
    ) -> tuple[Classification, LLMUsage]:
        self.calls += 1
        if self._fail_with is not None:
            raise self._fail_with
        return self._result, self._usage


def make_request(*, text: str = "classify this page", max_output: int = 100, batch: bool = False):
    return LLMRequest(
        messages=(LLMMessage(role=LLMRole.USER, content=text),),
        max_output_tokens=max_output,
        batch=batch,
    )


class TestEstimateTokens:
    def test_empty_string_is_zero(self):
        assert estimate_tokens("") == 0

    def test_scales_with_length(self):
        assert estimate_tokens("a" * 350) > estimate_tokens("a" * 35)

    def test_is_conservative(self):
        """Under-counting would let a call slip past the budget gate."""
        assert estimate_tokens("a" * 100) >= 100 / 4.0


class TestUsageCost:
    def test_computes_input_and_output_cost(self):
        usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert usage.cost_usd(HAIKU_PRICING) == pytest.approx(6.0)

    def test_cached_tokens_are_charged_at_the_cache_rate(self):
        usage = LLMUsage(cached_input_tokens=1_000_000)
        assert usage.cost_usd(HAIKU_PRICING) == pytest.approx(0.1)

    def test_batch_discount_halves_the_bill(self):
        usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert usage.cost_usd(HAIKU_PRICING, batch=True) == pytest.approx(3.0)

    def test_zero_usage_is_free(self):
        assert LLMUsage().cost_usd(HAIKU_PRICING) == pytest.approx(0.0)

    def test_output_tokens_cost_five_times_input(self):
        """Per token, output is the expensive side of the ledger."""
        one_m_in = LLMUsage(input_tokens=1_000_000)
        one_m_out = LLMUsage(output_tokens=1_000_000)
        assert one_m_out.cost_usd(HAIKU_PRICING) == pytest.approx(
            one_m_in.cost_usd(HAIKU_PRICING) * 5
        )

    def test_trimming_the_reasoning_field_is_a_material_saving(self):
        """Pins ADR 0005's 'no free-text reasoning field' rule to real arithmetic.

        Dropping ~110 output tokens of prose cuts roughly 28% off a typical
        Layer 3 call. Not a rounding error, and not the 4x some napkin maths
        suggests either — the input payload is a fixed floor under both.
        """
        prose = LLMUsage(input_tokens=1200, output_tokens=150).cost_usd(HAIKU_PRICING)
        terse = LLMUsage(input_tokens=1200, output_tokens=40).cost_usd(HAIKU_PRICING)
        assert prose == pytest.approx(0.00195)
        assert terse == pytest.approx(0.00140)
        assert (prose - terse) / prose == pytest.approx(0.28, abs=0.01)

    def test_cost_target_is_reachable_with_every_lever_applied(self):
        """Batch + trimmed output + a cached 4k prefix, at a 0.5% fallback rate.

        This is the only configuration that meets the <$0.05 per 20k-page target
        from TECH_STACK_SPECIFICATION §3. If this test fails, the cost claim in
        ADR 0005 is stale.
        """
        per_call = LLMUsage(input_tokens=200, cached_input_tokens=4096, output_tokens=40).cost_usd(
            HAIKU_PRICING, batch=True
        )
        calls_at_half_a_percent = 20_000 * 0.005
        assert per_call * calls_at_half_a_percent < 0.05


class TestRequestValidation:
    def test_requires_at_least_one_message(self):
        with pytest.raises(ValueError, match="at least 1"):
            LLMRequest(messages=(), max_output_tokens=10)

    def test_requires_positive_output_ceiling(self):
        with pytest.raises(ValueError):
            LLMRequest(messages=(LLMMessage(role=LLMRole.USER, content="x"),), max_output_tokens=0)

    def test_rejects_unbounded_output(self):
        with pytest.raises(ValueError):
            LLMRequest(
                messages=(LLMMessage(role=LLMRole.USER, content="x"),),
                max_output_tokens=999_999,
            )

    def test_defaults_to_deterministic_sampling(self):
        assert make_request().temperature == pytest.approx(0.0)

    def test_rejects_empty_message_content(self):
        with pytest.raises(ValueError):
            LLMMessage(role=LLMRole.USER, content="")

    def test_rejects_unknown_fields(self):
        """StrictModel forbids extras, so a renamed provider field surfaces loudly."""
        with pytest.raises(ValueError):
            LLMUsage(input_tokens=1, bogus_field=2)


class TestClientContract:
    def test_requires_model_id_and_pricing(self, settings, ledger):
        class Incomplete(FakeLLMClient):
            model_id = ""

        with pytest.raises(TypeError, match="model_id"):
            Incomplete(ledger, settings)

    def test_returns_validated_subclass_instance(self, settings, ledger):
        client = FakeLLMClient(ledger, settings)
        response = client.complete(make_request(), Classification)
        assert isinstance(response.parsed, Classification)
        assert response.parsed.label == "BLOG_ARTICLE"
        assert response.model == "fake-model-1"

    def test_generic_envelope_preserves_all_fields(self, settings, ledger):
        """An unparameterised generic would strip these down to StrictModel."""
        client = FakeLLMClient(ledger, settings)
        response = client.complete(make_request(), Classification)
        assert response.parsed.confidence == pytest.approx(0.91)

    def test_wraps_provider_failures_as_integration_errors(self, settings, ledger):
        client = FakeLLMClient(ledger, settings, fail_with=RuntimeError("provider exploded"))
        with pytest.raises(IntegrationError):
            client.complete(make_request(), Classification)


class TestCostAccounting:
    def test_charges_actual_cost_to_the_ledger(self, settings):
        ledger = CostLedger(ceiling_usd=1.0)
        client = FakeLLMClient(
            ledger, settings, usage=LLMUsage(input_tokens=1000, output_tokens=100)
        )
        response = client.complete(make_request(), Classification)

        expected = (1000 * 1.0 + 100 * 5.0) / 1_000_000
        assert response.cost_usd == pytest.approx(expected)
        assert ledger.spent_usd == pytest.approx(expected)

    def test_batch_request_is_charged_at_the_discount(self, settings):
        ledger = CostLedger(ceiling_usd=1.0)
        client = FakeLLMClient(ledger, settings)
        full = client.complete(make_request(), Classification).cost_usd
        discounted = client.complete(make_request(batch=True), Classification).cost_usd
        assert discounted == pytest.approx(full * 0.5)

    def test_successive_calls_accumulate(self, settings):
        ledger = CostLedger(ceiling_usd=1.0)
        client = FakeLLMClient(ledger, settings)
        first = client.complete(make_request(), Classification).cost_usd
        client.complete(make_request(), Classification)
        assert ledger.spent_usd == pytest.approx(first * 2)


class TestBudgetGate:
    def test_refuses_a_call_that_could_exceed_the_budget(self, settings):
        ledger = CostLedger(ceiling_usd=0.0000001)
        client = FakeLLMClient(ledger, settings)
        with pytest.raises(BudgetExceededError):
            client.complete(make_request(), Classification)

    def test_refused_call_never_reaches_the_provider(self, settings):
        """The gate must be pre-flight; a refused call must cost nothing."""
        ledger = CostLedger(ceiling_usd=0.0000001)
        client = FakeLLMClient(ledger, settings)
        with pytest.raises(BudgetExceededError):
            client.complete(make_request(), Classification)
        assert client.calls == 0
        assert ledger.spent_usd == pytest.approx(0.0)

    def test_worst_case_assumes_full_length_output(self, settings, ledger):
        client = FakeLLMClient(ledger, settings)
        cheap = client.estimate_worst_case_usd(make_request(max_output=10))
        pricey = client.estimate_worst_case_usd(make_request(max_output=1000))
        assert pricey > cheap

    def test_worst_case_accounts_for_batch_discount(self, settings, ledger):
        client = FakeLLMClient(ledger, settings)
        full = client.estimate_worst_case_usd(make_request())
        batched = client.estimate_worst_case_usd(make_request(batch=True))
        assert batched == pytest.approx(full * 0.5)

    def test_budget_exhaustion_degrades_rather_than_corrupting(self, settings):
        """Layer 3's contract: raise so the caller keeps its structural guess."""
        ledger = CostLedger(ceiling_usd=0.001)
        client = FakeLLMClient(ledger, settings, usage=LLMUsage(input_tokens=100, output_tokens=50))

        succeeded = 0
        with pytest.raises(BudgetExceededError):
            for _ in range(100):
                client.complete(make_request(), Classification)
                succeeded += 1

        assert succeeded > 0, "some calls must land before the cap bites"
        assert ledger.spent_usd <= 0.001


class TestParseStructured:
    def test_parses_valid_json(self):
        result = LLMClient.parse_structured('{"label": "X", "confidence": 0.5}', Classification)
        assert result.label == "X"

    def test_rejects_malformed_json(self):
        with pytest.raises(IntegrationError, match="not valid JSON"):
            LLMClient.parse_structured("{not json", Classification)

    def test_rejects_schema_violation(self):
        with pytest.raises(IntegrationError, match="did not match schema"):
            LLMClient.parse_structured('{"label": "X", "confidence": 9.9}', Classification)

    def test_rejects_extra_fields(self):
        with pytest.raises(IntegrationError, match="did not match schema"):
            LLMClient.parse_structured(
                '{"label": "X", "confidence": 0.5, "sneaky": 1}', Classification
            )
