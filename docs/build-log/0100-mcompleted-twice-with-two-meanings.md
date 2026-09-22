# Cycle 0100: mCompleted, twice, with two meanings

- **Date**: 2026-09-22
- **Scope**: Live progress telemetry (pages crawled, completion percentage,
  coarse phase) for Screaming Frog crawls dispatched through the ADR 0015
  worker system — a worker-side `trace.txt` tail, a new
  `POST /workers/jobs/{id}/progress` endpoint, and three new optional fields
  on `WorkerJobView`. Additive to ADR 0015, not a revision of it.
- **Commit**: `c7ff68b` — merge commit, first parent `9eeb218` (main's tip at
  merge time, a separate concurrent UI session), second parent `2884d59`
  (this cycle's single commit). Verified: `git merge-base 9eeb218 2884d59`
  resolves to `46863d2` — main's tip when the feature branch forked — and
  `git diff 46863d2 2884d59 --stat` produces byte-identical file/insertion/
  deletion counts to `git show --stat c7ff68b` (19 files, 1,597
  insertions(+), 13 deletions(-)), confirming a clean merge with nothing to
  resolve (the UI session's files and this cycle's files are disjoint).
- **Quality gate**: Targeted — 192 passed, 0 failed (independently re-run,
  exit 0). Coverage on this cycle's 8 new/touched `src/` files (excluding
  `core/config.py`, shared and 900+ lines, see §1) — 94.03% (independently
  re-run). `ruff format --check` clean on all 12 touched non-test files.
  `ruff check` clean except one pre-existing `E402` in
  `scripts/register_worker.py`, confirmed present before this cycle's diff.
  `mypy --strict` clean on 11 of 12 touched non-test files; the 12th
  (`postgres_worker_dispatch_store.py`) fails only on `psycopg` not being
  installed in this venv, the same pre-existing condition build-log 0098
  already documented, reproduced here on the same file. Whole-repo: the same
  single pre-existing `TestCircuitBreaker::test_circuit_breaker_recovers_
  after_success` failure, reproduced across two independent full-suite runs;
  no whole-repo aggregate pass count is asserted (see §1 — this session hit
  the identical trailing-summary-line buffering artifact build-log 0098 §1
  already reported, not fabricated around here either).

---

## 1. Gate results

Targeted suite, independently re-run:

```
.venv\Scripts\python.exe -m pytest tests/modules/seo/screaming_frog_control/test_progress_parser.py \
  tests/modules/seo/screaming_frog_control/test_tool.py \
  tests/modules/seo/screaming_frog_control/test_worker_daemon.py \
  tests/api/test_worker_routes.py \
  tests/core/test_postgres_worker_dispatch_store.py \
  tests/integrations/test_worker_cloud_client.py -q

192 passed, 1 warning in 25.14s
```

Coverage on this cycle's own touched/new `src/` files, independently re-run
(`core/config.py` deliberately excluded from this isolated figure: this
cycle added exactly 2 of its 250+ `Settings` fields, and running only this
cycle's 6 test files against the whole file reports 56% — an artifact of
scope, not a real gap; the whole-repo run below exercises the rest of it):

```
Name                                                        Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------------------------------------
src\api\worker_routes.py                                       86     10      4      0    89%
src\core\postgres_worker_dispatch_store.py                    169     26     16      1    85%
src\modules\seo\screaming_frog_control\progress_parser.py     112      6     28      3    94%
src\modules\seo\screaming_frog_control\tool.py                 99      2     16      2    97%
src\modules\seo\screaming_frog_control\worker_daemon.py       133      6     22      3    94%
-------------------------------------------------------------------------------------------------------
TOTAL                                                          896     50     92      9    94%

5 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 94.03%
```

(The 5 files at 100% and skipped from the printed table: `api/worker_schemas.py`,
`core/worker_dispatch_store.py`, `core/worker_dispatch_schemas.py`,
`integrations/worker_cloud_client.py`, `modules/.../schemas.py`.)

