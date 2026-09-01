# GSC API Integration: Edge Cases & Breaking Points Analysis

**Date**: 2026-09-01  
**Scope**: Risk identification before GSC client implementation  
**Related**: ADR 0010 (GSC API Integration Security, Quota & Account Safety Controls)

---

## 1. Authentication & Credential Lifecycle

### Edge Cases

#### 1.1 OAuth Token Expiration During Long Crawl
**Risk Level**: HIGH  
**Scenario**: A crawl runs for 2+ hours. OAuth access token (valid for 1 hour) expires mid-crawl.

**Breaking Point**:
- GSC API call returns `401 Unauthorized`
- Refresh token must be used to acquire new access token
- If refresh token is stale/revoked, entire GSC flow fails
- Any in-flight requests before token refresh fail

**Safeguard**:
- Implement proactive token refresh: refresh if `expires_at - now < 5 minutes`
- Wrap token refresh in retry logic (exponential backoff, max 3 retries)
- If refresh fails, emit `IntegrationError` with clear message: `"GSC token refresh failed; re-authenticate"`
- Do NOT attempt API call if token is invalid

#### 1.2 User Revokes OAuth Consent Between Crawls
**Risk Level**: MEDIUM  
**Scenario**: User revokes Rankuno's access in Google Account → Settings → Connected Apps. Next crawl tries to fetch GSC data.

**Breaking Point**:
- Refresh token becomes invalid
- API returns `401 Unauthorized` or `invalid_grant` error

**Safeguard**:
- Catch `invalid_grant` errors explicitly
- Log with actionable message: `"OAuth consent revoked; user must re-authenticate at /auth/gsc"`
- Return empty metrics gracefully (allow crawl to proceed with URL-pattern-only classification)
- Do NOT crash the entire crawl

#### 1.3 Credentials File Deleted or Lost
**Risk Level**: MEDIUM  
**Scenario**: User deletes `.env.local` or system keyring is cleared. Next crawl needs GSC data.

**Breaking Point**:
- `settings.require("google_search_console_private_key")` raises `ConfigurationError`
- No way to recover without manual re-authentication

**Safeguard**:
- Catch `ConfigurationError` in GSC client initialization
- Emit non-blocking warning: `"GSC credentials not configured; audit will use URL patterns only"`
- Return empty metrics instead of crashing
- Do NOT require GSC credentials for crawl to proceed

#### 1.4 Multiple Google Accounts on Same Workstation
**Risk Level**: MEDIUM  
**Scenario**: User has personal Gmail and company Google Workspace account. Which one does Rankuno authenticate with?

**Breaking Point**:
- OAuth flow could authenticate with wrong account
- "Verify account has access to client GSC properties" check fails
- User thinks they've authenticated, but API calls will fail

**Safeguard**:
- After OAuth flow completes, immediately fetch account email via `webmaster_center_api.sites()`
- Log account email: `"Authenticated as: {email}"`
- If email doesn't match expected domain (config option), emit warning
- Allow user to force logout and reauthenticate

---

## 2. Quota Management & Rate Limiting

### Edge Cases

#### 2.1 Client Has Multiple Properties; Quota Exhaustion on One
**Risk Level**: HIGH  
**Scenario**: Rankuno fetches Analytics for 10 client sites. Each site gets 120 QPM; total is 1200 QPM (the quota cap). While fetching site #5, sites #1-4 generate a burst of parallel queries.

**Breaking Point**:
- Requests to sites #6-10 hit `429 Too Many Requests`
- Exponential backoff retries delay crawl completion
- User sees slow/incomplete GSC data

**Safeguard**:
- Token bucket rate limiter: enforce 60 QPM per GscApiClient instance (2x headroom from 120 QPM per property)
- If multiple properties are fetched, each must wait for the bucket
- Monitor actual response times; log warning if `429` occurs: `"GSC quota exhausted; reducing request rate"`
- Cascade back to Layer 0 classification if GSC data unavailable (crawl succeeds with degraded intel)

#### 2.2 Burst Traffic: Parallel Crawls Hitting Same Property
**Risk Level**: MEDIUM  
**Scenario**: User starts 3 concurrent crawls of the same client property. All three fetch GSC analytics simultaneously.

