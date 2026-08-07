# 🚀 Rankuno AI Engine — Master Standards & SDLC Governance Foundation

Welcome to the central **Master Standards, Governance, & Review Agent Foundation** for **Rankuno's AI Automation Infrastructure**.

This repository (`project-standards`) is dedicated to **0 ➔ 1 System Architecture, SDLC Governance Standards, Domain Engineering Protocols, and Automated Review Agent Personas**. All domain engines built in future phases inherit the rules established here.

---

## ⚡ Rankuno Agentic Platform Architecture

```
   ┌─────────────────────────────────────────────────────────────┐
   │                       MODEL / LLM                           │
   │               (Selected per project evaluation)             │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
   ┌──────────────────────────────▼──────────────────────────────┐
   │                   RANKUNO AI AGENT                          │
   │                 (Decision & Action Loop)                    │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
    ┌───────────────────┬─────────┴─────────┬───────────────────┐
    │                   │                   │                   │
    ▼                   ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────┐   ┌──────────────┐    ┌──────────────┐
│    SKILLS    │  │  SUBAGENTS   │   │    TOOLS     │    │  ARTIFACTS   │
│  ("How-To")  │  │ (Delegation) │   │  ("Can-Do")  │    │ ("Outputs")  │
├──────────────┤  ├──────────────┤   ├──────────────┤    ├──────────────┤
│ - SDLC Flow  │  │ - CodeReview │   │ - read_file  │    │ - Plans      │
│ - SEO Engine │  │ - Security   │   │ - write_file │    │ - Reports    │
│ - GSC / GA4  │  │ - SEO Audit  │   │ - run_cmd    │    │ - Diagrams   │
│ - Google Ads │  │ - PPC Audit  │   │ - grep_search│    │ - Schemas    │
│ - AEO / GEO  │  │ - AEO Audit  │   │              │    │              │
└──────────────┘  └──────────────┘   └──────────────┘    └──────────────┘
                                  │
   ┌──────────────────────────────▼──────────────────────────────┐
   │                   GUARDRAILS & PERMISSIONS                  │
   │      (HITL Approvals, API Cost Limiters, Access Rules)      │
   └─────────────────────────────────────────────────────────────┘
```

---

## 📚 Exhaustive 8-Step SDLC Standards

Every software module or engine built across Rankuno microservices MUST follow the binding standards in `docs/standards/`:

1. 🔍 **Step 1**: [SDLC Step 1: Investigation & Requirement Discovery Standard](docs/standards/SDLC_STEP1_INVESTIGATION_STANDARD.md)
2. 📐 **Step 2**: [SDLC Step 2: System Architecture & Data Schema Standard](docs/standards/SDLC_STEP2_ARCHITECTURE_SCHEMA_STANDARD.md)
3. 🛡️ **Step 3**: [SDLC Step 3: HITL Architecture Review Checkpoint Standard](docs/standards/SDLC_STEP3_HITL_REVIEW_STANDARD.md)
4. 📝 **Step 4**: [SDLC Step 4: Implementation Plan Standard](docs/standards/SDLC_STEP4_IMPLEMENTATION_PLAN_STANDARD.md)
5. 🔐 **Step 5**: [SDLC Step 5: Security, Rate-Limit & Financial Audit Standard](docs/standards/SDLC_STEP5_SECURITY_FINANCIAL_AUDIT_STANDARD.md)
6. 💻 **Step 6**: [SDLC Step 6: Step-by-Step Modular Implementation Standard](docs/standards/SDLC_STEP6_MODULAR_CODING_STANDARD.md)
7. 🧪 **Step 7**: [SDLC Step 7: Automated Verification & Testing Standard](docs/standards/SDLC_STEP7_AUTOMATED_TESTING_STANDARD.md)
8. 📚 **Step 8**: [SDLC Step 8: README & Architecture Drift Audit Standard](docs/standards/SDLC_STEP8_README_DRIFT_AUDIT_STANDARD.md)

---

## 🤖 Domain Engineering & Review Agent Skills

Procedural skills in `skills/` equipping subagents and review agents with domain rules:

* ⚡ **SDLC Execution Flow**: [Antigravity 8-Step SDLC Protocol](skills/antigravity-sdlc-flow/SKILL.md)
* 🔍 **SEO Domain Reference**: [SEO Engine & Domain Engineering Guide](skills/seo-engine-guide/SKILL.md)
* 📐 **Data Contracts**: [Pydantic v2 Schema Design Standards](skills/pydantic-schema-design/SKILL.md)
* 🤖 **Code Quality Review**: [Code Reviewer Agent Protocol](skills/code-reviewer-agent/SKILL.md)
* 🧩 **Delegation**: [Subagent Orchestration Protocol](skills/subagent-orchestrator/SKILL.md)

> **Planned, not yet written**: GSC/GA4 analytics, Google Ads policy, SEO scraping
> audit, and AEO/GEO visibility skills. They are listed here rather than linked,
> because `SDLC_STEP8` §2.1 forbids presenting unbuilt capabilities as working.

