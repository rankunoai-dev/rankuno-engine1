# Cycle 0162: A second Google credential for GA4, per organisation

- **Date**: 2026-10-19
- **Scope**: GA4 page metrics for a crawl, read with a separate read-only Google credential held per organisation, entered in the GSC account form, with a GA4 dropdown on the new-crawl form (off by default). ADR 0038; ADR 0010 amended; ADR 0037 noted.
- **Commit**: uncommitted at time of writing. The implementation is commit `6d9d6f3` (`feat(ga4): separate read-only GA4 credential per org, with a crawl dropdown (ADR 0038)`), on branch `ga4-account-and-crawl`, on top of `bc35894`. This entry, the ADR 0038 corrections, and the README and ARCHITECTURE edits are not committed; the lead commits them.
- **Quality gate**: reported by the implementer, not re-run by the scribe (the brief forbids the Python gate and vitest for this step). The raw output was not in the inputs, so only the counts and exit codes the implementer reported are recorded in §1. **The live crawl path is not wired (§4.3): the green gate does not show the feature works end to end.**

## 1. Gate results

Reported by the implementer on `6d9d6f3`. Pasted from the implementer's report, not re-run:

| Stage | Result | Run by |
| :--- | :--- | :--- |
| `ruff format` | 710 files | implementer |
| `ruff check` | passed | implementer |
| `mypy --strict` (src) | 189 source files | implementer |
| `scripts/drift_check.py` (pre-edit, implementer) | PASSED, 260 files | implementer |
| `scripts/export_ui_contract.py --check` | up to date | implementer |
| `pytest` with coverage | 4689 passed, 2 skipped, 2 warnings, coverage 93.74%, exit 0 | implementer |
| UI `tsc --noEmit` | exit 0 | implementer |
| Full UI vitest | 61 files, 823 tests passed, exit 0 | implementer |
| Python gate, vitest, `npm` | not run by the scribe | brief |

The lead spot-checked the branch and the migration chain (`011` to `012`). The 2 skips were not analysed by the implementer. None of the skipped tests is a GA4 test, per the implementer's report; this was not checked by the scribe.