**Breaking Point**:
- Token bucket is per-client, not shared across crawl jobs
- Each job gets 60 QPM, total = 180 QPM (3x the quota per property)
- Google rate-limits; crawl becomes slow

**Safeguard**:
- Document: "Concurrent crawls of same property share GSC quota in RateLimiterRegistry"
- Token bucket is global (shared across jobs with same `rate_limit_key`)
- Crawl jobs automatically serialize GSC calls via the shared bucket
- Expected behavior: 3 concurrent crawls will each run at ~20 QPM (60 / 3)

#### 2.3 Google Temporarily Disables Quota on the Account
**Risk Level**: LOW  
**Scenario**: Google detects suspicious activity and temporarily caps quota to 0 QPM as a safety measure.

**Breaking Point**:
- Every GSC API request returns `403 Quota Exceeded`
- Exponential backoff + retries eventually exhaust retry budget
- Crawl stalls on GSC fetch attempts

**Safeguard**:
- After 3 consecutive `403 Quota Exceeded` responses, emit alert: `"GSC quota disabled; contact Google Support"`
- Fall back to Layer 0/Layer 1 classification (allow crawl to proceed)
- Do NOT retry indefinitely

---

## 3. Property Access & Authorization

### Edge Cases

#### 3.1 User Authenticated, but Property Not Accessible
**Risk Level**: HIGH  
**Scenario**: User owns Company A's Google Workspace account. Rankuno is configured to fetch analytics for Company B's GSC property.

**Breaking Point**:
- OAuth succeeds with Company A credentials
- API call to fetch Company B's property returns `403 Forbidden`
- User believes authentication worked but gets no data

**Safeguard**:
- After successful authentication, list accessible properties: `webmaster_center_api.sites().list()`
- Store list in memory
- When fetching analytics for a property, check: `property in accessible_properties`
- If not accessible, emit error: `"Property {property} not accessible to authenticated account {email}"`
- Return empty metrics; allow crawl to proceed

#### 3.2 Property Deleted from GSC After Config Was Saved
**Risk Level**: MEDIUM  
**Scenario**: User configured Rankuno for `example.com`. Later, they delete the property from GSC. Next crawl tries to fetch analytics.

**Breaking Point**:
- API returns `404 Not Found` for the property
- No historical data available

**Safeguard**:
- Catch `404 Not Found` errors explicitly
- Log: `"Property {property} not found in GSC; may have been deleted. Update configuration if this is incorrect."`
- Return empty metrics; crawl proceeds

#### 3.3 Property Requires Domain Verification; Verification Pending
**Risk Level**: MEDIUM  
**Scenario**: GSC property exists but hasn't been verified yet.

**Breaking Point**:
- API returns `403` or `400` indicating verification required
- No data available

**Safeguard**:
- Catch this error pattern
- Log: `"Property {property} requires verification in GSC. Complete verification at https://search.google.com/search-console"`
- Return empty metrics

---

## 4. URL Matching & Property-to-Crawl Mapping

### Edge Cases

#### 4.1 GSC Property != Crawl Base URL
**Risk Level**: MEDIUM  
**Scenario**: User configured GSC property as `https://www.example.com` but crawl base_url is `https://example.com` (no www).

**Breaking Point**:
- URL normalization might match or not match depending on implementation
- Metrics fetched for `www.example.com` cannot be reliably mapped to pages crawled under `example.com`

**Safeguard**:
- Normalize both property and crawl base_url using same logic: `normalize_url(property)` vs `normalize_url(crawl.base_url)`
- If they don't match after normalization, emit warning: `"GSC property {property} doesn't match crawl base {base_url}. Metrics may not apply correctly."`
- Allow mapping to proceed but flag affected pages/metrics

#### 4.2 User Provides Subdomain Property; Crawl is Superdomain
**Risk Level**: MEDIUM  
**Scenario**: GSC property is `https://blog.example.com`. Crawl includes `https://example.com`, `https://shop.example.com`, etc.

**Breaking Point**:
- Metrics from `blog.example.com` should NOT be applied to pages from other subdomains
- Naive URL matching could incorrectly attribute blog metrics to shop pages