`ruff format --check` on the 12 touched non-test files (11 `src/` +
`scripts/register_worker.py`): `12 files already formatted`.

`ruff check` on the same 12 files:

```
E402 Module level import not at top of file
  --> scripts\register_worker.py:22:1
   |
20 | sys.path.insert(0, str(REPO_ROOT))
21 |
22 | import httpx
```

Confirmed pre-existing: `git diff 46863d2 c7ff68b -- scripts/register_worker.py`
shows this cycle's only change to that file was removing two now-unused
imports (`json`, `os`) and fixing an f-string with no placeholders — the
`sys.path.insert` / `import httpx` ordering that trips `E402` was already
there. Not this cycle's regression.

`mypy --strict` on the same 12 files:

```
src\core\postgres_worker_dispatch_store.py:62: error: Cannot find implementation or
  library stub for module named "psycopg"  [import-not-found]
Found 1 error in 1 file (checked 12 source files)
```

Identical to the condition build-log 0098 §1 already documented and traced to
`psycopg` not being installed in this venv at all — not a regression.

Whole-repo `pytest -q` was run twice this session, once via `run_in_background`
with output piped through `tee` to a file. Both runs' visible failure lists were
identical:

```
FAILED tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success
```

`TestFacetRouterCapWiring` — the class build-log 0097 and 0098 both listed as a
pre-existing, concurrently-owned failure — is **not** in this failure list.
Verified directly, not just by absence: `pytest tests/api/test_server.py::
TestFacetRouterCapWiring -v` run in isolation this session passes clean, 6/6.
See §5.

