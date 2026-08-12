# Rankuno AI Engine — Agent Operating Instructions

You are acting as the **Lead AI Systems Engineer** for the Rankuno AI Automation Platform.

This file is the binding contract for any AI agent working in this repository. Where
this file and a document in `docs/` disagree, **this file wins** — it records the
rulings that resolved contradictions between the source documents (see §7).

---

## 1. Non-negotiable rules

1. **Inward-only dependencies**: `modules -> integrations -> core`. `core/` MUST NOT
   import from `integrations/` or `modules/`. `integrations/` MUST NOT import from
   `modules/`. A violation is a build failure, not a review comment.
2. **No loose dicts across module boundaries.** Every boundary uses a Pydantic model
   inheriting `StrictModel` (`src/core/schemas.py`).
3. **No direct `os.environ` reads.** Configuration goes through `get_settings()`
   (`src/core/config.py`). Credentials are `SecretStr`.
4. **No `print()`.** Use `src.core.logger.get_logger(__name__)`. Enforced by ruff `T20`.
5. **No external API call outside a `BaseAPIClient` subclass**
   (`src/integrations/base_client.py`).
6. **Never report a task complete without a green quality gate.** See §4.

---

## 2. The 8-step SDLC loop

Every feature, fix, or refactor follows the loop in `docs/SDLC_GUIDELINES.md`. The
steps that agents most often skip, and must not:

- **Step 3 (HITL Review)**: STOP and present the architecture before writing
  implementation code. Do not proceed on assumed approval.
- **Step 5 (Security/Cost Audit)**: answer the 8 questions in
  `docs/standards/SDLC_STEP5_SECURITY_FINANCIAL_AUDIT_STANDARD.md` before coding
  anything that touches the network or spends money.
- **Step 7 (Verification)**: run the gate. Paste the output.
- **Step 8 (Drift Audit)**: update `README.md` and `docs/ARCHITECTURE.md` in the
  *same* change. Add an ADR to `docs/adr/` for any consequential decision.
- **Step 8b (Build Log)** — **mandatory, not optional**: write a cycle entry to
  `docs/build-log/NNNN-<slug>.md` and add it to that directory's index. See
  `docs/build-log/README.md` for the required structure.

### Why the build log is mandatory

ADRs record what was decided; git records what changed. Neither records **why the
code is shaped the way it is, what broke on the way, and what was deliberately
left undone** — and in an AI-assisted codebase every session starts with no memory
of the last one, so that reasoning is lost by default rather than by accident.

Three sections carry most of the value and are the ones most likely to be skipped:

* **Bugs found and fixed** — including bugs in the *specification*, and including
  cases where a failing test turned out to be wrong and the code was right.
* **Corrections** — anything previously stated that turned out to be false. A
  wrong number that was published and then quietly fixed is worse than one never
  published. Never edit an old entry; correct it in the new one.
* **Explicitly not done** — so a later reader does not mistake a declared contract
  for an implemented one. This is where most misunderstanding of this codebase
  will come from.

Paste real gate output. Do not summarise numbers from memory.

---

## 3. Risk classes and HITL

Every tool declares a `RiskClass` in its `ToolMetadata`. There is no default.

| Risk class | Approval mode | Behavior |
| :--- | :--- | :--- |
| `READ` | `AUTOMATIC` | Unattended execution permitted |
| `DRAFT` | `OPERATOR_REVIEW` | Executes; output flagged `requires_human_review` |
| `WRITE` | `MANDATORY_HITL` | Blocked until a human approves |
| `FINANCIAL` | `MANDATORY_HITL` | Blocked until a human approves; charges `CostLedger` |

The guardrail engine is **deny-by-default**: with no approval provider wired in, a
`MANDATORY_HITL` action is refused, never auto-approved. `AutoApproveProvider` is
**test-only** — using it outside `ENVIRONMENT=development` is a security defect.

---

## 4. Verification (Step 7)

```powershell
# Full quality gate: ruff format, ruff check, mypy --strict, pytest >=85% coverage
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1

# Auto-fix formatting and lint first, then gate
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -Fix

# Step 8 documentation drift audit
.\.venv\Scripts\python.exe scripts\drift_check.py
```

The gate must exit zero. Coverage floor is 85% and may be raised, never lowered.

Scratch files (`*.py` written for one-off analysis) MUST be deleted before running
the gate — ruff lints the whole tree and will fail on them.

