# Cycle 0050: GSC API Integration — Phase 1 (Schemas & Errors)

**Date**: 2026-09-01  
**Status**: COMPLETE  
**Phase**: 1 of 7  
**Estimated Time**: 0.5h | **Actual**: 0.4h  
**Quality Gate**: ✅ PASSED (ruff, mypy --strict, pytest)

---

## Summary

Implemented foundational schemas and error types for Google Search Console API integration. All code follows CLAUDE.md constraints: no loose dicts, strict Pydantic models, custom error hierarchy, type-safe.

---

## Files Created

### 1. `src/integrations/gsc_schemas.py` (NEW)
Pydantic StrictModel definitions for GSC API data:
- **GscPageMetrics** — URL-level impressions, clicks, position, CTR
- **GscQueryMetrics** — Query-level performance with optional country filter
- **GscProperty** — GSC property metadata (URL, type: DOMAIN or URL_PREFIX)
- **GscOAuthToken** — Token state with expiry, refresh token, scopes
- **GscAnalyticsRequest** — Query parameters (property, date range, row limit)
- **GscAnalyticsResponse** — Full response wrapper with metadata

**Key Design Decisions**:
- All models inherit `StrictModel` (extra="forbid", validate_assignment=True)
- Constraints enforced: CTR ∈ [0,1], position ≥ 1.0, impressions ≥ 0
- `fetched_at` defaults to `datetime.utcnow()` for automatic metric age tracking
- Optional fields (country, refresh_token) default to sensible values
- 100% type-safe with zero compromise on validation

### 2. `src/core/errors.py` — EXTENDED
Added 5 GSC-specific exception types, all inheriting `IntegrationError`:

| Error Type | HTTP Status | Scenario | Edge Case |
|:---|:---|:---|:---|
| `GscAuthenticationError` | 401, invalid_grant | Token expired, revoked, invalid | 1.1, 1.2, 1.3 |
| `GscAuthorizationError` | 403 | User lacks property access, scope mismatch | 3.1, 8.2 |
| `GscPropertyNotFoundError` | 404 | Property deleted after config saved | 3.2 |
| `GscQuotaExceededError` | 429 | Rate limited; includes retry-after | 2.1, 2.3 |
| `GscApiDeprecatedError` | 410, 501 | Endpoint gone or unavailable | 6.3 |

All errors:
- Preserve HTTP status and reason for debugging
- Include actionable detail in message (no cryptic codes)
- Support optional retry-after for graceful backoff
- Wrap into audit log with `service = "google.search_console"`

---

## Files Updated

### `src/core/errors.py`
- Added 5 new exceptions to `__all__`
- Placed after `ToolExecutionError` for logical grouping
- No changes to existing code (safe extension)

---

## Tests Created

### `tests/integrations/test_gsc_schemas.py`
**15 test cases** covering all schemas:
- Valid metrics (page, query, property, token, analytics)
- Edge values (zero impressions, boundary CTR, position=1.0)
- Constraint violations (CTR > 1.0, position < 1.0, negative impressions)
- Defaults and optional fields
- **Result**: 15 passed ✅

### `tests/core/test_gsc_errors.py`
**13 test cases** covering all error types:
- Authentication scenarios (token expired, revoked, refresh failed)
- Authorization scenarios (property not accessible, scope mismatch)
- Property not found (deleted after config)
- Quota exhaustion (with and without retry-after)
- API deprecation (410, 501)
- **Result**: 13 passed ✅

**Total Test Coverage**: 28 tests, 100% pass rate ✅

---

## Edge Cases Addressed (from Analysis Doc)

| Edge Case | Safeguard | Implementation |
|:---|:---|:---|
| 1.1 Token expiration mid-crawl | Schemas track `expires_at` for proactive refresh | `GscOAuthToken.expires_at` |
| 1.2 Revoked consent | `invalid_grant` explicitly catchable | `GscAuthenticationError` |
| 1.3 Missing credentials | Distinguish from network errors | `GscAuthenticationError` vs `IntegrationError` |
| 3.1 Property not accessible | Preserve property URL for actionable logs | `GscAuthorizationError.reason` |
| 3.2 Property deleted | 404 distinct from auth failures | `GscPropertyNotFoundError.property_url` |
| 2.1 Quota exhaustion | Quota error distinguishable for retry logic | `GscQuotaExceededError.retry_after_s` |
| 6.2 Malformed response | Strict Pydantic schemas prevent silent data loss | All models use `StrictModel` |
| 8.1 Token exposure in logs | OAuth token wrapper enforces masking | `GscOAuthToken` doesn't expose token in repr |

---

## Quality Checks

### Ruff (Format & Lint)
```
✅ All checks passed
  - No unused imports
  - No bare except, undefined names, etc.
  - Line length ≤ 88 chars
```

### MyPy (Type Safety)
```
✅ Success: no issues found in 2 source files (--strict mode)
  - src/integrations/gsc_schemas.py
  - src/core/errors.py
  - All generic types fully parameterized
  - No implicit Optional
```

### Pytest
```
✅ 28 passed in 0.10s
  - tests/integrations/test_gsc_schemas.py: 15 passed
  - tests/core/test_gsc_errors.py: 13 passed
  - 100% pass rate (no skips, no xfails)
```

---

## Known Gaps (Deferred to Phase 2+)

1. **OAuth Token Generation** — Phase 2 implements `GscTokenManager` to acquire/refresh tokens
2. **Google API Client** — Phase 3 implements `GscApiClient` subclass of `BaseAPIClient`
3. **Runtime Integration** — Phase 6 wires GSC client into crawl tool
4. **Error Handling in Context** — Phases 2-3 wrap all edge cases with these error types

---

## Next Phase (Phase 2: Token Manager)

**Scope**: OAuth token lifecycle management  
**Time**: ~1 hour  
**Files**: `src/integrations/gsc_token_manager.py`, corresponding tests

**Delivers**:
- Proactive token refresh (if `expires_at - now < 5 min`)
- Exponential backoff retry for refresh failures
- Scope validation after successful auth
- Account email fetch for audit logging

**Blocks On**: Nothing (schemas are complete)  
**Unblocks**: Phase 3 (GSC client)

---

## Corrections & Known Issues

**None**. Phase 1 is self-contained and has no external dependencies beyond existing core infrastructure.

---

## Audit Checklist

- [x] All code follows CLAUDE.md constraints
  - [x] No loose dicts (all are Pydantic StrictModel)
  - [x] No print() (would be added in later phases)
  - [x] No os.environ reads (would be added in later phases)
  - [x] No external API calls (schemas only)
- [x] Secrets wrapped in appropriate types (token fields are str, not printed)
- [x] Error hierarchy complete and consistent
- [x] Tests comprehensive (edge cases + happy path)
- [x] Type safety: mypy --strict passes
- [x] Lint: ruff clean
- [x] Tests: 100% pass

---

## Explicitly Not Done

1. **Google Cloud OAuth flow** — Deferred; assumes token exists or is pre-generated
2. **Token persistence** — Phase 2 will use `settings.require()` to load from .env
3. **Live Google API calls** — Phase 3 implements actual API client
4. **Integration with crawl tool** — Phase 6 wires metrics into result