Neither whole-repo run printed pytest's own final aggregate summary line (`N
failed, M passed, K skipped in Ts`) — the identical artifact build-log 0098 §1
already reported and attributed to output buffering on very large redirected
runs in this Windows/git-bash environment, not a test-suite defect. Reproduced
here independently, on a different session, several days later. No whole-repo
pass/fail/skip total is asserted in this entry that was not directly observed.
The single failure above was directly observed on both runs.

`.\.venv\Scripts\python.exe scripts\drift_check.py`, run before any doc edits
this cycle:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 177 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

Re-run after this entry's own doc edits (this file, the `docs/build-log/
README.md` index row, and the `README.md`/`docs/ARCHITECTURE.md` additions):
still `PASSED: no drift detected across 177 markdown files`, an unchanged
count — `_iter_markdown_files()` counts via `git ls-files`, not a filesystem
walk (its own docstring: "Asks git rather than walking the filesystem"), so
this entry itself and the index row do not add to the count until committed.
`README.md`/`ARCHITECTURE.md` are already-tracked files, so their edits are
covered by the same 177 either way. See §7 for the full file list.

## 2. What landed

- **`src/modules/seo/screaming_frog_control/progress_parser.py`** (new,
  358 lines) — `parse_latest_progress`, `ScreamingFrogProgressReader`,
  `ScreamingFrogProgressThrottle`, `ProgressPollThread`,
  `make_progress_callback`. Read directly and verified against a real,
  currently-running `ScreamingFrogSEOSpiderCli.exe 19.4` crawl on this
  workstation, per the module's own docstring: the feature's original
  illustrative progress-line format (`Spidering ... (15 of 120, 12.5%)`) was
  never observed and does not exist. The real format is a `SpiderMain`
  thread line:

  ```
  SpiderProgress [mActive=4, mCompleted=3,718, mWaiting=5,474, mCompleted=40.43%]
  ```

  `mCompleted` appears twice, once as a raw completed-page count and once
  (later in the same bracket) as a percentage — the same key name for two
  different meanings, which is Screaming Frog's own field-naming collision,
  not a transcription error. Large counts use a comma thousands separator.
  The module's own regex (`_SPIDER_PROGRESS_LINE`) strips commas before
  parsing; `license_check.py`'s pre-existing, unrelated completion-line regex
  does not — see §4.
- **`ScreamingFrogProgressReader`** — offset-scoped, rotation-aware reads.
  Verified: once a rotation is detected (file shrinks below the last
  recorded offset, or disappears), `self._rotated` latches permanently and
  every subsequent `poll()` returns `None` without re-attempting a read —
  deliberately not "reattach to the new file," since a freshly rotated
  `trace.txt` may belong to a different run entirely (a manually started
  GUI, per `license_check.py`'s own shared-log-file caveat) and misattributing
  its contents to this job would be worse than going quiet. This closes the
  gap `license_check.py`'s own module docstring already named as unhandled.
- **`ScreamingFrogProgressThrottle`** — coalesces on the worker side, before
  any network call, floor `Settings.worker_progress_min_report_interval_s`
  (default 5.0s). A phase transition always passes through immediately
  regardless of the floor. Deliberate design choice, not an afterthought —
  the module's docstring and this entry's §3 both explain why: `Postgres
  WorkerDispatchStore` opens a fresh connection per call with no pool (ADR
  0015 condition 5), so an un-throttled "report every poll tick" policy would
  cost roughly one such connection every 1.5s for the length of a crawl that
  can legitimately run 2 hours — thousands of writes for one job.
- **`ProgressPollThread`** — a `threading.Thread` subclass, `daemon=True`.
  Verified: its stop flag is named `self._stop_event`, not `self._stop` — the
  module's own comment explains why (`threading.Thread` already owns a
  private `_stop` method used by `join()`'s internals; shadowing it with an
  instance attribute of the same name silently breaks `join()`). Caught by
  this cycle's own thread-lifecycle tests, not by inspection — see §4.
- **`src/modules/seo/screaming_frog_control/tool.py`** — `execute()` starts
  the poll thread (only if a caller passed `on_progress`; every pre-existing,
  non-worker caller sees no behaviour change) and stops+joins it
  unconditionally in the same block that already guarantees
  `process.terminate()` runs on every exit path — success, timeout, or an
  exception raised mid-loop. Join timeout 5.0s; the thread is a daemon, so a
  join that times out leaks at most one already-in-flight report, never the
  interpreter.
- **`src/api/worker_routes.py`** — `POST /workers/jobs/{job_id}/progress`.
  Read directly: `require_worker_principal` then `owned_job(state, job_id,
  principal.worker_id, principal.org_id)` — the exact same two-line
  ownership check `/upload` and `/failed` already use, refusing a worker that
  did not claim the job with `403` (the same IDOR discipline ADR 0015
  condition 2 and condition 6 require). Never changes `status`.
- **`src/api/worker_schemas.py`** — `WorkerProgressReport` (`StrictModel`,
  `extra="forbid"`, every field optional: `pages_crawled: int | None` `ge=0`,
  `progress_pct: float | None` `ge=0.0` with no upper bound, `phase:
  WorkerJobPhase | None`). `WorkerJobView` gained `pages_crawled`,
  `progress_pct`, `current_phase`, documented as `None` until a worker
  reports and never guaranteed monotonically increasing (Screaming Frog's own
  denominator grows as new URLs are discovered mid-crawl).
- **`src/core/worker_dispatch_store.py`** / **`postgres_worker_dispatch_store.py`**
  — `update_job_progress`, deliberately not routed through the existing
  `_transition` helper (verified: that helper always writes
  `status`/`finished_at` alongside its columns; a progress report is neither
  a status transition nor evidence of completion, and writing `finished_at`
  on every one of a multi-hour crawl's periodic reports would fabricate a
  finish time that keeps moving).
- **`src/integrations/worker_cloud_client.py`** — `report_progress`, a
  `BaseAPIClient` call like every other method on this client. Its own
  docstring is explicit that deciding a lost report is disposable is the
  *caller's* decision, not this client's — it still raises like every other
  call; `ProgressPollThread` is what treats the exception as swallow-and-log.
- **`src/core/config.py`** — two new `Settings` fields,
  `screaming_frog_progress_poll_interval_s` (default 1.5s, worker-side read
  interval) and `worker_progress_min_report_interval_s` (default 5.0s, the
  throttle floor described above).
- **`alembic/versions/0004_worker_job_progress_columns.py`** — additive
  migration, chains onto `003` correctly. Three nullable columns, no
  `server_default` (`NULL` means "no report yet," not zero), plus a check
  constraint on `current_phase IN ('crawling', 'exporting')`.

## 3. Design decisions

- **Throttle on the worker, before any network call, not on the cloud side.**
  The alternative — accept every report and let the cloud coalesce or
  rate-limit it — was rejected because `PostgresWorkerDispatchStore` has no
  connection pool and no in-process fallback by design (ADR 0015 condition
  5); a policy that still opens one Postgres connection per tick just to
  decide whether to *keep* the write does not save anything. Coalescing
  client-side means the expensive resource is never touched for a report that
  would be discarded anyway.
- **Progress never changes job `status`.** Verified as a design invariant,
  not an incidental property: `update_job_progress` is a separate code path
  from `_transition`, specifically so a progress report racing a terminal
  transition (`mark_uploaded`/`mark_failed`) can only ever overwrite the
  three progress columns, never resurrect or short-circuit the job itself. A
  late report after a job has already finished is explicitly harmless by
  construction, not by convention.
- **Rotation degrades permanently and silently (one warning log), rather than
  reattaching.** Named in §2; the alternative (reattach to the new, now-tiny
  `trace.txt`) was rejected because that file's origin cannot be
  distinguished from a different run's own start, and the crawl itself must
  never be affected either way — this class only ever reads.

## 4. Bugs found and fixed

- **`threading.Thread._stop` name collision.** Naming the poll thread's own
  stop flag `self._stop` silently shadows a private method
  `threading.Thread` already defines and uses internally in `join()`'s
  bookkeeping — the collision does not raise at assignment time, only breaks
  `join()` later, with an error unrelated to anything in this class's own
  code. Caught by this cycle's own thread-lifecycle tests (`test_join_
  succeeds_after_stop_is_called`, `test_polls_exactly_once_more_after_stop_
  even_with_a_long_interval` in `test_progress_parser.py`), not by
  inspection. Fixed by naming the attribute `self._stop_event` instead, with
  a code comment explaining why, so the same mistake is not made again
  locally.
- **The feature's own original design's illustrative progress-line format was
  never real.** `Spidering https://example.com/page-1 ... (15 of 120, 12.5%)`
  — this was the pasted design document's own example of what Screaming
  Frog's `trace.txt` looks like mid-crawl. Verified against a real, live
  19.4 headless crawl on this workstation: that line shape does not occur.
  This is a bug in the specification the implementation was handed, not in
  any code — flagged per CLAUDE.md §2's explicit instruction to record
  spec bugs, not only code bugs. The regex this cycle shipped was built
  against the real captured format instead.
