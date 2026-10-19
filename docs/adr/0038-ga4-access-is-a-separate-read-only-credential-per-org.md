# ADR 0038: GA4 access is a separate read-only credential per organisation

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: Lead AI Systems Engineer. The user approved, in the request that opened this
  cycle: (1) a GA4 credential stored separately from the GSC one; (2) build now, with GA4 entered
  in the GSC account form, the property picked from the list that credential can see, and an
  off-by-default GA4 dropdown on the new-crawl form.
- **Amends**: [ADR 0010](0010-gsc-api-security-and-safety-controls.md) §1 and the safety checklist,
  which said Rankuno requests `webmasters.readonly` ONLY. That remains true for Search Console.
  GA4 is a second Google API with its own scope, its own credential and its own store.
- **Relates to**: [ADR 0037](0037-cloud-gsc-credentials-are-encrypted-in-postgres.md) (the cipher
  and the Postgres selection rule are reused; the table, the AAD label and the store are new).

## Context

Search Console enrichment reads a client's clicks and impressions. Pages also need the traffic
they receive from GA4 (sessions and views for the path), and the operator wants the same
pattern as GSC: an account chosen on the account screen, and a dropdown on the crawl form that
is off unless asked for.

GA4 is not Search Console. Its read scope is different (`analytics.readonly`), so a Search
Console refresh token cannot read it, and it must not be asked to. The brief fixed the rules:
no in-app consent flow, no environment or default property, no reuse of the GSC token or its
ciphertext, no CostLedger charge, and a fixed reason for every refusal.

## Decision

1. **One GA4 credential and one mapped property per organisation**, in table `org_ga4_access`
   (migration 012). It is keyed by `org_id` alone. A GA4 property belongs to the organisation,
   not to a Search Console account, so the GSC account name plays no part in GA4 access.
2. **The refresh token is encrypted under its own AAD label**, `rankuno-ga4-cred-v1`, with the
   field name `ga4_refresh_token` and the org bound. The key is the same ADR 0037 key, so one
   rotation covers both credentials, but a GSC ciphertext copied onto the GA4 row fails
   authentication, and so does the reverse. Tested in `test_ga4_credential_crypto.py`.
3. **The scope gate is fail-closed.** `Ga4ApiClient.refresh_access_token` reads the `scope`
   field of the refresh response and requires `https://www.googleapis.com/auth/analytics.readonly`
   before any other GA4 call. A missing field, a different scope, or a grant Google calls
   `invalid_grant` is `Ga4NotAuthorizedError`, whose text is the fixed reason
   `not authorized, re-add the account`. A GSC-only token therefore fails here, with that reason,
   and never returns an empty result.
   - The scope string is an **assumption to confirm** against Google's current scope list.
4. **Saving a credential verifies it first.** `PUT /orgs/{org}/ga4/credential` refreshes the
   token and runs the gate, and stores nothing if either refuses. Google being unreachable is a
   503, not a stored credential.
5. **A property is picked from a live list, never typed.** `PUT /orgs/{org}/ga4/property` accepts
   an id only if the credential's current listing contains it. A truncated listing that lacks
   the id is refused with a message that says so, rather than guessed. Ids match
   `^[1-9][0-9]{0,19}$` at the API, in the table CHECK and in the crawl input.
6. **Unmapped is "not requested", never a fallback.** No environment token, no `.env.local`
   profile and no default property is ever used for GA4. A crawl naming a property the org does
   not map is refused at intake (400, fixed text), and re-checked at the crawl, because a mapping
   can be removed between the two.
7. **One report per crawl, host-scoped and allowlisted.** `run_host_report` requests one GA4 report
   for the crawl's host, with an exact `hostName` filter, dimensions `hostName` and `pagePath`,
   and metrics `screenPageViews` and `sessions`. No user-level or client-level dimension can be
   named (`validate_report_fields` refuses it before any request). The join is by path: GA4
   excludes the query string, so every crawled URL with that path gets the same totals. The
   report says so; the profile field documentation says so.
8. **Caps are operator settings, all UNVERIFIED.** `Settings.ga4_requests_per_minute`,
   `ga4_max_pages_per_crawl` (a crawl over the cap is `over_cap`, not a partial join),
   `ga4_max_rows_per_request`, `ga4_max_list_pages`, `ga4_daily_calls_per_org`, and the breaker
   pair `ga4_breaker_failure_threshold` and `ga4_breaker_recovery_s`. No quota, price or limit is
   stated as a fact in code or docs.
9. **Retries are capped per operation.** Every GA4 request except the refresh runs inside `BaseAPIClient.call()` with
   `max_attempts=2`, so a 429 or transient failure is retried exactly once. A 401, 403 or 404 is a
   refusal and is never retried. The refresh uses `max_attempts=1`, so a revoked token is tried
   once. `BaseAPIClient.call` gained the optional `max_attempts` argument for this; its default is
   unchanged, so no other connector moves.
10. **A service-level breaker** (process-wide, tuned from Settings) opens after consecutive upstream
    failures (a transport error, a 429 that survives its retry, a 5xx, or any other status that is
    not a refusal) and then refuses without a request. Refusals (401, 403, 404, and an OAuth
    `invalid_grant` or `unauthorized_client`) do not trip it: the service answered.
