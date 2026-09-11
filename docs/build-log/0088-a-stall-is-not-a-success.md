# Cycle 0088: A stall is not a success

- **Date**: 2026-09-11
- **Scope**: `_run_job` in `src/api/server.py` decided `SUCCEEDED` vs `PARTIAL` from
  `output.discovery.truncated` alone, so a crawl that stalled or aborted — with
  `truncated=False`, because it never reached the page ceiling — was reported
  `SUCCEEDED`. Fixed to consult `stopped_reason` too, per `discovery.py`'s own
  documented contract.
- **Commit**: uncommitted at time of writing
- **Quality gate**: targeted suite (`tests/api/test_server.py`,
  `tests/core/test_state_store.py`, `tests/core/test_postgres_store.py`,
  `tests/modules/seo/test_async_discovery.py`, `tests/modules/seo/test_discovery.py`)
  — **337 passed**, independently re-run, exit 0; mypy `--strict` and ruff clean on the
  3 touched `src/` files central to this fix (`server.py`, `state_store.py`,
  `postgres_store.py`); full-repo `verify.ps1` not green — 1 pre-existing test failure
  and 25 pre-existing lint errors, all independently confirmed outside this change's
  dependency chain (see §7).

## 1. Origin

This session's diagnosis of a live infosys.com crawl (job
`0f69b80025874d30b57f54de33b8f705`) — the same job that motivated cycle 0087's
`guardrail_refused` outcome bucket — surfaced a second, unrelated problem while
reading `discovery.py`'s contract for `unfetched_urls()`:

> Callers deciding whether a crawl has unfinished work must consult `truncated` and
> `stopped_reason`, not this length.

`src/api/server.py`'s completion decision honoured only half of that contract. It
read `output.discovery.truncated` to choose `PARTIAL` over `SUCCEEDED`, but never
read `output.discovery.stopped_reason` — the field `async_discovery.py` sets when a
crawl is abandoned (`CrawlStalledError`, or a generic exception caught around
`_acrawl`) rather than merely capped. A stalled or aborted crawl that had not yet
reached its page ceiling had `truncated=False`, so it read as a clean finish.

## 2. Bugs found and fixed

`_run_job` (`src/api/server.py`, pre-fix around lines 850-862) computed:

```python
partial = output.discovery.truncated
```

`stopped_reason` is set at two points in `async_discovery.py`:

- `_acrawl` catches `CrawlStalledError` and sets `graph.stopped_reason = str(exc)`
  (confirmed at line 725; the raise site is line 280 in the sync/shared module,
  triggered when nothing completes within `stall_timeout_s`).
- `adiscover_site`'s outer `except Exception` around `_acrawl` sets
  `graph.stopped_reason = f"{type(exc).__name__}: {exc}"` (confirmed at line 440) —
  the abort path, any exception that would otherwise have killed the crawl outright.

Neither path sets `truncated`. Regression tests
(`tests/api/test_server.py::TestJobLifecycle::test_a_stalled_crawl_never_reaches_succeeded`
and `::test_an_aborted_crawl_never_reaches_succeeded`) constructed a
`DiscoveryReport(truncated=False, stopped_reason=<reason>)` and asserted the job
record before the fix; both failed with `SUCCEEDED` instead of the expected
`PARTIAL`, confirming the bug independently of the implementer's report.

Fix, `src/api/server.py`:

```python
discovery = output.discovery
store.finish(
    job_id,
    output.model_dump(mode="json"),
    partial=discovery.truncated or discovery.stopped_reason is not None,
    error=discovery.stopped_reason,
)
```

`retrieved_nothing` does not reach this branch at all: `tool.py:436-437` raises
`CrawlBlockedError` for it inside `execute()` before a `PageClassificationOutput` is
ever returned, and the pre-existing `if not result.ok` check higher in `_run_job`
already routes that to `mark_failed` (macys.com-403, build-log 0013) — confirmed
unchanged by this cycle.

## 3. Design decision — no new `JobStatus` member

`PARTIAL` already means, by its own docstring, "finished, but the result is
incomplete." A stalled or aborted crawl produces a real partial graph exactly like a
ceiling-truncated one: same lifecycle state (terminal, has a result, UI must say it
is incomplete), different reason for stopping early. Adding a fourth terminal status
would have meant threading it through `TERMINAL_STATUSES`, `is_terminal`, the
TypeScript `JobStatus` union, `STATUS_COLOUR`, and every status-readiness check in
the UI, for a distinction that is about *why* a `PARTIAL` happened, not *what kind*
of terminal state it is.