- **`license_check.py`'s completion-line regex has the same comma-thousands-
  separator bug this cycle's own regex was built to avoid** — found, but
  correctly **not fixed** in this cycle (a pre-existing file this cycle does
  not otherwise touch; see §6 and §8).

## 5. Corrections

- **`TestFacetRouterCapWiring` is no longer failing.** Build-log 0097 and
  0098 both recorded this class (in `tests/api/test_server.py`, then an
  uncommitted file belonging to a separate concurrent session) as a
  reproducing, pre-existing whole-repo failure and explicitly declined to
  investigate it as out of scope. This cycle independently re-ran the class
  in isolation — `pytest tests/api/test_server.py::TestFacetRouterCapWiring
  -v` — and it passes, 6/6. It is also absent from both of this cycle's
  whole-repo failure lists (§1). The underlying default-mismatch bug
  build-log 0091 originally diagnosed and fixed in shipped code appears to
  have been re-applied to `test_server.py`'s own now-committed form by the
  separate concurrent session at some point between 0098 and this cycle —
  this entry does not trace the exact commit that did it (out of scope for
  an additive telemetry cycle) but records the observed, current state
  plainly rather than repeating the stale "known, ongoing issue" language
  0097/0098 used.

## 6. Explicitly not done

- **No frontend consumes this contract.** `rankuno-ui/` is untouched by this
  cycle — verified: `git diff 46863d2 c7ff68b --stat` lists no
  `rankuno-ui/` path under the worker-progress commit `2884d59`'s own diff.
  More than a plain gap: `WorkerJobsPanel.tsx` (built one commit earlier, in
  `123c165`, by a different session, and also untouched by this cycle)
  carries its own component docstring stating this outright —

  > "There is no progress column and there will not be one. The supervisor
  > knows whether the Screaming Frog process is alive, and nothing else: a
  > three-hour crawl reports 'running' for three hours. Elapsed time is real
  > and is shown; a percentage would be invented."

  That stance was written and committed *before* this cycle's backend made a
  real, non-invented percentage available. It is now stale as a statement of
  fact (a percentage is no longer invented — it comes from Screaming Frog
  itself, via `trace.txt`), but this entry does not resolve the tension by
  editing that component: whether to revisit `WorkerJobsPanel.tsx`'s own
  design stance, add a distinct progress surface, or leave it as-is pending a
  deliberate UI decision is left to whoever picks up the frontend follow-up,
  not assumed here. Flagged prominently so nobody mistakes the backend
  contract shipped this cycle for a feature a user can currently see.
