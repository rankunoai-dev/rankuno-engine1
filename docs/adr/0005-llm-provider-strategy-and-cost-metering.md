# ADR 0005: Provider-agnostic `LLMClient`; Claude Haiku 4.5 as the Layer 3 default

- **Status**: Accepted
- **Date**: 2026-08-06
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Layer 3 of the classification cascade invokes an LLM when combined signal confidence
falls below 0.85 — specified as under 2% of pages. The cost target is
**< $0.05 per 20,000-page run**.

Separately, `docs/PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md` §3 Signal 1 requires BYOK
queries against **eight** engines (ChatGPT, Claude, Perplexity, Gemini, Copilot, Grok,
Meta AI, DeepSeek). Multi-provider support is therefore not optional; it is a stated
Phase 7 requirement.

The source documents name "Gemini 2.0 Flash" (`TECH_STACK_SPECIFICATION.md`) and
"Gemini 3.6 Flash" (`CLAUDE_HANDOFF_DIRECTIVE.md`, governance doc). The latter is not a
real model. Neither is pinned in configuration.

A separate problem: `ToolMetadata.estimated_cost_usd` is a **static** value charged
once up front, and `ToolMetadata._cost_implies_financial` forces any non-zero-cost tool
to `RiskClass.FINANCIAL`, which maps to `MANDATORY_HITL`. A classification run costing
five cents would therefore require human approval **every run**, contradicting the
"READ / unattended" design goal.

## Decision

### 1. Provider abstraction

An **`LLMClient`** interface lives in `src/integrations/`, subclassing `BaseAPIClient`.
The classification pipeline depends only on the interface. The concrete provider and
model id are resolved from `Settings` — **no model name appears in prose or in code
outside configuration.**

### 2. Layer 3 default

**Claude Haiku 4.5**, with:

- **Structured outputs** — a JSON schema constrains the response, guaranteeing it
  validates. This maps directly onto the `StrictModel` `extra="forbid"` requirement and
  removes the parse-retry loop entirely.
- **Batch API** — 50% discount. Layer 3 is not latency-sensitive: Layers 0–2 complete,
  ambiguous pages are collected, one batch is submitted.

### 3. Response schema excludes free-text reasoning

At $1/MTok input and $5/MTok output, output tokens dominate. A prose `reasoning` field
costs more than the entire page payload. The Layer 3 schema returns enums, a bounded
confidence float, and nothing else.

### 4. Cost metering is per-call, not per-job

The job-level `estimated_cost_usd` is **not** used to charge for Layer 3. Instead:

- The crawl tool remains `RiskClass.READ`.
- A **spend cap** is passed into the job as an input field.
- The `LLMClient` charges `CostLedger` per call and refuses further calls once the cap
  is reached, degrading to "leave the page at its best structural guess" rather than
  failing the crawl.

This preserves unattended operation while keeping a hard ceiling.

## Alternatives considered

1. **Gemini Flash as default.** Not rejected on merit — current Gemini pricing was not
   verified at decision time, and at these volumes the cheap tiers differ by cents per
   run. Selected against primarily because guaranteed schema-valid output removes real
   error-handling code. Revisit with verified pricing if cost becomes the binding
   constraint; the `LLMClient` interface makes this a configuration change.
2. **Local Qwen 2.5 14B only.** Rejected as the sole option: it makes Layer 3 unavailable
   in any non-GPU environment and cannot serve Phase 7's cross-engine requirement.
   Remains viable as an additional `LLMClient` implementation.
3. **Classify `RiskClass.FINANCIAL` and require approval per run.** Rejected: it makes
   unattended classification impossible, defeating the automation goal.

## Consequences

**Positive**

- Phase 7's eight-engine requirement is satisfied by the same abstraction.
- Schema-guaranteed output eliminates a class of runtime validation failures.
- The spend cap is enforced at the point of spend, not estimated in advance.

**Negative**

- **The < $0.05 target is not reachable at a 2% fallback rate.** Baseline assumption is
  1,200 input tokens and 150 output tokens per call, at Haiku 4.5's $1 / $5 per MTok.
  These figures are pinned by tests in `tests/integrations/test_llm_client.py`, so this
  table cannot silently go stale:

  | Configuration | Per call | 2% fallback (400 calls) | 0.5% fallback (100 calls) |
  | :--- | ---: | ---: | ---: |
  | Naive | $0.00195 | $0.78 | $0.20 |
  | Batch API (50% off) | $0.00098 | $0.39 | $0.10 |
  | Batch + trimmed output (40 tok) | $0.00070 | $0.28 | $0.07 |
  | Batch + trimmed + 4k cached prefix | $0.00040 | $0.16 | **$0.04** ✅ |

  Only the last row meets the target, and only at a 0.5% fallback rate. **Reaching the
  cost target is an accuracy requirement on Layers 0–2, not a model choice**: they must
  resolve 99.5% of pages, not the 98% currently specified.

- A correction to earlier reasoning: output tokens are 5× the per-token price of input,
  but at these ratios they do **not** dominate the bill — a 1,200-token input payload is
  a fixed floor under every call. Trimming a prose `reasoning` field saves ~28% of call
  cost, which is worth doing but is not the 4× a quick estimate suggests. The dominant
  levers, in order, are: **fallback rate**, then batching, then prompt caching, then
  output trimming.

- Prompt caching has a **4,096-token minimum prefix on Haiku 4.5** (vs 1,024 on Sonnet 5).
  A shorter taxonomy prompt silently does not cache — no error, no discount. The table
  above depends on building a genuinely large few-shot prefix, which is not optional if
  the cost target is to be met. It should improve Layer 3 accuracy as a side effect.

- `CostLedger` is in-process. A multi-worker deployment would grant each worker the
  full cap. Blocking issue for hosted deployment, not for local (ADR 0004).

**Follow-up**

- Add `llm_provider`, `llm_model_id`, and `llm_spend_cap_usd` to `Settings`.
- Reconcile the cost claim in `TECH_STACK_SPECIFICATION.md` §3.
- `CostLedger` needs reserve/settle semantics before any variable-cost tool is
  classified `FINANCIAL`.
