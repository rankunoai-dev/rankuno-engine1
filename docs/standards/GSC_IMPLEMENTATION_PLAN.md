# GSC API Integration: Implementation Plan

**Date**: 2026-09-01  
**Status**: READY FOR IMPLEMENTATION  
**Related**: ADR 0010, GSC_EDGE_CASES_BREAKING_POINTS.md

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│          src/integrations/gsc_client.py (NEW)               │
│  - GscApiClient extends BaseAPIClient                       │
│  - Handles OAuth token lifecycle & refresh                  │
│  - Rate-limited analytics fetch per property                │
│  - Error handling per edge case doc                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                   ▼
   ┌─────────────────┐ ┌──────────────┐ ┌──────────────────┐
   │ schemas.py      │ │ errors.py    │ │ config.py        │
   │ (GscMetrics)    │ │ (OAuth errs) │ │ (already exists) │
   └─────────────────┘ └──────────────┘ └──────────────────┘
```

---

## Phase 1: Schemas & Error Types (0.5 hours)

### Files to Create

#### 1.1 `src/integrations/gsc_schemas.py` (NEW)
Pydantic models for GSC API request/response data.

```python
# What we need:
- GscPageMetrics (url, impressions, clicks, avg_position, ctr)
- GscQueryMetrics (query, impressions, clicks, avg_position, ctr, country)
- GscAnalyticsResponse (list of metrics, date range, property)
- GscOAuthToken (access_token, refresh_token, expires_at, scopes)
- GscAuthError (error_code, error_description, is_recoverable)
```

#### 1.2 `src/integrations/errors.py` — ADD new exception types
Extend for OAuth-specific errors.

```python
# What we need:
- GscAuthenticationError (invalid_grant, revoked, expired)
- GscAuthorizationError (property not accessible, scope mismatch)
- GscQuotaExceededError (429, rate limited)
- GscPropertyNotFoundError (404, deleted property)
- GscApiDeprecatedError (410, endpoint gone)
```

---

## Phase 2: OAuth Token Management (1 hour)

### Files to Create

#### 2.1 `src/integrations/gsc_token_manager.py` (NEW)
Manages OAuth token lifecycle.

```python
class GscTokenManager:
    """Handles OAuth token acquisition, refresh, validation."""
    
    def __init__(self, settings):
        # Load credentials from settings
        # Validate they're SecretStr
        pass
    
    def get_or_refresh_token(self) -> str:
        """
        If token valid for > 5 min, return it.
        If expiring soon, refresh using refresh token.
        If refresh fails, raise GscAuthenticationError.
        """
        
    def validate_token_scopes(self) -> None:
        """After successful auth, verify scope is readonly."""
        
    def get_account_email(self) -> str:
        """Fetch authenticated account email from API."""
```

**Edge cases handled**:
- Proactive refresh (1.1)
- Token expiration (1.1)
- Revoked consent (1.2)
- Scope validation (8.2)
- Account email logging (7.4)

---

## Phase 3: GSC Client Base (1.5 hours)

### Files to Create

#### 3.1 `src/integrations/gsc_client.py` (NEW)
Main GscApiClient implementation.

```python
class GscApiClient(BaseAPIClient):
    """Google Search Console API connector.

    Mandatory class vars:
    - service_name = "google.search_console"
    - rate_limit_key = "gsc_quota"
    - requests_per_minute = 60  # 2x headroom per property
    """

    def authenticate(self) -> None:
        """Load credentials via token manager."""

    def list_accessible_properties(self) -> list[str]:
        """Fetch list of GSC properties user has access to.

        Handles:
        - 401 Unauthorized (3.1)
        - 403 Forbidden (3.1)
        """

    def fetch_analytics(
        self, property_url: str, start_date: str, end_date: str
    ) -> GscAnalyticsResponse:
        """Fetch analytics for one property.

        Handles:
        - 404 Not Found (3.2)
        - 403 Property not accessible (3.1)
        - 429 Quota exceeded (2.1)
        - Malformed response (6.2)
        """
```

**Edge cases handled**:
- Property access check (3.1)
- Property not found (3.2)
- Quota exhaustion (2.1)
- Rate limiting (via BaseAPIClient)
- Malformed response (6.2)
- Network timeouts (6.1)

---

## Phase 4: URL Matching & Validation (1 hour)

### Files to Create

#### 4.1 `src/integrations/gsc_property_validator.py` (NEW)
Validates property-to-crawl URL matching.

```python
class GscPropertyValidator:
    """Validates that GSC property matches crawl base URL."""

    def validate_property_match(self, gsc_property: str, crawl_base_url: str) -> tuple[bool, str]:
        """
        Returns: (is_match, warning_message)

        Handles:
        - Domain normalization (4.1)
        - Subdomain matching rules (4.2)
        - URL-prefix vs domain properties (4.3)
        """