---

## 📄 Master Specifications & Directives

* 🤖 **Agent Operating Instructions**: [CLAUDE.md](CLAUDE.md) — binding rules, contradiction rulings, known gaps
* 🏗️ **System Architecture**: [ARCHITECTURE.md](docs/ARCHITECTURE.md)
* 📚 **Architecture Decision Records**: [docs/adr/](docs/adr/)
* 📓 **Build Log** — what shipped each cycle, why, and what broke: [docs/build-log/](docs/build-log/README.md)
* ⚡ **Tech Stack & Cost-Optimization**: [TECH_STACK_SPECIFICATION.md](docs/TECH_STACK_SPECIFICATION.md)
* 📐 **Phase 1 Page Classification Blueprint**: [PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md](docs/PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md)
* 🛒 **Amazon-Scale E-Commerce Crawling Strategy**: [AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md](docs/AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md)
* 🌳 **Interactive Tree Visualizer Specification**: [TREE_VISUALIZER_SPECIFICATION.md](docs/TREE_VISUALIZER_SPECIFICATION.md)
* 🌐 **HighRadius Crawl & 3-Path Discovery Record**: [HIGHRADIUS_CRAWL_AUDIT_RECORD.md](docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md)
* 🤖 **Phase 7 AI Answer Visibility Blueprint**: [PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md](docs/PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md)
* 📋 **Master System Context & Handoff Directive**: [CLAUDE_HANDOFF_DIRECTIVE.md](docs/CLAUDE_HANDOFF_DIRECTIVE.md)
* 📄 **Master Engineering, SDLC & DevOps Standard**: [MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md](docs/MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md)

---

## 🚦 Current Implementation Status

Honest state of the codebase. See [CLAUDE.md](CLAUDE.md) §8 for the full gap register.

| Component | Status |
| :--- | :--- |
| `core/` governed pipeline, guardrails, rate limiting, retry, registry | ✅ Implemented & tested |
| `core/url_safety.py` — SSRF guard | ✅ Implemented & tested |
| `core/robots.py` — robots.txt & crawl-delay (RFC 9309) | ✅ Implemented & tested |
| `core/rate_limiter.py` — `AsyncTokenBucket` for in-crawl politeness | ✅ Implemented & tested |
| `integrations/http_fetcher.py` — SSRF/robots-enforced fetcher, sync + async | ✅ Implemented & tested |
| `page_classifier/site_profile.py` — runtime platform detection | ✅ Implemented & tested |
| `page_classifier/discovery.py` — 3-path merged discovery → `PageEvidence` | ✅ Implemented & tested |
| `page_classifier/async_discovery.py` — concurrent crawl path | ✅ Implemented & tested |
| `page_classifier/tree_visualizer.py` — standalone interactive HTML report | ✅ Implemented & tested |
| `page_classifier/tool.py` — **governed entry point**, one run = one crawl job | ✅ Implemented & tested |
| `integrations/llm_client.py` — provider-agnostic LLM interface | ✅ Interface only; no concrete provider yet |
| `modules/seo/page_classifier/schemas.py` — Phase 1 taxonomy | ✅ Implemented & tested |
| `page_classifier/url_rules.py` — Layer 0 normalisation & pre-fetch rules | ✅ Implemented & tested |
| `page_classifier/signal_parsers.py` — 5 structural consensus signals | ✅ Implemented & tested |
| `page_classifier/cascading_pipeline.py` — Layer 0–3 cascade & consensus | ✅ Implemented & tested |
| `page_classifier/weights.py` — weight profiles & site-profile seam | ✅ Seam live; adaptive selection off pending corpus |
| Layer 2 local ML classifier | ❌ Protocol only; needs local GPU ([ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Layer 3 `LlmPageClassifier` implementation | ❌ Protocol only; needs a live credential |
| `core/circuit_breaker.py`, `core/state_store.py` | ❌ Not started |
| Idempotency keys; distributed rate limit & spend ceiling | ❌ Not started |
| `Dockerfile` / Railway deployment | ❌ Not started (deferred — see [ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |

### Running a crawl

```powershell
.\.venv\Scripts\python.exe scripts\run_crawl.py https://example.com
.\.venv\Scripts\python.exe scripts\run_crawl.py https://example.com --max-pages 250 --depth 2
```

Defaults are deliberately conservative (50 pages, depth 1, concurrency 3) — this
crawls somebody else's server. Writes a self-contained interactive HTML report.

> **Validated against a live site.** See
> [build-log/0007](docs/build-log/0007-first-live-run.md) for the first real run,
> including two specification-versus-reality findings that need decisions:
> Path A starves Path B on large sites, and the observed LLM escalation rate is
> ~50x the assumption in ADR 0005.

### Verification

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1   # SDLC Step 7 quality gate
.\.venv\Scripts\python.exe scripts\drift_check.py               # SDLC Step 8 drift audit
```

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