**Safeguard**:
- Enforce strict domain matching: `page.domain == property.domain` (no subdomain fallthrough)
- Document: "GSC property must match crawl domain exactly. A property for `blog.example.com` will not match pages under `shop.example.com`."

#### 4.3 GSC Property Uses URL Prefix; Crawl Uses Domain Property
**Risk Level**: MEDIUM  
**Scenario**: GSC has a URL-prefix property `https://example.com/us/` and a domain property `https://example.com/`. Rankuno is configured to one but crawl might need data from both.

**Breaking Point**:
- Data from `/us/` prefix won't match pages under `/de/` or `/`
- Incomplete picture of site performance

**Safeguard**:
- Configuration should specify exact GSC property URL (not domain)
- Validate on init: query the property to get its canonical URL from GSC
- Log warnings if property type is domain vs URL-prefix

---

## 5. Data Consistency & Metric Application

### Edge Cases

#### 5.1 GSC Data is Historical; Crawl is Real-Time
**Risk Level**: MEDIUM  
**Scenario**: Crawl fetches page inventory today. GSC metrics are from last 28 days (lag up to 2 days). A page may be in crawl but not in recent GSC metrics (or vice versa).

**Breaking Point**:
- Metric join on URL might fail or produce incomplete rows
- User sees "0 impressions" for indexed pages

**Safeguard**:
- Document: "GSC metrics have 2-day lag and 28-day retention. A newly indexed page may not appear in GSC for 2 days."
- When applying metrics, use fuzzy matching: if URL matches but no metric, show as "data pending"
- Explicitly document metric age in report

#### 5.2 Query-String Variations in GSC vs Crawl
**Risk Level**: MEDIUM  
**Scenario**: GSC treats `?foo=1&bar=2` and `?bar=2&foo=1` as same URL. Crawl normalizes the same way, but a third-party data source has different normalization.

**Breaking Point**:
- Metrics might be attributed to wrong page if normalization is inconsistent

**Safeguard**:
- Use centralized URL normalization: all GSC URLs, crawl URLs, and third-party URLs go through `normalize_url()` in `src/modules/seo/page_classifier/url_rules.py`
- Document the normalization rules used

#### 5.3 GSC Metrics Arrive Incomplete (Google Data Processing Lag)
**Risk Level**: LOW  
**Scenario**: User runs crawl on Monday. GSC hasn't finished processing Friday/Saturday data yet. Analytics call returns partial data.

**Breaking Point**:
- Metrics look incomplete but are actually just delayed

**Safeguard**:
- Log metric fetch date: `"Fetched GSC metrics as of {last_updated_date}"`
- Document in report: "Data may be incomplete if less than 2 days old"

---

## 6. Error Handling & Graceful Degradation

### Edge Cases

#### 6.1 Network Timeout During GSC Fetch
**Risk Level**: MEDIUM  
**Scenario**: Request to GSC API times out after 30 seconds. Retry logic kicks in, then exponential backoff delays recovery.

**Breaking Point**:
- Crawl stalls waiting for GSC metrics
- User perceives system as broken

**Safeguard**:
- Set reasonable timeout: 30 seconds per GSC request (inherited from `settings.default_timeout_s`)
- Retry max 3 times with exponential backoff (1s, 2s, 4s)
- Total max delay: ~7 seconds
- If all retries fail, log `IntegrationError` and return empty metrics
- Crawl proceeds with URL-pattern classification only

#### 6.2 GSC API Returns Partial/Malformed Response
**Risk Level**: MEDIUM  
**Scenario**: GSC returns valid JSON but is missing expected fields (e.g., `queries` array is empty when `rows` is not).

**Breaking Point**:
- Parsing fails; entire metrics import fails

**Safeguard**:
- Use strict Pydantic models for response parsing
- If response doesn't match schema, log warning: `"GSC response is malformed or unexpected format"`
- Return empty metrics; crawl proceeds
- Never crash on unexpected response structure

#### 6.3 GSC API Endpoint Changed or Deprecated
**Risk Level**: LOW  
**Scenario**: Google deprecates an API version or endpoint. Our calls start returning `410 Gone` or `501 Not Implemented`.

**Breaking Point**:
- All GSC calls fail permanently

