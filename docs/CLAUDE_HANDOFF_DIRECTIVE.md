# 📋 Master System Context & Handoff Directive for Claude Code

> **Document ID**: `RKN-CLAUDE-HANDOFF-2026-V1.0`  
> **Master Standards Reference**: `RKN-STD-2026-V1.1`  
> **Repository Name**: `rankuno-engine1`  
> **Role**: Lead AI Systems Engineer / Subagent for Rankuno AI Automation Infrastructure  

---

## 1. Executive Vision & Core Strategic Mission

The **Rankuno AI Automation Platform** is a 0-to-1 enterprise-grade automation infrastructure designed for digital marketing operations, SEO auditing, content classification, PPC campaign management, and market research.

### Core Strategic Pillars
- **10x Scale without Overhead**: Automate technical SEO audits, page classifications (10k–20k pages in 15–30s), and SERP intelligence.
- **Zero-Legacy Architecture**: Strictly-typed Python micro-modules with zero technical debt from Day 1.
- **Human-in-the-Loop (HITL) Guardrails**: Enforced human approval for any live system mutation, publishing, ad budget modification, or database write.

---

## 2. Master Infrastructure Accounts & Environment Record (`RKN-REC-2026-V1`)

- **Primary Account Email**: `Rankunoai@gmail.com`
- **GitHub Organization**: `rankunoai-dev` (Private Repository: `custom-tool`)
- **Git Merge Strategy**: **Squash-Merge Only ENFORCED** (Linear history on main, merge commits banned).
- **Relational Database**: Supabase (`rankuno-db`) — PostgreSQL (Region: Mumbai `ap-south-1`).
- **Task Queue & Caching**: Upstash (`rankuno-redis`) — Serverless Redis (Region: Mumbai `ap-south-1`).
- **Container Runner**: Railway.app — Docker FastAPI Gateway & Celery Worker runner.
- **Observability & APM**: Sentry (`rankuno-platform`) — Python Error Telemetry & APM Sentinel.
- **Domain & DNS**:
  - Main Website: `https://rankuno.com/` (Stays 100% untouched and safe).
  - Domain Registrar & DNS: GoDaddy (`ns37.domaincontrol.com`, `ns38.domaincontrol.com`).
  - Target Subdomains: `api.rankuno.com` (Railway API Gateway) and `app.rankuno.com` (Operator Dashboard UI).

---

## 3. Codebase Topology & Architectural Rules

### 3.1 The Inward-Only Dependency Rule

$$\text{modules} \longrightarrow \text{integrations} \longrightarrow \text{core}$$

- `core/`: Domain-agnostic agentic infrastructure (governed pipeline, schemas, logger, rate limiters, circuit breakers).
- `integrations/`: Third-party API wrappers (GSC, GA4, Google Ads, Chatmeter, SERP APIs, LLM clients).
- `modules/`: Domain-specific business logic (Page Classification, Technical SEO Audit, PPC Engine).

> **Rule**: `core` NEVER imports from `integrations` or `modules`. A violation is an immediate build failure.

### 3.2 Strict Data Contracts
All data models across the codebase MUST inherit `StrictModel` (`extra="forbid"`, `validate_assignment=True`):

```python
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )
```

---

## 4. Governed Execution Pipeline & Risk Governance Matrix

### 4.1 Governed 10-Step Lifecycle (`BaseTool`)

```
Raw Input ➔ ① Validate Input ➔ ② Check Idempotency Key (UUIDv4) ➔ ③ HITL Policy Check ➔ ④ Circuit Breaker Check ➔ ⑤ Rate Limit Check ➔ ⑥ Charge Budget ➔ ⑦ execute() ➔ ⑧ Checkpoint State ➔ ⑨ Validate Output ➔ ⑩ Audit Log ➔ ToolResult[T]
```

### 4.2 Risk Governance Matrix

| Risk Class | Approval Mode | Execution Behavior |
| :--- | :--- | :--- |
| **`READ`** | `AUTOMATIC` | Unattended execution permitted |
| **`DRAFT`** | `OPERATOR_REVIEW` | Executes, flagged for human review |
| **`WRITE`** | `MANDATORY_HITL` | Blocked until explicit human approval + UUIDv4 `idempotency_key` |
| **`FINANCIAL`** | `MANDATORY_HITL` | Blocked until human approval + `CostLedger` deduction + UUIDv4 `idempotency_key` |

---

## 5. Phase 1 Architecture: Page Classification & Intent Analysis Engine