- **`license_check.py`'s completion-line regex is not fixed here** (§4, §8) —
  out of scope for an additive telemetry cycle; a real, separate bug in a
  file this cycle otherwise does not touch.
- **The `gsc_token_manager` circuit breaker test failure is not
  investigated here** (§8) — flagged with a specific, traced observation
  rather than re-asserted as generic pre-existing noise.
- **`worker_daemon.py` and `postgres_worker_dispatch_store.py` are not split**
  (§8), though both grew past CLAUDE.md's 400-line target this cycle and
  were already over it beforehand.
- **No purge job for expired uploaded bundles** — unchanged, pre-existing gap
  from build-log 0098, not touched by this cycle.
- **No circuit breaker on the worker↔cloud progress-reporting call** — the
  same accepted condition-10 gap build-log 0098 already named for the rest of
  this channel; `report_progress` shares `WorkerCloudClient`'s existing
  posture, nothing new added or removed here.

## 7. Files changed

Per `git show --stat c7ff68b` (19 files, 1,597 insertions(+), 13 deletions(-)):

```
alembic/versions/0004_worker_job_progress_columns.py   |  52 +++
scripts/register_worker.py                             |   4 +-
src/api/worker_routes.py                                |  41 +++
src/api/worker_schemas.py                               |  37 ++-
src/core/config.py                                      |  25 ++
src/core/postgres_worker_dispatch_store.py              |  46 +++
src/core/worker_dispatch_schemas.py                     |  45 +++
src/core/worker_dispatch_store.py                       |  33 +-
src/integrations/worker_cloud_client.py                 |  37 ++-
src/modules/seo/screaming_frog_control/progress_parser.py | 358 +++++++++++
src/modules/seo/screaming_frog_control/schemas.py       |  39 +++
src/modules/seo/screaming_frog_control/tool.py          |  76 +++++
src/modules/seo/screaming_frog_control/worker_daemon.py |   4 +
tests/api/test_worker_routes.py                         | 121 +++++++
tests/core/test_postgres_worker_dispatch_store.py       |  81 ++++-
tests/integrations/test_worker_cloud_client.py          |  51 ++-
tests/modules/seo/screaming_frog_control/test_progress_parser.py | 303 +++++++
tests/modules/seo/screaming_frog_control/test_tool.py    | 129 +++++++-
tests/modules/seo/screaming_frog_control/test_worker_daemon.py | 128 +++++++-
```