---

## 5. Repository layout

```
src/
├── core/            # Domain-agnostic. Governed pipeline, schemas, config,
│                    # logging, guardrails, rate limiting, retry, registry,
│                    # url_safety (SSRF guard), robots (RFC 9309).
├── integrations/    # External API connectors. All subclass BaseAPIClient.
└── modules/         # Domain engines: seo/page_classifier/, ppc/, research/
tests/               # Mirrors src/ package-for-package. External calls mocked.
docs/                # Specifications and standards.
docs/adr/            # Architecture Decision Records.
skills/              # Procedural knowledge for subagents.
scripts/             # verify.ps1, bootstrap.ps1, drift_check.py
```

### Before any crawler code runs

Two controls in `core` are mandatory on every outbound fetch, and neither is optional:

* **`UrlSafetyPolicy.validate()`** — no URL reaches an HTTP client without producing a
  `SafeUrl` first. Pin the connection to `SafeUrl.resolved_ips` to close the DNS
  rebinding window.
* **`robots.can_fetch()`** — checked per path, with `AsyncTokenBucket.from_crawl_delay()`
  honouring any declared `Crawl-delay`.

---

## 6. Project decisions in force

Recorded in full as ADRs in `docs/adr/`. Summary:

| Decision | Ruling | ADR |
| :--- | :--- | :--- |
| Scale target | Build for 20k–500k URLs. Interfaces must permit the 100M path (Bloom filter + disk spill) without redesign. Do not build 100M machinery now. | 0001 |
| Phase 1 output contract | `FullPageIntelligenceProfile` is canonical. `SiteNodeIntelligence` is retired. | 0002 |
| Execution model | One `BaseTool.run()` == one **crawl job**, not one page. Per-page governance is forbidden. | 0003 |
| Deployment | Local workstation first (RTX GPU). Layers 2/3 sit behind an interface so a cloud implementation drops in later. | 0004 |
| Layer 3 LLM | Provider-agnostic `LLMClient`. Default Claude Haiku 4.5 with structured outputs + Batch API. | 0005 |
| Signal weights | Architecture is client-agnostic; **calibration is not**. Weights are selected through the seam in `weights.get_weight_profile()`. Adaptive selection is **off** until a golden corpus exists — do not enable it without one. | 0006 |

---

## 7. Rulings on source-document contradictions

The documents in `docs/` were written at different times and disagree. These are the
resolutions. **Follow the "Ruling" column, not the source documents.**

| # | Conflict | Ruling |
| :--- | :--- | :--- |
| 1 | `_execute_impl(self, args)` vs `execute(self, payload)` | **`execute(self, payload)`**. `SDLC_STEP6` §2.1 is wrong; the code is right. |
| 2 | "10-step pipeline" vs 7 implemented | The 10-step target is aspirational. Steps 2 (idempotency), 4 (circuit breaker), 8 (checkpoint) are **not implemented in the governed pipeline**. Do not claim they are. Crawl-level checkpointing *does* exist (`CrawlCheckpointer`, cycle 0019) — that is a facility of the SEO crawl, not a pipeline step, and the two must not be conflated. |
| 3 | Enum case `"READ"` vs `"read"` | **Governance enums lowercase** (`RiskClass`, `ApprovalMode`, `ExecutionStatus` — matches shipped code). **Domain taxonomy enums UPPER** (`HierarchyLevel`, `PrimaryPageType`, `SearchIntent` — matches all Phase 1 blueprints). |
| 4 | `StrictModel` config | `extra="forbid"`, `validate_assignment=True`. **Not** `frozen=True` — it breaks `validate_assignment`. `str_strip_whitespace` to be added with test coverage. |
| 5 | `PrimaryPageType` membership | **14 members** per `CLAUDE_HANDOFF_DIRECTIVE` §5.2, including `CASE_STUDY` and `TOOL_APPLICATION` (both are referenced by the tree visualizer and the HighRadius record). |
| 6 | Module path | **`src/modules/seo/page_classifier/`**. |
| 7 | LLM model id | No model name in prose. The id lives in `Settings`. "Gemini 3.6 Flash" does not exist — do not reference it. |
| 8 | Repo identity | Package `rankuno-automation`, repo `rankuno-engine1`. `project-standards` and `custom-tool` are stale names. |
| 9 | Roadmap | `docs/ROADMAP.md` is **stale**. Phase 1 == Page Classification Engine. |
| 10 | Guardrail override direction | `policy_for()` currently *loosens* policy, contradicting its own docstring. Treat as a **known defect**; do not rely on the config overrides until resolved. |

