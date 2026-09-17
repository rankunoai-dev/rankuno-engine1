# Cycle 0091: A default that disagreed with itself

- **Date**: 2026-09-12
- **Scope**: `ApiState.__init__` (`src/api/server.py`) special-cased
  `max_concurrent_jobs`: whenever the configured value equaled
  `DEFAULT_MAX_CONCURRENT_JOBS` (5) it was discarded and replaced with a
  hardcoded 3 when constructing `FacetRouter` for `seo.page_classifier`. Fixed
  to a one-line pass-through.
- **Commit**: uncommitted at time of writing
- **Quality gate**: targeted files clean (`ruff check`, `mypy --strict`, both
  independently re-run); `tests/api/test_server.py` + `tests/api/test_multi_org.py`
  together — **161 passed, 1 skipped**, independently re-run, exit 0 (§5). Whole-repo
  `verify.ps1` not independently re-run this cycle (report taken per §5); reported
  RED on lint/type-check/1 test, all in files on this cycle's do-not-touch list.

## 1. Origin

The user reported a live 429: `facet 'seo.page_classifier' is at capacity (3
concurrent); please retry in a moment`, while the same running API's health
endpoint (`GET /api/v1/health`) reported `max_concurrent_jobs: 5` — a direct
contradiction between what the server told an operator and what it actually
enforced, diagnosed live against the running server this session.

## 2. Bugs found and fixed

`ApiState.__init__` (`src/api/server.py:730-737`, pre-fix):

```python
self.facet_router = FacetRouter(
    max_concurrent=max_concurrent_jobs if max_concurrent_jobs != DEFAULT_MAX_CONCURRENT_JOBS else 3
)
```

`Settings.max_concurrent_crawls` and `DEFAULT_MAX_CONCURRENT_JOBS` both default
to 5, so `max_concurrent_jobs == DEFAULT_MAX_CONCURRENT_JOBS` was true on every
normal startup that did not explicitly override the setting — not an edge
case, the common case. The ternary then threw the configured value away and
hardcoded 3 for the one facet that matters in Phase 1
(`seo.page_classifier`), while `self.max_concurrent_jobs` (the value the
health endpoint reads, and the value the global admission check in
`try_reserve` — `len(self._active) >= self.max_concurrent_jobs`, line 767 —
uses) kept the real 5. Two numbers, one process, disagreeing with each other
by construction.