Three files show as locally modified in `git status` at time of writing
(`alembic/env.py`, `src/core/postgres_config.py`, `tests/api/test_server.py`)
but are **not** part of this merge commit — verified: none of the three
appear in `git show --stat c7ff68b`'s file list above. Diffed independently
against the working tree and confirmed to be pure `ruff format`-only changes
(import reordering, line wrapping) with no semantic difference, belonging to
a separate, still-uncommitted concurrent session. Deliberately excluded from
this cycle's commit to keep it scoped to the progress-telemetry feature.

Plus, from this docs-scribe pass itself: this entry, its `docs/build-log/
README.md` index row, and additive edits to `README.md` and
`docs/ARCHITECTURE.md` (§ below).

## 8. Follow-ups

- **`license_check.py`'s completion-line regex** (`_COMPLETED_LINE =
  re.compile(r"Completed the spider of .+ crawled (?P<count>\d+) urls?$")`)
  does not strip Screaming Frog's comma thousands separator, unlike this
  cycle's own `_SPIDER_PROGRESS_LINE` regex, which does. Confirmed by direct
  inspection of the file (not just the new module's docstring claim): `\d+`
  cannot match `2,676`. This silently breaks `pages_crawled` and
  `free_tier_capped` detection on any crawl completing at or above 1,000
  pages — the free-tier-cap check (`pages_crawled == FREE_TIER_URL_CEILING`,
  500) happens to still work below that threshold, which is likely why this
  has not surfaced as a visible failure yet. Needs its own bug-fixer cycle;
  not fixed here because `license_check.py` is otherwise untouched by this
  cycle and the fix deserves its own targeted tests against the real
  comma-separated completion line.
- **The `gsc_token_manager` circuit breaker test failure looks like a real
  logic gap, not flakiness.** Read directly (§1's traceback, both runs):
  `test_circuit_breaker_recovers_after_success` opens the circuit by calling
  `record_failure` five times directly, asserts `is_open()` is `True`, then
  calls `get_or_refresh_token()` once with a mocked *successful* HTTP
  response and expects the circuit to close. `circuit_breaker.py`'s own
  `is_open()` only transitions `OPEN -> HALF_OPEN` (and returns `False`,
  permitting a probe) once `recovery_timeout_s` (30.0s) of real wall-clock
  time has actually elapsed since the last recorded failure. The test does
  not advance time or mock `time.time()`, so within the test's own runtime
  the circuit is still genuinely `OPEN` when `get_or_refresh_token()` is
  called — that method's own `is_open()` check short-circuits straight to
  "no valid stale token, raise" without ever attempting the mocked HTTP call,
  so `record_success()` is never reached and the circuit never closes. This
  reads as a design tension between two components (`CircuitBreaker`'s
  wall-clock-gated half-open transition vs. a test that expects an immediate
  reset) rather than either determinism issue — but whether the fix belongs
  in the test (advance/mock time to actually cross `recovery_timeout_s`) or
  in `get_or_refresh_token()` (an explicit one-shot probe path independent of
  wall-clock `is_open()`) is exactly the kind of judgment call this entry
  does not make. Worth a dedicated investigation cycle rather than the same
  "pre-existing, unrelated" line every build-log has used for this failure
  for roughly a month.
- **`worker_daemon.py` (412 lines) and `postgres_worker_dispatch_store.py`
  (514 lines)** are both over CLAUDE.md §9's 400-line target and grew this
  cycle (`worker_daemon.py` 408->412 lines, `postgres_worker_dispatch_store.py`
  468->514 lines, verified against each file's pre-cycle blob via `git show
  46863d2:<path> | wc -l`). A refactor split was suggested during
  implementation but not attempted — correctly out of scope for a cycle
  whose brief was additive telemetry, not restructuring.
- **`WorkerJobsPanel.tsx`'s "there will not be one" progress-column stance**
  (§6) needs a deliberate decision, not a silent edit, given it now
  contradicts the backend contract this cycle shipped.
- A UI cycle to build the progress bar itself against the contract this entry
  documents (`GET /workers/jobs` fields, `progress_pct` not guaranteed
  monotonic) once that decision is made.
