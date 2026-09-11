# Cycle 0090: A deadline shorter than its retries

- **Date**: 2026-09-11
- **Scope**: `REQUEST_DEADLINE_S` raised 20.0 -> 200.0 and `STALL_TIMEOUT_S` raised
  30.0 -> 210.0 to match so the outer per-request deadline no longer fires before
  httpx's own retry policy gets to run; `FETCH_RETRY_ON` added so genuine httpx
  transport failures are retried at all (the shared `TRANSIENT_ERRORS` never matched
  httpx's exception hierarchy); three new additive `fetch_outcomes` buckets
  (`transport_timeout`, `transport_refused`, `transport_deadline`) via
  `_transport_outcome_for()`; `_LoadGovernor` extended to narrow its concurrency cap
  on `transport_refused` in addition to `server_error`.
- **Commit**: uncommitted at time of writing (per this cycle's own instructions —
  "do not commit"). The touched files (`src/integrations/http_fetcher.py`,
  `src/modules/seo/page_classifier/discovery.py`,
  `src/modules/seo/page_classifier/async_discovery.py`) are shared with two other
  concurrent, already-recorded cycles this session (0087's `guardrail_refused`
  bucket, 0089's `_verify_peer` peer-rotation fix) and a separate, still-in-progress
  parallel CDN-guard precision-fix cycle plus a Redis/Celery/Postgres/multi-tenant
  session — none of that other work is described here; see §6.
- **Quality gate**: full-repo `verify.ps1 -Fix`, independently re-run by
  docs-scribe: **RED** — Lint (25 errors), Type check (13 errors), Tests (1 failed,
  2356 passed, 2 skipped), all traced to files this cycle never touched (concurrent
  Redis/Celery/Postgres/multi-tenant session). Coverage **92.51%** (rounds to the
  implementer's reported 93%), above the 85% floor. UI: **254/254 passed**, 23 test
  files. Targeted suite for this cycle's own files — `tests/integrations/test_http_fetcher.py
  tests/modules/seo/test_async_discovery.py tests/modules/seo/test_discovery.py` —
  **208 passed**, independently re-run. See §5 and §7 for verbatim output.

## 1. Origin

This session's infosys.com crawl diagnosis (job `0f69b80025874d30b57f54de33b8f705`)
found `REQUEST_DEADLINE_S=20s` was shorter than httpx's own ~45s worst-case timeout
budget, so the outer deadline always fired first, masking httpx-native exceptions
and producing an estimated 363/3,960 unexplained `transport_error` records. A
parallel finding showed `TRANSIENT_ERRORS` (Python builtins only) never matched
httpx's own exception hierarchy, so genuine network failures got zero retries on
any crawl — independently confirmed this cycle: `httpx.ConnectError` does not
subclass the builtin `ConnectionError`, and `httpx.TimeoutException` does not
subclass the builtin `TimeoutError` (see §5 for the exact check). A
security-auditor pre-step (PASS WITH CONDITIONS) and a bug-fixer Step 3 design pass
turned this into exact numbers; the operator approved the full plan including the
one open design question — extend `_LoadGovernor` to react to timeout/refusal
pile-ups, not just server errors — with the explicit framing: "don't break the
present healthy logic, but the end goal is to achieve that we can crawl all the
pages."

## 2. What shipped

- `REQUEST_DEADLINE_S` raised 20.0 -> 200.0
  (`src/modules/seo/page_classifier/async_discovery.py:108`). Derivation, now
  recorded in the constant's own docstring: 4 retry attempts (the default
  `Settings.default_max_retries = 3`, confirmed at `src/core/config.py:136`, means
  4 total attempts via `attempts = max_attempts if max_attempts is not None else
  get_settings().default_max_retries + 1` in `src/core/retry.py:87`) x ~45s httpx
  phase budget (`CONNECT_TIMEOUT_S=5` + `POOL_TIMEOUT_S=10` + `default_timeout_s=30`,
  each maxed out sequentially in one attempt) = 180s, + ~7s cumulative
  exponential-jitter backoff across 3 inter-attempt waits ~= 187s, + 13s margin =
  200s. The docstring states this is coupled to `default_max_retries=3` and must be
  re-derived if that setting changes — confirmed present in the source, not just
  claimed.
- `STALL_TIMEOUT_S` raised 30.0 -> 210.0 (`async_discovery.py:134`), preserving the
  same `REQUEST_DEADLINE_S + 10` margin it held before.
- `_apaginate`'s previously-unbounded fetch call (`await fetcher.afetch(url)` with
  no timeout) is now wrapped in the same `asyncio.wait_for(..., timeout=
  REQUEST_DEADLINE_S)` every other async fetch path already used
  (`async_discovery.py:647`). Confirmed by reading the pre-change code: this was a
  genuine oversight, not a deliberate omission — nothing distinguishes CMS
  pagination fetches from the other three async fetch call sites that would justify
  leaving this one unbounded.
- `FETCH_RETRY_ON = TRANSIENT_ERRORS + (httpx.TimeoutException,)` added in
  `src/integrations/http_fetcher.py`, scoped to the fetch path only — wired into
  `afetch()` via `with_async_retries(lambda: self._afetch_chain(url),
  retry_on=FETCH_RETRY_ON)`. `httpx.TimeoutException` covers `ConnectTimeout`,
  `ReadTimeout`, `WriteTimeout` and `PoolTimeout` uniformly (confirmed: they share
  this one base class in the installed httpx version). `core.retry.TRANSIENT_ERRORS`
  itself is **not** widened — confirmed empty `git diff` on `src/core/retry.py` —
  since that set is shared by every `BaseAPIClient` subclass and a fetch-specific
  addition has no business widening retry behaviour for, say, the Search Console
  client.
- `httpx.ConnectError` is deliberately excluded from `FETCH_RETRY_ON` — zero
  retries, capped at `CONNECT_TIMEOUT_S=5s` (confirmed in source). A connect
  failure is either persistent or a possible defensive signal from the target.
- Three new additive `fetch_outcomes` buckets — `OUTCOME_TRANSPORT_TIMEOUT =
  "transport_timeout"`, `OUTCOME_TRANSPORT_REFUSED = "transport_refused"`,
  `OUTCOME_TRANSPORT_DEADLINE = "transport_deadline"` — via a new
  `_transport_outcome_for(exc)` helper in `discovery.py`. The existing
  `"transport_error"` and `"guardrail_refused"` strings are untouched; `transport_error`
  is now documented as the residual/fallback bucket for a transport failure that is
  none of the three `transport_*` outcomes (e.g. too many redirects) — the sync
  path still only records it as a flat fallback, since sync fetching was explicitly
  out of scope (§6).
- `_LoadGovernor` now narrows its concurrency cap on `OUTCOME_SERVER_ERROR +
  OUTCOME_TRANSPORT_REFUSED` combined (`_narrowing_signal()` helper, read fresh
  from the ledger on each `release()`, matching the pre-existing pattern),
  deliberately excluding the timeout/deadline buckets from the throttle trigger —
  a slow-but-alive host is not necessarily our own concurrency's fault, and
  narrowing on it would work against the "crawl all the pages" goal.
- Sync fetch path (`_safe_body`/`_safe_fetch_html`) and `_verify_peer`/DNS-rebinding
  logic explicitly untouched — both out of scope (§6).

## 3. Corrections

The approved Step 3 plan's literal wording for `_transport_outcome_for` — "reads
`exc.__cause__` when `exc` is an `IntegrationError`" — would have made
`OUTCOME_TRANSPORT_DEADLINE` permanently unreachable dead code. Independently
re-derived, not taken on the implementer's word: `REQUEST_DEADLINE_S`'s
`asyncio.wait_for()` wraps `fetcher.afetch(url)` from **outside** `afetch()` itself
(confirmed by reading both `async_discovery.py`'s call sites and `afetch()`'s own
body, `http_fetcher.py:409-417`). `afetch()` wraps whatever
`with_async_retries(...)` raises into an `IntegrationError` inside its own
`try/except`, but when `asyncio.wait_for`'s timeout fires it cancels the awaited
coroutine at the `await` point in the *caller* — the exception never re-enters
`afetch()`'s exception handling and is never wrapped. A bare `TimeoutError`
therefore reaches `_transport_outcome_for` directly. The implementer's fix —
`cause = exc.__cause__ if isinstance(exc, IntegrationError) else exc` — handles
both shapes; the plan's literal sentence would not have. Verified independently
this cycle:

```
>>> httpx.TimeoutException.__mro__
(httpx.TimeoutException, httpx.TransportError, httpx.RequestError, httpx.HTTPError, Exception, BaseException, object)
>>> issubclass(httpx.TimeoutException, TimeoutError)
False
>>> asyncio.TimeoutError is TimeoutError
True
```

`httpx.TimeoutException` does not collide with the builtin `TimeoutError` /
`asyncio.TimeoutError` on the installed version, so the classifier's ordering
(`httpx.TimeoutException` checked before the bare `asyncio.TimeoutError` branch)
correctly separates "httpx exhausted its own retries" from "our outer deadline
cancelled the call" on this Python/httpx combination.

Also: a pre-existing test (`tests/modules/seo/test_async_discovery.py::
TestGuardrailRefusalOutcome::test_an_unsafe_redirect_is_bucketed_separately_from_transport_errors`,
from the immediately-prior cycle 0087) asserted a plain `httpx.ConnectError` lands
in `transport_error` — correct under 0087's design, but this cycle's approved
design intentionally reclassifies `ConnectError` into `transport_refused`. The
test's assertion was locking in the old classification, not a real requirement;
fixed to expect `transport_refused==1, transport_error==0`. The code was right,
the test's expected value was stale — per CLAUDE.md's own build-log guidance, this
is recorded as "test was wrong, not the code."

## 4. Design decisions

| Decision | Alternative considered | Reason |
| :--- | :--- | :--- |
| `REQUEST_DEADLINE_S = 200s`, derived from 4 attempts x 45s + backoff + margin | Leave the deadline at 20s and shrink httpx's own per-phase timeouts instead | Would cut off slow-but-legitimate responses at the transport layer before the deadline ever mattered — the goal is more coverage, not a tighter net |
| `httpx.ConnectError` excluded from `FETCH_RETRY_ON` | Retry it like every other transient error | A connect refusal is either permanent or a possible defensive signal; retrying it burns the same budget as a merely slow host for no expected benefit |
| `_LoadGovernor` narrows on `server_error + transport_refused`, not on `transport_timeout`/`transport_deadline` | Narrow on all four `transport_*`/`server_error` outcomes uniformly | A slow-but-alive host is not evidence our own concurrency caused it; narrowing on it would throttle crawls against naturally slow sites, working against the operator's stated goal |
| `core.retry.TRANSIENT_ERRORS` left unchanged; `FETCH_RETRY_ON` added as a fetch-scoped superset | Widen `TRANSIENT_ERRORS` itself | That set is shared by every `BaseAPIClient` subclass (GSC client included); widening it for httpx exceptions has no business affecting non-HTTP integrations |

## 5. Tests

Regression test before/after, independently re-run by docs-scribe (scoped `git
stash` of `src/integrations/http_fetcher.py` only, immediately restored):

Before (pre-fix code, `FETCH_RETRY_ON` absent):

```
ImportError while importing test module 'tests\integrations\test_http_fetcher.py'.
tests\integrations\test_http_fetcher.py:18: in <module>
    from src.integrations.http_fetcher import (
E   ImportError: cannot import name 'FETCH_RETRY_ON' from 'src.integrations.http_fetcher'
=========================== short test summary info ===========================
ERROR tests/integrations/test_http_fetcher.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

After (stash popped, restored exactly):

```
tests\integrations\test_http_fetcher.py -k TestNonRetryable
2 passed in 0.10s
```

Full targeted run, independently re-run (`-o addopts=""` to surface the summary
line, which this pytest install's default `-q` addopts otherwise drops):

```
tests\integrations\test_http_fetcher.py tests\modules\seo\test_async_discovery.py tests\modules\seo\test_discovery.py
...............................                                          [ 56%]
tests\modules\seo\test_discovery.py .................................... [ 74%]
......................................................                   [100%]
======================= 208 passed in 74.58s (0:01:14) ========================
```

Matches the implementer's reported 208 passed.

## 6. Explicitly not done

- Sync fetch path (`_safe_body`/`_safe_fetch_html`) untouched — no change to
  transport-error classification granularity on the serial crawl path; it still
  records only the flat `transport_error` fallback.
- `_verify_peer`/DNS-rebinding/CDN peer-rotation logic in
  `src/integrations/http_fetcher.py` untouched — that is a separate,
  still-in-progress parallel cycle (recorded as cycle 0089, "Rotation is not
  rebinding") and not this cycle's to document further.
- `core.retry.TRANSIENT_ERRORS` not widened globally — kept fetch-scoped in the new
  `FETCH_RETRY_ON` only.
- `UnsafeUrlError`/`RobotsDisallowedError` not added to `FETCH_RETRY_ON` — locked in
  by the new `TestNonRetryableExceptionsPropagateOnFirstAttempt` regression test
  (§5); both are decisions already made before any socket opened, and retrying
  either just re-asks a question that has already been answered.
- `src/workers/job_executor.py`, `src/core/celery_config.py`,
  `src/core/redis_config.py`, `src/core/rate_limiter.py`,
  `src/core/postgres_store.py`, `scripts/chaos_test.py`,
  `tests/core/test_redis_token_bucket.py`, `tests/api/test_idempotency.py` — all
  belong to a concurrent Redis/Celery/Postgres/multi-tenant session, not touched.
- The 2 pre-existing `D205` docstring issues in `tests/modules/seo/test_discovery.py`
  (`TestSitemapFetchCeiling`, lines 843 and 917) are not part of this cycle and were
  not fixed.
- No commit made, per this cycle's instructions.

## 7. Gate (verbatim, independently re-run)

Lint — 25 errors, all outside this cycle's files:

```
=== Lint ===
[... 12 x S101/B007 in scripts\chaos_test.py ...]
[... S106/S105 in tests\core\test_redis_config.py ...]
[... RET503/ANN202/SIM222 in tests\core\test_redis_token_bucket.py ...]
D205 1 blank line required between summary line and description
   --> tests\modules\seo\test_discovery.py:843:9
D205 1 blank line required between summary line and description
   --> tests\modules\seo\test_discovery.py:917:9
Found 25 errors.
FAILED: Lint
```

Type check — 13 errors, all outside this cycle's files:

```
=== Type check ===
src\core\postgres_store.py:22: error: Cannot find implementation or library stub for module named "psycopg"  [import-not-found]
src\core\redis_config.py:63: error: Unused "type: ignore" comment  [unused-ignore]
src\core\rate_limiter.py:546: error: Unused "type: ignore" comment  [unused-ignore]
src\core\rate_limiter.py:575: error: Unused "type: ignore" comment  [unused-ignore]
src\core\celery_config.py:9: error: Skipping analyzing "celery": module is installed, but missing library stubs or py.typed marker  [import-untyped]
src\core\celery_config.py:101: error: Missing type arguments for generic type "dict"  [type-arg]
src\core\celery_config.py:120: error: Missing type arguments for generic type "dict"  [type-arg]
src\workers\job_executor.py:20: error: Untyped decorator makes function "execute_crawl" untyped  [untyped-decorator]
src\workers\job_executor.py:21: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
src\workers\job_executor.py:21: error: Missing type arguments for generic type "dict"  [type-arg]
src\workers\job_executor.py:100: error: Untyped decorator makes function "recover_job" untyped  [untyped-decorator]
src\workers\job_executor.py:101: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
src\workers\job_executor.py:101: error: Missing type arguments for generic type "dict"  [type-arg]
Found 13 errors in 5 files (checked 85 source files)
FAILED: Type check
```

Tests — 1 failed (concurrent idempotency work, unrelated), 2356 passed, 2 skipped:

```
=== Tests ===
FAILED tests/api/test_idempotency.py::TestIdempotencyKeyDeduplication::test_idempotency_key_per_org
E       KeyError: 'id'
...
src\modules\seo\page_classifier\async_discovery.py               312     36    114     14    86%
src\modules\seo\page_classifier\discovery.py                     461     28    150      9    93%
src\integrations\http_fetcher.py                                 273     10     48      3    96%
TOTAL                                                           9022    582   2234    167    93%
Required test coverage of 85.0% reached. Total coverage: 92.51%
1 failed, 2356 passed, 2 skipped, 1 warning in 554.96s (0:09:14)
FAILED: Tests
```

UI Component Tests:

```
=== UI Component Tests ===
 Test Files  23 passed (23)
      Tests  254 passed (254)
PASSED: UI Component Tests

VERIFICATION FAILED: Lint, Type check, Tests
```

Overall: RED on Lint/Type-check/1 test, all confirmed pre-existing/concurrent-session
(same pattern as 0087/0088/0089), not regressions from this cycle. Coverage 92.51%
(rounds to 93%), above the 85% floor. UI 254/254 passed.

## 8. Per-level tail latency

Real number, not hand-waved: worst case ~1000s (~16.7 min) for a 50-URL level at
default concurrency=10, if every request in that level hits the full 200s worst
case — 5 sequential concurrent batches x `REQUEST_DEADLINE_S=200s`.

## 9. Handoffs

The gate-blocking concurrent-work failures (idempotency test, `chaos_test.py`/
`test_redis_config.py`/`test_redis_token_bucket.py` lint, postgres/celery/redis/
job_executor mypy) are not this cycle's scope — they belong to the concurrent
Redis/Celery/Postgres/multi-tenant session running this same session, as recorded
in cycles 0085 onward.

The 2 pre-existing `D205` issues in `tests/modules/seo/test_discovery.py` belong to
a sitemap-discovery feature (`MAX_SITEMAP_FETCH_ATTEMPTS`, `_sitemap_seeds`,
`robots_for`/`arobots_for`) that is also present, uncommitted, in the same shared
working tree this cycle but is not this cycle's to document — it touches neither
`REQUEST_DEADLINE_S`/`STALL_TIMEOUT_S`/`FETCH_RETRY_ON` nor any `fetch_outcomes`
bucket named in this cycle's brief.

## 10. Files changed

- `src/integrations/http_fetcher.py` — `FETCH_RETRY_ON` constant and its use in
  `afetch()` only (the file's `robots_for`/`arobots_for` additions and `_verify_peer`
  changes belong to other concurrent cycles, not this one).
- `src/modules/seo/page_classifier/discovery.py` — `OUTCOME_TRANSPORT_TIMEOUT`,
  `OUTCOME_TRANSPORT_REFUSED`, `OUTCOME_TRANSPORT_DEADLINE`, `_transport_outcome_for()`,
  updated `OUTCOME_MEANINGS` entries.
- `src/modules/seo/page_classifier/async_discovery.py` — `REQUEST_DEADLINE_S`,
  `STALL_TIMEOUT_S`, `_apaginate`'s new `wait_for` wrap, `_LoadGovernor._narrowing_signal()`,
  `_abody`/`_ahtml`/`_apaginate` routed through `_transport_outcome_for`.
- `tests/integrations/test_http_fetcher.py` — new
  `TestNonRetryableExceptionsPropagateOnFirstAttempt` class (2 tests).
- `tests/modules/seo/test_async_discovery.py` — one assertion fixed in
  `TestGuardrailRefusalOutcome::test_an_unsafe_redirect_is_bucketed_separately_from_transport_errors`
  (§3).

## 11. Follow-ups

None raised by this cycle beyond the concurrent-session gate blockers already
tracked in §9, which belong to other cycles.
