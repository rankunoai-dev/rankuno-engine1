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
| `page_classifier/corpus.py` + `evaluation.py` — golden corpus & accuracy harness | ✅ Implemented & tested |
| `page_classifier/tool.py` — **governed entry point**, one run = one crawl job | ✅ Implemented & tested |
| `integrations/llm_client.py` — provider-agnostic LLM interface | ✅ Interface only; no concrete provider yet |
| `modules/seo/page_classifier/schemas.py` — Phase 1 taxonomy | ✅ Implemented & tested |
| `page_classifier/url_rules.py` — Layer 0 normalisation & pre-fetch rules | ✅ Implemented & tested |
| `page_classifier/signal_parsers.py` — 5 structural consensus signals | ✅ Implemented & tested |
| `page_classifier/cascading_pipeline.py` — Layer 0–3 cascade & consensus | ✅ Implemented & tested |
| `page_classifier/weights.py` — weight profiles & site-profile seam | ✅ Seam live; adaptive selection off pending corpus |
| `modules/seo/contracts/` — `AuditDataset` contract + 110-row issue catalogue ([ADR 0011](docs/adr/0011-deliverables-boundary-and-screaming-frog-input.md)) | ✅ Models, catalogue and the `UrlNormalizer` seam (Phase 0 P0-1/P0-2/P0-3). Four invariants; `AuditSource` is a `StrEnum`. The seam is enforced by `tests/modules/seo/test_import_boundary.py` (P0-6, [build-log 0079](docs/build-log/0079-sixteen-measured-ninety-four-not.md)): `ast` over every module in `contracts/`, `page_classifier/`, `deliverables/`; no import crosses in any direction |
| `modules/seo/deliverables/` — Screaming Frog export → `AuditDataset` (`screaming_frog_adapter.py`, `_bundle.py`) | ✅ Implemented & tested (P0-3/P0-5, [build-log 0074](docs/build-log/0074-absent-is-not-empty.md)). `links` is never filled. RAE diff script (P0-7) and the Phase 1 rulebook not started |
| `page_classifier/audit_export.py` — crawl profiles → `AuditDataset(source=ENGINE)` | ✅ Implemented & tested (P0-4, [build-log 0079](docs/build-log/0079-sixteen-measured-ninety-four-not.md)). **16 of 110 issues `MEASURED`**, 94 `NOT_MEASURED` with the reason in `notes`; `CANONICALS_MISSING` is not measurable from the profile; 4xx/5xx are read from `indexability_reason` and test-bound; `links` never filled. Nothing calls it yet — no endpoint, workbook or UI (Phase 2) |
| `core/logger.py` — structured `extra=` fields on log records | ✅ Fixed in [build-log 0078](docs/build-log/0078-the-fields-that-never-left-the-call-site.md): `get_logger` returns a merging adapter, caller keys win (6 tests). Was dropped on Python 3.11 from the first commit; found in cycle 0074 |
| Layer 2 local ML classifier | ❌ Protocol only; needs local GPU ([ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Layer 3 `LlmPageClassifier` implementation | ❌ Protocol only; needs a live credential |
| Golden corpus coverage | ⚠️ 13 labels, 1 of 6 archetypes — **not yet enough to validate any accuracy claim**. 141 draft rows await review in [drafts/](tests/fixtures/corpus/drafts/README.md) |
| CMS pagination | ✅ Multi-page retrieval via `Link` cursor, `X-WP-TotalPages` and `?page=N`. Effect on live confidence **not yet measured** — see [build-log 0011 §5](docs/build-log/0011-cms-pagination.md) |
| `core/circuit_breaker.py` | ❌ Not started |
| `core/state_store.py` — durable job records | ✅ Implemented & tested (`DiskJobStore`; see [CLAUDE.md](CLAUDE.md) §8 "Closed since the audit") |
| Idempotency keys; distributed rate limit & spend ceiling | ❌ Not started |
| `Dockerfile` / Railway deployment | ❌ Not started (deferred — see [ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |

### Running a crawl

```powershell
.\.venv\Scripts\python.exe scripts\run_crawl.py https://example.com
.\.venv\Scripts\python.exe scripts\run_crawl.py https://example.com --max-pages 250 --depth 2
```

Defaults are deliberately conservative (50 pages, concurrency 3) — this crawls
somebody else's server. Writes a self-contained interactive HTML report.

`--max-pages` is what bounds a run; `--depth` is unlimited by default. A depth
ceiling does not reduce how many pages are fetched — the page budget is spent
either way — it only decides whether a deep site's lower levels are reachable.

### Cross-checking against Screaming Frog (optional)

**Entirely optional.** A crawl is complete on its own terms; this is an extra
pass for operators who happen to have a Screaming Frog licence. Nothing in the
crawl path imports it, and no workflow requires an export.

```powershell
# Report the gap, change nothing (the default)
.\.venv\Scripts\python.exe scripts\reconcile_screaming_frog.py <job-id> internal_html.csv

# Fold the pages Screaming Frog found and the engine missed into the tree
.\.venv\Scripts\python.exe scripts\reconcile_screaming_frog.py <job-id> internal_html.csv --merge --out merged.json
```

The same thing over HTTP, posting the file (`.csv` or `.xlsx`) as the raw body — not
`multipart/form-data`, which would need a dependency this project does not have:

```
POST /api/v1/jobs/{id}/reconcile/screaming-frog     Content-Type: text/csv
```

Both directions of the disagreement are reported, and they call for opposite
fixes:

| Direction | What it means | The fix |
| :--- | :--- | :--- |
| Screaming Frog found it, the engine did not | Linked but in no sitemap, usually deep | Add it to a sitemap |
| The engine found it, Screaming Frog did not | Published with no internal link — a sitemap orphan | Add internal links |
| The engine found it, and it is a file | A PDF, deck, spreadsheet or other document. Screaming Frog lists these on its own tab, not under HTML | Nothing; a difference, not a finding |

The downloadable workbook is one sheet per reason: `Summary`, `Missed pages`,
`Orphans`, then `PDF files`, `Presentations`, `Spreadsheets`, `Other files`,
then every other reason by size. Splitting the files out took infosys.com's
Orphans sheet from 8,123 rows to 630
([build-log 0076](docs/build-log/0076-a-pdf-is-not-an-orphan.md)).

Only the first direction is merged, and only its `MISSED_PAGE` rows: redirect
sources, off-site URLs, media and 4xx are differences the engine holds on
purpose, not gaps. Merged pages are classified from the URL alone — an export
carries no HTML — so they keep a low confidence score, which is how you tell
them from crawled pages. A merge always writes a **new** job; the original is
never modified. Both `.csv` and `.xlsx` exports are read; the format is detected from
the content, not the extension ([build-log 0031](docs/build-log/0031-native-xlsx-excel-reconciliation-support.md)).

A plain one-column list of URLs — a masterfile tab headed `HTML Pages`, or a
headerless dump — is also accepted, but only as a set comparison. It carries no
status, indexability or content type, so a URL it holds that the crawl lacks is
reported as `UNKNOWN`, never as a missed page, and nothing from a list is ever
merged; the report declares `source_format=BARE_URL_LIST`. Anything else without
an `Address` column is still refused ([build-log 0072](docs/build-log/0072-a-list-is-not-an-export.md)).

### The local API and the React UI

```powershell
.\.venv\Scripts\python.exe -m src.api.server        # http://127.0.0.1:8000
cd rankuno-ui; npm run dev                          # http://localhost:5173
```

The server binds loopback deliberately: there is no authentication and it fetches
arbitrary URLs on request ([ADR 0008](docs/adr/0008-local-api-layer-and-job-store.md)).
Started without it, the UI falls back to bundled fixtures and says so on screen —
fixture data is indistinguishable from crawl output otherwise.

Job records persist under `.jobs/`, so crawls survive a restart. A crawl
interrupted mid-run is marked `failed` rather than resumed: there is no
within-crawl checkpointing, so the work genuinely is lost.

### Search Console accounts (optional)

A crawl can read Google Search Console for its property through the connector
in `src/integrations/gsc_client.py` (read-only scope, [ADR 0010](docs/adr/0010-gsc-api-security-and-safety-controls.md)).
Credentials live only in `.env.local`, which is gitignored; the API never
reads, writes or echoes them ([ADR 0012](docs/adr/0012-gsc-account-profiles.md)).

```dotenv
# The default account, used when a crawl names no profile
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REFRESH_TOKEN=

# One named profile per authorised Google account. Only REFRESH_TOKEN is
# required; CLIENT_ID / CLIENT_SECRET are inherited from GOOGLE_OAUTH_* unless set.
GSC_ACCOUNTS__ACME__REFRESH_TOKEN=
```

Profile names are lowercase, `[a-z0-9_-]`, up to 64 characters. A crawl selects
one with `gsc_account` on the request (the crawl modal offers a picker when the
engine lists at least one); `null` means the default account. An unknown name is
refused at admission with 400 and no job is created — there is no fallback to
the default. The full key set is in [.env.example](.env.example).

```
GET  /api/v1/gsc/accounts        -> {"accounts": ["acme", ...]}   names only, never credentials
POST /api/v1/jobs                {"base_url": ..., "gsc_property": ..., "gsc_account": "acme"}
```

> **Validated against a live site.**
> [build-log/0007](docs/build-log/0007-first-live-run.md) records the first real
> run; [build-log/0008](docs/build-log/0008-dom-budget-reserve.md) records the
> budget-reserve fix that followed from it, which recovered 4 of the 5
> sitemap-omitted pages named in the HighRadius audit record.
>
> One finding remains open: the observed LLM escalation rate is ~50x the
> assumption in [ADR 0005](docs/adr/0005-llm-provider-strategy-and-cost-metering.md),
> so the cost model is not yet trustworthy.

### Verification

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1   # SDLC Step 7 quality gate
.\.venv\Scripts\python.exe scripts\drift_check.py               # SDLC Step 8 drift audit
```

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
