# Cycle 0087: A refusal is not a failure

- **Date**: 2026-09-11
- **Scope**: Add a distinct `guardrail_refused` fetch-outcome bucket so the SSRF/DNS-rebinding
  guard's refusals are no longer indistinguishable from ordinary transport failures in
  `DiscoveryReport.fetch_outcomes`.
- **Commit**: uncommitted at time of writing
- **Quality gate**: mypy --strict clean on the 2 touched `src/` files; ruff clean on those 2
  files; 2 pre-existing D205 errors in `test_discovery.py` outside the new test class (unrelated
  hunk, see §5); targeted suite `tests/modules/seo/test_discovery.py`,
  `tests/modules/seo/test_async_discovery.py`, `tests/integrations/test_http_fetcher.py` —
  **200 passed**; full-repo `verify.ps1` gate not run to a green exit — see §6 and §1.

## 1. Origin

Diagnosing a live crawl of infosys.com (job `0f69b80025874d30b57f54de33b8f705`) this session found
that 3,597 of 3,960 records bucketed as `"transport_error"` were not network failures at all: they
were the DNS-rebinding / SSRF guard (`UnsafeUrlError`) refusing legitimate CDN traffic — a redirect
to an address the guard will not follow. Nothing in `fetch_outcomes` told the two apart; finding
this required manual correlation with raw application logs, which does not scale to routine crawl
review.

A parallel security-auditor review of the guard's actual refuse-vs-retry behaviour for CDN-fronted
hosts is a separate, still-open cycle awaiting operator sign-off (see §7 — that decision is not
this one). That review explicitly cleared the change below — a new outcome label, no behaviour
change — as safe to ship independently of it, on the grounds that `fetch_outcomes` is an
unvalidated string-keyed map on both the Python (`Mapping[str, int]`) and TypeScript
(`Record<string, number>`) sides, so adding a key changes nothing for any existing reader.

## 2. What shipped

