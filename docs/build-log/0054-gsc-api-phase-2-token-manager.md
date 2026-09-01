# Cycle 0054: GSC API Integration — Phase 2 (Token Manager)

**Date**: 2026-09-01  
**Status**: COMPLETE  
**Phase**: 2 of 7  
**Estimated Time**: 1.0h | **Actual**: 0.7h  
**Quality Gate**: ✅ PASSED (ruff, mypy --strict, pytest)

---

## Summary

Implemented OAuth token lifecycle management for Google Search Console API. Handles service account authentication, proactive token refresh, scope validation, and graceful error handling.

---

## Files Created

### 1. `src/integrations/gsc_token_manager.py` (NEW)
OAuth token lifecycle manager with these responsibilities:

**Core Methods**:
- `authenticate()` — Loads service account credentials from settings (email + private key)
- `get_or_refresh_token()` — Returns valid token, refreshing proactively if expiring within 5 minutes
- `validate_scopes()` — Verifies token has read-only GSC scope
- `get_account_email()` — Returns authenticated service account email
- `get_token_state()` — Inspects current token for logging/debugging

**Design Decisions**:
- **Proactive refresh window**: 5 minutes before expiry. Prevents mid-crawl token expiration
- **Service account credentials**: Uses `google.oauth2.service_account.Credentials` (not OAuth3/user flow)
- **Fail-fast on refresh**: Refresh failures raise `GscAuthenticationError` (non-retryable; caller halts crawl)
- **Memory-only tokens**: No persistence; loaded fresh per crawl from settings
- **No-return guarantee**: All code paths return `str` token or raise exception (type-safe)

**Edge Cases Addressed**:
- Token refresh failure (1.1) → `GscAuthenticationError`
- Missing credentials (1.3) → `ConfigurationError` at init
- Malformed credentials (1.3) → `ConfigurationError` at init
- Invalid scopes (8.2) → `GscAuthorizationError` from `validate_scopes()`
- Token with no value after refresh → explicit error

### 2. `pyproject.toml` — EXTENDED
Added new optional dependency group:
```toml
gsc = [
    "google-auth>=2.32,<3.0",
    "google-api-python-client>=2.100,<3.0",
    "requests>=2.32,<3.0",
]
```

**Why separate extra?**
- Integrations that don't use GSC shouldn't require Google dependencies
- Allows `pip install rankuno-automation[gsc]` for GSC users
- Follows project's philosophy of minimal core dependencies

---

## Tests Created

### `tests/integrations/test_gsc_token_manager.py`
**15 test cases** covering:

**Initialization**:
- Valid credentials → manager ready
- Missing client email → `ConfigurationError`
- Missing private key → `ConfigurationError`
- Malformed private key → `ConfigurationError`

**Token Retrieval**:
- Valid, non-expiring token → returned without refresh (1 case)
- Token expiring within 5 min → proactive refresh triggered (1 case)
- Token valid for > 5 min → no refresh needed (1 case)
- Refresh failure → `GscAuthenticationError` raised (1 case)
- Refresh succeeds but returns no token → explicit error (1 case)

**Scope Validation**:
- Correct scope present → passes (1 case)
- Required scope missing → `GscAuthorizationError` (1 case)
- Multiple scopes with required one → passes (1 case)
- Empty scopes → `GscAuthorizationError` (1 case)

**Account Email & State**:
- `get_account_email()` returns correct email (1 case)
- `get_token_state()` returns `GscOAuthToken` with current state (1 case)

**Result**: 15 passed ✅

---

## Quality Checks

### Ruff (Format & Lint)
```
✅ All checks passed
  - No unused imports (removed unused json, timedelta)
  - Type-safe token returns (str(token) conversion)
```

### MyPy (Type Safety)
```
✅ Success: no issues found in 1 source file (--strict mode)
  - Explicit type: ignore for untyped google-auth calls (unavoidable; google-auth not fully typed)
  - All code paths return str or raise exception
```

### Pytest
```
✅ 15 passed + 28 from Phase 1 = 43 total
  - tests/integrations/test_gsc_token_manager.py: 15 passed
  - tests/integrations/test_gsc_schemas.py: 15 passed
  - tests/core/test_gsc_errors.py: 13 passed
  - 100% pass rate (no skips, no xfails)
```

---

## Design Decisions

### 1. Service Account vs OAuth3 User Flow
**Decision**: Service account (`Credentials.from_service_account_info`)  
**Why**: 
- No user browser interaction needed (works in CI/automation)
- Credentials are rotatable via service account key management
- Scope is fixed at service account level (cannot change at runtime)
- Aligns with ADR 0010's "official company account" requirement

