# Cycle 0055: GSC API Integration — Phase 3 (Client)

**Date**: 2026-09-01  
**Status**: COMPLETE  
**Phase**: 3 of 7  
**Estimated Time**: 1.5h | **Actual**: 1.1h  
**Quality Gate**: ✅ PASSED (ruff, mypy --strict, pytest)

---

## Summary

Implemented Google Search Console API client as a `BaseAPIClient` subclass. Handles property listing and analytics fetching with full rate limiting, token refresh integration, and graceful error degradation.

---

## Files Created

### 1. `src/integrations/gsc_client.py` (NEW)
Production-grade GSC API client with these public methods:

**Key Methods**:
- `authenticate()` — Validate credentials and scopes at init time
- `list_accessible_properties()` → `list[GscProperty]` — Fetch all accessible properties
- `fetch_analytics(property_url, date_range)` → `GscAnalyticsResponse` — Fetch page-level analytics

**Design Decisions**:

1. **Service Building**:
   - Fresh service created per call (no caching) to ensure token is always current
   - Service uses `googleapiclient.discovery.build()` with OAuth2 credentials wrapping our token
   - Token refresh delegated to `GscTokenManager`

2. **Rate Limiting**:
   - Inherits `BaseAPIClient.call()` which enforces token bucket (60 QPM)
   - All API calls go through `self.call(operation, attempt_func)`
   - Rate limiter shared across concurrent properties via `RateLimiterRegistry`

3. **Error Handling**:
   - HttpError mapping happens inside `attempt()` before retry logic
   - Specific errors (`GscPropertyNotFoundError`, etc.) prevent retries
   - Graceful degradation: most errors return empty response, not exceptions
   - Only network/transient errors are retried by BaseAPIClient

4. **URL Normalization**:
   - Property URLs normalized to include trailing `/` for API consistency
   - All page URLs parsed from responses used as-is

5. **Metrics Transformation**:
   - Raw GSC rows transformed to `GscPageMetrics` with CTR calculation
   - CTR clamped to [0, 1] (GSC can return fractional values)
   - Handles zero-impression edge case (CTR = 0 when impressions = 0)

---

## Tests Created

### `tests/integrations/test_gsc_client.py`
**10 test cases** covering:

**Initialization**:
- Valid credentials → client ready (1 case)
- Init validates scopes on construction (1 case)

**List Properties**:
- Multiple properties returned correctly (1 case)
- Empty property list (1 case)
- Error returns empty list (graceful degradation) (1 case)

**Fetch Analytics**:
- Success: rows parsed, CTR calculated (1 case)
- Empty result set (1 case)
- CTR calculation & clamping (1 case)
- Trailing slash handling (1 case)
- Graceful degradation on error (1 case)

**Result**: 10 passed ✅

---

## Quality Checks

### Ruff (Format & Lint)
```
✅ All checks passed
  - Line length ≤ 100 characters (fixed 2 long lines)
  - No unused imports
```

### MyPy (Type Safety)
```
✅ Success: no issues found in 1 source file (--strict mode)
  - type: ignore for googleapiclient (untyped library)
  - All code paths properly typed
```

### Pytest
```
✅ 10 new + 43 Phase 1-2 = 53 total passed
  - tests/integrations/test_gsc_client.py: 10 passed
  - tests/integrations/test_gsc_schemas.py: 15 passed
  - tests/integrations/test_gsc_token_manager.py: 15 passed
  - tests/core/test_gsc_errors.py: 13 passed
  - 100% pass rate
```

---

## Design Decisions

### 1. Fresh Service Per Call (No Caching)
**Decision**: Build Google API service fresh each time token is accessed  
**Why**:
- Token refresh happens per `fetch_analytics()` call via `_get_service()`
- Ensures OAuth2Credentials wraps the latest token (prevents stale-token calls)
- Cost: service discovery is cached by googleapiclient, not rebuilt

### 2. Error Handling Inside attempt()
**Decision**: Map HttpError to specific Gsc exceptions within `attempt()` function  
**Why**:
- HttpError must be caught *before* retry logic (inside attempt)
- 404/403/410/501 are non-retryable; mapping them lets BaseAPIClient skip retries
- Graceful degradation errors (403, 404) caught by outer try/except, return empty response

### 3. Graceful Degradation
**Decision**: Most errors return empty response instead of raising exception  
**Why**:
- Crawl can proceed with Layer 0/1 classification if GSC metrics unavailable
- Property access errors (403, 404) are data issues, not system failures
- Rate limit errors (429) cascade gracefully (crawl slows, eventually succeeds)
- Unexpected errors still logged; empty response maintains data consistency

### 4. Properties Fetched on Demand
**Decision**: `list_accessible_properties()` is separate method; not called by default  
**Why**:
- Caller decides whether they need the property list (useful for validation)
- Most crawls know their property URL; list fetch is optional
- Saves a network round-trip if not needed

---

## Edge Cases Addressed (5 of 18 in Phases 1-3)

| Edge Case | Phase | Safeguard | Status |
|:---|:---|:---|:---|
| 2.1 Quota exhaustion | 3 | Token bucket (60 QPM) + rate limiter | ✅ IMPLEMENTED |
| 3.1 Property not accessible | 3 | 403 caught, empty response, logged | ✅ IMPLEMENTED |
| 3.2 Property deleted | 3 | 404 caught, empty response, logged | ✅ IMPLEMENTED |
| 6.1 Network timeout | 3 | Timeout inherited from BaseAPIClient (30s) | ✅ IMPLEMENTED |
| 6.2 Malformed response | 3 | Pydantic parsing validation in schemas | ✅ IMPLEMENTED |

Remaining 13 edge cases deferred to Phase 4-6 (URL validation, metrics aggregation, tool integration).

---

## Dependency Notes

**New Imports**:
- `googleapiclient.discovery.build` — Google API client factory
- `googleapiclient.errors.HttpError` — HTTP error wrapping
- `google.oauth2.credentials.Credentials` — OAuth2 token wrapper (from google-auth)

**No new dependencies** — all already in `gsc` extra (`pyproject.toml`)

---

## Known Gaps (Deferred to Later Phases)

1. **Property validation** — Phase 4 validates property matches crawl URL
2. **Metrics aggregation** — Phase 5 joins GSC metrics to crawled pages
3. **Concurrent property handling** — Currently fetches one property per call
4. **Caching GSC properties list** — Could cache for duration of crawl
5. **Query parameters** — Currently only queries by page; could add query-level metrics later

---

## Next Phase (Phase 4: URL Validator)

**Scope**: Validate GSC property matches crawl domain  
**Time**: ~1 hour  
**Files**: `src/integrations/gsc_property_validator.py`, tests

**Delivers**:
- `GscPropertyValidator` validates property URL against crawl base URL
- Handles: domain normalization, subdomain matching, URL-prefix properties
- Returns: match status + actionable warning if mismatch

**Blocks On**: Nothing (Phase 3 client is complete)  
**Unblocks**: Phase 5 (metrics aggregator), Phase 6 (tool integration)

---

## Explicitly Not Done

1. **Query-level analytics** — Only page-level supported; queries deferred
2. **Multi-property parallelism** — Called sequentially; parallelism per crawl job
3. **Caching or persistence** — No cache of property lists or metrics
4. **Live Google API calls in tests** — All tests mock googleapiclient
5. **OAuth browser flow** — Service account only; no user consent required

---

## Corrections to Phases 1-2

None. Schemas and token manager remain unchanged and work seamlessly with client.