Instead, `JobRecord.error` — previously `FAILED`-only by convention, not by any
enforced invariant — was extended to also carry `stopped_reason` verbatim on a
`PARTIAL` job. `JobStore.finish()` (the `Protocol`, `DiskJobStore`, and
`PostgresJobStore`) gained an `error: str | None = None` keyword argument;
`DiskJobStore.finish()` forwards it into `_transition(..., error=error)`.

This is the design decision an operator should be able to reverse if it proves
wrong: the alternative (a real 4th status, e.g. `STALLED`) was considered and
rejected for cost, not correctness. It is recorded here rather than as an ADR
because it extends an existing field rather than introducing a new concept —
`JobRecord.error` already existed and already meant "why did this job not finish
cleanly"; broadening which terminal statuses populate it is not, on its own, a new
architectural decision requiring the ADR process's overhead.

### Status-mapping table

| `truncated` | `stopped_reason` | `retrieved_nothing` | `JobStatus` | `JobRecord.error` |
|---|---|---|---|---|
| False | None | False | `SUCCEEDED` (unchanged) | `None` |
| True | None | False | `PARTIAL` (unchanged) | `None` — ceiling only, not an error |
| False | set (stall or abort) | False | `PARTIAL` (was `SUCCEEDED` — the bug) | `stopped_reason`, verbatim |
| True | set | False | `PARTIAL` (unchanged status) | `stopped_reason`, verbatim — both signals reach the record: `truncated` stays visible via `output.discovery.truncated` / `CrawlJobSummary.truncated`, `stopped_reason` via `error` |
| any | any | True | `FAILED` (unchanged — `CrawlBlockedError` → `mark_failed`, never reaches this branch) | `_blocked_message(...)` |

Independently exercised by
`tests/api/test_server.py::TestJobLifecycle::test_ceiling_and_stall_together_drop_neither_signal`,
which asserts both `record.error == reason` and, via the `/result` endpoint, that
`discovery.truncated is True` and `discovery.stopped_reason == reason` survive
together — confirmed passing.

UI surface: `rankuno-ui/src/adapters/adapterInterface.ts` adds
`CrawlJobSummary.stoppedReason?: string | null`; `httpAdapter.ts` populates it from
`record.error` only when `status === "partial"` (a `FAILED` job's `error` already
renders through the existing error path, so it is deliberately not duplicated here).
`CrawlJobsView.tsx`'s new `statusDetail()` renders "hit page ceiling" for a
`stoppedReason`-less `PARTIAL` and "stalled/aborted" for one that has it, next to the
status tag. Covered by the new
`rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx` (4 tests, independently
re-read).

## 4. A test that was wrong, not the code

`tests/core/test_postgres_store.py::TestPostgresJobStoreMethodDelegation::test_finish_delegates_to_fallback`
failed after the `src/core/state_store.py` fix — not because the fix was wrong, but
because `PostgresJobStore.finish()` needed to forward the new `error` kwarg to
satisfy the extended `JobStore` Protocol, and the test's mocked expectation had not
been updated to match:

```python
# before (wrong once the Protocol changed)
fallback.finish.assert_called_once_with("job-id", result, partial=False)
# after
fallback.finish.assert_called_once_with("job-id", result, partial=False, error=None)
```

The source (`PostgresJobStore.finish`) was changed to forward `error` because the
Protocol now requires it — that is a real code change, not a test-only fix. What was
wrong was the pre-existing test's expected call signature, which no longer matched
the (correctly extended) Protocol. Independently confirmed by reading the diff: only
the assertion changed, `PostgresJobStore.finish()`'s body changed to add the
parameter and forward it, both `finish()` calls under `is_open()` / not identical
(pre-existing duplication, untouched by this cycle).

## 5. Gate

Targeted suite, independently re-run by docs-scribe:

```
tests/api/test_server.py tests/core/test_state_store.py tests/core/test_postgres_store.py
tests/modules/seo/test_async_discovery.py tests/modules/seo/test_discovery.py

........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 64%]
........................................................................ [ 85%]
.................................................                        [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
  deprecated; install `httpx2` instead.
[exited with code 0]
```

337 passed, exit 0 (the implementer's report claims a 3x-repeated run; docs-scribe
independently re-ran once and reproduced the same pass count and exit code — the
`3x consecutively` claim itself was not re-verified beyond this one confirming run).

