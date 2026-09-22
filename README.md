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
| `page_classifier/content_signals.py` — native title/H1/meta-description extraction (`html.parser`, no new dependency) | ✅ Implemented & tested ([ADR 0014](docs/adr/0014-native-title-h1-meta-description-extraction.md), [build-log 0096](docs/build-log/0096-twenty-nine-measured-eighty-one-not.md)). Hooked into `discovery.SiteGraph.record_fetch`, the single method both sync and async discovery call, so sync/async parity is structural. First-occurrence-wins text, independent occurrence counts, `OUTSIDE_HEAD` heuristic for malformed/no-`<head>` markup, `<noscript>` excluded, truncated (not dropped) at 500/500/1000 chars |
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
| `modules/seo/deliverables/` — Screaming Frog export → `AuditDataset` (`screaming_frog_adapter.py`, `_bundle.py`) | ✅ Implemented & tested (P0-3/P0-5, [build-log 0074](docs/build-log/0074-absent-is-not-empty.md)). `links` is never filled |
| `modules/seo/deliverables/rulebook.py` — client URL-pattern rulebook → `theme_1`/`theme_2`/`language`/`business_priority` on `AuditPage` | ✅ Implemented & tested (P1-1–P1-4, [build-log 0083](docs/build-log/0083-a-rulebook-that-never-says-low.md)). `from_xlsx()` tolerant header/fallback detection; `classify()` order-independent (`EXACT` wins, then longest pattern); missing file raises unless `lenient=True`; no match and no fallback row → `Others`/`N/A`, never `Low`. Reachable from the CLI and, as of cycle 0087, `POST /api/v1/deliverables/rulebooks` |
| `page_classifier/audit_export.py` — crawl profiles → `AuditDataset(source=ENGINE)` | ✅ Implemented & tested (P0-4, [build-log 0079](docs/build-log/0079-sixteen-measured-ninety-four-not.md); title/H1/meta-description rules added in [build-log 0096](docs/build-log/0096-twenty-nine-measured-eighty-one-not.md)). **29 of 110 issues `MEASURED`**, 81 `NOT_MEASURED` with the reason in `notes`; `CANONICALS_MISSING` is not measurable from the profile; 4xx/5xx are read from `indexability_reason` and test-bound; the four `PAGE_TITLES`/`META_DESCRIPTION` pixel-width ids stay `NOT_MEASURED` — no verified glyph-width table sourced ([ADR 0014](docs/adr/0014-native-title-h1-meta-description-extraction.md)); `links` never filled. Called from `POST /api/v1/jobs/{id}/deliverable` as of cycle 0087 |
| `modules/seo/deliverables/scoring.py` — per-category penalty totals over `AuditDataset` (ADR 0011 D2) | ✅ Implemented & tested (P2-a, [build-log 0084](docs/build-log/0084-a-workbook-behind-every-category-total.md)). `score_dataset()` produces one `IssuePenalty` per catalogue row (all 110, `NOT_MEASURED` included at zero) and one `CategoryPenalty` per category; no field anywhere aggregates into a single site score. `get_severity_weights()` is a swappable seam, same shape as `weights.get_weight_profile()` (ADR 0006) |
| `modules/seo/deliverables/workbook.py` — four-sheet client workbook (Overview/Issues/Pages/Notes) | ✅ Implemented & tested (P2-b, [build-log 0084](docs/build-log/0084-a-workbook-behind-every-category-total.md)). `build_workbook(dataset, scoring, *, output_dir=None)`; `write_only` openpyxl mode; `MAX_PAGES_PER_WORKBOOK = 500_000` raises `WorkbookPageLimitExceededError` (a `WorkbookBuildError` subclass since cycle 0087, so an oversized dataset is distinguishable from a generic write failure) instead of truncating. Every text cell across all four sheets passes through `_safe_cell()`, which neutralises openpyxl's leading-character formula classification (`= + - @`, tab, CR) — a workbook-wide test asserts zero cells anywhere have `data_type == "f"`. Writes to `Settings.deliverables_output_dir` by default when built from the CLI; the API routes each build under its own job-scoped directory instead (see below) |
| `scripts/diff_against_rae.py` — opt-in differential check, our SF adapter vs an independent reimplementation of RAE's `load_url_set` semantics (ADR 0011) | ✅ Implemented & tested (P0-7, [build-log 0081](docs/build-log/0081-an-oracle-for-membership-only.md)). Reads `Settings.rae_archive_dir`; skips cleanly (exit 0) when unset. Not part of `verify.ps1` — the 49-crawl archive lives outside the repo and is run manually by an operator who has it |
| `modules/seo/deliverables/pipeline.py` — `run_deliverable_pipeline()`, the one call every entry point uses: theme (optional) → score → workbook | ✅ Implemented & tested ([build-log 0085](docs/build-log/0085-a-cli-for-a-pipeline-that-already-existed.md)). Never loads a source itself — see `scripts/build_deliverable.py` below |
| `scripts/build_deliverable.py` — operator CLI chaining a source loader into `run_deliverable_pipeline()`; `sf-bundle` and `engine-crawl` subcommands | ✅ Implemented & tested ([build-log 0085](docs/build-log/0085-a-cli-for-a-pipeline-that-already-existed.md)). Loading dispatch lives in the script, not `pipeline.py`, so `deliverables/` never imports `page_classifier` (ADR 0011 d.1) — same pattern as `reconcile_screaming_frog.py` and `diff_against_rae.py`. Still the only way to build a workbook from a terminal; `src/api/deliverables_routes.py` is the separate, equivalent HTTP surface (cycle 0087) |
| `src/api/deliverables_routes.py` — `POST /jobs/{id}/deliverable`, `POST /deliverables/from-screaming-frog`, `POST`/`GET`/`DELETE /deliverables/rulebooks`, `GET /deliverables`, `GET /deliverables/{id}`, `GET /deliverables/{id}/download` | ✅ Implemented & tested (cycle 0087). Every build runs as an async job on a worker thread (`asyncio.to_thread`), gated by `ApiState`'s own deliverable concurrency guard (default 3, independent of `FacetRouter`) — never a synchronous handler blocking on `build_workbook` (measured up to 26.3s at 500k pages). `ApiState.deliverable_store` is a second `DiskJobStore` under `.deliverable_jobs/`, separate from crawl jobs; `ApiState.rulebook_store` is a new `RulebookStore` under `.deliverable_rulebooks/`. Every record carries `org_id`; every read, status check and download enforces `record.org_id == org_id`, the same 403-after-404 shape `get_job`/`get_result` already use. No web UI page yet — only the API (deferred, separate cycle) |
| `core/logger.py` — structured `extra=` fields on log records | ✅ Fixed in [build-log 0078](docs/build-log/0078-the-fields-that-never-left-the-call-site.md): `get_logger` returns a merging adapter, caller keys win (6 tests). Was dropped on Python 3.11 from the first commit; found in cycle 0074 |
| Layer 2 local ML classifier | ❌ Protocol only; needs local GPU ([ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Layer 3 `LlmPageClassifier` implementation | ❌ Protocol only; needs a live credential |
| Golden corpus coverage | ⚠️ 13 labels, 1 of 6 archetypes — **not yet enough to validate any accuracy claim**. 141 draft rows await review in [drafts/](tests/fixtures/corpus/drafts/README.md) |
| CMS pagination | ✅ Multi-page retrieval via `Link` cursor, `X-WP-TotalPages` and `?page=N`. Effect on live confidence **not yet measured** — see [build-log 0011 §5](docs/build-log/0011-cms-pagination.md) |
| `core/circuit_breaker.py` | ❌ Not started |
| `core/state_store.py` — durable job records | ✅ Implemented & tested (`DiskJobStore`; see [CLAUDE.md](CLAUDE.md) §8 "Closed since the audit") |
| `core/process_supervisor.py` + `_process_ledger.py`/`_process_orphans.py`/`_win32_bindings.py` — Windows Job Object process supervision (kill-on-close, PID+start-time ledger, startup reconciliation) | ✅ Implemented & tested (47 tests, [ADR 0013](docs/adr/0013-screaming-frog-cli-process-governance-exception.md), [build-log 0095](docs/build-log/0095-a-crash-the-kernel-cleans-up.md)). Domain-agnostic `core/` infrastructure, not SEO-specific. Now has a caller — see the row below |
| `modules/seo/screaming_frog_control/` — Screaming Frog CLI launched under `launch_supervised`; the seed-URL `UrlSafetyPolicy` gate, `.seospiderconfig` template-by-name mapping, positive licence verification, and the first `RiskClass.WRITE`/`MANDATORY_HITL` tool this codebase ships (ADR 0013 conditions 4-8) | ✅ Implemented & tested (build-log entry pending — docs-scribe). `POST /api/v1/screaming-frog/jobs/preview` mints a short-lived, single-use token; `POST /api/v1/screaming-frog/jobs` re-validates and burns it inside the governed `GuardrailEngine.authorize()` call via `CallbackApprovalProvider`, never a client-asserted boolean. `GET /api/v1/screaming-frog/templates` lists pre-authored `.seospiderconfig` files by name — the directory ships empty; nothing in this engine can author one (Java `ObjectInputStream`-serialised, GUI-only). `export_manifest.py`'s `--export-tabs`/`--bulk-export` argument list was derived from `catalogue.py`'s `sf_sources` and cross-checked against real `ScreamingFrogSEOSpiderCli.exe 19.4` output; 5 of 95 filenames depend on Screaming Frog's active character/pixel thresholds matching the catalogue's hardcoded numbers, verified live for one of the five. `.seospiderconfig`'s magic bytes were **not** independently verified — no real sample exists on the build workstation, only a crash log's Java `ObjectInputStream` error text |
| Idempotency keys; distributed rate limit & spend ceiling | ❌ Not started |
| `Dockerfile` / Railway deployment | ❌ Not started (deferred — see [ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Cloud + desktop worker dispatch for Screaming Frog ([ADR 0015](docs/adr/0015-cloud-local-desktop-worker-architecture.md), built on [ADR 0016](docs/adr/0016-cloud-api-authentication.md)) — worker identity (`core/worker_auth.py`), the dual approval gate (`core/worker_dispatch_signing.py` for gate (b), `core/postgres_worker_dispatch_store.py`/`core/worker_dispatch_store.py` for gate (a) and the job queue), at-rest bundle encryption (`core/worker_bundle_crypto.py`), untrusted-upload validation (`modules/seo/screaming_frog_control/upload_manifest.py`), the cloud HTTP surface (`api/worker_routes.py`: `POST/GET /workers`, `POST /workers/{id}/dispatch/preview`\|`dispatch`, `GET /workers/dispatch/poll`, `POST /workers/jobs/{id}/upload`\|`failed`), and the worker daemon (`modules/seo/screaming_frog_control/worker_daemon.py`, `integrations/worker_cloud_client.py`) | ✅ Implemented & tested ([build-log 0098](docs/build-log/0098-expires-at-is-not-deletion.md)). Worker identity is `DiskWorkerStore` (single-process, the same accepted posture `DiskOperatorStore` already carries — ADR 0015 condition 5 names the dispatch gate and job queue, not identity storage, for the Postgres move). The dispatch preview/confirm gate and `worker_jobs` queue are Postgres-backed (`alembic/versions/0002_worker_dispatch_schema.py`) with **no** in-process fallback — a store outage raises `DispatchStoreUnavailableError` (mapped to `503`), never silently approves. Gate (b)'s signed assignment (`DispatchAssignmentClaims`) embeds the job envelope inside the same HMAC signature as the approval, so tampering either invalidates both; the worker independently re-verifies it — never a bare boolean — via `make_approval_callback`, wired into `GuardrailEngine` exactly like `preview_tokens.py`'s local pattern. No circuit breaker for the worker↔cloud channel (accepted gap, condition 10); the daemon's own bounded exponential backoff (floor `Settings.worker_poll_interval_s`, ceiling `worker_poll_max_backoff_s`) is the v1 substitute. At-rest bundle encryption is a hand-rolled, stdlib-only HMAC-SHA256 encrypt-then-MAC construction (`worker_bundle_crypto.py`) — a deliberate trade against adding a new dependency this cycle, documented as follow-up work, not a claim that it is preferable to a vetted AEAD library. No React UI for any of this — cloud dashboard and worker-management screens are out of scope this cycle |
| Launching a Screaming Frog crawl from the deployed dashboard — the backend half (`core/postgres_worker_store.py`, `api/worker_route_helpers.py`, `modules/seo/screaming_frog_control/worker_daemon_cli.py`, `alembic/versions/0003_worker_identity_table.py`) | ✅ Implemented & tested. Closes the four gaps that made ADR 0015's surface unusable from a browser. **(1) Durable worker identity**: `DiskWorkerStore` wrote to container-local disk, so every Railway redeploy destroyed every registration and forced a new secret; `WORKER_STORE_BACKEND=postgres` now selects `PostgresWorkerStore` (PBKDF2 hashes unchanged, no fallback path, `WorkerStoreUnavailableError` -> `503` rather than a `401` a daemon would read as revocation). There is **no data migration** — switching backends requires re-registering each desktop once. **(2) A way to start the daemon**: `run_worker_daemon` had no caller anywhere; it is now the `rankuno-worker` console script plus `scripts/run_worker_daemon.py`, reading identity from `Settings` (never an argument), naming missing environment variables on `--check`, stopping on a refused credential instead of hot-looping, and shutting down between jobs on Ctrl+C so no upload is left half done. **(3) Liveness**: a poll records `last_seen_at`; `GET /workers` serves `is_online` and `offline_after_s` (default 60s, four poll intervals) so the UI does not invent a staleness rule, and a dispatch confirm for an offline worker is refused `409` rather than queued into a void. **(4) Bundle download**: `GET /workers/jobs/{id}/bundle`, human-authenticated, org-scoped in the route *and* again in the store's SQL, decrypted then streamed, `404` on an expired `expires_at`, `500` naming `WORKER_BUNDLE_ENCRYPTION_SECRET` if the key is absent or rotated — never a partial or ciphertext body. Also: per-worker template reporting via `POST /workers/heartbeat` + `GET /workers/{id}/templates` (a worker is untrusted input; names are pattern- and count-checked server-side, and the server-side `GET /screaming-frog/templates` route still works for the local case), the upload cap raised to 100 MB and enforced **before** the body is buffered (`413` on an over-cap `Content-Length`, stream abandoned mid-body otherwise), and abandoned `DISPATCHED` jobs swept to terminal `FAILED` after `WORKER_DISPATCH_TIMEOUT_S` (not requeued — the worker's single-use ledger would refuse the same job id, and a re-run needs a fresh preview/confirm). **Unverified**: no PostgreSQL server is reachable from this environment and `psycopg` is not installed locally, so `PostgresWorkerStore`'s SQL and migration 0003 are covered only by an in-memory fake cursor. No React UI — a separate task owns it |
| Live progress telemetry for Screaming Frog crawls dispatched through the ADR 0015 worker ([build-log 0100](docs/build-log/0100-mcompleted-twice-with-two-meanings.md)) — `modules/seo/screaming_frog_control/progress_parser.py`, `POST /workers/jobs/{id}/progress` (`api/worker_routes.py`), `alembic/versions/0004_worker_job_progress_columns.py` | ✅ Implemented & tested. Additive to ADR 0015, not part of it — never changes a job's lifecycle `status`. The worker daemon tails its own run's `trace.txt` from a background thread and reports `pages_crawled`/`progress_pct`/`phase` to the cloud, throttled client-side (`ScreamingFrogProgressThrottle`, floor `Settings.worker_progress_min_report_interval_s`) before any network call is attempted — deliberate, because `PostgresWorkerDispatchStore` opens a fresh connection per call with no pool (ADR 0015 condition 5). The feature's own original illustrative progress-line format (`Spidering ... (15 of 120, 12.5%)`) was verified against a real, live `ScreamingFrogSEOSpiderCli.exe 19.4` crawl and found never to occur; the real format is a `SpiderMain` `SpiderProgress [mActive=N, mCompleted=N, mWaiting=N, mCompleted=N.NN%]` line, comma-thousands-separated, with `mCompleted` appearing twice for two different meanings — see the module docstring. `GET /workers/jobs` and `GET /workers/jobs/{id}` gained three new optional `WorkerJobView` fields (`pages_crawled`, `progress_pct`, `current_phase`), all `None` for jobs predating this feature and never guaranteed monotonically increasing. **No frontend consumes this.** `rankuno-ui/` is untouched by this cycle, and the existing `WorkerJobsPanel.tsx` (built one commit earlier) carries its own docstring stating "There is no progress column and there will not be one" — a deliberate stance recorded *before* this backend contract existed, now in direct tension with it; resolving that tension is a decision for whoever picks up the UI follow-up, not assumed here |

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
then, for a bare-list cross-check, one sheet per `DefaulterCategory` (below),
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

Because a bare list carries no status, an `UNKNOWN` row is further guessed at
by URL shape alone: `DefaulterCategory` sorts it into `DAM_HTML_ARCHIVE`,
`DAM_FORMS_OTHER`, `CMS_INTERNAL_LEAK`, `CORRUPTED_URL`, or leaves it
uncategorised (`None`) as a "presumed real" residual — a guess, not a
verification; roughly 80% of a real bare-list `UNKNOWN` bucket stays
uncategorised even after the rules run. All four categories are quarantined
out of the interactive tree by default behind an "Include Defaulters" toggle
in the React UI — whether `DAM_FORMS_OTHER` belongs there is still an open
question, see the build log — and each gets its own workbook sheet.
Attaching a Search Console export to a job re-checks every
defaulter row against GSC's own "not crawled" bucket and marks any with real
impressions or clicks `flagged_real=True` — additively, without erasing or
overwriting the original shape-based guess
([build-log 0086](docs/build-log/0086-a-pattern-is-not-a-verdict.md)).

### Building a client deliverable workbook

Chains an already-shipped source loader into the scoring/theming/workbook
pipeline that Phase 0/1/2a/2b built but nothing previously called end to end
([build-log 0085](docs/build-log/0085-a-cli-for-a-pipeline-that-already-existed.md)):

```powershell
# From a Screaming Frog export (directory or zip)
.\.venv\Scripts\python.exe scripts\build_deliverable.py sf-bundle <bundle_path> [--rulebook path.xlsx]

# From a stored engine crawl (job id, or a path to a .result.json)
.\.venv\Scripts\python.exe scripts\build_deliverable.py engine-crawl <job-id-or-result.json> [--rulebook path.xlsx]
```

Omitting `--rulebook` skips theming entirely — no error, nothing to report. A
`--rulebook` path that does not exist is a hard `RulebookMissingError` unless
`--lenient-rulebook` is passed explicitly. `pipeline.py` never loads a source
itself: the two loaders (Screaming Frog bundle vs. engine crawl) are not
symmetric enough to hide behind one injected callable without `deliverables/`
importing `page_classifier` (ADR 0011 d.1), so loading dispatch stays in this
script — the one layer allowed to import both packages, the same pattern as
`reconcile_screaming_frog.py` and `diff_against_rae.py`.

#### The same thing over HTTP (cycle 0087)

Everything above is also reachable from the local API server — an operator no
longer needs a terminal to produce a workbook, only the browser's `fetch` (or
`curl`) against `127.0.0.1`. Every build is async: the endpoint returns `202`
with an id immediately, and the client polls `GET /deliverables/{id}` for a
terminal `status` before downloading.

```
# Upload a rulebook once, reuse its id on later builds. Body is the raw
# .xlsx, not multipart/form-data — the same reasoning the GSC and Screaming
# Frog upload endpoints already give.
POST   /api/v1/deliverables/rulebooks?label=Acme        Content-Type: application/octet-stream
GET    /api/v1/deliverables/rulebooks
DELETE /api/v1/deliverables/rulebooks/{id}

# Build from an already-finished crawl job
POST   /api/v1/jobs/{job_id}/deliverable    {"rulebook_id": "..."}   (or an empty body)

# Build from an uploaded Screaming Frog export bundle (a zip, sent as the raw body)
POST   /api/v1/deliverables/from-screaming-frog?rulebook_id=...

# Poll, list, download
GET    /api/v1/deliverables
GET    /api/v1/deliverables/{id}
GET    /api/v1/deliverables/{id}/download
```

Every endpoint requires a bearer session token and derives `org_id` from it,
the same as every route in `server.py` ([ADR 0016](docs/adr/0016-cloud-api-authentication.md)) —
a `403` for a record another org owns, never a silent empty response. This
closed a second instance of ADR 0016's own IDOR class: at merge time this
module still derived `org_id` from the client-asserted `X-Org-Id` header, a
gap ADR 0016's own route enumeration did not name because it never listed
this file (build-log 0097). Workbook builds run on a worker thread behind their own
concurrency guard on `ApiState` (default 3 at once, independent of the crawl
`FacetRouter`) — `build_workbook` alone measures up to 26.3s at the 500k-page
ceiling, so nothing here may block a request handler on it. There is still no
web UI page for this — only the API; a UI affordance is a follow-up, tracked
as a handoff to `ui-engineer`.

### The local API and the React UI

```powershell
.\.venv\Scripts\python.exe -m src.api.server        # http://127.0.0.1:8000
cd rankuno-ui; npm run dev                          # http://localhost:5173
```

The server binds loopback deliberately: it still fetches arbitrary URLs on
request, and on a routable interface that remains an open proxy regardless of
login ([ADR 0008](docs/adr/0008-local-api-layer-and-job-store.md)). Started
without it, the UI falls back to bundled fixtures and says so on screen —
fixture data is indistinguishable from crawl output otherwise.

Almost every route now requires a bearer session token
([ADR 0016](docs/adr/0016-cloud-api-authentication.md)):

```powershell
# Provision the first operator (offline, interactive — never over HTTP)
.\.venv\Scripts\python.exe scripts\create_operator.py --operator-id alice --org-id default

# Exchange credentials for a session token
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "alice", "password": "..."}'
# -> {"token": "...", "token_type": "bearer", "org_id": "default", "expires_at": "..."}

curl -s http://127.0.0.1:8000/api/v1/jobs -H "Authorization: Bearer <token>"
```

`org_id` is now derived from the token's verified claim everywhere — never
from the `X-Org-Id` header or a URL path segment. This closed a critical,
previously-unauthenticated IDOR on the three `/orgs/{org_id}/gsc-accounts`
routes and retrofitted an org-ownership check onto fourteen job-family routes
that had none. Authentication does not change what `GuardrailEngine` requires
for a `RiskClass.WRITE`/`FINANCIAL` action — a logged-in operator can be
correctly identified as the actor requesting a write, not skip HITL approval
for one.

Job records persist under `.jobs/`, so crawls survive a restart. A crawl
interrupted mid-run is marked `failed` rather than resumed: there is no
within-crawl checkpointing, so the work genuinely is lost.

The server runs at most 5 crawls at once by default and answers `429` beyond
that; `MAX_CONCURRENT_CRAWLS` (1–10) sets the cap. It bounds memory, not CPU:
each in-flight crawl holds its whole graph in RAM, so raise it only on a host
with the RAM to match.

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