```

**Edge cases handled**:
- URL normalization (4.1)
- Subdomain matching (4.2)
- Property type detection (4.3)

---

## Phase 5: Metrics Aggregation & Application (1 hour)

### Files to Create

#### 5.1 `src/integrations/gsc_metrics_aggregator.py` (NEW)
Maps GSC metrics to crawled pages.

```python
class GscMetricsAggregator:
    """Applies GSC analytics to crawl results."""

    def apply_metrics(
        self, pages: list[FullPageIntelligenceProfile], gsc_metrics: list[GscPageMetrics]
    ) -> list[FullPageIntelligenceProfile]:
        """
        Join GSC metrics to pages by URL.

        Handles:
        - Query string variations (5.2)
        - Missing metrics (5.1)
        - Metric lag documentation (5.1, 5.3)
        """
```

**Edge cases handled**:
- Query string normalization (5.2)
- Historical data lag (5.1)
- Incomplete data (5.3)

---

## Phase 6: Tool Integration (0.5 hours)

### Files to Modify

#### 6.1 `src/modules/seo/page_classifier/tool.py` (MODIFY)
Add GSC metric fetching to the crawl tool.

```python
# In BaseCrawlTool.run():
if self._should_fetch_gsc_metrics(base_url):
    try:
        gsc_client = GscApiClient()
        gsc_metrics = gsc_client.fetch_analytics(...)
        result.pages = aggregator.apply_metrics(result.pages, gsc_metrics)
    except (GscAuthenticationError, GscQuotaExceededError) as e:
        logger.warning(f"GSC fetch failed; proceeding without metrics: {e}")
        # Crawl continues with URL-pattern classification only
```

---

## Phase 7: Testing (2 hours)

### Test Files to Create

#### 7.1 `tests/integrations/test_gsc_client.py`
- Token refresh on expiry
- Invalid grant handling
- Property access check
- Property not found (404)
- Quota exceeded (429)
- Network timeout + retry
- Malformed response
- Concurrent property fetches

#### 7.2 `tests/integrations/test_gsc_token_manager.py`
- Token refresh when expiring
- Scope validation
- Account email fetch
- Revoked consent detection

#### 7.3 `tests/integrations/test_gsc_property_validator.py`
- URL normalization matching
- Subdomain mismatch detection
- Property type detection

#### 7.4 `tests/integrations/test_gsc_metrics_aggregator.py`
- Metrics join by URL
- Query string variations
- Missing metrics handling
- Metric lag logging

---

## Implementation Order

**Recommended sequence** (lowest risk, fastest feedback):

1. **Schemas & Errors** (Phase 1) — 0.5h
   - No dependencies, fast validation
   
2. **Token Manager** (Phase 2) — 1h
   - Can mock the Google API for testing
   
3. **GSC Client** (Phase 3) — 1.5h
   - Depends on Phases 1-2
   - Can test against mock API
   
4. **URL Validator** (Phase 4) — 1h
   - No API dependency; pure logic
   
5. **Metrics Aggregator** (Phase 5) — 1h
   - No API dependency; pure logic
   
6. **Tool Integration** (Phase 6) — 0.5h
   - Ties everything together
   
7. **Testing** (Phase 7) — 2h
   - Parallel with implementation

**Total Estimated Time**: ~7 hours  
**Critical Path**: Phases 1-3 (3 hours minimum)

---

## Quality Gates

Before merging, verify:

- [ ] All edge cases from GSC_EDGE_CASES_BREAKING_POINTS.md are handled
- [ ] No `print()` statements; use `get_logger()` (CLAUDE.md §1.4)
- [ ] No `os.environ` reads; use `get_settings()` (CLAUDE.md §1.3)
- [ ] All boundaries use Pydantic `StrictModel` (CLAUDE.md §1.2)
- [ ] Secrets wrapped in `SecretStr`
- [ ] Rate limiter enforced (60 QPM)
- [ ] Retry logic with exponential backoff
- [ ] `scripts/verify.ps1` passes with ≥85% test coverage
- [ ] All tests mock external GSC API (no real Google calls)

---

## Known Limitations (Scope Boundary)

**Phase 1 excludes**:
- OAuth consent flow / browser-based authentication
- Token storage/retrieval from Google OAuth API (assumes service account or pre-obtained token)
- Multi-account switching
- Token refresh via Google OAuth endpoint (assumes `google-auth` library handles it)

These are deferred to Phase 2 (if needed).

