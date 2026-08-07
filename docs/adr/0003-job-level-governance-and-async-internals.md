# ADR 0003: One `BaseTool.run()` is one crawl job, not one page

- **Status**: Accepted
- **Date**: 2026-08-06
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`BaseTool.run()` (`src/core/base_tool.py`) is synchronous and applies, per invocation:
a guardrail evaluation, a blocking `TokenBucket.acquire()` that uses `time.sleep()`,
a `CostLedger.charge()`, and two audit log records written through a synchronous
`logging.FileHandler`.

Phase 1 targets 20,000 pages in 15–30 seconds using async `httpx` with HTTP/2
connection pooling.

If one `run()` were one page, a 20,000-page crawl would perform 20,000 guardrail
evaluations, 20,000 blocking bucket acquisitions, and 40,000 synchronous JSON writes
to `logs/audit.jsonl`. The logging alone would exceed the entire 30-second budget, and
the blocking sleeps are incompatible with an async event loop.

There is also a governance argument: an operator approving "crawl highradius.com" is
making **one** decision. Asking them to approve 20,000 page fetches is not more
safety, it is an unusable prompt.

## Decision

**One `BaseTool.run()` invocation == one crawl job.** The governed pipeline
(validate → guardrail → rate limit → charge → execute → validate → audit) wraps the
*job*. Per-page governance is forbidden.

Inside `execute()`, the crawl runs its own async pipeline. This requires two additions
to `core`:

1. **`AsyncTokenBucket`** — same semantics as `TokenBucket` but awaits `asyncio.sleep()`.
   Per-domain politeness throttling inside a crawl happens here, not through the
   governed pipeline. The two bucket types share a `RateLimiterRegistry`-style
   registry so a domain's quota is respected across both.
2. **Per-page audit records go to a job-scoped summary, not the audit log.** The audit
   log receives one record per job. Per-page classification results are an output
   artifact, persisted to the graph store.

The tool declares `RiskClass.READ` — a crawl mutates nothing outside this repository.
Cost governance for the Layer 3 LLM fallback is handled per ADR 0005, not by the
job-level `estimated_cost_usd` field.

## Alternatives considered

1. **Per-page `run()`.** Rejected on the performance arithmetic above and because it
   produces an unusable approval prompt.
2. **Make `BaseTool` itself async.** Rejected for now: it would require rewriting every
   existing test and the `BaseAPIClient` call path, for no benefit at job granularity.
   Revisit if a future tool needs to await at the governance layer.
3. **Two base classes, `BaseTool` and `AsyncBaseTool`.** Deferred. If a second async
   tool appears, extract the shared pipeline then. Building it for one caller is
   speculative.

## Consequences

**Positive**

- The performance target becomes achievable; governance overhead is amortized to
  effectively zero per page.
- One approval per crawl is a sensible operator experience.
- `BaseTool` stays synchronous, so all 65 existing tests remain valid.

**Negative**

- `core` gains an async concern (`AsyncTokenBucket`) while `BaseTool` stays sync,
  which is an asymmetry a reader will notice. It must be documented at the module
  docstring level, explaining that governance is sync because it is per-job while
  politeness is async because it is per-request.
- A crawl that runs for minutes holds one audit record open. Job progress is therefore
  invisible to the audit log until completion. Crash recovery depends on
  `state_store.py`, which does not yet exist — until it does, an interrupted crawl
  loses its work.

**Follow-up**

- `AsyncTokenBucket` needs its own tests, including the cancellation path.
- The interaction with `state_store.py` checkpointing must be designed before any
  crawl longer than a few minutes is run in production.