- `src/modules/seo/page_classifier/discovery.py` — added `OUTCOME_GUARDRAIL_REFUSED =
  "guardrail_refused"` and its `OUTCOME_MEANINGS` gloss ("The SSRF guard refused the connection —
  not a network failure."). Imported `UnsafeUrlError` from `src.core.errors`. Branched
  `isinstance(exc, UnsafeUrlError)` ahead of the generic transport bucketing at three call sites:
  `_paginate`, `_safe_body`, `_safe_fetch_html`.
- `src/modules/seo/page_classifier/async_discovery.py` — same import and the same branch at the
  three async twins: `_abody`, `_ahtml`, `_apaginate`.
- `OUTCOME_TRANSPORT = "transport_error"` is untouched everywhere else in both files. This is
  purely additive: an existing `UnsafeUrlError` that used to fall into `transport_error` now falls
  into `guardrail_refused` instead; every other exception still lands in `transport_error` exactly
  as before.
- `tests/modules/seo/test_discovery.py` — new `TestGuardrailRefusalOutcome` class (sync
  regression test), lines 553–596.
- `tests/modules/seo/test_async_discovery.py` — new `TestGuardrailRefusalOutcome` class (async
  regression test), lines 479–521.

Both new tests simulate a redirect to `169.254.169.254` (the same trigger
`test_refuses_a_redirect_to_an_internal_address` in `tests/integrations/test_http_fetcher.py`
uses) on one URL, alongside a plain `httpx.ConnectError` on a sibling URL, then assert the two
land in different `fetch_outcomes` buckets.

No change to `_verify_peer`, `UrlSafetyPolicy.validate()`, or any refuse/retry logic. The guard's
behaviour — what it refuses and when — is exactly what it was before this cycle.

## 3. Design decisions

The branch is placed ahead of the generic `except Exception` bucketing at each of the six call
sites rather than centralised in one helper, because the three-argument (`graph`, `url`,
exception) shape differs enough between `_safe_body`'s `(body, refused)` return, `_safe_fetch_html`'s
bare `str | None`, and the paginate generators' `graph.record_outcome` calls that a shared helper
would need its own branching per caller anyway. Matching the existing duplication pattern (already
present between the sync and async twins for outcome recording) kept the diff local and
reviewable per call site instead of introducing a new abstraction under time pressure.

## 4. Bugs found and fixed

None new. This entry is itself the fix for the observability gap found during diagnosis (§1):
a `UnsafeUrlError` refusal was silently indistinguishable from a genuine transport failure in
`fetch_outcomes`, which is what made the infosys.com diagnosis require manual log correlation in
the first place.

## 5. Corrections

The brief's `VERIFY WITH` command named `tests/core/test_retry.py`. That file does not exist in
this repository (confirmed via glob before and independently re-confirmed here — `ls tests/core/`
has no `test_retry.py`). The implementer ran the three files that do exist and that actually cover
this change instead: `tests/modules/seo/test_discovery.py`, `tests/modules/seo/test_async_discovery.py`,
`tests/integrations/test_http_fetcher.py`.

## 6. Tests

Before-fix regression proof (temporarily reverted the `isinstance(exc, UnsafeUrlError)` branch in
`_safe_fetch_html` back to unconditional `OUTCOME_TRANSPORT`, independently re-run by docs-scribe
this cycle to confirm the claim rather than take it on faith):

```
tests\modules\seo\test_discovery.py:581: in handler
    raise httpx.ConnectError("boom", request=request)
httpx.ConnectError: boom
FAILED tests/modules/seo/test_discovery.py::TestGuardrailRefusalOutcome::test_an_unsafe_redirect_is_bucketed_separately_from_transport_errors
============================== 1 failed in 0.34s ==============================
```

(The implementer's own before-fix run reported the same failure shape from the assertion side —
`assert 0 == 1` against `outcomes.get('guardrail_refused', 0)`, with `fetch_outcomes` showing the
refusal folded into `transport_error`: `{"not_found": 2, "ok": 1, "transport_error": 2}`. Both
runs are the same regression: without the fix, the guard's refusal has no bucket of its own.)

After fix (branch restored), targeted re-run by docs-scribe:

```
tests\modules\seo\test_discovery.py::TestGuardrailRefusalOutcome .              [ 50%]
tests\modules\seo\test_async_discovery.py::TestGuardrailRefusalOutcome .        [100%]
2 passed in 0.57s
```

Full targeted run, independently re-run by docs-scribe:

```
tests/modules/seo/test_discovery.py tests/modules/seo/test_async_discovery.py tests/integrations/test_http_fetcher.py
200 passed in 48.58s
```

This matches the implementer's reported `200 passed in 43.73s` exactly on count; the ~5s
difference is normal run-to-run variance.

`UnsafeUrlError` propagation/refusal itself is already covered by existing, unchanged tests in
`tests/integrations/test_http_fetcher.py` (`TestSsrfEnforcement`, `TestRedirectSafety` — e.g.
`test_refuses_a_redirect_to_an_internal_address`), confirmed still passing, unchanged, in the
200-test run above.

## 7. Gate

mypy `--strict` on the 2 touched `src/` files (`discovery.py`, `async_discovery.py`) —
independently re-run:

```
Success: no issues found in 2 source files
```

ruff check on the 2 touched `src/` files — clean. ruff check on the 2 touched test files —
2 `D205` errors, both re-confirmed by line number to sit inside `TestSitemapFetchCeiling`
(lines 793–873 of `test_discovery.py`), not the new `TestGuardrailRefusalOutcome` class
(lines 553–596). That class and its sitemap-seed-source machinery
(`MAX_SITEMAP_FETCH_ATTEMPTS`, `_sitemap_seeds`, off-host filtering) belong to the concurrent
uncommitted work already present in this working tree before this cycle started (visible in
`git status` at session start), not to this change.

Full `verify.ps1` was not run to a green exit this cycle. Per the task brief, the whole-repo
Lint/Type-check phases are red exclusively from files belonging to the concurrent
Redis/Celery/Postgres/multi-tenant session (`src/workers/job_executor.py`,
`src/core/postgres_store.py`, `src/core/redis_config.py`, `src/core/rate_limiter.py`,
`src/core/celery_config.py`, `tests/core/test_redis_config.py`,
`tests/core/test_redis_token_bucket.py`, `scripts/chaos_test.py`), plus the 2 pre-existing D205
errors in `test_discovery.py` above, plus one pre-existing, unrelated UI test timeout in
`ReconcilePanel.test.tsx`. None of these are regressions introduced by this change. Per CLAUDE.md
§1.6, a task must never be reported complete without a green gate — the whole-repo gate is not
green, and this entry does not claim it is. What is verified clean in isolation is this cycle's
own deliverable: the 2 touched `src/` files (mypy + ruff) and the 200-test targeted suite that
exercises the dependency chain this change actually touches. The full `pytest`+coverage phase was
not waited out, given its real `time.sleep()`-bound length from unrelated chaos-test fixtures in
the concurrent session; the targeted subset above is the evidence offered instead of blocking on
it.

## 8. Handoffs

- The still-open, separate cycle on whether/how to change the guard's actual refuse-vs-retry
  behaviour for CDN-fronted hosts is awaiting operator sign-off. This entry is not that decision —
  it is only the safe labelling half: making an existing refusal visible as what it is, not
  changing when a refusal happens.
- Whoever owns `retry.py` test coverage: the brief handed to this cycle's implementer named
  `tests/core/test_retry.py` as the verification target; that file does not exist. Either the
  brief was written against a different branch/plan, or that coverage was never created. Worth
  checking which.

## 9. Explicitly not done

- No change to `_verify_peer`, `UrlSafetyPolicy.validate()`, or any refusal/retry logic anywhere.
  The guard refuses exactly the same requests it refused before this cycle; only the label applied
  to that refusal in `fetch_outcomes` changed.
- No fix to the unrelated concurrent-session gate failures listed in §7 — those belong to a
  different session's files and are out of scope for this cycle.
- No touch to `rankuno-ui`. `fetch_outcomes: Record<string, number>` is untyped by key on the
  TypeScript side (confirmed at `rankuno-ui/src/types/schema.ts:233`), so a new bucket key
  requires no schema or component change.
- Did not run the nonexistent `tests/core/test_retry.py` (see §5, §8).
- Did not wait out the full `pytest`+coverage run (see §7).
- No ADR. This is an additive labelling change with a security-auditor pre-step this session
  clearing it as zero security behaviour change; it does not meet the bar for a consequential
  architectural decision.

## 10. Files changed

- `src/modules/seo/page_classifier/discovery.py`
- `src/modules/seo/page_classifier/async_discovery.py`
- `tests/modules/seo/test_discovery.py`
- `tests/modules/seo/test_async_discovery.py`
