# ADR 0004: Local-workstation deployment first, ML layers behind an interface

- **Status**: Accepted
- **Date**: 2026-08-06
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`docs/TECH_STACK_SPECIFICATION.md` specifies the classification cascade as:

- **Layer 2**: `DeBERTa-v3-large-mnli` via ONNX Runtime on a local RTX 4070 Ti Super
  (16 GB VRAM), ~15 ms/page, $0.00.
- **Layer 3**: `Qwen 2.5 14B/32B` via vLLM or Ollama on the same GPU, with cloud
  Gemini as the ultimate fallback.

`docs/CLAUDE_HANDOFF_DIRECTIVE.md` §2 specifies deployment on **Railway.app** Docker
containers, and `AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md` Rule 5 caps worker
containers at **512 MB RAM**.

These cannot both hold. Railway containers have no GPU. A 14B-parameter model does not
fit in 512 MB of RAM, and DeBERTa-v3-large does not run at 15 ms/page on shared CPU.
The "$0.00 base compute" claim depends entirely on the local GPU existing.

## Decision

**Phase 1 targets the local workstation.** The RTX 4070 Ti Super is the reference
execution environment, and the $0.00 local-inference claim is honored there.

Layers 2 and 3 sit behind interfaces so a hosted deployment can substitute
implementations without touching the pipeline:

- **`ZeroShotClassifier`** — Layer 2. `LocalOnnxClassifier` (DeBERTa-v3 on GPU) now;
  a cloud implementation later.
- **`LLMClient`** — Layer 3. See ADR 0005.

The pipeline depends only on the interfaces. Selection happens in `Settings`, so the
same code runs locally and hosted with different configuration.

## Alternatives considered

1. **Target Railway immediately.** Rejected: forces Layer 2 to a paid cloud call,
   which eliminates the cost advantage that justifies the cascading architecture.
2. **Build both implementations now.** Rejected: roughly doubles Phase 1 scope and
   requires two independent accuracy test suites before either is proven.
3. **Drop Layer 2 entirely and cascade Layer 1 straight to the LLM.** Rejected: it
   raises LLM invocation from <2% toward 10%, multiplying cost per ADR 0005's analysis.

## Consequences

**Positive**

- The local GPU is already purchased; using it is free capacity.
- Local inference means no page content leaves the machine at Layer 2 — a genuine
  privacy advantage when auditing client sites.
- Ships faster than dual implementations.

**Negative**

- **Phase 1 is not deployable to `api.rankuno.com` as built.** Railway, Celery workers,
  and the FastAPI gateway described in the handoff directive are out of scope until a
  cloud `ZeroShotClassifier` exists. Documentation must not imply otherwise.
- The system has a hardware dependency. CI cannot run Layer 2 tests on GitHub Actions
  runners, so Layer 2 must be mocked in CI and validated locally against the golden
  corpus. This is a real coverage gap and must be stated in the test plan.
- Model weights are large binaries. `.gitignore` excludes `models/`, `*.onnx`,
  `*.safetensors`, `*.gguf`; a documented download/export step is required for
  reproducibility.

**Follow-up**

- Update `TECH_STACK_SPECIFICATION.md` and `CLAUDE_HANDOFF_DIRECTIVE.md` to state that
  Railway deployment is deferred, resolving the current contradiction.
- Decide whether Qwen 2.5 local is worth running at all given ADR 0005 selects a cloud
  model for Layer 3. Running both is likely redundant.
