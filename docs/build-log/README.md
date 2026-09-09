# 📓 Build Log — Implementation Cycle Records

One entry per implementation cycle, written at the close of SDLC Step 8 and
committed alongside the code it describes.

---

## Why this exists

ADRs record **what was decided**. Git history records **what changed**. Neither
records the thing that is most expensive to lose: **why the code looks the way it
does, what was tried, what broke, and what was deliberately left undone.**

A build-log entry captures:

- Reasoning that would otherwise survive only in a chat transcript.
- Bugs found during implementation and what the fix actually was — including
  bugs in the specification, not just in the code.
- Corrections to earlier claims. A wrong number that was published and then
  quietly fixed is worse than one that was never published.
- Work explicitly **not** done, so a later reader does not mistake a gap for an
  oversight, or an oversight for a gap.

The audience is a future engineer or agent with no memory of the session —
which, for an AI-assisted codebase, is every session.

---

## Index

| Cycle | Date | Title | Gate |
| :--- | :--- | :--- | :--- |
| [0001](0001-governance-foundation-and-safety-core.md) | 2026-08-06 | Governance foundation & Phase 1 safety core | 248 tests, 96.91% |
| [0002](0002-weight-seam-and-classification-pipeline.md) | 2026-08-07 | Weight-profile seam & classification pipeline | 424 tests, 96.59% |
| [0003](0003-http-fetcher-and-site-profiling.md) | 2026-08-07 | HTTP fetcher & site profiling | 475 tests, 95.95% |
| [0004](0004-three-path-merged-discovery.md) | 2026-08-07 | 3-path merged discovery | 554 tests, 94.99% |
| [0005](0005-governed-crawl-tool.md) | 2026-08-07 | Governed crawl tool | 583 tests, 95.10% |
| [0006](0006-async-crawl-and-tree-report.md) | 2026-08-07 | Concurrent crawl & hierarchy report | 638 tests, 94.50% |
| [0007](0007-first-live-run.md) | 2026-08-07 | First live run — 3 findings | 640 tests, 94.56% |
| [0008](0008-dom-budget-reserve.md) | 2026-08-07 | DOM discovery budget reserve | 646 tests, 94.55% |
| [0009](0009-golden-corpus.md) | 2026-08-07 | Golden corpus & evaluation harness | 705 tests, 94.92% |
| [0010](0010-draft-label-worksheets.md) | 2026-08-07 | Draft worksheets & multi-archetype crawls | 742 tests, 94.95% |
| [0011](0011-cms-pagination.md) | 2026-08-07 | Multi-page CMS retrieval | 777 tests, 95.15% |
| [0012](0012-live-api-and-unlimited-depth.md) | 2026-08-10 | Live API, job store, unlimited depth | 877 tests, 95.65% |
| [0013](0013-blocked-crawl-honesty.md) | 2026-08-10 | Blocked crawls fail instead of reporting success | 891 tests, 95.48% |
| [0014](0014-navigation-hierarchy.md) | 2026-08-11 | Header-navigation grouping and OTHERS | 943 tests, 95.57% |
| [0015](0015-navigation-dashboard.md) | 2026-08-11 | Navigation dashboard; browser mode actually works | 949 tests, 95.66% |
| [0016](0016-crawl-telemetry.md) | 2026-08-11 | Live crawl telemetry: progress, ETA, URL stream | 966 tests, 95.71% |
| [0017](0017-crawl-speed-and-unlimited-pages.md) | 2026-08-11 | Crawl speed presets; optional page ceiling | 987 tests, 95.74% |
| [0018](0018-stall-detection-and-partial-results.md) | 2026-08-11 | Bounded requests, stall detection, partial results | 992 tests, 95.75% |
| [0019](0019-checkpoints-and-partial-recovery.md) | 2026-08-11 | Crawl checkpoints, IPv6 parse fix, partial-tree recovery | 1,010 tests, 95.69% |
| [0020](0020-non-page-url-filtering.md) | 2026-08-12 | Media URLs stop entering the graph as pages; PDF export | 1,050 tests, 95.62% |
| [0021](0021-crawl-traps-and-background-jobs.md) | 2026-08-12 | Spider-trap refusal, www site identity, background jobs | 1,096 tests, 95.67% |
| [0022a](0022-webflow-dropdown-tabs-and-blank-ua-fix.md) | 2026-08-12 | Webflow DOM dropdown tabs, leaf pruning, menu duplicate fix | 1,113 tests, 95.70% |
| [0022b](0022b-navigation-coverage-counts-breadcrumbs.md) | 2026-08-19 | Nav coverage counts breadcrumbs; KPI cards match the tree | 1,238 tests, 95.17% |
| [0023](0023-placement-fidelity.md) | 2026-08-17 | Self-referential breadcrumbs, mega-menu nesting, duplicate URLs | 1,202 tests, 95.43% |
| [0024](0024-job-capacity-provenance-and-cancellation.md) | 2026-08-19 | Placement provenance, job capacity checks, and cancellation semantics | 1,212 tests, 95.39% |
| [0025](0025-fragment-id-dropdown-panels.md) | 2026-08-19 | Fragment-ID mega-menu dropdown panel detection | 1,218 tests, 95.39% |
| [0026](0026-homepage-sidecar-and-reparse-endpoint.md) | 2026-08-19 | Homepage HTML sidecar storage and zero-network re-parse endpoint | 1,231 tests, 95.19% |
| [0027](0027-site-report-structural-depth-truncation.md) | 2026-08-19 | Site report structural container filtering & print spooler fix | 1,236 tests, 95.19% |
| [0028](0028-screaming-frog-merge-and-optional-reconcile.md) | 2026-08-19 | Screaming Frog gap merge, optional reconcile endpoint & CLI | 1,280 tests, 95.21% |
| [0029](0029-malformed-url-refusal-and-reconcile-ui.md) | 2026-08-19 | Markup-artefact URL refusal; Screaming Frog upload & gap panel | 1,315 tests, 95.29% |
| [0030](0030-ui-component-test-runner.md) | 2026-08-19 | UI Component Test Runner (Vitest + React Testing Library) | 1,320 tests, 94.98% |
| [0031](0031-native-xlsx-excel-reconciliation-support.md) | 2026-08-20 | Native .xlsx Excel Spreadsheet Support in Reconciler & API | 1,329 tests, 95.37% |
| [0032](0032-resume-excludes-what-was-already-fetched.md) | 2026-08-20 | Resume skips already-fetched URLs instead of re-crawling the site | 1,354 py + 23 ui |
| [0033](0033-menus-that-declare-their-own-depth.md) | 2026-08-20 | Nav items declaring their own top level are promoted to roots | 1,369 py + 23 ui |
| [0034](0034-focus-graph-overlap-in-the-others-lane.md) | 2026-08-20 | Focus graph stops stacking chain and children in the OTHERS lane | 1,369 py + 29 ui |
| [0035](0035-the-orphan-worklist.md) | 2026-08-20 | Orphans become a filterable, exportable worklist split by discovery path | 1,372 py + 43 ui |
| [0036](0036-duplicate-sets-as-a-worklist.md) | 2026-08-20 | Duplicate URL sets become an exportable worklist, clustered per page | 1,388 py + 57 ui |
| [0037](0037-one-address-spelled-two-ways.md) | 2026-08-20 | normalize_path folds percent-encoding, ending a false duplicate finding | 1,398 py + 65 ui |
| [0038](0038-expand-one-branch-not-the-whole-tree.md) | 2026-08-20 | Whole-branch expand/collapse on any tree row; honest whole-tree labels | 1,398 py + 76 ui |
| [0039](0039-the-google-url-join.md) | 2026-08-21 | Google URL to crawled page: alias index, match rate, duplicate profiles found | 1,430 py + 76 ui |
| [0040](0040-rolling-metrics-up-the-nav-tree.md) | 2026-08-21 | Section rollups: whole-trail keys, weighted position, nothing dropped | 1,458 py + 76 ui |
| [0041](0041-what-the-data-would-not-support.md) | 2026-08-21 | Opportunity scorer; depth_from_l0 found to hold path depth, not click depth | 1,481 py + 76 ui |
| [0042](0042-the-file-search-console-actually-gives-you.md) | 2026-08-21 | Search Console upload, sidecar and panel; the export is a ZIP of localised tabs | 1,526 py + 88 ui |
| [0043](0043-the-refusal-that-described-the-wrong-file.md) | 2026-08-21 | A refusal that names what it found, after a real upload of the wrong GSC report | 1,527 py + 98 ui |
| [0044](0044-the-first-real-export.md) | 2026-08-21 | First real GSC export: spam subdomains surfaced, three scorer defects fixed | 1,530 py + 101 ui |
| [0045](0045-the-buttons-that-could-not-win.md) | 2026-08-21 | A global button reset was silently discarding component styling | 1,526 py + 90 ui |
| [0046](0046-a-download-per-section.md) | 2026-08-21 | Per-section CSV export; the panel's sections are not the visualizer's tabs | 1,530 py + 103 ui |
| [0047](0047-showing-the-other-585-rows.md) | 2026-08-21 | Both halves of the join downloadable; subdomain split from off-site | 1,537 py + 107 ui |
| [0048](0048-a-finding-that-is-not-about-a-page.md) | 2026-08-21 | Indexed uncrawled subdomains become a critical finding; severity added | 1,568 py + 131 ui |
| [0049](0049-lp-demo-is-not-a-language.md) | 2026-08-21 | A hyphenated segment is a locale only when one half is a real language | 1,568 py + 131 ui |
| [0050](0050-where-the-unfetched-urls-went.md) | 2026-09-01 | A per-outcome fetch ledger; 442 URLs that were counted nowhere | 1,572 py + 131 ui |
| [0051](0051-a-file-behind-every-number.md) | 2026-09-01 | A download behind every cross-check figure; the agreement list was discarded | 1,576 py + 135 ui |
| [0052](0052-one-sheet-per-question.md) | 2026-09-01 | The cross-check becomes a workbook, one sheet per reason | 1,581 py + 135 ui |
| [0053](0053-gsc-api-phase-1-schemas-errors.md) | 2026-09-01 | GSC API integration Phase 1: Pydantic schemas & error types | 28 tests, 100% |
| [0054](0054-gsc-api-phase-2-token-manager.md) | 2026-09-01 | GSC API integration Phase 2: OAuth token lifecycle management | 43 tests, 100% |
| [0055](0055-gsc-api-phase-3-client.md) | 2026-09-01 | GSC API integration Phase 3: API client with rate limiting & error handling | 53 tests, 100% |
| [0056](0056-gsc-api-phase-4-url-validator.md) | 2026-09-01 | GSC API integration Phase 4: Property URL validation | 96 tests, 100% |
| [0057](0057-gsc-api-phase-5-metrics-aggregator.md) | 2026-09-01 | GSC API integration Phase 5: Metrics aggregation to crawled pages | 1671 tests, 95.21% |
| [0058](0058-gsc-api-phase-6-tool-integration.md) | 2026-09-01 | GSC API integration Phase 6: Tool integration with enrichment | 1678 tests, 95.21% |
| [0060](0060-gsc-api-phase-7-integration-tests.md) | 2026-09-01 | GSC API integration Phase 7: End-to-end integration tests | 1690 tests, 95.21% |
| [0061](0061-gsc-api-phase-8-ui-integration.md) | 2026-09-02 | GSC API integration Phase 8: UI display & analyst insights | 1690 py + 143 ui |
| [0062](0062-one-sheet-per-reason-everywhere.md) | 2026-09-02 | Gap and recommendation downloads split one sheet per reason, not one flat list | 1,697 py + 143 ui |
| [0063](0063-oauth-token-manager-implementation.md) | 2026-09-02 | OAuth token manager implementation per ADR 0010 (user login, not service account) | 1700 py + 143 ui |
| [0064](0064-gsc-oauth-and-config-integration.md) | 2026-09-03 | GSC OAuth and config integration complete | 1702 py + 143 ui |
| [0065](0065-navigation-context-classifier.md) | 2026-09-03 | Navigation context classifier for discovery method and reachability tier | 1705 py + 143 ui |
| [0066](0066-gsc-integrated-report-ui.md) | 2026-09-04 | GSC Integrated Report UI — unified table of metrics + navigation context | 1705 py + 176 ui |
| [0067](0067-where-the-redirect-goes.md) | 2026-09-03 | Sitemap redirects render their destination and hop count, with a CSV | 1705 py + 151 ui |
| [0068](0068-what-a-page-permits-and-what-google-did.md) | 2026-09-07 | Every URL labelled indexable / non-indexable, read against Search Console | 1705 py + 177 ui |
| [0069](0069-cross-check-overlay-and-full-screen-tree.md) | 2026-09-07 | Tree marks and counts what Screaming Frog missed; full-screen tree with section totals and the OTHERS insight | 1705 py + 202 ui |
| [0070](0070-collapse-where-the-tree-is.md) | 2026-09-07 | Expand/collapse moved into the tree's own controls, so full screen has them | 1705 py + 206 ui |
| [0071](0071-clickable-page-links-in-tree.md) | 2026-09-07 | Page rows in the tree link to their URL in a new tab; row stops being a `<button>` | py gate not run + 211 ui |
| [0072](0072-a-list-is-not-an-export.md) | 2026-09-08 | A bare URL list cross-checks as a set: every gap `UNKNOWN`, never merged, format declared | 1,813 py + 226 ui |
| [0073](0073-not-measured-is-a-value.md) | 2026-09-08 | `AuditDataset` contract and the 110-row issue catalogue as typed data (ADR 0011, P0-1/P0-2); D1 applied per field; two rows unresolved by D1 flagged | 1,813 py + 226 ui (see §1.4) |
| [0074](0074-absent-is-not-empty.md) | 2026-09-08 | Screaming Frog export → `AuditDataset` (P0-3/P0-5): absent file is `NOT_MEASURED`, header-only is `MEASURED`; links never retained; `extra=` log fields found to be dropped | 1,964 py + 232 ui |
| [0075](0075-which-search-console-account.md) | 2026-09-08 | Named Search Console account profiles selected per crawl; names-only API; admission refuses an unknown profile (ADR 0012) | 93.86% cov; 1,964 py (scribe run, §1.3) + 232 ui |
| [0076](0076-a-pdf-is-not-an-orphan.md) | 2026-09-08 | Engine-only PDFs, decks, spreadsheets and other files get their own reason and sheet; infosys orphans 8,123 to 630 | 1,964 py + 232 ui |
| [0077](0077-screaming-frog-adapter-and-zip-guards.md) | 2026-09-08 | Screaming Frog adapter & streaming zip guards (P0-3/P0-5); 1,000 member cap, 2 GB file / 8 GB bundle limits; `links = ()` with note | 1,964 py + 232 ui |
| [0078](0078-the-fields-that-never-left-the-call-site.md) | 2026-09-08 | `get_logger` dropped every caller `extra=` field since the first commit; merging adapter, caller keys win | **RED**: 3 failed / 1,967 py (failures in another session's `test_server.py`, §1.2) + 232 ui; 93.81% |
| [0079](0079-sixteen-measured-ninety-four-not.md) | 2026-09-08 | Engine adapter (P0-4): profiles → `AuditDataset`, 16 measured / 94 `NOT_MEASURED`, `CANONICALS_MISSING` unmeasurable (D-A); import-boundary test (P0-6) in all directions | **RED**: 1 failed / 2,012 py (one of the 0078 §1.2 `test_server.py` set, §1.3) + 232 ui; 93.91% |
| [0080](0080-recovery-had-no-way-to-say-it-was-done.md) | 2026-09-09 | Orphan-recovery race fixed: `ApiState.recovery_done` (`threading.Event`) makes startup recovery's completion observable instead of racing it; closes the 0078/0079 `test_server.py` handoff | **GREEN**: 2,020 py + 232 ui; 93.92% |
| [0081](0081-an-oracle-for-membership-only.md) | 2026-09-09 | RAE differential check (P0-7): `scripts/diff_against_rae.py` reimplements `load_url_set`'s column/size rules independently, reuses the real SF adapter, filters the four documented differences; `Settings.rae_archive_dir` opt-in; Phase 0 (P0-1–P0-8) now fully done | **GREEN**: 2,033 py + 232 ui; 93.92% |
| [0082](0082-phase-1-tool-registry-facet-router.md) | 2026-09-09 | Phase 1 Tool Registry & Facet Router: per-facet concurrency isolation, FacetRouter dispatch, stubs for Health Engine and Theme Classification | **RED**: 6 failed / 2,093 passed, 232 ui; 93.50% |
| [0083](0083-a-rulebook-that-never-says-low.md) | 2026-09-09 | Rulebook engine (P1-1–P1-4): order-independent classify(), N/A never Low, missing rulebook fails loud unless `lenient=True` | rulebook.py: 50 tests, 100% cov, green in isolation; whole-repo **RED** carried from 0082 (6 pre-existing `test_server.py` failures, unrelated) — 2,096 passed, 232 ui; 93.56% |


---

## Writing an entry

Copy the structure below. Numbering is sequential and never reused.

```markdown
# Cycle NNNN: <title>

- **Date**: YYYY-MM-DD
- **Scope**: one sentence
- **Commit**: <sha or "uncommitted at time of writing">
- **Quality gate**: <verbatim summary line>

## 1. Gate results
## 2. What landed          (per module: what it does, and WHY it is shaped that way)
## 3. Design decisions      (the choice, the alternatives, the reason)
## 4. Bugs found and fixed  (including spec bugs)
## 5. Corrections           (anything previously stated that turned out wrong)
## 6. Explicitly not done   (with the reason, so gaps read as decisions)
## 7. Files changed
## 8. Follow-ups
```

### Rules

1. **Write it in the same change as the code.** A log written later is a
   reconstruction, and reconstructions omit the parts that were embarrassing.
2. **Record failures, not just outcomes.** A test that caught a real bug is more
   useful to a future reader than three that passed first time.
3. **State what is not done, and why.** Section 6 is not optional. Most
   misunderstanding of this codebase will come from someone assuming a declared
   contract has an implementation behind it.
4. **Never revise history.** If a later cycle proves an earlier entry wrong,
   correct it in the *new* entry's §5 and leave the original intact.
5. **Numbers must be real.** Paste gate output; do not summarise it from memory.
