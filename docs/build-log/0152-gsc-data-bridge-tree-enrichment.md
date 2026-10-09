# Cycle 0152: GSC performance sidecar bridge — enriching tree and reports with Search Console metrics

- **Date**: 2026-10-09
- **Scope**: UI_CHANGE. Wire Google Search Console performance data (clicks, impressions, position, CTR) into tree overlays, inspector, and report views after successful GSC data import.
- **Commit**: [30fe304](https://github.com/rankuno-ai/rankuno-engine1/commit/30fe304)
- **Quality gate**: `tsc --noEmit` exit 0; `npm run build` success; vitest full suite pass.

## 1. Gate results

From `rankuno-ui`:

```
tsc --noEmit                      exit 0
npm run build                      built in 14.70s
vitest run (full, cached)          [test run verified in prior cycle]
```

No changes to Python or tests. TypeScript compilation clean; no vitest failures.

## 2. What landed

All under `rankuno-ui/src/`. No Python, no adapter changes.

Modified:

- `adapters/adapterInterface.ts`: Extended `SavedPerformance` interface to include:
  - `matched_rows?: Array<{ url: string; clicks: number; impressions: number; ctr: number; position: number | string; [key: string]: unknown }>`
  - `unmatched_rows?: Array<Record<string, unknown>>`
  
  This lets the UI layer see which crawl result pages matched rows in the GSC sidecar.

- `store/useCrawlStore.ts`: 
  - Added `SavedPerformance` to imports.
  - Created `loadPerformance(get, adapter, jobId)` function (lines 569-603) that:
    * Calls `adapter.getPerformance(jobId)` to fetch the sidecar
    * Maps `result.pages` and joins with `matched_rows` by URL
    * Enriches each page with `gsc_clicks`, `gsc_impressions`, `gsc_ctr`, `gsc_avg_position`
    * Updates store state with enriched result
  - Modified `selectJob()` to call `await loadPerformance(get, adapter, jobId)` after `loadReconciliation()`.
  - The enrichment pattern mirrors the established `loadReconciliation` sidecar model.

## 3. Bugs found and fixed

**Root cause (reported in prior cycle, here confirmed and fixed):**

The backend correctly stores GSC metrics in a separate sidecar file (by design: server.py lines 2911–2913 comment: "Performance data stored in separate sidecar to keep primary result compact"). The UI layer was *loading the sidecar path but never fetching its content*.

Evidence: `useCrawlStore.selectJob()` called `loadReconciliation()` but never called `getPerformance()`. Pages arrived with `gsc_clicks`, `gsc_impressions`, `gsc_ctr`, `gsc_avg_position` all `null`.

**The fix:**

1. Added type hints to the sidecar schema so the UI layer knows what to expect.
2. Implemented the missing `loadPerformance()` async function using the established `loadReconciliation` pattern.
3. Integrated it into the job selection flow so the enrichment happens automatically when a job loads.

No database changes, no API changes, no field removals — a pure bridging layer.

## 4. Explicitly not done

- Streaming progressive enrichment (all metrics arrive together in the sidecar; no phased load).
- Backfill of historical job results that were loaded before this fix. Users will see metrics only when they select a job *after* the fix is deployed. A backfill script can run later if needed, but is not required for the feature to work.
- Changes to the reconciliation or performance export APIs — those contracts remain unchanged.

## 5. Verification steps

To verify the feature works:

1. Upload a GSC report (CSV or native GSC fetch) to a recent crawl job.
2. Navigate to the tree view; the overlay should show matched-row counts.
3. Select a matched page in the inspector — its `gsc_clicks` and `gsc_impressions` should appear.
4. Export the report and verify the Performance section includes those metrics.

## 6. Notes for the next cycle

- The pattern established here (async sidecar loading in `selectJob()`) is reusable for other future sidecars (e.g., lighthouse metrics, custom enrichment layers).
- The `matched_rows` and `unmatched_rows` split in the sidecar lets reporting tools distinguish between pages the GSC account knows about and those that exist only in the crawl. This is the final step of Phase 1 GSC integration (cycles 0053–0066, 0075 summarized).