mypy `--strict` on the 3 touched `src/` files central to this fix, independently
re-run:

```
Success: no issues found in 2 source files
```

(`server.py` and `state_store.py` checked together; `postgres_store.py` depends on
`sqlalchemy`/Postgres stubs shared with the concurrent multi-tenant session and was
not re-run in isolation — the implementer's report of a clean whole-repo mypy pass
outside the 13 pre-existing errors below was taken on that basis, not independently
re-verified file-by-file for `postgres_store.py`.)

`ruff check .` (whole repo), independently re-run:

```
Found 25 errors.
```

All 25 attributed to 5 files, independently confirmed by file-level count:

```
     12 scripts\chaos_test.py
      6 src\workers\job_executor.py
      2 tests\core\test_redis_config.py
      3 tests\core\test_redis_token_bucket.py
      2 tests\modules\seo\test_discovery.py
```

The 2 `test_discovery.py` errors are both `D205` inside `TestSitemapFetchCeiling`
(lines 795 and 869) — outside this cycle's `discovery.py`/`async_discovery.py`
touch, matching the "pre-existing D205s not part of this cycle" exclusion in the
task brief; independently confirmed by line number, not taken on the implementer's
word. `chaos_test.py`, `job_executor.py`, `test_redis_config.py`, and
`test_redis_token_bucket.py` are all on the explicit do-not-touch list for this
cycle (concurrent Redis/Celery/Postgres/multi-tenant session).

`tests/api/test_idempotency.py::TestIdempotencyKeyDeduplication::test_idempotency_key_per_org`,
independently re-run in isolation (not via git-stash reproduction — that step was
not repeated here, see §7 handoff): fails with `KeyError: 'id'` after a
`job_rejected_unknown_org` warning — an org-provisioning failure, unrelated to the
completion-status decision this cycle touches. This confirms the failure is real and
present, though the implementer's specific claim of reproducing it identically via
`git stash` on the unmodified tree was not independently re-performed.

Full `verify.ps1` pytest+coverage phase (2,348 passed / 1 failed / 2 skipped,
552.98s) and the UI suite (254 passed) were not independently re-run in full this
cycle, given their reported length; the targeted suite and lint/mypy spot-checks
above are the evidence offered instead of re-running the entire gate a second time.

## 6. Explicitly not done

- No new `JobStatus` enum member — justified in §3.
- `CrawlCheckpointer` / resume semantics untouched.
- `src/workers/job_executor.py` (the Celery stub) left alone — confirmed not the
  effective execution path; `asyncio.to_thread` via `_dispatch`/`_run_job` is what
  actually runs a job, `execute_crawl` is unused.
- Pre-existing lint/type/test failures outside this fix's dependency chain not
  fixed (§5).
- Did not independently re-run the implementer's `git stash` reproduction of the
  idempotency failure, or the implementer's claimed 3x-consecutive targeted-suite
  repetition — both taken partially on report, with one direct re-run each as a
  check rather than a full re-verification (§5).

## 7. Handoffs

- `tests/api/test_idempotency.py::TestIdempotencyKeyDeduplication::test_idempotency_key_per_org`
  fails independent of this change (confirmed §5) and belongs to the multi-tenant
  org-config work, not this fix.
- CLAUDE.md §8 still lists `src/core/circuit_breaker.py` as "does not exist." It
  exists and is imported at `src/core/postgres_store.py:16` (confirmed by direct
  read this cycle). README.md's architecture table (line 129) makes the same stale
  claim. Both are documentation drift belonging to the concurrent
  Redis/Celery/Postgres session that introduced `circuit_breaker.py` and
  `postgres_store.py`, not to this cycle's scope (JobStatus/PARTIAL/the completion
  decision only) — flagged here for a future correction under CLAUDE.md §8's
  "Closed since the audit" pattern. Not edited in this cycle without operator
  approval, per this project's standing rule against agents editing CLAUDE.md
  unprompted.

## 8. Files changed

- `src/api/server.py`
- `src/core/state_store.py`
- `src/core/postgres_store.py`
- `rankuno-ui/src/adapters/adapterInterface.ts`
- `rankuno-ui/src/adapters/httpAdapter.ts`
- `rankuno-ui/src/components/jobs/CrawlJobsView.tsx`
- `rankuno-ui/src/components/jobs/jobs.css`
- `tests/api/test_server.py`
- `tests/core/test_state_store.py`
- `tests/core/test_postgres_store.py`
- `rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx` (new)