11. **A per-org daily budget**, in process, counts crawls per organisation per UTC day that reach
    the GA4 step (`Ga4DailyBudget`): one unit per crawl, spent before the token refresh, so a crawl
    that then fails still spends it. Exhausting it gives `over_budget` for that crawl. The unit is
    a crawl, not a request: a crawl makes at least two GA4 requests (refresh and report).
12. **No CostLedger charge.** GA4 is `READ` with zero recorded spend (C10). The budget is a
    request-volume guard, not a spend guard.
13. **Nothing secret reaches a response, a log or an exception.** Refusals are fixed reasons.
    Transport and HTTP failures are recorded by exception class or status only. Audit lines carry
    org, operator and action. The property id is logged as a length, never a value.
14. **Postgres only.** `Settings.ga4_access_store` follows the GSC selection rule. Without Postgres
    there is no GA4 store, and GA4 reads as not configured. There is no disk variant: a GA4 token
    on the container disk is the failure ADR 0037 removed.
15. **Re-authorisation stays operator-run.** `scripts/ga4_consent_url.py` prints the consent URL
    for the GA4 scope. It makes no network call and does not exchange the code. The operator
    completes the exchange with the same OAuth client and pastes the refresh token into the form.

## Alternatives considered

- **Reuse the GSC refresh token and add the scope.** Rejected: C2. It would widen what an existing
  Search Console credential may read, and an operator could not revoke one without the other.
- **A GA4 field inside `org_gsc_accounts`.** Rejected: the mapping is per organisation, the
  credential is not per account, and a shared row would let a GSC account's lifecycle delete GA4
  access.
- **An in-app consent redirect.** Rejected for this cycle: C1. The operator script covers the need.
- **A GA4 `.env.local` profile.** Rejected: C5. No default or environment property exists.
- **Per-URL GA4 metrics via `pagePathPlusQueryString`.** Deferred: it multiplies rows, and the
  profile field would then need query-level semantics the classifier does not carry.

## Consequences

- A new table, an Alembic revision (`012`), and a new `Settings` group. Migration 012 creates
  `org_ga4_access`; its offline SQL is pinned by `test_ga4_migration.py`.
- `FullPageIntelligenceProfile` gains `ga4_screen_page_views` and `ga4_sessions`, and
  `PageClassificationOutput` gains `ga4`. Both are optional, so stored results still load.
  The UI contract is regenerated.
- GA4 values appear only in the JSON result. No CSV writer emits them in this cycle. The
  formula-trigger guard therefore has no GA4 string to guard; the only GA4 strings (property
  display names) render as text in the picker and are never written to a file.
- The GA4 route set is `GET` and `DELETE /orgs/{org}/ga4`, `PUT /orgs/{org}/ga4/credential`,
  `GET /orgs/{org}/ga4/properties`, `PUT /orgs/{org}/ga4/property`, and `GET /ga4/mapping` for the
  crawl form's own organisation.

## Known gaps (not done, not hidden)

- **Closed in cycle 0161: the live crawl did not receive the GA4 store.** The crawl runner
  built `PageClassificationTool` without `ga4_access_store`, so every crawl that named a property
  reported `unmapped`. `src/api/server.py` now passes `state.ga4_access_store`, and
  `tests/api/test_crawl_ga4_wiring.py` drives `POST /jobs` through the real runner to prove it
  (build-log 0162 §4.3, build-log 0161 §4.1). The tool's `ga4_access_store` still defaults to
  `None` and does not fall back to `Settings`, so an omitted argument can recur silently (build-log
  0161 §6.5).
- **Unverified against Google.** The endpoint paths (`accountSummaries`, `runReport`), the field
  names and the `analytics.readonly` scope string are written from the documented shapes and have
  not been exercised against a live property. No live credential is available to this repository.
  Confirm each before relying on GA4 data.
- **The OAuth client is the shared one.** GA4 refreshes with `GOOGLE_OAUTH_CLIENT_ID` and
  `GOOGLE_OAUTH_CLIENT_SECRET`. A per-organisation GA4 client override is not built.
- **The daily budget is in process.** Multi-worker deployment multiplies the allowance by the
  worker count, as the rate limiter does. Blocking for hosted multi-worker deployment, not for
  local (CLAUDE.md §8).
- **The breaker is in process**, for the same reason.
- **No code exchange in the app.** The operator performs the authorisation-code exchange.
- **No live Postgres.** The store is covered by a recording fake and the offline migration render.
- **Crawl-time GA4 status is not shown before a crawl.** The form shows the mapping, not whether
  the credential still passes the scope gate. A revoked grant is discovered at the crawl and
  shown as `not_authorized`.
- **Path join, not URL join** (decision 7). Query variants of one path share totals.
- **The scope gate depends on a `scope` field in the refresh response.** If Google omits that
  field on refresh, every GA4 credential fails closed with `not authorized, re-add the account`.
  That is a safe failure, but a false one, and it must be checked against a live refresh before
  the feature is relied on.
- **Handoff (pre-existing, out of scope):** `GscApiClient` logs `str(exc)` on failure in
  `fetch_analytics` and `list_accessible_properties`, which can quote a request. Recorded in the
  cycle's handoffs; not changed here, because GSC behaviour is out of scope.