Drift check, run after this entry and the corrections in this change were written (§7):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 262 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
EXIT=0
```

The file count is 262. The implementer's run reported 260. This change adds one entry, which accounts for one file. The other is not explained here and was not analysed.

## 2. What landed

Migration and storage:

- `alembic/versions/0012_org_ga4_access.py` (revision `012`, down `011`, single head). Creates `org_ga4_access`: `org_id` primary key with a foreign key to `org_configs` (`ON DELETE CASCADE`), `refresh_token_ct` (bytea), `key_id`, `property_id` (nullable, CHECK `^[1-9][0-9]{0,19}$`), audit columns and timestamps.
- `src/core/ga4_access_store.py`: the `Ga4AccessStore` protocol, `GA4_PROPERTY_ID_PATTERN`, `is_valid_ga4_property_id()`. The pattern is the one shared rule for the API, the table CHECK and the crawl input.
- `src/core/postgres_ga4_access_store.py`: the Postgres implementation. Fail closed, like the GSC store.
- `src/core/gsc_credential_crypto.py`: GA4 methods added to the existing cipher. The GA4 AAD is `rankuno-ga4-cred-v1|<key_id>|<org_id>|ga4_refresh_token`. A GSC ciphertext does not authenticate as GA4, and the reverse.
- `src/core/config.py`: `Settings.ga4_access_store` (Postgres-only, cached, raises `ConfigurationError` if the credential key is missing). Seven GA4 caps (§3, decision 5).
- `src/core/errors.py`: `Ga4NotAuthorizedError` (fixed text `not authorized, re-add the account`), `Ga4UnavailableError`, `Ga4CredentialDecryptionError`, `Ga4AccessStoreUnavailableError`. All carry fixed messages, never a response body.

Connector:

- `src/integrations/ga4_client.py` (471 lines): `Ga4ApiClient(BaseAPIClient)`. `refresh_access_token` (the scope gate), `list_properties` (capped listing), `run_host_report` (one host-filtered report). Endpoint paths are constants (`ADMIN_SUMMARIES_URL`, `REPORT_URL`), each marked UNVERIFIED in the source.
- `src/integrations/ga4_budget.py`: `Ga4DailyBudget` and the process-wide `DAILY_BUDGET`.
- `src/integrations/ga4_schemas.py`: typed boundary models. No refresh token is in any model.
- `src/integrations/base_client.py`: `call()` gained `max_attempts=` (default unchanged, so no other connector moves) and `_quota_per_minute()`, which GA4 overrides to read `Settings`.

Enrichment and the crawl:

- `src/modules/seo/page_classifier/ga4_enrichment.py` (270 lines): `run_ga4_enrichment()`. Returns the pages and a `Ga4EnrichmentReport` with one of seven statuses: `not_requested`, `succeeded`, `unmapped`, `not_authorized`, `over_cap`, `over_budget`, `failed`.
- `src/modules/seo/page_classifier/tool.py`: `PageClassificationInput.ga4_property_id`, `PageClassificationOutput.ga4`, `_enrich_with_ga4()`. The tool takes `ga4_access_store=` in its constructor, as it takes `org_id`, so a request cannot choose the store.
- `src/modules/seo/page_classifier/schemas.py`: `FullPageIntelligenceProfile.ga4_screen_page_views` and `ga4_sessions`, both optional.
- `src/api/server.py`: the intake check (400 with fixed text when the property is not the org's mapping; 400 when no store is configured). `create_app()` resolves `Settings.ga4_access_store`. The crawl runner does not pass the store (§4.3).
- `src/api/error_handlers.py`: a 503 handler for `Ga4AccessStoreUnavailableError`, as for GSC.

Routes and the operator script:

- `src/api/ga4_account_routes.py` (333 lines): `GET /orgs/{org}/ga4`, `PUT /orgs/{org}/ga4/credential`, `DELETE /orgs/{org}/ga4`, `GET /orgs/{org}/ga4/properties`, `PUT /orgs/{org}/ga4/property`, `GET /ga4/mapping`. Every route requires a session. The org check runs before any lookup. There is no consent route.
- `scripts/ga4_consent_url.py`: prints the consent URL for the GA4 scope. It makes no network call and does not print the client secret.

UI:

- `rankuno-ui/src/components/gsc/Ga4Section.tsx` (232 lines): the GA4 section of the GSC account form. Stores a token, lists the properties the token can see, maps one of them.
- `rankuno-ui/src/components/gsc/GscAccountForm.tsx`: mounts the section.
- `rankuno-ui/src/components/layout/LiveCrawlModal.tsx`: the GA4 dropdown. Its options are "off" and the org's one mapped property. "Off" is the default value. The reason beside the control is fixed text.
- `rankuno-ui/src/adapters/adapterInterface.ts`, `httpAdapter.ts`, `rankuno-ui/src/types/schema.ts`: the adapter methods and the regenerated types.

Golden snapshot:

- `tests/fixtures/golden/extract_at_fetch_500.json.gz` was regenerated. See §5.1 for the exact change.

## 3. Design decisions

The decisions are in ADR 0038. This section records the ones the ADR does not state, and the reasons for the others in one line each.

1. **One credential and one property per organisation, not per GSC account.** A GA4 property belongs to the organisation. The GSC account name plays no part.
2. **Separate AAD label.** The GA4 token is encrypted under `rankuno-ga4-cred-v1`, so it cannot be copied between the two tables. The same key is used (one rotation covers both), as ADR 0037 describes.
3. **Re-saving a credential clears the mapping.** `PostgresGa4AccessStore`'s upsert sets `property_id = NULL` on conflict. An operator who re-authorises must map the property again. ADR 0038 does not say so. Recorded here, not changed in the ADR.
4. **The crawl's report window is the trailing 365 days** (`REPORT_WINDOW = ("365daysAgo", "today")` in `ga4_client.py`). The window is not the crawl's date range and no crawl-time date is sent. The ADR does not say so. Recorded here as an unverified product choice, not changed in the ADR.
5. **Caps are Settings, not constants.** `ga4_requests_per_minute` (60), `ga4_max_pages_per_crawl` (50,000), `ga4_max_rows_per_request` (10,000), `ga4_max_list_pages` (10), `ga4_daily_calls_per_org` (200), `ga4_breaker_failure_threshold` (5), `ga4_breaker_recovery_s` (60.0). The six quota-like caps are marked UNVERIFIED in their descriptions. The breaker pair is not marked, because it is an operator choice, not a Google quota.
6. **The daily budget counts crawls, not requests.** `run_ga4_enrichment` spends one unit per crawl that reaches the GA4 step, before the token refresh. A crawl that then fails still spends the unit. The ADR and the Settings description call the unit a "call". Corrected in the ADR (§4.4); the Settings description is not changed (§6).
7. **Path-level join, one report per crawl.** The request count does not grow with the page count. A query-string variant of a path receives the same totals (ADR 0038 decision 7).
8. **Scope gate before any report.** `refresh_access_token` requires the scope in the refresh response. The refresh runs with `max_attempts=1`, so a revoked grant is tried once.
9. **Intake and crawl both check the mapping.** Intake refuses a property that is not the org's mapping (400). The crawl checks the mapping again, because it can be removed between the two.
10. **No CostLedger charge.** GA4 is a READ with zero recorded spend (ruling C10 in the security review; see §6.6 on where those conditions are written).

## 4. Bugs found and fixed

### 4.1 Specification bug: the "GSC property picker" did not exist

The brief said the GA4 property should be picked "the same way as the GSC property". There was no GSC property picker. The GSC property is a free-text field in the crawl modal. The implementer built a new picker in the GA4 section of the account form. This is a false premise in the brief, not a defect in the code. Recorded so that a reader does not look for a GSC picker to compare against.

### 4.2 Process: this entry's number

The brief gave the last known build-log number as 0158. `0159-nine-columns-the-export-did-not-have.md` is on `origin/main` and in the main checkout, so this entry is **0160**. Checked across this worktree, `origin/main`, every local and remote branch and every worktree: no `0160` exists.

### 4.3 Found on review after the build: the live crawl is not wired (NOT FIXED in this cycle)

`src/api/server.py` builds the crawl tool at the one live construction site (about line 1248):

```python
result = PageClassificationTool(
    url_policy=state.url_policy,
    org_id=running.org_id,
    progress_sink=...,
    ...
    memory_account=account,
).run(payload)
```

It does not pass `ga4_access_store=`. The tool's constructor defaults that argument to `None` and does not fall back to `Settings`. The enrichment step therefore receives `store=None`, and `run_ga4_enrichment` returns:

- status `unmapped`
- reason `not requested: GA4 is not configured on this server`

for **every** crawl that names a GA4 property. The intake check uses `state.ga4_access_store` and passes, so the user gets a crawl whose GA4 report says the server does not have GA4.

Checked by reading, not by running:

- `grep` for `PageClassificationTool(` in `src` finds one instantiation (`server.py`), plus a registry registration in `tool.py`.
- `grep` for `ga4_access_store` in `tests` finds route tests that inject the store into `create_app`, and no test that injects it into the tool. `tests/modules/seo/page_classifier/test_ga4_enrichment.py` calls `run_ga4_enrichment` directly.
- So no test in the suite covers the wiring, and the 4689 passing tests do not show the feature works end to end.

Status: **open**. This cycle is documentation only, so the code was not changed. The likely fix is to pass `ga4_access_store=state.ga4_access_store` at that call site, plus a test that drives the crawl runner with a store and asserts `pages_matched` on a known path. The fix belongs to the implementer, and it needs its own gate run. Until it lands:

- ADR 0038 has a Known gap that says so.
- The README row for GA4 is marked as not wired, with its status changed from "Implemented & tested".
- The ARCHITECTURE row for ADR 0038 says so.

### 4.4 Errors in the ADR and docs, corrected in this change

Found by checking the ADR against the code. Corrected in place. These are corrections to this cycle's own documents, which are not yet committed, so no earlier entry is edited.

- ADR 0038, route set: the ADR listed `GET/PUT/DELETE /orgs/{org}/ga4`. The code has no `PUT /orgs/{org}/ga4`. The credential write is `PUT /orgs/{org}/ga4/credential`, which the list omitted.
- ADR 0038, decision 9: "Every GA4 call ... `max_attempts=2`" contradicted the next sentence, which says the refresh uses `max_attempts=1`. Corrected to say every request except the refresh.
- ADR 0038, decision 10: the breaker was described as tripping on "transport failures". The code trips on any `IntegrationError`: a transport error, a 429 that survives its retry, a 5xx, or any other non-refusal status (`_request_json`'s final `raise Ga4UnavailableError` becomes an `IntegrationError` in `BaseAPIClient.call`'s generic catch). The refusal list also omitted OAuth `invalid_grant` and `unauthorized_client`, which return `None` and so count as a success for the breaker. Corrected.
- ADR 0038, decision 11: the budget was described as counting "GA4 calls". It counts crawls (§3.6). Corrected.
- ARCHITECTURE, `ga4_budget.py` line: "GA4 call allowance" corrected to "allowance of crawls that reach GA4".
- README and ARCHITECTURE, GA4 rows: "Implemented & tested" changed to "not wired into the live crawl" (§4.3).

### 4.5 Settings and module docstrings that say "call"

`Settings.ga4_daily_calls_per_org` is described as "GA4 calls one organisation may make per UTC day". `ga4_budget.py` says `try_spend` "Record[s] one call". Both are wrong for the reason in §3.6. The Settings description is code and was not changed in this docs-only cycle. Follow-up in §8.

## 5. Corrections

### 5.1 The golden snapshot changed: a visible result-contract addition

`tests/fixtures/golden/extract_at_fetch_500.json.gz` now pins three additive keys. The scribe compared the snapshot with the version at `bc35894` (read-only, decompressed in memory, recursive comparison of the two JSON trees):

```
{'ADDED': 1007}
added keys: ga4, ga4_screen_page_views, ga4_sessions
tool.ga4 = {"pages_crawled": 503, "pages_matched": 0, "property_id": null,
            "reason": "", "rows_available": 0, "rows_used": 0,
            "status": "not_requested", "truncated": false}
```

- Zero keys changed and zero removed. The 1,007 additions are `tool.ga4` (one) and `ga4_screen_page_views` and `ga4_sessions` on each of 503 pages (2 × 503 = 1,006).
- **This is a contract addition for API consumers.** Every crawl result now carries `tool.ga4` (`status: not_requested` when no property was asked for). Every page now carries `ga4_screen_page_views` and `ga4_sessions`, which are `null` unless the path matched. Earlier results without these keys still load, because the fields are optional.
- The scribe found no change to any existing key, so the golden change is additive-only. The implementer's report says the regeneration was checked the same way with a scratch script; that script was not in the inputs and was not re-run here.

### 5.2 Earlier statement superseded, not false when written

`build-log 0042` and the ARCHITECTURE row for `integrations/google_analytics.py` said GA4 had no ingestion. That was true when written. ADR 0038 adds a connector, so the ARCHITECTURE row now points to `integrations/ga4_client.py`. The build-log entry is not edited.

### 5.3 ADR 0010 safety checklist

ADR 0010 item 1 said Rankuno requests `webmasters.readonly` ONLY. That remains true for Search Console. ADR 0038 amends it for GA4, which is a second API with its own scope, stored apart. The amendment is inline in ADR 0010, and the original sentence is kept.

## 6. Explicitly not done

1. **Live Google behaviour is unverified.** The scope string `https://www.googleapis.com/auth/analytics.readonly` (`GA4_READONLY_SCOPE`), the endpoint paths (`accountSummaries`, `runReport`), the request body and every field name were written from the documented shapes. None was called against a real GA4 property. The `scope` field of the refresh response is an assumption. If Google omits it, every GA4 credential fails closed with `not authorized, re-add the account`. That is a safe failure and a false one. It must be checked against a live refresh before GA4 is relied on.
2. **The crawl runner does not pass the GA4 store** (§4.3). Open.
3. **No live Postgres.** The store is covered by a recording fake and by the offline migration render only (`test_ga4_migration.py`). The SQL has not run against Postgres.
4. **All caps are UNVERIFIED** against Google's quotas, and so is the 365-day window (§3.4). No quota figure is stated as fact anywhere in the code or docs.
5. **The daily budget and the breaker are in process.** A multi-worker deployment multiplies both by the worker count, as the rate limiter and the cost ledger do (CLAUDE.md §8). Blocking for hosted multi-worker deployment, not for local.
6. **The C1 to C11 conditions are not in the repository.** ADR 0038 and the code comments cite conditions such as C1, C2, C5, C8, C9 and C10. They come from the pre-build security review and are not written in any file here, so a reader cannot check them. The lead holds the list. It should be pasted into an ADR or the build log, or the references dropped.
7. **In-app Google consent (C1) is not built.** `scripts/ga4_consent_url.py` prints the URL, and the operator completes the code exchange with the shared OAuth client.
8. **No per-organisation GA4 OAuth client.** GA4 refreshes with `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`, the same client as GSC.
9. **No per-URL join.** GA4 totals attach by path. Query-string variants of one path share them. A `pagePathPlusQueryString` join is deferred (ADR 0038 alternatives).
10. **GA4 values are not in any CSV or XLSX.** The CSV endpoints in `server.py` write explicit column lists, and none names a GA4 field. This was checked by reading those writers, not by a search of every writer in the tree. The formula-neutraliser criterion in the brief is therefore **vacuous this cycle**: nothing that needs neutralising is written. Adding GA4 columns requires the neutraliser and its test in the same change.
11. **Crawl-time credential status is not shown before a crawl.** The form shows the mapping. A revoked grant is discovered at the crawl and reported as `not_authorized`.
12. **Re-saving a credential clears the mapping** (§3.3). Not announced to the operator in the UI.
13. **Pre-existing handoffs, not fixed here.** `gsc_client.py` logs `str(exc)` on failure in `fetch_analytics` (line 321) and `list_accessible_properties` (line 173), which can quote a request. `GscTokenManager.validate_scopes()` is a no-op, and the GSC refresh response's `scope` is never read. Both are outside GA4.
14. **The tutor lesson (Step 8c)** is not written. It runs after the entry is committed.

## 7. Files changed

Implementation, commit `6d9d6f3` (44 files, 4,769 insertions, 14 deletions, from `git show --stat`):

`alembic/versions/0012_org_ga4_access.py`; `src/core/{config,errors,ga4_access_store,postgres_ga4_access_store,gsc_credential_crypto}.py`; `src/integrations/{base_client,ga4_budget,ga4_client,ga4_schemas}.py`; `src/modules/seo/page_classifier/{ga4_enrichment,schemas,tool}.py`; `src/api/{error_handlers,ga4_account_routes,server}.py`; `scripts/{export_ui_contract,ga4_consent_url}.py`; the UI files listed in §2; `tests/` (12 files: the GA4 test modules, `tests/core/test_postgres_schema.py` (head moved 011 to 012), and the golden snapshot; 1,963 insertions and 4 deletions in `tests/` per the stat); `README.md`; `docs/ARCHITECTURE.md`; `docs/adr/0010-...md`; `docs/adr/0037-...md`; `docs/adr/0038-...md`.

Docs, this change (uncommitted):

- `docs/build-log/0162-ga4-separate-credential-per-org.md` (new, this entry).
- `docs/build-log/README.md`: index row for 0162.
- `docs/adr/0038-ga4-access-is-a-separate-read-only-credential-per-org.md`: route set (§4.4), decision 9 (refresh exception), decision 10 (breaker trigger), decision 11 (budget unit), new Known gap for the unwired store.
- `docs/ARCHITECTURE.md`: `ga4_budget.py` description; ADR 0038 index row (not wired).
- `README.md`: GA4 row status (not wired).

## 8. Follow-ups

- **Implementer (blocking)**: pass `ga4_access_store=state.ga4_access_store` at the crawl runner's construction of `PageClassificationTool` (`src/api/server.py`, about line 1248). Add a test that runs the crawl runner with a store and asserts `pages_matched` on a known path. Then re-run the gate. Remove the not-wired notes in README, ARCHITECTURE and ADR 0038 in the same change.
- **Implementer**: change the wording of `Settings.ga4_daily_calls_per_org` and the `ga4_budget.py` docstrings from "call" to "crawl that reaches GA4" (§4.5).
- **Lead**: confirm the Step-7 gate after the wiring fix, since the reported green gate predates it.
- **Lead**: CLAUDE.md §8 has no GA4 entry. The GA4 gaps (unverified endpoints, in-process budget and breaker, no in-app consent) are not listed there, and the lead owns that file. This entry does not edit it.
- **Lead**: decide whether to record the 365-day window (§3.4) and the re-save clearing the mapping (§3.3) in ADR 0038.
- **Lead**: paste the C1 to C11 conditions into the repository (§6.6).
- **Operator, before live use**: enable the Google Analytics Admin API and the Analytics Data API in the Google Cloud project, and re-authorise each account to grant `analytics.readonly`. `scripts/ga4_consent_url.py` prints the URL. Existing GSC-only tokens show `not authorized, re-add the account` until then.
- **Security handoffs**: §6.13.
- **Rebase**: this branch is cut from `bc35894`. `origin/main` has build-log `0159`, so the index row for 0160 must be placed after the 0159 row when the branch is rebased.
