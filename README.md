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
| `modules/seo/url_filter.py` — include/exclude URL patterns (wildcard `*`/`**` or regex), applied in `SiteGraph.add()` | ✅ Implemented & tested (44 tests, [build-log 0106](docs/build-log/0106-a-pattern-that-never-reaches-the-form.md)). Include list is a whitelist applied first, exclude a blacklist applied second; path only (query and fragment are stripped); the base URL is never filtered; `DiscoveryReport.filter_skipped` counts what was dropped. ⚠️ **API-only** — `include_patterns`/`exclude_patterns` exist on `PageClassificationInput` and in `schema.ts`, and **no UI surface sets them** |
| `page_classifier/content_signals.py` — native title/H1/meta-description extraction (`html.parser`, no new dependency) | ✅ Implemented & tested ([ADR 0014](docs/adr/0014-native-title-h1-meta-description-extraction.md), [build-log 0096](docs/build-log/0096-twenty-nine-measured-eighty-one-not.md)). Hooked into `discovery.SiteGraph.record_fetch`, the single method both sync and async discovery call, so sync/async parity is structural. First-occurrence-wins text, independent occurrence counts, `OUTSIDE_HEAD` heuristic for malformed/no-`<head>` markup, `<noscript>` excluded, truncated (not dropped) at 500/500/1000 chars |
| `page_classifier/async_discovery.py` — concurrent crawl path | ✅ Implemented & tested |
| `page_classifier/tree_visualizer.py` — standalone interactive HTML report | ✅ Implemented & tested |
| `page_classifier/corpus.py` + `evaluation.py` — golden corpus & accuracy harness | ✅ Implemented & tested |
| `page_classifier/tool.py` — **governed entry point**, one run = one crawl job | ✅ Implemented & tested |
| `integrations/llm_client.py` — provider-agnostic LLM interface | ✅ Interface only; no concrete provider yet |
| `modules/seo/page_classifier/schemas.py` — Phase 1 taxonomy | ✅ Implemented & tested |
| `page_classifier/url_rules.py` — Layer 0 normalisation & pre-fetch rules | ✅ Implemented & tested. **Path case is significant** ([ADR 0027](docs/adr/0027-url-path-case-is-significant.md), [build-log 0129](docs/build-log/0129-two-pages-that-differed-only-by-case.md)): `/A` and `/a` are two pages, as they are to Google and Screaming Frog. Only scheme and host are lowercased; kept percent-escapes are upper-cased so `%2f`/`%2F` stay one key. Search Console/GA4 matching folds path case only as an explicit `MatchTier.CASE_FOLDED` fallback after an exact miss, and resolves `AMBIGUOUS` when two crawled pages differ only by case. Until this change the whole path was lowercased; new crawls of mixed-case sites count more pages than old ones |
| URL provenance reported from evidence ([ADR 0026](docs/adr/0026-url-provenance-reports-evidence-or-says-unknown.md), [build-log 0127](docs/build-log/0127-a-reason-the-crawl-never-recorded.md)) — `DiscoverySource` flags (`sitemap`, `dom_link`, `cms_api`) drive the Screaming Frog engine-only reason, the navigation "Discovery Method" and checkpoint recovery | ✅ Phase 1 only. Where the flags are absent the engine says the source is unknown, never guesses. Navigation: `SITEMAP_ONLY` requires the sitemap flag; an unlinked page without it (including CMS-only) is `ORPHANED`. Fetch ledger: a robots.txt refusal is `robots_disallowed`, not `transport_error`. Checkpoints store per-URL source letters (`sources`, aligned with `urls`); an older checkpoint loads and states that how each URL was found is unknown. Page links resolve against the URL the fetch landed on and the first same-site `<base href>` ([build-log 0128](docs/build-log/0128-a-link-resolved-against-the-address-that-was-asked-for.md)), so a `dom_link` flag is no longer set for a URL built from the pre-redirect address. **Not done**: referrer URL, sitemap path, link depth, CMS record, per-URL refusal list (Phase 2); provenance export columns and UI (Phase 3); canonical/hreflang/`rel=next`/iframe discovery (Phase 4). Stored results are not rewritten |
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
| `modules/seo/deliverables/masterfile_*.py` — 21 RAE masterfile export services + `masterfile_registry.py` | ⚠️ **12 of 21 produce rows against a real export; 21 are not yet 21 working reports.** Measured against one real Screaming Frog 19.4 export of ~24,000 pages ([build-log 0116 §2.1](docs/build-log/0116-three-causes-for-one-empty-workbook.md)), where 4 of 21 produced rows before: `non_functional_internal_links` 51,965, `security` 34,347, `directives` 10,309, `response_codes` 7,756, `meta_description` 4,511, `custom_extraction` 4,847, `page_titles` 2,180, `h1` 1,291, `url_issues` 939, `content_issues` 626, `canonicals` 232, and `overview_report` 4 sheets where it previously **crashed**. Of the 9 that still render nothing: 3 are `NOT_MEASURED` (no catalogue source exists), 5 have genuinely empty inputs on that one site, and `pagination` is a real residual needing per-issue filtering. Output shape is still a **flat URL list with no column naming which issue applied**, and nothing deduplicates across source files, so a URL in two issue exports yields two identical rows; RAE's equivalent is 18 columns of per-issue flags. Commit `0d26e26`'s "Complete RAE masterfile parity" and build-log 0105's "Phase 1 COMPLETE" were both false ([build-log 0107 §5](docs/build-log/0107-a-directory-that-could-never-exist.md)) and 12 of 21 is still not complete |
| `modules/seo/contracts/sources.py` — `sources_for_categories()` / `sources_for_issues()`, the only place a masterfile learns its input filenames | ✅ Implemented & tested ([build-log 0116 §2.2](docs/build-log/0116-three-causes-for-one-empty-workbook.md)). Derives from `ISSUE_CATALOGUE.sf_sources` in catalogue order, deduplicated, so a filename can only reach a workbook by first entering the catalogue — the same source `ALLOWED_BUNDLE_FILENAMES` derives from ([ADR 0018](docs/adr/0018-bundle-allow-list-derives-from-the-issue-catalogue.md)). Replaces 37 of 49 filenames that existed in no real export because they had been generated from the service's own module name (`masterfile_page_titles.py` → `title_missing.csv`). A test asserts the union of every service's `SOURCE_FILES` **equals** the allow-list minus the spine, and that no service module except the declared-dynamic `custom_extraction` holds a quoted `.csv` literal |
| `modules/seo/deliverables/masterfile_enrichment.py` — URL-column resolution and enrichment maps | ✅ Implemented & tested ([build-log 0116 §2.3/§4.1](docs/build-log/0116-three-causes-for-one-empty-workbook.md)). **12 of the 96 allow-listed exports have no `Address` column** — they are edge lists headed `Type,Source,Destination,…` — so concatenating them with page exports and reading `Address` printed the literal string `"nan"` as a URL. `url_column_for()` resolves per file *before* concat: `Destination` for the nine `*_inlinks.csv`, `Source` for the three describing offending markup. Also owns `NOT_MEASURED`: `search_console_all.csv` and `analytics_all.csv` are deliberately **outside** the allow-list and can never arrive, so their columns say "Not measured by this crawl" rather than printing a zero that reads as "this page gets no traffic" (ADR 0011 §5) |
| `MasterfileService.INDEXABLE_ONLY` — per-service declaration of whether a deliverable reports on indexable pages only | ✅ Implemented & tested ([ADR 0020](docs/adr/0020-a-deliverable-declares-whether-it-reports-on-indexable-pages.md), [build-log 0116 §2.4](docs/build-log/0116-three-causes-for-one-empty-workbook.md)). Defaults `True`; `False` on exactly `directives`, `response_codes`, `non_functional_internal_links` and `overview_report`, pinned as an exact set by a test. Those three report on pages that are Non-Indexable **by definition** — a `noindex` directive, a 4xx response, an inlink to a broken page — so the old unconditional `Indexability == "Indexable"` filter could not match a row by construction, costing 10,309 / 7,756 / 51,127 rows on the measured export. Implements the exception build-log 0104 §223 specified and never shipped. Per service, not per issue: `pagination` is the known casualty of that boundary |
| `modules/seo/deliverables/masterfile_source.py` — `MasterfileSource` seam: a folder of CSVs **or** a zip read in memory | ✅ Implemented & tested (42 tests, [ADR 0017](docs/adr/0017-masterfile-input-is-an-in-memory-export-bundle.md), [build-log 0107](docs/build-log/0107-a-directory-that-could-never-exist.md)). A decrypted worker bundle is never written to disk (ADR 0015 condition 11); `_bundle.open_bundle_bytes()` reuses the existing zip pre-flight. `read_csv_safe` now defaults to `utf-8-sig`, because Screaming Frog writes a UTF-8 BOM that bare `utf-8` glues to the first header cell — which produced a silent empty report on real exports and on no fixture. There is no `sf_export/` directory and never was |
| `POST /jobs/{id}/masterfile/{slug}` — one masterfile workbook from a job's Screaming Frog exports | ✅ Route works (14 tests, [build-log 0107](docs/build-log/0107-a-directory-that-could-never-exist.md)); it had **never succeeded for any input** before that cycle. Resolves the id against **both** job namespaces — engine store first, then the ADR 0015 worker dispatch store — so the caller has one id to send and one deliverable id to poll. `409` a native crawl or no uploaded bundle, `410` the retention window closed, `500` the bundle cannot be decrypted, `503` the dispatch store is unreachable. The UI calls it from a "Masterfiles" popover on finished Screaming Frog worker-job rows and sends the **worker** job id; the earlier menu on native crawl rows sent a native id, which this route refuses, and was removed ([build-log 0115](docs/build-log/0115-a-menu-that-sent-the-wrong-id.md)). `GET /masterfiles/available` supplies the button list |
| `core/logger.py` — structured `extra=` fields on log records | ✅ Fixed in [build-log 0078](docs/build-log/0078-the-fields-that-never-left-the-call-site.md): `get_logger` returns a merging adapter, caller keys win (6 tests). Was dropped on Python 3.11 from the first commit; found in cycle 0074 |
| Layer 2 local ML classifier | ❌ Protocol only; needs local GPU ([ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Layer 3 `LlmPageClassifier` implementation | ❌ Protocol only; needs a live credential |
| Golden corpus coverage | ⚠️ 13 labels, 1 of 6 archetypes — **not yet enough to validate any accuracy claim**. 141 draft rows await review in [drafts/](tests/fixtures/corpus/drafts/README.md) |
| CMS pagination | ✅ Multi-page retrieval via `Link` cursor, `X-WP-TotalPages` and `?page=N`. Effect on live confidence **not yet measured** — see [build-log 0011 §5](docs/build-log/0011-cms-pagination.md) |
| `core/circuit_breaker.py` — `CLOSED`/`OPEN`/`HALF_OPEN`, 5-failure threshold, 30s recovery | ✅ Implemented & tested (20 tests). This row said "❌ Not started" until cycle 0110; the file has existed since 2026-09-09 and is wired into `core/postgres_store.py`, `core/worker_dispatch_signing.py` and `integrations/gsc_token_manager.py`. Nothing wires a breaker to ADR 0015's worker-dispatch HTTP channel — that is an accepted v1 gap (ADR 0015 condition 10) and a different statement ([build-log 0098](docs/build-log/0098-expires-at-is-not-deletion.md), [0110](docs/build-log/0110-what-the-gate-had-not-been-run-on.md)). `CLAUDE.md` §8 still carries the old claim and needs the same correction |
| `core/memory_budget.py` — process-wide budget on retained crawl HTML (`CRAWL_MEMORY_BUDGET_MIB`, default 3072 MiB) | ✅ Implemented & tested ([ADR 0031](docs/adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md), [build-log 0136](docs/build-log/0136-a-crawl-that-stops-before-the-container-does.md)). Each async DOM-crawl page body is charged as it lands (`sys.getsizeof`); when the projected total reaches the budget, the largest crawl over its fair share (budget / `MAX_CONCURRENT_CRAWLS`) stops at a safe point and ends `partial` with "memory budget reached" instead of the container being OOM-killed. A crawl at or under its share is never stopped by another org's load. **Not an OOM guarantee**: sitemap/CMS bodies, the serial fallback, `/result` reads, deliverables and Screaming Frog jobs are uncounted, and the HTML is still retained until the job ends (step 2, not started) |
| `scripts/run_local.ps1` + `scripts/local_preflight.py` — the full site (API and built UI) on this workstation, loopback only, for crawls larger than the Railway container allows | ✅ Implemented; preflight tested (56 tests, [ADR 0032](docs/adr/0032-a-local-server-never-reaches-a-shared-database.md), [build-log 0138](docs/build-log/0138-a-site-that-runs-at-home-without-touching-production.md)). Refuses dotenv database/cache keys by name, blanks them in the server's environment and proves `is_configured()` is `False` before listening. Opens the browser already signed in through a single-use, five-minute, loopback-only link (`POST /api/v1/auth/local-signin`, operator `local` in org `default`; `-NoAutoSignIn`, `-AutoSignInOperatorId`, `-AutoSignInOrgId`) and Host-checks with `API_ALLOWED_HOSTS` ([ADR 0033](docs/adr/0033-a-local-launch-signs-in-through-a-single-use-loopback-link.md), [build-log 0139](docs/build-log/0139-a-browser-that-opens-already-signed-in.md)). Refuses to `npm ci` through a linked `node_modules`. The PowerShell launcher is only parse-checked by a test; a non-loopback database host is not refused in code. See [Running the full site locally](#running-the-full-site-locally-for-large-crawls) |
| `scripts/push_job_to_cloud.py` + `POST /api/v1/jobs/import` — copy a finished local crawl into your cloud org | ✅ Implemented & tested ([ADR 0034](docs/adr/0034-a-local-crawl-reaches-the-cloud-as-a-terminal-provenance-stamped-import.md)). Terminal, provenance-stamped, idempotent per org; no ledger charge; whole-bundle refusal on any non-http(s) URL. **Not yet**: the UI's "Imported from local" badge, hidden Retry/Resume and shared `safeHref()` (ui-engineer follow-up); no "Copy to cloud" button; import memory uncounted by the ADR 0031 budget. See [Copying a finished local crawl to the cloud](#copying-a-finished-local-crawl-to-the-cloud) |
| `core/state_store.py` — durable job records | ✅ Implemented & tested (`DiskJobStore`; see [CLAUDE.md](CLAUDE.md) §8 "Closed since the audit") |
| `core/postgres_store.py` — durable job records over Postgres | ✅ Implemented & tested ([ADR 0022](docs/adr/0022-postgres-backed-job-store.md), [build-log 0118](docs/build-log/0118-a-store-that-only-wrote-its-own-name.md)). Every `JobStore` method now writes real Postgres, not just `create()`/`get()`/`list_jobs()` as before this cycle; falls back to `DiskJobStore` once its `CircuitBreaker` opens. `create_app()` selects it automatically whenever `PostgresSettings.is_configured()` is true, so a job's status, result, checkpoint and homepage snapshot survive a Railway redeploy — `DiskJobStore`'s `.jobs/` alone does not. `job_payloads` (migration 0006, plus migration 0008 for `reconciliation`/`performance` — [build-log 0121](docs/build-log/0121-a-scope-out-that-shipped-as-a-bug.md)) holds the large payloads. Delegating `reconciliation`/`performance` to the disk fallback unconditionally was a production bug, not a deferred feature: `create()` writes a Postgres-backed job's row to Postgres only, and `DiskJobStore`'s writers require the job to exist on disk first, so the write silently no-oped and every later `GET` (including the download buttons) 404'd for every job since this store became the default (build-log 0118). Fixed — same circuit-breaker/upsert pattern as every other method. The unrelated `.orgs`/`.operators` stores stay disk-only, a deferred follow-up |
| `core/process_supervisor.py` + `_process_ledger.py`/`_process_orphans.py`/`_win32_bindings.py` — Windows Job Object process supervision (kill-on-close, PID+start-time ledger, startup reconciliation) | ✅ Implemented & tested (51 tests, [ADR 0013](docs/adr/0013-screaming-frog-cli-process-governance-exception.md), [build-log 0095](docs/build-log/0095-a-crash-the-kernel-cleans-up.md)). Domain-agnostic `core/` infrastructure, not SEO-specific. Now has a caller — see the row below. **A PID + start-time match is a liveness test, not an orphan test**, and treating it as one killed two live crawls of 1:05:47 and 1:47:39, one at 99.7% complete: `reconcile_orphans` runs on every API-server startup and every `TestClient(create_app(...))` runs `lifespan`, so `pytest` reaped the workstation's real ledger. `LedgerEntry` now also records `supervisor_pid`/`supervisor_start_time` (written by `launch_supervised` from `os.getpid()` + `GetProcessTimes(GetCurrentProcess())`), checked first, under the same start-time tolerance that guards child PID reuse; a live supervisor's entry is skipped **and kept** in the ledger. A legacy entry with no supervisor marker is still reaped, deliberately — unknown ownership must fail toward reaping, or every pre-upgrade entry becomes an immortal Screaming Frog process holding a licence seat. `create_app(..., process_ledger_path=)` and an import-time redirect in `tests/conftest.py` keep the suite off the real ledger and audit log; reconciliation itself stays on under test ([build-log 0113](docs/build-log/0113-the-test-suite-was-killing-live-crawls.md)) |
| `modules/seo/screaming_frog_control/` — Screaming Frog CLI launched under `launch_supervised`; the seed-URL `UrlSafetyPolicy` gate, `.seospiderconfig` template-by-name mapping, positive licence verification, and the first `RiskClass.WRITE`/`MANDATORY_HITL` tool this codebase ships (ADR 0013 conditions 4-8) | ✅ Implemented & tested (build-log entry pending — docs-scribe). `POST /api/v1/screaming-frog/jobs/preview` mints a short-lived, single-use token; `POST /api/v1/screaming-frog/jobs` re-validates and burns it inside the governed `GuardrailEngine.authorize()` call via `CallbackApprovalProvider`, never a client-asserted boolean. `GET /api/v1/screaming-frog/templates` lists pre-authored `.seospiderconfig` files by name — the directory ships empty; nothing in this engine can author one (Java `ObjectInputStream`-serialised, GUI-only). `export_manifest.py`'s `--export-tabs`/`--bulk-export` argument list was derived from `catalogue.py`'s `sf_sources` and cross-checked against real `ScreamingFrogSEOSpiderCli.exe 19.4` output; 5 of 95 filenames depend on Screaming Frog's active character/pixel thresholds matching the catalogue's hardcoded numbers, verified live for one of the five. `.seospiderconfig`'s magic bytes were **not** independently verified — no real sample exists on the build workstation, only a crash log's Java `ObjectInputStream` error text |
| Idempotency keys; distributed rate limit & spend ceiling | ❌ Not started |
| `Dockerfile` / Railway deployment | ❌ Not started (deferred — see [ADR 0004](docs/adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Cloud + desktop worker dispatch for Screaming Frog ([ADR 0015](docs/adr/0015-cloud-local-desktop-worker-architecture.md), built on [ADR 0016](docs/adr/0016-cloud-api-authentication.md)) — worker identity (`core/worker_auth.py`), the dual approval gate (`core/worker_dispatch_signing.py` for gate (b), `core/postgres_worker_dispatch_store.py`/`core/worker_dispatch_store.py` for gate (a) and the job queue), at-rest bundle encryption (`core/worker_bundle_crypto.py`), untrusted-upload validation (`modules/seo/screaming_frog_control/upload_manifest.py`), the cloud HTTP surface (`api/worker_routes.py`: `POST/GET /workers`, `POST /workers/{id}/dispatch/preview`\|`dispatch`, `GET /workers/dispatch/poll`, `POST /workers/jobs/{id}/upload`\|`failed`), and the worker daemon (`modules/seo/screaming_frog_control/worker_daemon.py`, `integrations/worker_cloud_client.py`) | ✅ Implemented & tested ([build-log 0098](docs/build-log/0098-expires-at-is-not-deletion.md)). Worker identity is `DiskWorkerStore` (single-process, the same accepted posture `DiskOperatorStore` already carries — ADR 0015 condition 5 names the dispatch gate and job queue, not identity storage, for the Postgres move). The dispatch preview/confirm gate and `worker_jobs` queue are Postgres-backed (`alembic/versions/0002_worker_dispatch_schema.py`) with **no** in-process fallback — a store outage raises `DispatchStoreUnavailableError` (mapped to `503`), never silently approves. Gate (b)'s signed assignment (`DispatchAssignmentClaims`) embeds the job envelope inside the same signature as the approval, so tampering either invalidates both. That signature was a shared-key HMAC until cycle 0133 and is now Ed25519 ([ADR 0028](docs/adr/0028-dispatch-claims-are-signed-asymmetrically.md)) — see the worker-credentials row below; the worker independently re-verifies it — never a bare boolean — via `make_approval_callback`, wired into `GuardrailEngine` exactly like `preview_tokens.py`'s local pattern. No circuit breaker for the worker↔cloud channel (accepted gap, condition 10); the daemon's own bounded exponential backoff (floor `Settings.worker_poll_interval_s`, ceiling `worker_poll_max_backoff_s`) is the v1 substitute. At-rest bundle encryption is a hand-rolled, stdlib-only HMAC-SHA256 encrypt-then-MAC construction (`worker_bundle_crypto.py`) — a deliberate trade against adding a new dependency this cycle, documented as follow-up work, not a claim that it is preferable to a vetted AEAD library. No React UI for any of this — cloud dashboard and worker-management screens are out of scope this cycle. **What the bundle contains now decides the job's status** ([ADR 0019](docs/adr/0019-an-export-bundle-decides-its-own-job-status.md), [build-log 0113](docs/build-log/0113-the-test-suite-was-killing-live-crawls.md)): zero members → `FAILED` and the bundle is **not stored**, members without `internal_all.csv` → `PARTIAL` (stored, downloadable, but no deliverable can be built from it), otherwise `SUCCEEDED`. All three return `200` deliberately — `WorkerCloudClient.upload_bundle` calls `raise_for_status()`, so a 4xx would raise on the daemon for an already-terminal job no retry can improve. Until this landed, `upload_bundle` never inspected the bundle and a 22-byte empty zip from a crawl killed at 99.7% was reported `SUCCEEDED`; `WorkerJobStatus.PARTIAL` existed but was unreachable because its only caller never passed `partial` |
| Launching a Screaming Frog crawl from the deployed dashboard — the backend half (`core/postgres_worker_store.py`, `api/worker_route_helpers.py`, `modules/seo/screaming_frog_control/worker_daemon_cli.py`, `alembic/versions/0003_worker_identity_table.py`) | ✅ Implemented & tested. Closes the four gaps that made ADR 0015's surface unusable from a browser. **(1) Durable worker identity**: `DiskWorkerStore` wrote to container-local disk, so every Railway redeploy destroyed every registration and forced a new secret; `WORKER_STORE_BACKEND=postgres` now selects `PostgresWorkerStore` (PBKDF2 hashes unchanged, no fallback path, `WorkerStoreUnavailableError` -> `503` rather than a `401` a daemon would read as revocation). There is **no data migration** — switching backends requires re-registering each desktop once. **(2) A way to start the daemon**: `run_worker_daemon` had no caller anywhere; it is now the `rankuno-worker` console script plus `scripts/run_worker_daemon.py`, reading identity from `Settings` (never an argument), naming missing environment variables on `--check`, stopping on a refused credential instead of hot-looping, and shutting down between jobs on Ctrl+C so no upload is left half done. **(3) Liveness**: a poll records `last_seen_at`; `GET /workers` serves `is_online` and `offline_after_s` (default 60s, four poll intervals) so the UI does not invent a staleness rule, and a dispatch confirm for an offline worker is refused `409` rather than queued into a void. **(4) Bundle download**: `GET /workers/jobs/{id}/bundle`, human-authenticated, org-scoped in the route *and* again in the store's SQL, decrypted then streamed, `404` on an expired `expires_at`, `500` naming `WORKER_BUNDLE_ENCRYPTION_SECRET` if the key is absent or rotated — never a partial or ciphertext body. Also: per-worker template reporting via `POST /workers/heartbeat` + `GET /workers/{id}/templates` (a worker is untrusted input; names are pattern- and count-checked server-side, and the server-side `GET /screaming-frog/templates` route still works for the local case), the upload cap raised to 100 MB and enforced **before** the body is buffered (`413` on an over-cap `Content-Length`, stream abandoned mid-body otherwise), and abandoned `DISPATCHED` jobs swept to terminal `FAILED` after `WORKER_DISPATCH_TIMEOUT_S` (not requeued — the worker's single-use ledger would refuse the same job id, and a re-run needs a fresh preview/confirm). **Unverified**: no PostgreSQL server is reachable from this environment and `psycopg` is not installed locally, so `PostgresWorkerStore`'s SQL and migration 0003 are covered only by an in-memory fake cursor. No React UI — a separate task owns it |
| Worker credentials and dispatch signing — `core/worker_dispatch_keys.py`, `core/worker_dispatch_signing.py`, `api/worker_verify_key_routes.py`, `api/worker_credential_routes.py`, `scripts/register_worker.py`, `scripts/generate_dispatch_keypair.py`, `WorkerCredentialsPanel.tsx` ([ADR 0028](docs/adr/0028-dispatch-claims-are-signed-asymmetrically.md), [ADR 0029](docs/adr/0029-a-worker-credential-is-revoked-or-rotated-never-reactivated.md), [build-log 0133](docs/build-log/0133-a-key-every-verifier-could-sign-with.md)) | ✅ Implemented & tested; ⚠️ **operator rollout not done**. Gate (b) used to sign and verify with one shared HMAC key, `WORKER_DISPATCH_SIGNING_SECRET`, which every worker held in plaintext, so any worker's `.env.local` could forge a dispatch for any worker or org. The cloud now signs with an Ed25519 private key (`WORKER_DISPATCH_SIGNING_PRIVATE_KEY`, Railway only; generate one with `python scripts/generate_dispatch_keypair.py`) and a worker verifies with the public key (`WORKER_DISPATCH_VERIFY_KEY`, not secret). A worker with a verify key never accepts an HMAC-only claim. While the legacy secret is set and `WORKER_DISPATCH_LEGACY_HMAC_ENABLED` is true (the default) the cloud also signs with HMAC, so un-upgraded workers keep running. **Registering a worker**: `python scripts/register_worker.py` logs in as an operator, fetches the cloud's public key from `GET /api/v1/workers/dispatch-verify-key`, registers the machine and writes `WORKER_CLOUD_API_BASE_URL`, `WORKER_ID`, `WORKER_ORG_ID`, `WORKER_CREDENTIAL` and `WORKER_DISPATCH_VERIFY_KEY` to `.env.local`; it no longer asks for any signing secret, refuses a non-`https://` URL except localhost, and reports failures by status code only. Set the private key in Railway **before** re-registering any worker: without one a non-production cloud generates a new key on every restart. **Revoking a worker**: `POST /api/v1/workers/{id}/revoke` and `/rotate-credential` (operator session, org-scoped, Revoke / Rotate token buttons in the Screaming Frog view). A revoked daemon gets `401` and exits with code 3; rotation shows the new secret once and is the only way to re-enable a revoked worker. **Not done**: the ADR 0028 runbook has not been run — no private key in Railway, no worker re-registered, the shared secret not yet burned, so existing worker desktops still hold a key that can forge dispatches; no overlapping key rotation; no pinned verify-key fingerprint; jobs queued for a revoked, never-rotated worker are never cleaned up; no register-a-machine UI; the standalone `rankuno-worker.exe` is not built |
| Packageable desktop worker — `core/app_paths.py`, `core/credential_vault.py`, `core/url_hosts.py`, `integrations/worker_registration_client.py`, `modules/seo/screaming_frog_control/bundle_filenames.py`, `modules/seo/screaming_frog_control/worker_setup.py` ([ADR 0030](docs/adr/0030-the-worker-ships-as-a-standalone-client.md), [build-log 0135](docs/build-log/0135-a-worker-that-carried-the-engine.md)) | ✅ Implemented & tested; ⚠️ **no executable built yet**. The worker CLI no longer imports engine code: its import closure dropped from 11 engine modules to 0, and `test_worker_import_boundary.py` fails if any `src` module outside `src.core`, the worker integration clients and `screaming_frog_control` loads. When frozen (`sys.frozen`), the worker keeps its state in `%LOCALAPPDATA%\Rankuno\Worker` (`worker.env`, logs, output, templates, both ledgers; `RANKUNO_WORKER_HOME` overrides, frozen only) and reads its credential from Windows Credential Manager (`Rankuno Worker/<worker_id>`), ignoring any `WORKER_CREDENTIAL` in env files. **Setting up a packaged worker**: `rankuno-worker setup` (also run on the first interactive launch) asks for the Rankuno URL (`https://` required except loopback), operator id, password and a PC name, checks the credential store before any network call, fetches the verify key before registering, never retries registration, stores the credential and writes `worker.env` atomically. In a checkout `setup` is refused; use `scripts/register_worker.py`, which is unchanged. A checkout can opt in to the vault with `WORKER_CREDENTIAL_STORE=credential_manager`. `RANKUNO_PROCESS_ROLE=worker` skips production's cloud-secret checks and `create_app` refuses to start under it. **Not done**: PyInstaller build, release workflow and dashboard download (Phase 3, HITL first); explicit Windows ACL on the data folder; uninstall / sign-out; template delivery to a frozen worker; revoking the replaced worker from the client |
| Live progress telemetry for Screaming Frog crawls dispatched through the ADR 0015 worker ([build-log 0100](docs/build-log/0100-mcompleted-twice-with-two-meanings.md)) — `modules/seo/screaming_frog_control/progress_parser.py`, `POST /workers/jobs/{id}/progress` (`api/worker_routes.py`), `alembic/versions/0004_worker_job_progress_columns.py` | ✅ Implemented & tested. Additive to ADR 0015, not part of it — never changes a job's lifecycle `status`. The worker daemon tails its own run's `trace.txt` from a background thread and reports `pages_crawled`/`progress_pct`/`phase` to the cloud, throttled client-side (`ScreamingFrogProgressThrottle`, floor `Settings.worker_progress_min_report_interval_s`) before any network call is attempted — deliberate, because `PostgresWorkerDispatchStore` opens a fresh connection per call with no pool (ADR 0015 condition 5). The feature's own original illustrative progress-line format (`Spidering ... (15 of 120, 12.5%)`) was verified against a real, live `ScreamingFrogSEOSpiderCli.exe 19.4` crawl and found never to occur; the real format is a `SpiderMain` `SpiderProgress [mActive=N, mCompleted=N, mWaiting=N, mCompleted=N.NN%]` line, comma-thousands-separated, with `mCompleted` appearing twice for two different meanings — see the module docstring. `GET /workers/jobs` and `GET /workers/jobs/{id}` gained three new optional `WorkerJobView` fields (`pages_crawled`, `progress_pct`, `current_phase`), all `None` for jobs predating this feature and never guaranteed monotonically increasing. A frontend now consumes this ([build-log 0101](docs/build-log/0101-a-percentage-is-no-longer-invented.md)): `WorkerJobsPanel.tsx` renders a `DispatchProgress` bar (antd `Progress`, `showInfo={false}`) for a `dispatched` job once `progress_pct` is non-null, with no clamping or monotonic-increase assumption, and falls back to the original "no progress detail available" text otherwise. The panel's docstring previously said "There is no progress column and there will not be one" on the grounds that a percentage would be invented; that reasoning is now recorded as obsolete rather than deleted |
| Screaming Frog config templates carry a human-authored description, and stop hiding the files they skip ([build-log 0117](docs/build-log/0117-a-sentence-beside-a-binary.md), [ADR 0021](docs/adr/0021-no-binary-config-upload-to-a-worker.md)) — `core/worker_templates.py`, `modules/seo/screaming_frog_control/template_registry.py` `scan()`, `alembic/versions/0005_worker_template_descriptions.py` | ✅ Implemented & tested. A `.seospiderconfig` is a Java `ObjectInputStream` blob nothing in this system can read, so an operator picking `advance-with-url-parameter` from the dispatch dropdown was choosing on a slug alone. A description now travels worker → cloud → browser as a sidecar `<name>.md` beside each config — one file per template rather than a shared `descriptions.json`, because one unparseable JSON blanks **every** description at once while a bad `.md` costs exactly its own (pinned by test). Read as plain text; **nothing renders it as Markdown**. At most 16 KiB read, whitespace collapsed, over 500 chars truncated **not dropped** and logged, no sidecar renders **nothing** rather than an empty element. **The upload half of RAE's config panel was refused and is not built** (ADR 0021): no upload endpoint, no engine→worker byte channel, and the `DispatchPreviewRequest` → `DispatchPreviewToken` → `DispatchAssignmentClaims` → `WorkerJobEnvelope` → `ScreamingFrogJobInput` chain is byte-identical, so there is no HMAC implication. Also: `TEMPLATE_NAME_PATTERN` (`^[a-z0-9_-]{1,128}$`, unchanged) used to *filter* non-matching filenames silently, so a config saved from the GUI as `SEO Spider Config - Basic.seospiderconfig` vanished and the operator saw an empty dropdown with no explanation; `scan()` now returns `unrecognised` alongside `templates`, with the **filenames logged worker-side only** — the one machine where a human can rename them — and **only the count** crossing the network, because a filename is arbitrary text from outside the trust boundary and can carry a client's name. Security: the description is attacker-controlled text entering a browser, so it is length-capped at three boundaries, rendered as a text node (zero `dangerouslySetInnerHTML` in `rankuno-ui/src`), never interpolated into a log or error, and bidirectional overrides `U+202A`–`U+202E` / `U+2066`–`U+2069` are **refused, not stripped**, at every trust boundary — React escapes HTML, but nothing escapes a right-to-left override, which makes a label render as a string it does not contain. **BREAKING for an un-upgraded daemon**: the heartbeat body changed from `{"template_names": [str]}` to `{"templates": [{name, description}], "unrecognised_count": n}`, and `StrictModel` forbids extras, so an old daemon's heartbeat is refused **422**. It keeps polling, claiming, running jobs and its liveness; only its reported template list stops refreshing until that desktop is updated. Migration 0005 (head `0004`) renames `workers.template_names` → `templates` and rewrites the JSON array of strings as objects in place — the rename is deliberate, because a column still called `template_names` holding objects is how the next person writes a wrong query. **Unverified**: like migrations 0002–0004, 0005 is covered only by an in-memory fake cursor — no Postgres server is reachable from the build workstation |
| A crawl's orphan and sitemap-only URLs dispatched to a worker as a `--crawl-list` file ([ADR 0023](docs/adr/0023-a-url-list-travels-as-a-digest.md), [build-log 0119](docs/build-log/0119-a-list-that-travels-as-a-hash.md)) — `modules/seo/screaming_frog_control/url_list.py`/`worker_url_list.py`, `core/json_stream.py`, `api/url_list_routes.py`, `alembic/versions/0007_worker_dispatch_url_lists.py` | ✅ **Implemented & tested, backend and UI** ([build-log 0120](docs/build-log/0120-an-action-beside-the-download.md)). This row read "no UI consumes it, so it is API-only" until `52532ba`, which was true only between `cc7dac1` and that commit. Screaming Frog's `--crawl` follows links, so it can miss sitemap-only and CMS-only URLs; this engine already holds them. (This row used to say orphans are "exactly what it cannot reach". On saved data 47.6% of orphans had an internal link that Screaming Frog's crawl still did not follow; see [build-log 0127](docs/build-log/0127-a-reason-the-crawl-never-recorded.md).) The list is generated and **frozen at preview time**, because the bytes an operator approves a fingerprint of have to already exist — generating at download time would let the source crawl be deleted or re-run in between. Only the 64-character SHA-256 is signed: it rides inside `DispatchAssignmentClaims`, so the existing dispatch signature covers it with **no change to the signing construction** (an HMAC when this shipped; Ed25519 for upgraded workers since [ADR 0028](docs/adr/0028-dispatch-claims-are-signed-asymmetrically.md)), while the bytes live in a content-addressed `worker_dispatch_url_lists` table and are fetched over the worker's own authenticated, org-scoped channel (`GET /workers/jobs/{id}/url-list` — the only route in this architecture where bytes travel cloud → worker). The digest is deliberately **not** sent in a response header. This is the **first field added to `WorkerJobEnvelope` since ADR 0015** and a documented reversal of its "carries nothing else" stance. Over `SCREAMING_FROG_URL_LIST_MAX_URLS` (default 10,000) the list is **refused, never trimmed** — a truncated list audits fewer pages than the approval says and would destroy the new free-tier truncation check, which is the first thing in this codebase able to tell "crawled exactly 500" from "capped at 500". Off-domain URLs are dropped and *counted*, never a refusal. SSRF is validated at admission **once per unique host**, not per URL, because `UrlSafetyPolicy.validate()` calls an uncached `socket.getaddrinfo`. `core/json_stream.py` reads the URL column without the document: 5.3 MB peak against 292.3 MB for `json.load`, measured on a real 100,687-page, 93 MB result — `PostgresJobStore` does **not** get that property (ADR 0004 deploys the workstation, which uses `DiskJobStore`). Bug caught in review before commit: `issue_dispatch_assignment` was never given the digest, so it defaulted to `None` on every mint and **every approved list dispatch would have run as an ordinary `--crawl` of the seed URL**, unsigned. **Not done**: the worker does **not** re-apply `UrlSafetyPolicy` to entries it downloads — it verifies the digest only — so list-mode SSRF protection is cloud-side admission alone; and migration `0007` has never run against a real database. **The UI half** ([build-log 0120](docs/build-log/0120-an-action-beside-the-download.md)): the reconciliation panel's engine-only gap has a **Run in Screaming Frog** action beside its Download, which opens `ScreamingFrogView.tsx` in list mode on that crawl; `UrlListSourcePicker.tsx` offers "Orphans Only (Recommended)" and "All Discovered URLs" with **availability served, never derived** — an unavailable option renders disabled with the server's own `unavailable_reason`, because an orphan is defined by a saved cross-check and no browser can know whether one exists. Only the crawl id crosses; which URLs is re-decided and re-approved at the launcher. `DispatchConfirmModal.tsx` shows source, post-filter count, the off-domain exclusion with the domain that produced it and a verbatim sample, and echoes the preview `sha256` untouched; `WorkerJobsPanel.tsx` renders `url_list_shortfall: null` as "cannot say" and never as `0`. `MockAdapter` deliberately does not implement `listUrlListSources`. **Unverified**: no browser has rendered any of it — jsdom, `tsc` and the production bundle only, and not one list-mode dispatch has been run end to end |
| `POST /jobs/{id}/cancel` — abandon a running Python crawl ([ADR 0025](docs/adr/0025-cooperative-cancellation-is-python-crawler-only.md), [build-log 0126](docs/build-log/0126-a-flag-checked-before-the-fetch-starts.md)) | ✅ **Cooperative, not instant.** A per-job `threading.Event` on `ApiState` is set before the concurrency slot is released (order is load-bearing — reversed, the flag is already gone by the time it would be looked up). `async_discovery.py` checks it in two places on the DOM crawl path (Path B) only: before a queued fetch claims a concurrency slot, and before a new BFS level begins — so no *new* fetch starts once cancelled. An already-in-flight fetch is not aborted; it runs to completion or hits `REQUEST_DEADLINE_S` (200s), the same disclosed bound the endpoint's own docstring states. Path A (sitemap) and Path C (CMS) discovery are not gated and run to their own completion. Applies to the Python autonomous crawler only — **Screaming Frog dispatches are explicitly out of scope** (ADR 0025): its process poll loop cannot currently distinguish a normal exit from an externally-triggered `terminate()`, so wiring one into the cancel endpoint without fixing that first risks reporting a killed crawl as `SUCCEEDED`. Closes DEF-02 (RAE comparison: RAE's cancel endpoint SIGKILLs its worker before its Redis flag is written, orphaning child processes). ⚠️ **Known race, not fixed here**: `DiskJobStore`/`PostgresJobStore`'s `_transition` has no terminal-state guard, so a cancelled crawl's own fast exit (`store.finish(..., partial=True, error="cancelled by operator")`) now usually overwrites the `FAILED` status `cancel_job`'s `mark_failed()` wrote moments earlier — the recorded final status is typically `PARTIAL`, not `FAILED` |

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

For large crawls through the full UI on this workstation instead of Railway, see
[Running the full site locally for large crawls](#running-the-full-site-locally-for-large-crawls).

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
| The engine found it, Screaming Frog did not | An orphan, split by how this crawl found it (below) | Depends on the reason |
| The engine found it, and it is a file | A PDF, deck, spreadsheet or other document. Screaming Frog lists these on its own tab, not under HTML | Nothing; a difference, not a finding |

An engine-only page that no earlier rule explains (file, trap, malformed
address, query variant) is labelled from the crawl's own `DiscoverySource`
flags, never from the URL string
([ADR 0026](docs/adr/0026-url-provenance-reports-evidence-or-says-unknown.md),
[build-log 0127](docs/build-log/0127-a-reason-the-crawl-never-recorded.md)):

| Reason | What this crawl observed |
| :--- | :--- |
| `LINKED_NOT_IN_EXPORT` | Reached by an internal link; the export does not contain it |
| `SITEMAP_ONLY_NO_LINK` | Listed in a sitemap; no internal link was followed to it |
| `CMS_API_ONLY` | Found only through the CMS API |
| `PROVENANCE_UNKNOWN` | No flags recorded; not guessed |
| `SITEMAP_ORPHAN` (legacy) | Cross-checked before sources were tracked; how it was found is unknown |

No reason claims anything about Screaming Frog's configuration, which the
reconciler cannot see. Until cycle 0127 every one of these was labelled a
sitemap orphan; on 21,910 saved entries only 17.6% were. The set of orphans,
and so what "Orphans Only" list mode sends, did not change.

The downloadable workbook is one sheet per reason: `Summary`, `Missed pages`,
the five `Orphans – …` sheets, then `PDF files`, `Presentations`,
`Spreadsheets`, `Other files`, then, for a bare-list cross-check, one sheet per
`DefaulterCategory` (below), then every other reason by size. Splitting the
files out took infosys.com's Orphans sheet from 8,123 rows to 630
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

# Build one RAE masterfile workbook from a job's Screaming Frog export bundle.
# The id must be an ADR 0015 Screaming Frog worker job with an uploaded bundle; a
# native crawl id is refused 409, because it produces a page-intelligence result
# and not CSVs. The UI sends the worker job id (build-log 0115).
POST   /api/v1/jobs/{job_id}/masterfile/{service_slug}
GET    /api/v1/masterfiles/available
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
web UI page for the deliverable-workbook routes above — only the API; a UI
affordance is a follow-up, tracked as a handoff to `ui-engineer`. The two
masterfile routes are the exception: a "Masterfiles" popover on finished
Screaming Frog rows in `WorkerJobsPanel.tsx` builds and downloads them
([build-log 0115](docs/build-log/0115-a-menu-that-sent-the-wrong-id.md)).

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

Job records persist under `.jobs/` on a workstation with no Postgres configured
(ADR 0004's local-first default), so crawls survive a restart there too. When
Postgres is configured (`DATABASE_URL`/`POSTGRES_URL`/`DATABASE_PRIVATE_URL`, the
Railway deployment case), `PostgresJobStore` is used instead — a job's status,
result, checkpoint and homepage snapshot now survive a container redeploy, not
just its creation record ([ADR 0022](docs/adr/0022-postgres-backed-job-store.md)).
A crawl interrupted mid-run is marked `failed` rather than resumed. Its last
checkpoint (URLs found so far, and since cycle 0127 how each was found) is kept
and renders as a partial tree, but nothing resumes it automatically
([build-log 0019](docs/build-log/0019-checkpoints-and-partial-recovery.md),
[0127](docs/build-log/0127-a-reason-the-crawl-never-recorded.md)). This
paragraph said "there is no within-crawl checkpointing" until cycle 0127.
`POST /jobs/{id}/resume` starts a separate job over the checkpoint's unfetched
URLs; it is not merged into the original
([build-log 0032](docs/build-log/0032-resume-excludes-what-was-already-fetched.md)).
Until cycle 0136 this paragraph said "nothing resumes from it". Until cycle 0137
the async crawl marked a page fetched only when its whole BFS level ended, so a
crawl that died mid-level, and every resumed crawl (one level), checkpointed
fetched pages as unfetched and its resume re-downloaded them. A page now counts
as fetched when its HTML lands; errors and non-HTML responses stay unfetched and
are retried. A resume of a resume can still re-fetch pages the first job fetched
([build-log 0137](docs/build-log/0137-a-page-fetched-a-level-too-late.md)).

The server runs at most 5 crawls at once by default and answers `429` beyond
that; `MAX_CONCURRENT_CRAWLS` (1–10) sets the cap. It limits how many crawls
hold memory, not how much one crawl holds: each in-flight crawl keeps its whole
graph, including every page's HTML, in RAM until the job ends — about 2.2 MiB
per page on sites with ~1 MB pages. `CRAWL_MEMORY_BUDGET_MIB` (default 3072,
256–65536) caps the HTML that async DOM crawls retain in total: when it is
reached, the largest crawl over its fair share (budget / `MAX_CONCURRENT_CRAWLS`)
stops and ends `partial` with "memory budget reached"
([ADR 0031](docs/adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md)).
The default is sized for an 8 GB container (the operator's figure, unverified).
It counts tracked DOM-crawl HTML only, so process memory as a whole is not
bounded by it.

`GET /api/v1/crawl-activity` (same bearer auth, scoped to the caller's org only) returns `{rankuno_active, rankuno_cap, sf_active}`, cached 5 s per org, and feeds the header indicator on every view (polled every 10 s visible / 60 s hidden). The two counts are deliberately separate: the cap governs server-run crawls only, and Screaming Frog worker dispatches are not limited by it ([build-log 0114](docs/build-log/0114-a-count-that-belongs-to-one-org.md)).

A finished crawl's job-row `...` menu offers "Download URLs" alongside
"Search Console", "Cross-check" and "Run again": one click, no intermediate
panel, fetching `GET /jobs/{id}/urls.xlsx` — every URL the crawl found, as a
3-sheet workbook (All URLs, By Indexability, By HTTP Status) built by
`MasterURLReport` (`modules/seo/page_classifier/reports.py`). A "Download URLs
(PDF)" entry sits directly below it, fetching `GET /jobs/{id}/urls.pdf` —
the same "All URLs" columns as a flat, printable table (landscape A4, via
`MasterURLReport.generate_pdf`), for a client deliverable or an email
attachment rather than a spreadsheet ([ADR 0024](docs/adr/0024-pdf-url-export-uses-reportlab-in-core-dependencies.md);
[build-log 0124](docs/build-log/0124-a-pdf-beside-the-workbook.md)). The
"HTTP Status" column both exports show is a genuine absence, not a code —
no per-page HTTP status reaches either report anywhere in the pipeline, so
the column reads `Unknown` rather than substitute the URL
([build-log 0123](docs/build-log/0123-a-status-cell-that-was-a-url-cell.md)).
Until cycle 0130 neither item actually downloaded: the UI called the adapter's
download methods detached from the adapter, so they threw before sending a
request ([build-log 0131](docs/build-log/0131-a-method-called-without-its-object.md)).

### Running the full site locally for large crawls

The Railway container caps memory. For large crawls you can run the whole site,
API and built UI together, on this workstation:

```powershell
.\scripts\run_local.ps1                          # opens http://127.0.0.1:8000/ signed in
.\scripts\run_local.ps1 -Port 8899 -MemoryBudgetMiB 16000
.\scripts\run_local.ps1 -CheckOnly               # run every guard, start nothing
.\scripts\run_local.ps1 -Rebuild                 # force a fresh UI build
.\scripts\run_local.ps1 -NoAutoSignIn            # log in with an operator id and password
```

If the checkout has no `.venv` (a git worktree, for example), pass
`-Python <path to another checkout's .venv\Scripts\python.exe>`.

**Loopback only.** The server binds `127.0.0.1` with one worker. It fetches arbitrary URLs on request, so on a routable interface it
would be an open proxy whatever the login says
([ADR 0008](docs/adr/0008-local-api-layer-and-job-store.md)). The launcher also
sets `API_ALLOWED_HOSTS=127.0.0.1,localhost`, so any other `Host` header gets a
400. That closes the DNS-rebinding path by which a web page in the same browser
could otherwise reach the local server under a foreign host name.

**Signed in on launch.** Once `/api/v1/health` answers, the launcher opens the
default browser already signed in
([ADR 0033](docs/adr/0033-a-local-launch-signs-in-through-a-single-use-loopback-link.md)).
It generates a fresh 32-byte token on every start, in the server's environment
only, and opens `http://127.0.0.1:<port>/#autosignin=<token>`. The token rides in
the URL fragment, which a browser never sends to a server. The UI strips it from
the address bar before any request and exchanges it once at
`POST /api/v1/auth/local-signin` for an ordinary session, with the same lifetime
as a password login.

- The link works once, for five minutes after the server starts, from loopback
  only, and stops working after five wrong tokens. Every refusal is the same
  401; the UI then shows the normal login screen.
- It signs in as the operator `local` in org `default`, which is where local
  crawls live. `-AutoSignInOperatorId` and `-AutoSignInOrgId` change that. If
  the operator does not exist it is created with no usable password, so it can
  never log in by password. If it exists but is inactive or in another org, the
  server refuses to start. The link never signs in as whichever operator
  happens to exist.
- The console prints only `http://127.0.0.1:<port>/`, never the link. If no
  browser can be opened, use normal login at that address.
- `-NoAutoSignIn` turns it off, including a token inherited from the shell.
  `-CheckOnly` reports whether it would be on.
- The route exists only while a token is set. The server refuses a token
  outside `ENVIRONMENT=development` and whenever Postgres is configured, and the
  launcher refuses a dotenv that names `AUTH_LOCAL_AUTOSIGNIN_TOKEN`.
- Residual: while the browser runs, its process command line holds the spent
  link. Do not put a reverse proxy in front of the local server; a proxy on the
  same machine looks like loopback.

**Local data is separate from production.** Jobs go to `.jobs/` (`DiskJobStore`),
and operators, orgs and workers go to `.operators/`, `.orgs/` and `.workers/`, all
in the checkout you run from. Nothing is synced with Railway in either direction.
Run from the main checkout to keep one local history.

**The guard.** A server that saw a production database would choose
`PostgresJobStore`, and its startup orphan recovery would mark every crawl
running on Railway as failed. The launcher prevents that in four steps
([ADR 0032](docs/adr/0032-a-local-server-never-reaches-a-shared-database.md)):

1. It refuses to start if `.env` or `.env.local` names any of `DATABASE_URL`,
   `POSTGRES_URL`, `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
   `REDIS_URL`, `REDIS_PRIVATE_URL` or `ENVIRONMENT`, or sets
   `WORKER_STORE_BACKEND=postgres`. Keys are matched by name in any case,
   with or without an `export` prefix. No value is printed, and the only value
   read is `WORKER_STORE_BACKEND`'s. If you copied `.env.example`, comment out or delete
   the `ENVIRONMENT` line in that file; the launcher always runs `development`.
   It also refuses a dotenv naming `AUTH_LOCAL_AUTOSIGNIN_TOKEN`: a sign-in
   token stored on disk would never expire.
2. In the server's environment it sets `DATABASE_URL`, `POSTGRES_URL`,
   `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`, `REDIS_URL` and
   `REDIS_PRIVATE_URL` to empty strings. A process value beats dotenv, and empty
   counts as unset. (`env -u` is not a substitute: removing a key from the process
   leaves the dotenv value in force.) It also pins
   `ENVIRONMENT=development` and `WORKER_STORE_BACKEND=disk`.
3. It runs Python in that exact environment and requires
   `get_postgres_settings().is_configured()` to be `False` before anything
   listens.
4. It generates a fresh `AUTH_SESSION_SECRET` for every run, in the server's
   environment only. Tokens issued locally therefore never verify anywhere else,
   even if a dotenv carries another key.

**Required versus optional.**

- Required: the Python venv. Node.js 18+ is needed only when the UI has to be
  built. The launcher runs `npm ci` when `rankuno-ui/node_modules` is missing or
  older than `package-lock.json`. If `node_modules` is a junction or symlink
  (common in a git worktree) and needs reinstalling, the launcher stops with
  "node_modules is a link to another folder; refusing to reinstall through it.
  Run npm ci in the link target, or remove the link." `npm ci` deletes
  `node_modules` first, and through a link that empties the folder it points at.
  A link that is current is used as is.
- The UI is rebuilt with `VITE_API_BASE=/api/v1` when `dist` is missing, is
  older than its sources, or was not built by the launcher.
- Search Console and Google Ads credentials are needed only for those features.
- Screaming Frog dispatch routes will error locally. `PostgresWorkerDispatchStore`
  cannot connect, and that is expected.

**First run.** On an empty operator store the launcher creates the operator
`admin` and shows a generated password once on the console. It is never written
to disk. Use `-PromptPassword` to type your own, and use
`scripts\create_operator.py` for more operators. Bootstrap only fires on an empty
store; the `local` sign-in operator is created alongside it, so from then on the
store is never empty and `admin` is not seeded again in that checkout.

**Memory budget.** `CRAWL_MEMORY_BUDGET_MIB` is set to 40% of physical RAM,
clamped to 256–65536. For example, 12990 MiB on a 32 GB machine is a 2598 MiB
fair share across the 5 concurrent crawls. `-MemoryBudgetMiB` overrides it, and
any dotenv value is overridden with a notice. The budget counts retained page
HTML only and is not an OOM guarantee
([ADR 0031](docs/adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md)).
On sites with ~1.1 MB pages that is roughly 5,900 pages across all running crawls
at the measured 2.2 MiB per page (any non-ASCII character in a page, such as one
curly apostrophe, doubles its in-memory size), or about 11,800 if every page is
pure ASCII.

**One worker only.** The rate limiter and the cost ledger are in-process.
A second worker would double both the API quota and the spend ceiling
(CLAUDE.md §8).

**Why the built UI rather than `npm run dev`.** The launcher gives you one
process on one origin. A long-running crawl station therefore has no second dev
server to die overnight, no hot-reload refresh dropping the page mid-crawl, and
no CORS split between ports 5173 and 8000.

**If you ever ran a server locally without this guard** while a dotenv held the
Railway `DATABASE_URL`, check Railway's `jobs` table for crawls your local
startup marked as interrupted:

```sql
SELECT id, status, finished_at FROM jobs
WHERE error LIKE 'interrupted by a server restart%'
ORDER BY finished_at;
```

Compare the `finished_at` times with Railway's deploy times. Rows that match no
deploy were most likely failed by a local startup.

### Copying a finished local crawl to the cloud

A crawl run locally lives only in this workstation's `.jobs/`. To make it a
normal job in your cloud org, push it over the cloud's HTTPS API
([ADR 0034](docs/adr/0034-a-local-crawl-reaches-the-cloud-as-a-terminal-provenance-stamped-import.md)).
The local server does not need to be running.

```powershell
# Which finished crawls can be pushed (newest first)
.\.venv\Scripts\python.exe scripts\push_job_to_cloud.py --list --target groundsguys.com
# Check one without sending anything (writes nothing, not even the instance id)
.\.venv\Scripts\python.exe scripts\push_job_to_cloud.py --job <local id> --dry-run
# Push the newest finished crawl of a site
.\.venv\Scripts\python.exe scripts\push_job_to_cloud.py --latest --target groundsguys.com --cloud-url https://<your-cloud-host>
```

- The cloud URL comes from `--cloud-url` or `CLOUD_IMPORT_BASE_URL`. It must be
  `https://` (plain `http://` only to localhost), and a redirect is refused.
- It prompts for your cloud operator id and password. The password is read
  only from that masked prompt, never from an argument, the environment or a
  file, and it is never stored. The session token lives in memory for the run
  and is dropped at exit. It is valid for 12 hours.
- The job lands in **your** cloud org as `succeeded` or `partial`, with its
  original crawl times, marked "Imported from local". It costs nothing: there is
  no budget check and no ledger charge.
- Pushing the same crawl again is safe: the cloud answers "already imported" and
  changes nothing. If the local job changed in between, the cloud refuses it
  (409) rather than keep two versions.
- Before sending, it applies every check the cloud will apply. A crawl with a
  URL the cloud would refuse (a `javascript:` link, say) is refused locally,
  with the field named.
- An imported job cannot be retried or resumed in the cloud: run it again
  locally and push the new result. Reparse, the workbook deliverable,
  `urls.xlsx`/`urls.pdf` and the result view all work. Masterfiles do not, as
  for every native crawl.
- Limits: 32 MiB gzipped, 128 MiB unpacked (the largest local result, 93 MB,
  is 3.3 MiB gzipped), one import at a time per server, 6 per operator per hour.
  Import memory is not counted by the crawl memory budget: about 1.1 GiB for the
  93 MB result, measured on the development workstation.
- The first real push creates `.jobs/.instance-id`, a random id that lets the
  cloud tell this folder's jobs from another machine's. It holds no hostname.

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
.\.venv\Scripts\python.exe scripts\prune_lessons.py             # Step 8c: keep the newest 5 tutor lessons
```

After the build-log entry (Step 8b), the `tutor` agent (`.claude/agents/tutor.md`, or `/learn`
on demand) writes a senior-architect lesson about the change to `docs/learning/`. That folder is
gitignored and capped at the newest 5 lessons; lessons are private learning notes, not project
history, and are never cited from code or docs
([build-log 0134](docs/build-log/0134-a-tutor-that-explains-every-decision.md)).

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