`git blame` on the line (confirmed directly, not taken from the implementer's
report) attributes it to commit `04a8b15` ("Phase 1 Tool Registry & Facet
Router for multi-facet isolation", 2026-09-09) — **not** `ee58eceb` as the
implementer's report states; `ee58eceb` is a different, later commit
("Idempotency-Key header and request deduplication"). This is corrected here
rather than silently, per the standing rule against editing a stated fact
without flagging it (§6).

Fix:

```python
self.facet_router = FacetRouter(max_concurrent=max_concurrent_jobs)
```

`FacetRouter.__init__`'s own default (`primary_max = max_concurrent if
max_concurrent is not None else 3`, `src/core/facet_router.py:74`) was read
and confirmed correct and untouched: it only applies when the caller passes
`None`, which `ApiState` never does — `max_concurrent_jobs` always has a
concrete `int` value (its own default is `DEFAULT_MAX_CONCURRENT_JOBS`, not
`None`). The bug was entirely in what `ApiState` chose to pass in, not in
`FacetRouter`'s fallback.

`seo.health_engine` and `seo.theme_classification`'s hardcoded
`max_concurrent=2` (`facet_router.py:88`, `:96`) were read and confirmed to be
unrelated: independent placeholder ceilings for two facets the module
docstring (`facet_router.py:12-13`) states are "(Placeholder, not yet
implemented)" — not instances of the same bug, and left unchanged.

Independently re-verified before/after by temporarily restoring the ternary
and re-running the two regression tests added this cycle
(`tests/api/test_server.py::TestFacetRouterCapWiring`):

```
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[5]
    assert page_classifier_cap == cap
E   assert 3 == 5
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_health_endpoint_agrees_with_facet_cap_on_default_startup
    assert body["max_concurrent_jobs"] == facet_cap
E   assert 5 == 3
```

With the one-line fix restored, both pass, along with the pre-existing
`test_page_classifier_has_its_own_concurrency_cap` (7 tests total in
`-k "TestFacetRouterCapWiring or test_page_classifier_has_its_own_concurrency_cap"`,
independently re-run, all pass).

## 3. Corrections — the tests were incidentally right, not deliberately

Seven existing tests called `create_app()` without an explicit
`max_concurrent_jobs` and asserted a 3-slot `seo.page_classifier` cap: the 5 in
`TestConcurrencyCap` (`test_excess_jobs_are_refused_with_429`,
`test_a_refused_job_leaves_no_record`,
`test_releasing_a_reservation_decrements_active_count`,
`test_reserving_is_atomic`, `test_releasing_frees_a_slot`),
`TestPerFacetConcurrency::test_page_classifier_has_its_own_concurrency_cap`,
and `TestConcurrencyIsolation::test_org_a_at_capacity_does_not_block_org_b`.
Before this fix, that passed only because the bug's hardcoded 3 happened to
match what the test wanted — the tests were correct about *what* should exist
(a 3-slot cap must be testable somewhere) but wrong about *how* they got it
(relying on a startup default coinciding with a hardcoded fallback, not on a
deliberately configured cap). Fixed by pinning `max_concurrent_jobs=3`
explicitly at each call site instead of leaving it to a default that, after
this fix, is no longer 3.

## 4. A follow-up this fix exposes but does not close

`tests/api/test_multi_org.py::TestConcurrencyIsolation::test_different_facets_have_separate_concurrency`
still passes after this fix, but its assertion is no longer proving what its
name claims. It calls `create_app()` with no explicit cap (so
`max_concurrent_jobs=5`, the real default now that it is not overridden),
reserves 3 `seo.page_classifier` slots and 2 `seo.health_engine` slots (5
total), then asserts a 4th `seo.page_classifier` reservation and a 3rd
`seo.health_engine` reservation both fail.

Read against `try_reserve` (`server.py:753-780`), that check happens in two
stages — a global check first, a facet check second:

```python
if len(self._active) >= self.max_concurrent_jobs:  # global: 5
    return False
...
if len(active) >= facet_config.max_concurrent:  # facet: 3 or 2
    return False
```

With the cap correctly at 5, both assertions are satisfied by the **global**
`len(self._active) >= 5` check firing at exactly 3+2 = 5 active jobs, not by
the per-facet checks the test exists to demonstrate: `page_classifier`'s own
facet cap (5, untouched by the two health_engine reservations) is nowhere
close to being reached, and `health_engine`'s facet cap (2) is reached at the
same moment the global cap is. Verified by direct read of the reservation
counts and both cap values, not inferred. Not fixed this cycle — touching a
passing test outside this cycle's acceptance criteria would be scope creep —
but recorded here so a later reader does not mistake "this test passes" for
"per-facet isolation is what makes it pass."

## 5. Tests

Independent full-file run of both touched test files together (this cycle's
own run, not copied from the implementer's report — see the count correction
below):

```
tests/api/test_server.py tests/api/test_multi_org.py --no-header

........................................................................ [ 44%]
........................................................................ [ 88%]
............s.....                                                       [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
  deprecated; install `httpx2` instead.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
161 passed, 1 skipped, 1 warning in 228.37s (0:03:48)
```

**Correction to the implementer's report**: the implementer's report states
"tests/api/test_server.py (full file): 145 passed. tests/api/test_multi_org.py
(full file): 24 passed, 1 skipped" (169/170 total). Independently re-run
`--collect-only` counts are `tests/api/test_server.py: 137` and
`tests/api/test_multi_org.py: 25` (162 total), matching the 161-passed/1-skipped
figure above exactly (137 + 24 passed + 1 skipped = 162). `test_server.py`'s
real count is 137, not 145 — an 8-test overstatement in the implementer's
report. The discrepancy does not change the outcome (no failures either way,
exit 0 both times) and is recorded as a correction per this project's
build-log rule, not silently reconciled.

Targeted regression proof (before/after the fix, §2) and ruff/mypy on the
three touched files, independently re-run:

```
ruff check src/api/server.py tests/api/test_server.py tests/api/test_multi_org.py
All checks passed!

mypy --strict src/api/server.py
Success: no issues found in 1 source file
```

`scripts/drift_check.py`, independently re-run:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 163 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 6. Gate (whole-repo, as reported by the implementer — not independently re-run)

The whole-repo `verify.ps1` gate was not independently re-run this cycle
(observed cost: the two-file targeted run alone took 228s in this
environment; a full run is several times that — see cycle 0088/0089/0090 for
comparable full-run durations). The implementer's reported tail is pasted
here per the "paste verbatim" rule, with the caveat that it is reported, not
independently reproduced end-to-end:

```
=== Format === 346 files already formatted, PASSED
=== Lint === Found 25 errors. FAILED
=== Type check === Found 13 errors in 5 files. FAILED
=== Tests === TOTAL 9022 582 2234 167 93%; 2 failed, 2361 passed, 2 skipped, 1 warning in 453.58s. FAILED
=== UI Component Tests === 254/254 passed. PASSED
VERIFICATION FAILED: Lint, Type check, Tests
```

The implementer attributes every lint/type-check failure to files never
touched by this fix (`scripts/chaos_test.py`, `src/workers/job_executor.py`,
`src/core/postgres_store.py`, `src/core/redis_config.py`,
`src/core/rate_limiter.py`, `src/core/celery_config.py`,
`tests/core/test_redis_config.py`, `tests/core/test_redis_token_bucket.py`,
`tests/modules/seo/test_discovery.py`'s pre-existing `D205`s) — all on this
cycle's explicit do-not-touch list, confirmed unrelated by the independent
`ruff`/`mypy` spot-check on the touched files in §5, which is clean. Of the
"2 failed": one is reported as `test_org_a_at_capacity_does_not_block_org_b`
failing only because the gate's single pytest collection ran before the
`test_multi_org.py` fix was on disk — independently re-run in §5 (24 passed
within the 161, 0 failed). The other is the pre-existing unrelated
idempotency/org-access failure (§7). Coverage reported at 93%, above the 85%
floor.

## 7. Handoffs

- `src/api/server.py` carries one unrelated in-flight hunk from the
  concurrent multi-tenant/facet session (`_run_job`'s `stopped_reason`
  handling, build-log 0088) interleaved in the same file. Left untouched.
- `tests/api/test_idempotency.py::TestIdempotencyKeyDeduplication::test_idempotency_key_per_org`
  fails for an unrelated org-access-control gap in the in-progress
  multi-tenant work — not this cycle's concern.
- `TestConcurrencyIsolation::test_different_facets_have_separate_concurrency`
  now passes for a coincidental reason (§4) rather than the per-facet
  isolation its name claims. Flagged, not fixed.

## 8. Live server

The fix was applied to the running local API server (previously enforcing the
buggy 3-slot cap since `ApiState.facet_router` is built once at process
startup — restarting is required for the fix to take effect on an already-running
process). The server (previously PID 952 on port 8000) was restarted this
session; `GET /api/v1/health` returned
`{"status":"ok","active_jobs":0,"max_concurrent_jobs":5}` immediately after.
Independently re-checked at the time of writing this entry:
`{"status":"ok","active_jobs":1,"max_concurrent_jobs":5}` — `max_concurrent_jobs`
still correctly 5; `active_jobs` differs from the immediate post-restart
reading because a job was admitted in the interim, not because of a
regression.

## 9. Explicitly not done

- `seo.health_engine` / `seo.theme_classification`'s hardcoded `max_concurrent=2`
  left unchanged — confirmed unrelated placeholder ceilings (§2).
- The global admission cap logic (`DEFAULT_MAX_CONCURRENT_JOBS`,
  `try_reserve`'s `len(self._active) >= self.max_concurrent_jobs` check) left
  unchanged — it was never the buggy path; only what `ApiState` passed to
  `FacetRouter` was wrong.
- `test_different_facets_have_separate_concurrency`'s coincidental pass (§4)
  not fixed, only flagged.
- The concurrent-session gate failures (Redis/Celery/Postgres/multi-tenant
  work) not fixed; out of scope and on the explicit do-not-touch list.
- No ADR: this restores previously intended behavior (a one-line pass-through
  that the code's own docstring already implied — "typically set from
  `Settings.max_concurrent_crawls`") rather than establishing a new
  architectural ruling.

## 10. Files changed

- `src/api/server.py` — `ApiState.__init__`, one-line fix (§2).
- `tests/api/test_server.py` — `TestFacetRouterCapWiring` (new, 2 tests);
  `max_concurrent_jobs=3` pinned explicitly across `TestConcurrencyCap` and
  `test_page_classifier_has_its_own_concurrency_cap` (§3).
- `tests/api/test_multi_org.py` — same pin in
  `test_org_a_at_capacity_does_not_block_org_b` (§3).
