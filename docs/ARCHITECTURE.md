# 🏗️ Rankuno AI Automation Platform - System Architecture & Standard Index

> **Document ID**: `RKN-ARCH-2026-V1`  
> **Status**: Binding Architecture Specification  
> **Repository Role**: Master Standards & SDLC Governance Foundation  

---

## 1. Executive Summary

This repository (`project-standards`) serves as the **Master Governance & SDLC Rules Foundation** for Rankuno's AI Automation Infrastructure. All subagents, review agents, SDLC standards, data contract conventions, and domain engineering rules are defined here and inherited by every domain engine repository built in future phases.

---

## 2. Inward-Only Dependency Rule

The platform architecture enforces an immutable inward-only dependency flow across all modules and subagents:

$$\text{modules} \longrightarrow \text{integrations} \longrightarrow \text{core}$$

**Implemented** — this tree reflects files that exist today. Planned modules are listed
separately below, per `SDLC_STEP8` §2.1 (documentation describes verified state only).

```
src/
├── core/                        # Domain-agnostic agentic infrastructure
│   ├── base_tool.py             # Governed execution pipeline (7 of 10 steps — see below)
│   ├── schemas.py               # StrictModel, RiskClass, ToolMetadata, ToolResult
│   ├── config.py                # Typed Settings singleton (ONLY os.environ reader)
│   ├── logger.py                # Structured JSON audit logging + trace context
│   ├── errors.py                # RankunoError exception hierarchy
│   ├── guardrails.py            # HITL policy engine (deny-by-default)
│   ├── rate_limiter.py          # TokenBucket + AsyncTokenBucket + CostLedger
│   ├── registry.py              # Tool catalogue & risk-surface audit
│   ├── retry.py                 # Exponential backoff with jitter (tenacity)
│   ├── url_safety.py            # SSRF guard: private-range blocker, scheme allowlist
│   └── robots.py                # robots.txt & crawl-delay parsing (RFC 9309)
├── integrations/                # External API wrappers
│   ├── base_client.py           # Quota, retry, credential handling for all connectors
│   ├── http_fetcher.py          # The ONLY outbound web fetcher. Enforces SSRF,
│   │                            # robots, per-host throttling. Sync + async.
│   └── llm_client.py            # Provider-agnostic LLM interface + spend metering
└── modules/                     # Domain engines
    ├── seo/
    │   └── page_classifier/     # Phase 1 engine
    │       ├── schemas.py            # FullPageIntelligenceProfile + taxonomy
    │       ├── weights.py            # Weight profiles + site-profile seam
    │       ├── site_profile.py       # Runtime platform detection (probe pass)
    │       ├── url_rules.py          # Layer 0 normalisation, pre-fetch rules
    │       ├── signal_parsers.py     # The 5 structural consensus signals
    │       └── cascading_pipeline.py # Layer 0-3 cascade + weighted consensus
    ├── ppc/                     # Reserved namespace, no implementation
    └── research/                # Reserved namespace, no implementation
```

**Planned, not yet implemented** (do not describe these as working):

| Path | Purpose |
| :--- | :--- |
| `core/circuit_breaker.py` | Upstream `CLOSED → OPEN → HALF-OPEN` state machine |
| `core/state_store.py` | Redis/Postgres checkpointing for crash recovery |
| `modules/seo/page_classifier/tool.py` | `BaseTool` entry point (one call = one crawl job) |
| `modules/seo/page_classifier/discovery.py` | 3-path merged URL discovery producing `PageEvidence` |
| A Layer 2 `ZeroShotClassifier` implementation | Protocol exists; local ONNX model does not |
| `modules/seo/page_classifier/tree_visualizer.py` | Standalone interactive HTML site tree |
| `modules/answer_visibility/` | Phase 7 AI Answer Visibility Engine (AEO & GEO) |

> **Pipeline status**: `base_tool.py` implements 7 of the specified 10 steps. Idempotency
> key validation, circuit breaker checks, and state checkpointing are **not** implemented.
> See [CLAUDE.md](../CLAUDE.md) §7 ruling 2 and §8.

---

## 3. SDLC 8-Step Standards Index

Every code change across Rankuno microservices MUST follow the 8-Step SDLC loop specified in `docs/standards/`:

