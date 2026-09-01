# Cycle 0057: GSC API Integration — Phase 5 (Metrics Aggregator)

**Date**: 2026-09-01  
**Status**: COMPLETE  
**Phase**: 5 of 7  
**Estimated Time**: 1.0h | **Actual**: 0.6h  
**Quality Gate**: ✅ PASSED (ruff, mypy --strict, pytest)

---

## Summary

Implemented metrics aggregation and enrichment logic for Google Search Console. Joins GSC analytics to crawled pages by URL, returning enriched pages with GSC signals (clicks, position, CTR, impressions). Handles URL normalization, conflict resolution (multiple matches), and graceful error degradation.

---

## Files Created

### 1. `src/modules/seo/page_classifier/gsc_aggregator.py` (NEW)
Production-grade aggregator with four main components:

**Classes**:
- `GscSignals` — Dataclass holding GSC metrics (clicks, impressions, avg_position, CTR)
- `EnrichedPageWithMetrics` — A crawled page with attached GSC metrics and match metadata
- `AggregationResult` — Result envelope with matched/unmatched pages, GSC URLs, and validation errors
- `GscMetricsAggregator` — Main orchestrator

**Key Method**:
- `aggregate(property_url, crawl_base_url, gsc_response, pages)` → `AggregationResult`
  - Validates property matches crawl using Phase 4 validator
  - Matches GSC URLs to crawled pages (exact + prefix matching)
  - Aggregates metrics when multiple GSC URLs match one page
  - Returns enriched pages with signals or gracefully degrades on error

**URL Matching Strategy** (in order):
1. **Exact match** — GSC URL == page URL (after normalization)
2. **Prefix match** — GSC URL is parent path of page URL
3. **No match**

**Normalization**:
- Strip query parameters
- Strip fragments
- Lowercase domain for comparison
- Trailing slash handling

**Conflict Resolution**:
- Multiple GSC URLs → 1 page: Sum clicks/impressions, weighted-average position
- 1 GSC URL → multiple pages: Not possible (exact match is greedy)

---

## Tests Created

### `tests/modules/seo/page_classifier/test_gsc_aggregator.py`
**16 test cases** across 9 test classes:

**GscSignals Tests** (3):
- Create from single metric
- Aggregate multiple metrics (conflict resolution)
- Aggregate empty list (edge case)

**Exact Matching** (2):
- Same URL exact match
- Query parameter stripping

**Prefix Matching** (1):
- GSC parent path matches page child path

**Conflict Resolution** (1):
- Multiple GSC URLs → 1 page aggregation

**URL Normalization** (3):
- Trailing slash normalization
- Case-insensitive domain matching
- Query/fragment stripping

**Property Validation** (1):
- Validation failure cascades to all URLs unmatched

**Edge Cases** (4):
- Empty GSC metrics
- Empty crawl
- No matches anywhere
- Mixed matched/unmatched

**Metadata** (1):
- Enriched pages track matched GSC URLs

**Result**: 16 passed ✅

---

## Quality Checks

### Ruff (Format & Lint)
```
✅ All checks passed
  - Line length ≤ 100 characters
  - No unused imports
  - All code paths formatted
```

### MyPy (Type Safety)
```
✅ Success: no issues found in 56 source files (--strict mode)
  - Full aggregator and tests properly typed
  - No type: ignore comments needed
```

### Pytest
```
✅ 16 new + 1655 prior = 1671 total passed
  - tests/modules/seo/page_classifier/test_gsc_aggregator.py: 16 passed
  - Full suite: 1671 passed
  - 100% pass rate on Phase 5
```

### Coverage
```
✅ 95.21% total (threshold: 85%)
  - gsc_aggregator.py: 95% (5 lines missed, 2 branch variants)
  - All critical paths covered
```

---

## Design Decisions

### 1. Greedy URL Matching (First Match Wins)
**Decision**: Match GSC URL to first matching crawled page; don't try all matches  
**Why**:
- Prevents ambiguity when one GSC URL could match multiple pages
- Prioritizes exact match, then prefix match (natural hierarchy)
- No artificial "best match" scoring

### 2. Metric Aggregation on Conflict
**Decision**: When multiple GSC URLs match one page, sum clicks/impressions, weighted-average position  
**Why**:
- Sum is analytically correct (total traffic to page across variants)
- Position: weighted by impressions reflects visibility distribution
- Alternative ("best" URL) would lose signal and be arbitrary

### 3. Graceful Degradation on Property Mismatch
**Decision**: Return validation error + all URLs unmatched; don't raise exception  
**Why**:
- Caller (aggregator caller, not yet implemented) can distinguish between "bad input" (exception) and "metrics unavailable for this crawl" (error in result)
- Keeps aggregation non-blocking: crawl continues if GSC join fails
- Matches Phase 4 validator design pattern