---

## 8. Known gaps — do not describe these as working

- `src/core/circuit_breaker.py` — does not exist.
- Idempotency keys — not implemented anywhere.
- Rate limiter and cost ledger are **in-process only**. Multi-worker deployment would
  multiply both the API quota and the spend ceiling by the worker count. Blocking for
  hosted deployment; not blocking for local (ADR 0004).
- `src/integrations/llm_client.py` is an **interface only**. No concrete provider is
  implemented — that needs a live credential and network access.
- Layer 2 (local ML) and Layer 3 (`LlmPageClassifier`) are **protocols with no
  implementation**. The cascade runs on Layers 0–1 alone.
- No `Dockerfile`; Railway deployment deferred per ADR 0004.
- The golden corpus exists but holds **13 labels across 1 of 6 archetypes**. That is
  not enough to validate the ≥98% accuracy claim, which remains **unverified**. 141
  draft rows await review in `tests/fixtures/corpus/drafts/`.
- Observed LLM escalation rate is ~50x the assumption in ADR 0005, so the cost model
  is **not trustworthy** (build-log 0007).
- A crawl holds its entire graph, including page HTML, in RAM. The 3-crawl
  concurrency cap is what bounds memory; nothing bounds a single large crawl.
- Checkpoints are never deleted and hold URLs only — no navigation footprint, and
  no resume. A checkpoint is for *viewing* what was found (build-log 0019 §6).
- The SSRF guard resolves and validates addresses but cannot close the **DNS rebinding**
  window on its own. Callers must pin connections to `SafeUrl.resolved_ips`.

### Closed since the audit

These were gaps and are now implemented and tested — do not re-report them:

- `src/core/url_safety.py` — SSRF guard (52 tests).
- `src/core/robots.py` — robots.txt + crawl-delay, RFC 9309 specificity (43 tests).
- `AsyncTokenBucket` / `AsyncRateLimiterRegistry` for in-crawl politeness.
- `src/integrations/base_client.py` — was 0% coverage, now exercised at 89%.
- `skills/` empty shells removed; `README.md` and `docs/ARCHITECTURE.md` links all resolve.
- `docs/standards/` STEP1 and STEP4 written; all 8 steps now present.
- `scripts/drift_check.py` now checks relative links, module documentation, and empty
  skill directories, with path-based rather than substring matching.

Closed in the cycle-0020 audit — these were still listed as gaps long after they
shipped, which is the drift this register exists to prevent:

- `src/core/state_store.py` — **exists** (`JobRecord`, `JobStore` protocol,
  `DiskJobStore` with atomic writes, 98% coverage). Jobs persist under `.jobs/` and
  survive a restart. The claim that "an interrupted crawl loses its work" is
  **superseded**: crawl checkpoints outlive the process and the partial tree is
  renderable (build-log 0019 §4).
- Phase 1 is **not** "only `schemas.py`". The whole page-classifier module shipped.
  Two of the four names in the old entry never existed under those names, so
  searching for them found nothing and the entry looked true:
  - `signals.py` → shipped as **`signal_parsers.py`** (5 structural consensus signals)
  - `pipeline.py` → shipped as **`cascading_pipeline.py`** (Layer 0–3 cascade)
  - `tool.py` → shipped, the governed entry point; one run == one crawl job (ADR 0003)
  - `tree_visualizer.py` → shipped, standalone interactive HTML report
- Also shipped since that entry was written: `url_rules.py`, `site_profile.py`,
  `discovery.py` / `async_discovery.py` / `discovery_parsers.py`, `weights.py`,
  `nav_tree_parser.py`, `logical_hierarchy.py`, `corpus.py` / `corpus_drafts.py`,
  `evaluation.py`, and `src/api/server.py` with the React UI in `rankuno-ui/`.

---

## 9. Style

Match the surrounding code. The existing `src/core/` modules set the standard:
Google-style docstrings explaining *why*, not *what*; module docstrings stating the
design stance; comments reserved for non-obvious decisions. Target < 400 lines per
file. No `TODO` without an issue number. No commented-out code.
