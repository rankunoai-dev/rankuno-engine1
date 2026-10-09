# Cycle 0153: A refusal that read as success

- **Date**: 2026-10-09
- **Scope**: Bug fix inside existing contracts. A Search Console 403 or 404 now ends GSC enrichment as `failed` with an engine-written reason instead of `succeeded` with 0 matched pages; Domain properties (`sc-domain:example.com`) can be entered, are sent to Google as typed, validated, and matched without folding other hosts' rows into the crawled site.
- **Commit**: `2267c22` on branch `gsc-honest-errors` (parent `5e0febc`); this entry and the README/ARCHITECTURE edits uncommitted at time of writing.
- **Quality gate**: LEAD GATE: pending. Builder's run: pytest 4396 passed, 2 skipped, 0 failed, 93.39% (§1).

Numbering: the lead assigned 0143. It is not free: `0143-a-directory-tree-with-its-filters-folded.md` exists in this worktree and on `origin/main`, and `origin/main` already reaches 0151 (`0151-dark-mode-glassmorphism-theme.md`). No ref, worktree under `.claude/worktrees/`, or the main checkout holds anything above 0151, so this entry is 0152. 0141 stays skipped (a draft exists only on the GitHub branch `backup/other-session-fetched-flag`). The 0144 reserved for the parallel `gsc-accounts-postgres` cycle is also taken on `origin/main` (`0144-kpi-metrics-collapse-expand-toggle.md`), as is ADR 0036 (`0036-the-ui-is-themed-by-overriding-tokens-on-the-root-element.md`); that cycle needs new numbers (§8).

## 1. Gate results

**LEAD GATE: pending.** The lead's full `verify.ps1` run was in progress when this entry was written. Nothing below is the lead's output.

Builder's run (reported by the implementer, not re-executed by the scribe):

| Stage | Result |
| :--- | :--- |
| ruff format | 661 files |
| ruff check | ok |
| mypy --strict | 176 source files, ok |
| pytest | 4396 passed, 2 skipped, 0 failed; coverage 93.39% |
| drift_check | PASSED, 246 |
| UI `tsc` | clean |
| vitest | 53 files / 719 tests passed |

Scribe's run of the four GSC test files, executed in this worktree (`import src` resolves to `.claude\worktrees\gsc-honest-errors\src\__init__.py`):

```
> python -m pytest tests/integrations/test_gsc_client.py tests/integrations/test_gsc_property_validator.py tests/modules/seo/page_classifier/test_gsc_aggregator.py tests/modules/seo/page_classifier/test_gsc_e2e.py -p no:cacheprovider --no-cov
99 passed in 0.86s
exit=0
```

## 2. What landed

### Why this cycle exists

The user reported that live GSC data was not attached to a recent rankuno.com crawl, while a GEP crawl did get data, after attaching a GSC account and filling the form. A read-only investigation established that both crawls ran on Railway, not locally, and reproduced three defects:

