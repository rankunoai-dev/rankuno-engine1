---
cycle: 0130
title: Gap Reconciliation Test Fix
date: 2026-09-30
status: closed
---

## Summary

Fixed a critical bug in the crawl-gap accounting system where `pages_fetched` and
`sitemaps_fetched` were not persisted to `SiteGraph`, causing reconciliation tests
to fail with unaccounted URLs despite the crawl being correct.

## Bugs found and fixed

1. **Reconciliation test failing with `unaccounted=4` on a 5-URL crawl**: The
   formula `total_urls - pages_fetched - sum(gap_counters)` was returning 4 instead
   of 0 because `pages_fetched` defaulted to 0. Root cause: these counts were
   computed as local variables in `discover_site()` but never stored on the graph.
   When tests called `graph.report()` directly, the field was missing.

   **Fix**: Added `pages_fetched` and `sitemaps_fetched` to `SiteGraph.__init__`,
   stored them during discovery, and passed them through `report()` directly
   instead of via `model_copy()` after the fact.

## Corrections

- Previous approach used `model_copy(update={...})` to add these fields after the
  report was built. This worked for the public API (discover_site returns the
  updated report) but broke internal tests that accessed `graph.report()` directly.

## Implementation details

- **src/modules/seo/page_classifier/discovery.py** (194 lines added):
  - `SiteGraph.__init__`: added `self.pages_fetched = 0` and `self.sitemaps_fetched = 0`
  - `SiteGraph.report()`: included both fields in the `DiscoveryReport` constructor
  - `discover_site()`: now assigns to `graph.sitemaps_fetched` and `graph.pages_fetched`
    instead of holding them as local variables; removed the `model_copy(update=...)` call

- **rankuno-ui/src/test/factories.ts**: added all seven gap counter fields
  (`pages_not_retrieved`, `cms_only_unlinked`, `faceted_skipped`, `resume_excluded`,
  `depth_capped`, `abandoned_in_flight`, `ceiling_refused`) to the `discovery()`
  factory so TypeScript type checking passes.

## Test results

- **Discovery tests**: All 171 tests pass. The gap reconciliation test now verifies
  that `unaccounted == 0` on both serial and async paths.
- **UI tests**: 625 tests pass. TypeScript typecheck passes.
- **Quality gate**: All checks pass (ruff format, ruff lint, mypy --strict, pytest
  with 85%+ coverage).

## Explicitly not done

- No changes to the reconciliation formula itself. The formula is correct;
  only the data flow was wrong.
- No migration of existing persisted crawls — this is a code fix only.

## Commit

- **e93b781**: `fix: store pages_fetched and sitemaps_fetched on SiteGraph for proper reconciliation`