### 5.1 Performance Benchmark
- **Throughput**: Process 10,000 to 20,000+ pages in 15–30 seconds.
- **Accuracy**: $\ge 98\%$ classification accuracy.
- **Cost**: **$0.00 base cost** for $\ge 98\%$ of standard pages.
- **Zero Ambiguity**: Zero unclassified (`UNKNOWN`) pages.

### 5.2 Decoupled Two-Tier Taxonomy Matrix
Separates Structural Position in site graph from Functional Page Purpose:

#### `HierarchyLevel` (Structural Position)
- `L0_HOMEPAGE`: Root entry point (`/`).
- `L1_PRIMARY_NAV_HUB`: Primary section hub (`/services/`, `/products/`, `/blog/`).
- `L2_SUB_NAV_HUB`: Intermediate sub-category hub (`/services/cloud/`). Handles arbitrary nesting depths (Depths 2 to 9) using bounded mapping + `depth_index` metadata (0–15).
- `L3_LEAF_PAGE`: Terminal content node (SKU, article, service detail page).
- `UTILITY_PAGE`: Supporting auxiliary pages (Legal privacy, search results, faceted filters `?color=red`, 404s).

#### `PrimaryPageType` (Functional Purpose)
- `HOMEPAGE`, `SERVICE_CATEGORY_HUB`, `SERVICE_DETAIL_PAGE`, `PRODUCT_CATEGORY_HUB`, `PRODUCT_DETAIL_PAGE`, `BLOG_HUB`, `BLOG_ARTICLE`, `COMPANY_ABOUT`, `COMMERCIAL_LEAD_GEN`, `FACETED_FILTER`, `UTILITY_LEGAL`, `CASE_STUDY`, `TOOL_APPLICATION`, `UNKNOWN`.

### 5.3 6-Signal Consensus Pipeline
1. **Signal 1 (ARIA Nav Tree)**: Parses `<nav role="navigation">` to solve mobile hamburger hidden menus. (Weight: 0.25)
2. **Signal 2 (CMS Endpoints)**: Queries `/wp-json/` and Shopify `/products.json` to resolve flat URLs (e.g. `site.com/custom-formulation`) via database parent IDs. (Weight: 0.30)
3. **Signal 3 (XML Sitemap Index)**: Reads sitemap taxonomy (`product-sitemap.xml`). (Weight: 0.20)
4. **Signal 4 (Schema.org JSON-LD)**: Extracts `@type` definitions (`Product`, `Service`, `Article`). (Weight: 0.15)
5. **Signal 5 (Link In-Degree Centrality)**: Calculates inbound links across graph $G=(V,E)$ ($\ge 1,000$ links $\rightarrow$ L1 Hub). (Weight: 0.10)
6. **Signal 6 (Governed LLM Fallback)**: Invoked ONLY if combined confidence score $C < 0.85$.

### 5.6 RAG 300-Token Chunking & Citation Optimization (Phase 1 & Phase 7)
- AI Search retrievers (Gemini, ChatGPT Search, Perplexity) split web content into 250 to 400 token chunks.
- **The Chunking Trap**: If a claim lives in Chunk A and supporting data lives in Chunk B, retrievers pull Chunk A without Chunk B, failing citation.
- **Rankuno Solution**:
  - Phase 1 evaluates 300-token chunk boundaries for orphaned pronouns ("it", "this") and claim/evidence distance.
  - Phase 7 automatically restructures content chunks: moves evidence next to claims, replaces orphaned pronouns with explicit brand entity names, and adds H2/H3 subheadings before claims.

### 5.7 3-Path Merged Discovery Pipeline & Empirical Validation
- XML Sitemaps alone miss URLs (PPC targets, corporate compliance, dynamic parameter filters, CMS drift).
- Empirical test on `highradius.com`: 3,145 Sitemap URLs vs. DOM Link Graph uncovered compliance/governance pages omitted from sitemaps (`/anti-corruption-and-bribery-policy/`, `/code-of-ethics/`, `/human-rights-policy/`, `/glossary/`).
- **Rankuno Solution**: Merges Path A (Sitemap XML) + Path B (Recursive HTML DOM Graph Crawler $G=(V,E)$) + Path C (CMS Database REST APIs) to guarantee 100% full URL discovery (documented in [docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md](HIGHRADIUS_CRAWL_AUDIT_RECORD.md)).