### 2. Proactive Refresh Window (5 Minutes)
**Decision**: Refresh if `expires_at - now < 5 minutes`  
**Why**:
- Google tokens are valid for 1 hour (3600s). 5-min window is ~1.4% overhead
- Prevents scenarios where token expires mid-API-call (1.1 edge case)
- Gives time for refresh retry if first attempt fails
- Safe margin: even 3 concurrent retries (3s + 6s + 12s = 21s) succeed with time to spare

### 3. Fail-Fast on Refresh Failure
**Decision**: Raise `GscAuthenticationError`, don't retry in token manager  
**Why**:
- Refresh failure means credentials are invalid (not a transient network issue)
- Retrying here would add complexity; caller (crawl) already has retry logic
- Easier to audit: token refresh failures are explicit, not hidden in retry loops
- Forces caller to decide: halt crawl or proceed without GSC metrics

### 4. Memory-Only Token Storage
**Decision**: Load from settings, keep in memory, discard after crawl  
**Why**:
- No file I/O or keyring calls during token refresh
- Settings already handles credential loading from .env / OS keyring
- Simpler test surface (no mock filesystems)
- Token lifetime (1 hour) is shorter than crawl duration anyway; refresh happens in-memory

---

## Edge Cases Addressed (5 of 18 from Analysis Doc)

| Edge Case | Phase | Safeguard | Status |
|:---|:---|:---|:---|
| 1.1 Token expires mid-crawl | 2 | Proactive refresh at 5-min window | ✅ IMPLEMENTED |
| 1.2 Revoked consent | 2 | Distinct `GscAuthenticationError` for invalid_grant | ✅ READY FOR PHASE 3 |
| 1.3 Missing credentials | 2 | `ConfigurationError` at init; crawl halts with clear message | ✅ IMPLEMENTED |
| 8.2 Token scope mismatch | 2 | `validate_scopes()` checks for readonly; logs warning | ✅ IMPLEMENTED |
| 1.4 Multiple Google accounts | 2 | `get_account_email()` provides audit trail | ✅ IMPLEMENTED |

Remaining 13 edge cases are deferred to Phase 3+ (API client, property validation, metrics, etc.)

---

## Known Gaps (Deferred to Phase 3)

1. **Actual API calls** — Phase 3 implements `GscApiClient` that uses tokens from here
2. **Token refresh retry logic** — Currently fail-fast; Phase 3 caller adds retry if needed
3. **Live Google API integration** — Tests use mocks; Phase 3 adds real API tests
4. **OAuth consent flow** — Assumes credentials already exist; user-facing flow deferred
5. **Multi-account switching** — Credential is single account per crawl; switching not implemented

---

## Dependencies Added

| Package | Version | Why | Notes |
|:---|:---|:---|:---|
| `google-auth` | 2.32–2.x | Service account credential handling | Full type stubs available; type: ignore needed for deprecated methods |
| `google-api-python-client` | 2.100–2.x | (Phase 3 uses this; adding now) | Not used in Phase 2 but required for Phase 3 |
| `requests` | 2.32–2.x | Transitive dep of google-auth | google-auth requires requests for `Request()` transport |

**Installation**:
```bash
pip install rankuno-automation[gsc]
```

---

## Next Phase (Phase 3: GSC Client)

**Scope**: HTTP API client for GSC analytics  
**Time**: ~1.5 hours  
**Files**: `src/integrations/gsc_client.py`, corresponding tests

**Delivers**:
- `GscApiClient` extends `BaseAPIClient` (subclasses base_client, not token_manager)
- `fetch_analytics(property, date_range)` → `GscAnalyticsResponse`
- `list_properties()` → list of accessible GSC properties
- Property access validation (edge case 3.1)
- Rate-limited API calls (60 QPM, respects BaseAPIClient token bucket)
- Error handling for 404, 403, 429, etc.

**Blocks On**: Nothing (Phase 2 token manager is complete)  
**Unblocks**: Phase 4 (URL validator), Phase 5 (metrics aggregator), Phase 6 (tool integration)

---

## Explicitly Not Done

1. **Browser-based OAuth flow** — Service accounts only; no user consent screen
2. **Token rotation** — Credentials rotate via service account key management in Google Cloud Console
3. **Multi-service-account support** — One account per crawl; no selection UI
4. **Refresh retry logic** — Caller's responsibility; token manager fails fast
5. **Token caching across crawls** — Each crawl loads fresh; no inter-process state

---

## Corrections to Phase 1

None. Phase 1 schemas and error types are unchanged and work perfectly with Phase 2.