### 4. URL Normalization Before Comparison
**Decision**: Normalize inline (strip query, fragment, lowercase domain) before matching  
**Why**:
- Prevents false negatives from minor URL differences
- GSC normalizes URLs the same way; matching should too
- Normalization is deterministic and fast

### 5. Eager URL → Page Indexing
**Decision**: Build `page_by_url` dict upfront rather than linear search per metric  
**Why**:
- O(1) lookup per GSC URL instead of O(n*m) for n metrics, m pages
- Crawls can be large (20k-500k pages); linear search becomes painful
- Small upfront cost for big throughput gain

---

## Edge Cases Addressed (8 of 18 from Phase Analysis Doc)

| Edge Case | Approach | Status |
|:---|:---|:---|
| 5.1 Empty GSC metrics | Return all pages unmatched with null signals | ✅ |
| 5.2 Empty crawl | Return no matches, all GSC URLs unmatched | ✅ |
| 5.3 Property validation fails | Return error, don't attempt any matching | ✅ |
| 5.4 Multiple GSC URLs → 1 page | Sum clicks/impressions, weighted-avg position | ✅ |
| 5.5 Query parameter in GSC URL | Normalize before matching | ✅ |
| 5.6 Fragment in GSC URL | Normalize before matching | ✅ |
| 5.7 Trailing slash mismatch | Normalize before matching | ✅ |
| 5.8 Case-sensitive domain | Lowercase for comparison | ✅ |

Remaining 10 defer to Phase 6-7 (tool integration, end-to-end tests).

---

## Known Gaps (Deferred to Phase 6-7)

1. **Caching validation results** — Validator is called once; no repeat benefit (not needed for Phase 5)
2. **Subdomain with path matching** — Property `example.com/blog/` vs crawl `blog.example.com/other/` (out of scope)
3. **URL encoding handling** — Not normalizing percent-encoding (basic comparison works)
4. **Internationalized domains (IDN)** — Not punycode-decoding (GSC uses punycode anyway)
5. **Multi-currency metrics** — Not handling regional rollups (single aggregation only)
6. **Redirect chain matching** — Not following crawl redirects to match GSC (would require redirect graph)
7. **Filtering metrics by date range** — Phase 3 response already filtered; aggregator doesn't re-filter
8. **Metrics persistence** — Not storing enriched pages; in-memory result only
9. **Bulk aggregation** — Processes one property at a time; no batch mode
10. **Conflict notifications** — Multiple matches not surfaced to caller (could add in Phase 6)

---

## Bugs Found and Fixed

### None
All test cases passed on first run after fixing missing `depth_from_l0` in test fixtures (not an aggregator bug; test setup issue).

---

## Corrections to Phases 1-4

None. All prior phases remain unchanged and integrate seamlessly:
- Phase 4 validator used directly; works as designed
- Phase 3 API client response structure (GscAnalyticsResponse) understood and consumed
- FullPageIntelligenceProfile schema read correctly; no mismatches

---

## Next Phase (Phase 6: Tool Integration)

**Scope**: Wire aggregator into the crawl tool  
**Time**: ~0.5 hours  
**Files**: `src/modules/seo/page_classifier/tool.py`, update endpoints

**Delivers**:
- Crawl tool accepts optional `gsc_property_url` parameter
- If provided, fetches GSC metrics after crawl (via Phase 3 client)
- Aggregates metrics to crawled pages (via Phase 5 aggregator)
- Enriched pages returned in result

**Blocks On**: Phase 5 (complete)  
**Unblocks**: Phase 7 (end-to-end tests)

---

## Explicitly Not Done

1. **Async I/O in aggregator** — Synchronous matching appropriate (CPU-bound, no network)
2. **Retry on aggregation failures** — Caller handles retry if needed
3. **Logging per URL match** — Would be verbose for 20k pages; warning-level only on validation failure
4. **Metric validation** — Phase 3 API client validates; aggregator assumes valid input
5. **Dedupe GSC URLs** — Assuming Phase 3 response is deduplicated
6. **URL canonicalization** — Not rewriting URLs; matching as-provided by GSC and crawl
7. **Cross-property aggregation** — Single property per call; caller orchestrates multi-property
8. **Metric time-decay** — No weighting by freshness; equal treatment of all metrics
9. **Signal confidence scoring** — No scoring; signals are either present (matched) or absent (unmatched)
10. **Fallback matching strategies** — Exact + prefix is sufficient; no domain-only or path-only fallback

---

## Breaking Points Tested

✅ **Empty inputs**: No pages, no metrics, no domains  
✅ **URL mismatches**: Domain mismatch, path mismatch, partial path  
✅ **Normalization**: Trailing slashes, query params, fragments, case differences  
✅ **Aggregation**: One metric per page, multiple metrics per page, zero metrics  
✅ **Validation failure**: Property-crawl incompatibility correctly cascades  
✅ **Type safety**: All code paths properly typed under --strict mode