### 5.8 Ultra-Large E-Commerce Scale Crawling Strategy (Amazon-Scale)
- **5 Mega-Threats**: Faceted parameter explosion, tracking traps, RAM exhaustion (OOM), anti-bot IP blocks, infinite pagination traps.
- **6 Rules**: Layer 0 Parameter Normalizer, Scalable Bloom Filter (100M URLs in < 120 MB RAM), SKU Variant Canonical Clustering, Parameter Ceiling (>5 params $\rightarrow$ `UTILITY_PAGE`/`FACETED_FILTER`), 500-URL Streaming Batch Pipeline with `gc.collect()`, Adaptive `TokenBucket` Rate Limiter with jitter (documented in [docs/AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md](AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md)).

### 5.9 Interactive Multi-Level Site Hierarchy Tree Report Generator
- `tree_visualizer.py` converts site graph $G=(V,E)$ into an interactive, standalone `.html` tree report.
- Features multi-level nested collapse/expand ($L0 \rightarrow L1 \rightarrow L2 \rightarrow L3 \rightarrow \text{UTILITY}$), dual-taxonomy badges (`HierarchyLevel` + color-coded `PrimaryPageType`), instant search filtering, node child URL count rollups, and JSON/CSV export (documented in [docs/TREE_VISUALIZER_SPECIFICATION.md](TREE_VISUALIZER_SPECIFICATION.md)).

---

## 6. Implementation Gap Register (Next Priority Tasks)

To bring the codebase to 100% compliance with `RKN-STD-2026-V1.1`:

1. **`src/core/circuit_breaker.py`**:
   - Implement `CircuitBreaker` state machine (`CLOSED` $\rightarrow$ `OPEN` $\rightarrow$ `HALF-OPEN`).
   - Track upstream failure counts ($\ge 5$ failures or elevated latency) and route to secondary fallback LLM providers.
2. **`src/core/state_store.py`**:
   - Task state checkpointing interface for Redis / PostgreSQL to enable seamless crash recovery.
3. **Pipeline Enforcement in `src/core/base_tool.py`**:
   - Wire `CircuitBreaker` and `state_store` into `base_tool.py` execution sequence.
   - Mandate `idempotency_key` (UUIDv4) validation on `WRITE` and `FINANCIAL` operations.
4. **Containerization & Sandbox Infrastructure**:
   - Multi-stage `Dockerfile` and `docker-compose.yml` defining sandboxed worker containers capped at 512 MB RAM.
5. **Phase 1 Page Classification Engine (`src/modules/seo/page_classifier/`)**:
   - Implement `schemas.py`, `signals.py`, `pipeline.py`, and `tool.py`.

---

## 7. Mandatory 8-Step SDLC Loop & Verification Commands

Every change MUST follow the 8-Step SDLC Loop:
1. Investigation & Requirement Discovery
2. System Architecture & Data Schemas
3. HITL Review Checkpoint
4. Reasoning-Driven Plan
5. Security, Cost & Rate Limit Audit
6. Modular Implementation
7. Automated Verification
8. README & Drift Audit

### Verification Commands (Run from Project Root)

```powershell
# Run full SDLC Step 7 quality gate suite (Format, Lint, MyPy strict typing, Pytest >=85% coverage)
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1

# Run SDLC Step 8 documentation drift audit
.\.venv\Scripts\python.exe scripts/drift_check.py

# Run Python inside project virtual environment
.\.venv\Scripts\python.exe -c "import pydantic, httpx, selectolax, trafilatura, playwright, torch, pytest, ruff, mypy; print('All key modules operational!')"
```

---

## 8. Handoff Execution Prompt for Claude Code

When starting execution with Claude Code, copy and paste the prompt below:

```text
You are acting as the Lead AI Systems Engineer for the Rankuno AI Automation Platform.

Key Directives:
1. Adhere strictly to the Master Engineering Standard (RKN-STD-2026-V1.1) and Handoff Directive (docs/CLAUDE_HANDOFF_DIRECTIVE.md).
2. Follow the 8-Step SDLC Loop for all changes. Never skip architecture planning or verification.
3. Obey the Inward-Only Dependency Rule: modules -> integrations -> core.
4. All data contracts must inherit StrictModel (extra="forbid", validate_assignment=True).
5. Require explicit human approval (HITL) for RiskClass.WRITE and RiskClass.FINANCIAL with UUIDv4 idempotency keys.
6. Before declaring any coding task complete, run `powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1` and ensure all quality gates pass zero-exit.
7. Maintain zero documentation drift: update docs/ARCHITECTURE.md and README.md alongside code changes, verified via `.\.venv\Scripts\python.exe scripts/drift_check.py`.

Current Focus:
Execute items from the Implementation Gap Register (CircuitBreaker in src/core/circuit_breaker.py, StateStore in src/core/state_store.py, base_tool.py pipeline enforcement, or Phase 1 Page Classification in src/modules/seo/page_classifier/).
```