**Safeguard**:
- Catch `410` and `501` explicitly
- Emit alert: `"GSC API endpoint deprecated or unavailable; check Google documentation"`
- Return empty metrics
- Allow crawl to proceed with cached metrics if available

---

## 7. Concurrency & Job Management

### Edge Cases

#### 7.1 Job Cancellation While GSC Fetch is In-Flight
**Risk Level**: MEDIUM  
**Scenario**: User cancels a crawl job while it's waiting for GSC metrics.

**Breaking Point**:
- GSC request continues in background (wastes quota)
- Job state becomes inconsistent

**Safeguard**:
- Implement job cancellation handler
- On cancellation, set a flag that GSC fetch checks: `if job.cancelled: return empty_metrics`
- Log cancellation

#### 7.2 Resume After Partial Crawl (Checkpoint)
**Risk Level**: MEDIUM  
**Scenario**: Crawl ran for 1 hour, fetched GSC metrics for properties 1-5, then crashed. User resumes. Should we re-fetch metrics for 1-5?

**Breaking Point**:
- Re-fetching wastes quota
- Or skipping re-fetch means metrics are missing if crawl restarted

**Safeguard**:
- Checkpoint stores which properties had metrics fetched
- On resume, skip already-fetched properties
- Log: `"Resume: skipping GSC metrics for {already_fetched}; fetching {remaining}"`

---

## 8. Security & Compliance

### Edge Cases

#### 8.1 Credential Exposure in Logs
**Risk Level**: HIGH  
**Scenario**: Logging library accidentally logs the OAuth access token or refresh token.

**Breaking Point**:
- Credentials are exposed in audit logs (public or stored)

**Safeguard**:
- All OAuth tokens are wrapped in `SecretStr`
- Never log the token value directly
- Log only the token's ID or hash: `"Using token {hash(token)[:8]}"`
- Audit logging uses `SecretStr` repr (masked automatically)

#### 8.2 User Manually Edits .env and Adds Wrong Token
**Risk Level**: MEDIUM  
**Scenario**: User copies a personal OAuth token (from another project) into `GOOGLE_SEARCH_CONSOLE_PRIVATE_KEY`.

**Breaking Point**:
- Token has wrong scopes or is invalid
- API calls fail with cryptic error

**Safeguard**:
- After authentication, validate token scopes: request should be `readonly`
- Log a warning if scope is not `readonly`: `"WARNING: GSC token may have excessive permissions. Scope = {scopes}"`
- Document in `.env.example` what token format is expected

---

## Summary: Implementation Checklist

### Critical (Must Implement Before Launch)
- [ ] Proactive token refresh before expiry
- [ ] Handle `401` and `invalid_grant` errors gracefully
- [ ] Catch `ConfigurationError`; don't crash crawl if credentials missing
- [ ] Implement property access check after auth
- [ ] Normalize property URL and match against crawl base URL
- [ ] Use centralized `normalize_url()` for all URLs
- [ ] Rate limiter: 60 QPM (2x headroom per property)
- [ ] Catch `429` errors; fall back to Layer 0/1 classification
- [ ] SecretStr for all OAuth tokens
- [ ] Mask token values in logs

### High Priority (Before Integration Testing)
- [ ] Handle network timeouts + exponential backoff
- [ ] Validate GSC response against Pydantic models
- [ ] Catch `403`, `404`, `410` errors with actionable messages
- [ ] Job cancellation handler for in-flight GSC requests
- [ ] Checkpoint logic for resume (skip re-fetching metrics)
- [ ] Query string normalization consistency
- [ ] Document metric lag and data staleness

### Medium Priority (Before Production)
- [ ] Account email validation after OAuth
- [ ] Subdomain matching rules
- [ ] URL-prefix vs domain property detection
- [ ] GSC API deprecation handling
- [ ] Credential scope validation

---

## Test Scenarios

Each edge case above should have a corresponding test:
1. Token refresh on expiry
2. Invalid grant error
3. Missing credentials
4. Property not accessible
5. Property deleted
6. URL mismatch
7. Subdomain mismatch
8. Quota exhausted (429)
9. Network timeout + retry
10. Malformed response
11. Partial data
12. Concurrent property fetches

