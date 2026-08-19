# Cycle 0024: Placement provenance, job capacity checks, and cancellation semantics

- **Date**: 2026-08-19
- **Scope**: Land placement provenance tracking (`trail_source`), fix job queue capacity checks to prevent refusal ghost records, and implement `POST /jobs/{id}/cancel` with honest thread cancellation semantics.
- **Commit**: `dae958a`
- **Quality gate**: `1,212 passed`, `Total coverage: 95.39%`

## 1. Gate results

```
=== Format ===
PASSED: Format

=== Lint ===
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.39%
1212 passed, 1 warning in 87.45s
ALL GATES PASSED.
```

UI, separately: `tsc --noEmit` clean.

---

## 2. What landed

### A. Placement Provenance Tracking (`trail_source`)
- Added `trail_source: Literal["menu", "breadcrumb", "none"]` to `FullPageIntelligenceProfile` in `src/modules/seo/page_classifier/schemas.py`.
- Exported updated TypeScript contracts to `rankuno-ui/src/lib/schemas.ts` via `scripts/export_ui_contract.py`.
- Preserved placement evidence origin inside `_better_trail()` (`tool.py`) when menu or breadcrumbs win precedence, enabling the UI drawer to explicitly display whether structural placement was menu-derived or published DOM breadcrumb-derived.

### B. Job Queue Capacity & Refusal Ghost Records
- **Problem**: Previously, `_start` created a job record in `.jobs/` *before* checking capacity limit. When max capacity (`max_active_jobs=3`) was reached, it marked that brand-new record as `FAILED` on refusal, generating ghost refusal records (16% of total job history) that were indistinguishable from genuine crawl failures.
- **Fix**: Capacity is now checked and claimed *first* against a provisional ID before minting the real job record. Refusals return HTTP 429 without polluting the stored job history.

### C. Job Cancellation (`POST /jobs/{id}/cancel`) and Worker Thread Semantics
- Implemented `POST /jobs/{id}/cancel` endpoint and UI **Kill** button (with red styling and confirmation modal).
- **CRITICAL TECHNICAL LIMITATION (`asyncio.to_thread`)**:
  > [!IMPORTANT]
  > Cancelling a job releases the concurrency slot immediately and marks the job record as cancelled (`cancelled by operator — the crawl thread may still be running until it finishes or the server restarts`).
  > Because Python worker threads launched via `asyncio.to_thread` cannot be killed asynchronously from the outside, the underlying thread continues running in the background until the crawl loop completes or the server restarts. The thread's results are cleanly ignored once cancelled.

---

## 3. Orphaned Job Startup Cleanup
- Verified that server startup automatically recovers orphaned jobs left in a `RUNNING` state by an abrupt process restart, marking them `FAILED`.
- Test context updated so test fixtures set job state `RUNNING` inside active client context.