| # | Defect | Offline repro |
| :--- | :--- | :--- |
| 1 | `gsc_client.py` mapped 403 to `GscAuthorizationError` and 404 to `GscPropertyNotFoundError` (old lines 261-266), then caught both (old 282-300) and returned an empty response. `tool.py` reported `status="succeeded"` with 0 matched, and `gscEnrichment.ts` told the operator "the credentials and the property are fine". | HTTP 403 → `status=succeeded matched=0 reason=''` |
| 2 | The New crawl form's antd `type: "url"` rule refused `sc-domain:rankuno.com`; the client appended `/`, sending `sc-domain:rankuno.com/`; the validator returned `property_mismatch` "missing domain". | validator and client tests below |
| 3 | The account picker defaults to "Default (.env.local)" (`gsc_account: null`, the server's default credentials), and on Railway saved org GSC accounts live on container disk and are wiped on every redeploy. | not in this cycle (§6) |

Ruled out during the investigation: the field lost between UI and API; the date range (rolling 365 days); path case (ADR 0027); released page bodies (ADR 0035); import (ADR 0034); recent GSC commits (none after `a7d4bc1`, 2026-09-21).

Build-log 0064 lines 61-64 already recorded `sc-domain:rankuno.com` among the properties this account can see, so a Domain property is a real input for this site, not a hypothetical.

The user chose fix 1 (honest 403/404), fix 2 (sc-domain support), and fix 3 (persist cloud accounts) as a separate cycle. They declined "check access before crawling" for now.

### Per module

- `src/integrations/gsc_client.py`: `fetch_analytics` re-raises `GscPropertyNotFoundError` and `GscAuthorizationError` (line 291). 429 after retries (`GscQuotaExceededError`), 410/501 (`GscApiDeprecatedError`) and any other exception keep their empty-response degradation. Retries are unchanged. A value starting `sc-domain:` is sent with trailing slashes stripped (line 212); a URL prefix still gets one appended. The class docstring now says which errors propagate.
- `src/modules/seo/page_classifier/tool.py`: `_gsc_failure_reason()` (line 354) builds the `failed` reason from the class name plus a fixed string from `_GSC_FAILURE_EXPLANATIONS` (line 111):
  - `GscAuthorizationError: this Google account cannot access this property`
  - `GscPropertyNotFoundError: property not found in Search Console`

  Other exceptions still render the class name only. Fixed strings, not `str(exc)`, because `GscAuthorizationError`'s message quotes Google's reason phrase and nothing Google sent may reach a browser. No new fields; `GscEnrichmentReport` and the API contract are unchanged.
- `src/integrations/gsc_property_validator.py`: new `_validate_domain_property` (line 118). A `sc-domain:` value is valid for a crawl on that domain or any subdomain, on either protocol, matched on whole DNS labels through the existing `_is_subdomain`, so `example.com.evil.net`, `notexample.com` and `example.co` are refused. `match_type="domain"`. The `_normalize_netloc` docstring claimed it stripped `www.`; the code never did, and the docstring now says so and why (§3).
- `src/integrations/gsc_schemas.py`: the `match_type` description lists `'domain'`.
- `src/modules/seo/page_classifier/gsc_aggregator.py`: the prefix fallback compares whole normalized URLs (line 225), so scheme and host must agree. `_normalize_path` was removed as dead.
- `rankuno-ui/src/lib/gscEnrichment.ts`: `gscPropertyError()` accepts an http(s) URL with a host, or `sc-domain:` plus a dotted hostname (case-insensitive), and returns one refusal message otherwise. The `succeeded` / 0-matched message no longer says the credentials are fine; it lists three causes: "<account> cannot see this property", the property has no search data for these pages, or it covers a different hostname or protocol.
- `rankuno-ui/src/components/layout/LiveCrawlModal.tsx`: the property field uses `gscPropertyError` as a custom validator in place of `type: "url"`; help text and placeholder name both property forms.

### Tests added (test functions in the diff)

| File | New tests |
| :--- | :--- |
| `tests/integrations/test_gsc_client.py` | 4 |
| `tests/integrations/test_gsc_property_validator.py` | 6 |
| `tests/modules/seo/page_classifier/test_gsc_aggregator.py` | 1 |
| `tests/modules/seo/page_classifier/test_gsc_e2e.py` | 2 |
| `rankuno-ui/src/lib/gscEnrichment.test.ts` | 3 |
| `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx` | 1 |

Counts are `def test_` / `it(` / `test(` lines added; parametrised cases are not counted separately.

## 3. Design decisions

**403 and 404 fail the step, the crawl still succeeds.** Enrichment already had a `failed` status rendered as a warning; a refusal now uses it. The crawl itself is unaffected (`_enrich_with_gsc` catches every exception and returns the pages unchanged), so build-log 0060's "403 → pages returned unchanged" still holds. Only the status and reason differ.

**Fixed explanation strings, not the exception text.** The alternative, `str(exc)`, would have been more specific but forwards Google's reason phrase to the browser. The class name alone (the previous behaviour for `failed`) does not tell an operator what to do.

**URL-prefix properties are not www-stripped.** Google Search Console Help, "Add a website property" (https://support.google.com/webmasters/answer/34592): a URL-prefix property "only includes URLs with the specified prefix, including the protocol". So `https://www.example.com/` does not cover `https://example.com/`. The validator already behaved this way; only its docstring said otherwise. A Domain property is the Search Console construct that spans `www.`, other subdomains and both protocols, and that is what `_validate_domain_property` implements. The existing subdomain rule (`https://example.com/` covers `www.` and `blog.`) was left as it is, although it is looser than Google's definition (§6).

**Cross-host matching rule in the aggregator.** Exact match first; then a GSC URL may claim a crawled page only if it is a prefix of the whole normalized page URL, scheme and host included. Before, the fallback compared paths only. That was harmless while every row came from one URL-prefix property, but a Domain property returns rows for every host and protocol it covers, and a path-only comparison filed them under the crawled site's pages: in the test, `https://blog.example.com/` folded into the www homepage (129 clicks reported where 30 belonged), and an `http` row into the `https` page (6 vs 5).

**Assumed, not confirmed live**: the Domain-property `searchanalytics.query` response shape, with `dimensions=["page"]` returning absolute page URLs in `rows[].keys[0]` and sibling hosts and protocols in one response. This matches Google's documented response; it was not checked against the live API.

## 4. Bugs found and fixed

1. **403/404 reported as success** (§2, defect 1). Fail-before on unmodified code: e2e 403 and 404 cases `assert 'succeeded' == 'failed'`; client tests `DID NOT RAISE GscAuthorizationError` / `DID NOT RAISE GscPropertyNotFoundError`.
2. **Domain property unenterable and mangled** (defect 2). Fail-before: `assert 'sc-domain:example.com/' == 'sc-domain:example.com'` (client); validator sc-domain cases `assert False is True`; aggregator `'Property or crawl URL missing domain' is None`; UI form-submit spy not called; refuse and help-text tests failed.
3. **Aggregator prefix fallback crossed hosts and protocols.** Found while testing defect 2, not reported by the user. Fail-before: `129 == 30` and `6 == 5`.
4. **Misleading 0-match message.** "The credentials and the property are fine" was false whenever the old code swallowed a 403. Fail-before: the 0-match message test failed.
5. **A test of ours was wrong.** The builder's first e2e test asserted the substring "Authorization" never appears in the report. It must: it is in the required class name `GscAuthorizationError`. The assertion was changed to ban Google's reason phrases ("Forbidden", "Not Found") and the response-body and token canaries instead.
6. **Docstring bug**: `_normalize_netloc` documented www-stripping that the code never performed. Corrected to match the code, not the other way round (§3).

## 5. Corrections

- **Build-log 0055** line 123 ("Graceful degradation errors (403, 404) caught by outer try/except, return empty response") and the edge-case table at line 147 ("3.1 Property not accessible ... 403 caught, empty response, logged ✅") and line 148 (the same for 404) described this as intended behaviour. It is superseded: a 403 or 404 now propagates and the enrichment step reports `failed`. The empty response is what made the step read as success.
- **Build-log 0055** line 122 says "404/403/410/501 are non-retryable; mapping them lets BaseAPIClient skip retries". False: `GscAuthorizationError` and `GscPropertyNotFoundError` subclass `IntegrationError` (`src/core/errors.py:164,176`), which is in `TRANSIENT_ERRORS` (`src/core/retry.py:44-49`), so they are retried. Not fixed here (§6).
- **`README.md`** "Search Console accounts" showed `POST /api/v1/jobs {"base_url": ..., "gsc_property": ...}`. The field is `gsc_property_url` (`tool.py:256`); `PageClassificationInput` is a `StrictModel` with `extra="forbid"`, so the documented body would be refused. Corrected in this change.
- **`gscEnrichment.ts`** comment and message (shipped before this cycle) stated that a `succeeded` response proves the credentials and property are fine. Withdrawn (§4.4).

## 6. Explicitly not done

1. **403/404 are still retried 4 times** before propagating, because of the `TRANSIENT_ERRORS` membership above. Wasted quota and backoff; the outcome is now correct, the cost is not.
2. **429 after retries, 410/501 and generic errors still return an empty response**, so they still end as "succeeded, 0 matched". The new 0-match message names possible causes but cannot tell these apart.
3. **The validator's subdomain rule is looser than Google's URL-prefix semantics** (`https://example.com/` is accepted for a `www.` or `blog.` crawl). Left unchanged; tightening it could refuse properties that work today.
4. **The aggregator's prefix fallback can still attribute a GSC parent-path row to the first crawled child page within the same host.** This cycle only stopped it crossing hosts and protocols.
5. **The account picker still defaults to the server's default credentials** (`gsc_account: null`). UI handoff.
6. **Cloud GSC accounts are still wiped on every Railway redeploy.** Separate cycle on branch `gsc-accounts-postgres` (planned as build-log 0144 and ADR 0036, both of which are taken; see the numbering note).
7. **"Check access before crawling"** was offered and declined by the user for now.
8. **The user's two Railway jobs were not inspected** (no cloud access). That defects 1-3 explain those exact jobs is inferred from offline reproduction, not confirmed.
9. **No live Search Console call** was made; the Domain-property response shape is assumed (§3).
10. **No ADR.** The lead's view: a bug fix within existing contracts (ADR 0010, 0012). The www semantics and cross-host rule are recorded here instead.

## 7. Files changed

Commit `2267c22`: 13 files, 553 insertions, 47 deletions.

| File | Lines changed |
| :--- | :--- |
| `src/integrations/gsc_client.py` | 34 |
| `src/integrations/gsc_property_validator.py` | 53 |
| `src/integrations/gsc_schemas.py` | 2 |
| `src/modules/seo/page_classifier/gsc_aggregator.py` | 23 |
| `src/modules/seo/page_classifier/tool.py` | 32 |
| `rankuno-ui/src/lib/gscEnrichment.ts` | 44 |
| `rankuno-ui/src/components/layout/LiveCrawlModal.tsx` | 12 |
| `tests/integrations/test_gsc_client.py` | 76 |
| `tests/integrations/test_gsc_property_validator.py` | 63 |
| `tests/modules/seo/page_classifier/test_gsc_aggregator.py` | 84 |
| `tests/modules/seo/page_classifier/test_gsc_e2e.py` | 65 |
| `rankuno-ui/src/lib/gscEnrichment.test.ts` | 69 |
| `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx` | 43 |

This change (docs, uncommitted): this entry; `docs/build-log/README.md` (index row); `README.md` (Search Console accounts: property forms, enrichment status, `gsc_property_url` field name); `docs/ARCHITECTURE.md` (`gsc_client.py`, `gsc_property_validator.py` and `tool.py` comments, `gsc_aggregator.py` line added).

## 8. Follow-ups

- Remove `GscAuthorizationError` / `GscPropertyNotFoundError` from the retry path (a non-transient `IntegrationError` subclass, or an exclusion in `TRANSIENT_ERRORS`), with a call-count test.
- Distinguish quota exhaustion and API deprecation from "no data" in `GscEnrichmentReport` rather than returning an empty response.
- Found by the scribe, not verified with a test: the client's domain check is case-sensitive (`property_url.startswith("sc-domain:")`, `gsc_client.py:212`) while the validator lowercases and the UI regex is `/i`. `SC-DOMAIN:example.com` would pass the form and the validator and then be sent to Google with `/` appended. It should now surface as a 404 `failed` rather than silent success.
- `_gsc_failure_reason` looks up `type(exc)` exactly, so a future subclass of either error would lose its explanation and render the class name only.
- The `gsc-accounts-postgres` cycle must take numbers above the highest on `origin/main` at its merge (currently build-log 0151, ADR 0036), and this branch's index row will conflict textually with `origin/main`'s rows 0148-0151 on rebase; keep both.