1. 🔍 **Step 1**: [SDLC Step 1: Investigation & Requirement Discovery Standard](standards/SDLC_STEP1_INVESTIGATION_STANDARD.md)
2. 📐 **Step 2**: [SDLC Step 2: System Architecture & Data Schema Standard](standards/SDLC_STEP2_ARCHITECTURE_SCHEMA_STANDARD.md)
3. 🛡️ **Step 3**: [SDLC Step 3: HITL Architecture Review Checkpoint Standard](standards/SDLC_STEP3_HITL_REVIEW_STANDARD.md)
4. 📝 **Step 4**: [SDLC Step 4: Implementation Plan Standard](standards/SDLC_STEP4_IMPLEMENTATION_PLAN_STANDARD.md)
5. 🔐 **Step 5**: [SDLC Step 5: Security, Rate-Limit & Financial Audit Standard](standards/SDLC_STEP5_SECURITY_FINANCIAL_AUDIT_STANDARD.md)
6. 💻 **Step 6**: [SDLC Step 6: Step-by-Step Modular Implementation Standard](standards/SDLC_STEP6_MODULAR_CODING_STANDARD.md)
7. 🧪 **Step 7**: [SDLC Step 7: Automated Verification & Testing Standard](standards/SDLC_STEP7_AUTOMATED_TESTING_STANDARD.md)
8. 📚 **Step 8**: [SDLC Step 8: README & Architecture Drift Audit Standard](standards/SDLC_STEP8_README_DRIFT_AUDIT_STANDARD.md)

---

## 4. Specialized Domain & Review Agent Skills Index

Procedural skills in `skills/` equipping subagents and review agents with domain rules:

- ⚡ **SDLC Execution Flow**: [Antigravity 8-Step SDLC Protocol](../skills/antigravity-sdlc-flow/SKILL.md)
- 🔍 **SEO Domain Reference**: [SEO Engine & Domain Engineering Guide](../skills/seo-engine-guide/SKILL.md)
- 📐 **Data Contracts**: [Pydantic v2 Schema Design Standards](../skills/pydantic-schema-design/SKILL.md)
- 🤖 **Code Quality & PR Review**: [Code Reviewer Agent Protocol](../skills/code-reviewer-agent/SKILL.md)
- 🧩 **Delegation**: [Subagent Orchestration Protocol](../skills/subagent-orchestrator/SKILL.md)

Planned but not yet written: GSC/GA4 analytics, Google Ads policy, SEO scraping audit,
and AEO/GEO visibility skills.

---

## 5. Architecture Decision Records

Consequential decisions are recorded in [adr/](adr/):

| ADR | Decision |
| :--- | :--- |
| [0001](adr/0001-scale-target-and-deferred-100m-path.md) | Build for 20k–500k URLs; defer the 100M path behind interfaces |
| [0002](adr/0002-canonical-phase1-output-contract.md) | `FullPageIntelligenceProfile` is the canonical Phase 1 output |
| [0003](adr/0003-job-level-governance-and-async-internals.md) | One `BaseTool.run()` is one crawl job, not one page |
| [0004](adr/0004-local-first-deployment-swappable-ml-layer.md) | Local-workstation deployment first; ML layers behind interfaces |
| [0005](adr/0005-llm-provider-strategy-and-cost-metering.md) | Provider-agnostic `LLMClient`; per-call spend metering |
| [0006](adr/0006-weight-profile-seam-and-runtime-site-detection.md) | Signal weights vary by runtime-detected site profile, behind a seam |

---

## 6. Master Engineering Specifications & Blueprints

- 🤖 **Agent Operating Instructions**: [CLAUDE.md](../CLAUDE.md)
- 📓 **Build Log** — per-cycle implementation records: [build-log/](build-log/README.md)
- ⚡ **Tech Stack & Cost-Optimization Specification**: [TECH_STACK_SPECIFICATION.md](TECH_STACK_SPECIFICATION.md)
- 🛒 **Amazon-Scale E-Commerce Crawling Strategy**: [AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md](AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md)
- 🌳 **Interactive Multi-Level Tree Visualizer Specification**: [TREE_VISUALIZER_SPECIFICATION.md](TREE_VISUALIZER_SPECIFICATION.md)
- 📋 **Master System Context & Handoff Directive**: [CLAUDE_HANDOFF_DIRECTIVE.md](CLAUDE_HANDOFF_DIRECTIVE.md)
- 🌐 **HighRadius Crawl & 3-Path Discovery Record**: [HIGHRADIUS_CRAWL_AUDIT_RECORD.md](HIGHRADIUS_CRAWL_AUDIT_RECORD.md)
- 📄 **Master Engineering, SDLC & DevOps Standard**: [MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md](MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md)
- 📄 **Phase 1 Page Classification Blueprint**: [PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md](PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md)
- 📄 **Phase 7 AI Answer Visibility Blueprint**: [PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md](PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md)

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
