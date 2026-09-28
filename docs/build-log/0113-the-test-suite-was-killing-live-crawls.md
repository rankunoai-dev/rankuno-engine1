# Cycle 0113: The test suite was killing live crawls, and the kill reported SUCCEEDED

- **Date**: 2026-09-28
- **Scope**: Startup orphan reconciliation stopped reaping processes a live supervisor is still watching; a bundle with no export files is now a failed job instead of a 22-byte download; the test suite no longer acts on this workstation's real PID ledger or audit log.
- **Commit**: uncommitted at time of writing (the working tree carries this cycle and cycle 0112 together)
- **Quality gate**: **ALL GATES PASSED** — 3189 passed, 2 skipped, 88.42% against an 85% floor; UI 39 files / 455 tests

## 1. Gate results

```
Format:      500 files already formatted                        — PASSED
Lint:        All checks passed!                                 — PASSED
Type check:  Success: no issues found in 144 source files       — PASSED
Tests:       3189 passed, 2 skipped, coverage 88.42% (floor 85%) — PASSED
UI:          39 files, 455 tests                                — PASSED
ALL GATES PASSED, exit 0.
```

Three of the five stages were independently re-executed while writing this entry
and reproduced byte-for-byte:

```
$ .venv/Scripts/python.exe -m ruff format --check .
500 files already formatted

$ .venv/Scripts/python.exe -m ruff check .
All checks passed!

$ .venv/Scripts/python.exe -m mypy --strict src
Success: no issues found in 144 source files
```

`pytest` and the UI runner were **not** re-executed here — a second `pytest`
overwrites the in-flight run's `.coverage`, which is how build-log 0106 lost its
figures. What was verified statically instead:

| Measurement | Value | How |
| :--- | :--- | :--- |
| Baseline (`bfb8518`, build-log 0112) | 3178 py / 88.40% / 455 ui | 0112 §1 |
| This cycle | 3189 py / 88.42% / 455 ui | reported |
| Net Python tests | **+11** | reported |
| New `def test_` in the diff | **+11** | `git diff -U0 -- tests/` \| `grep -cE '^\+\s*(async )?def test_'` |
| UI files changed | **0** | `git status` lists nothing under `rankuno-ui/` |

The +11 matches the diff exactly, and the unchanged UI total is consistent with a
cycle that touched no UI file. Coverage moved +0.02pp, which is what 11 tests over
an added ~90 source lines should do.

## 2. What happened

A user started two Screaming Frog crawls on their own workstation. Both ran to
near-completion — **1:05:47** and **1:47:39** — both reported **SUCCEEDED**, and
both produced a **22-byte** download. 22 bytes is a ZIP containing zero entries:
an End-of-Central-Directory record and nothing else. One of the two was killed at
**99.7% complete**.

The repo's own `logs/audit.jsonl` holds the whole sequence, with a single
`trace_id` tying the kill to the reported success:

```json
{"ts":"2026-09-25T18:29:11.250039+00:00","message":"orphan_killed_via_job_object","job_id":"292dade041ff457ca88f5027ecc531a0","pid":12056,"path":"job_object"}
{"ts":"2026-09-25T18:29:11.250039+00:00","message":"sf_orphans_reconciled","count":1}
{"ts":"2026-09-25T18:29:11.729219+00:00","message":"process_terminated","trace_id":"80a5f37922a648d6","job_id":"292dade041ff457ca88f5027ecc531a0","pid":12056}
{"ts":"2026-09-25T18:29:11.757189+00:00","message":"tool_succeeded","trace_id":"80a5f37922a648d6","tool":"seo.screaming_frog_control","duration_ms":6458366.33}
{"ts":"2026-09-25T18:29:12.600649+00:00","message":"worker_bundle_uploaded","job_id":"292dade041ff457ca88f5027ecc531a0","files":0}
```

`duration_ms=6458366.33` is 1:47:38. The first incident is the same shape, a day
earlier: `pid=40892`, `trace_id=b394119856944a67`, `duration_ms=3946288.79`
(1:05:46), `worker_bundle_uploaded files=0`.

The correlation is exact and was re-checked while writing this entry:

| Fact | Value | How |
| :--- | :--- | :--- |
| `sf_orphans_reconciled` occurrences in the whole 510 MB log | **6** | `grep -c` |
| Distinct timestamps they fall on | **2** (`2026-09-24T10:22:40–41`, `2026-09-25T18:29:11`) | `grep -h` |
| Empty-bundle jobs ever recorded | the same **2** | `worker_bundle_uploaded … "files": 0` |

Three `sf_orphans_reconciled` lines per incident, all within ~800 ms, because
three app instances were built in that window and each one reconciled. Screaming
Frog's `trace.txt` truncates less than a second before each kill with no shutdown
hook, and both output directories are still on disk, **empty** — Screaming Frog
writes nothing to `--output-folder` until a crawl completes, so a kill at 99.7%
leaves an empty folder and 1 hour 47 minutes of crawling with nothing to show.

### Three composing defects

Each was individually survivable. Only the combination made an hour and 47 minutes
of work disappear silently.

1. **`worker_routes.upload_bundle` never looked inside the bundle.** It called
   `mark_uploaded(job.id, bundle_size_bytes=...)` and left `partial` at its
   default `False`, which maps to `SUCCEEDED`. `WorkerJobStatus.PARTIAL` already
   existed, and `mark_uploaded` already took `partial: bool` — its only caller
   never passed it. The status was therefore structurally unreachable, which is
   what its own docstring claimed (see §5).
2. **`reconcile_orphans` gated solely on child PID + start time.** That answers
   "is this process alive?", not "is this process abandoned?". A process alive
   because a worker is supervising it *right now* was indistinguishable from one
   nobody is watching.
3. **`server.py`'s lifespan read `get_settings().process_supervisor_ledger_path`
   directly.** `reconcile_orphans` runs on every API-server startup, and every
   `TestClient(create_app(...))` construction runs `lifespan` — so running
   `pytest` on that workstation reconciled the real
   `REPO_ROOT/.process_ledger.json` and killed whatever live crawl was enrolled
   in it.

## 3. What landed

### 3.1 A bundle's contents decide the job's status (`api/worker_routes.py`)

| Bundle | Status | Stored? |
| :--- | :--- | :--- |
| Zero members | `FAILED` | **No** |
| Members, no `internal_all.csv` | `PARTIAL` | Yes |
| Members including the spine | `SUCCEEDED` | Yes |

The empty bundle is deliberately **not stored**. Offering a 22-byte download was
the precise failure being removed, and keeping the bytes would preserve it.

The spine rule is not a judgement call: `load_screaming_frog_bundle` requires
`internal_all.csv` non-optionally (`screaming_frog_adapter.py:79`, `SPINE_FILE`),
so a bundle without it can never become a deliverable however many other files it
carries. That data is still worth keeping — it is just not a finished job.
`SPINE_FILENAME` was promoted out of `ALLOWED_BUNDLE_FILENAMES`'s set
comprehension in `upload_manifest.py` and exported, so the route can ask the
question without re-deriving the transform.

**All three outcomes return HTTP 200, and that is the non-obvious part.**
`WorkerCloudClient.upload_bundle` calls `raise_for_status()`, so a 4xx would
surface on the daemon as an exception on a job that is already terminal and cannot
be improved by retrying. The upload *report* was accepted; the *job* failed. Those
are two different claims, and only the first one is what an HTTP status code on
this route is answering. A worker that reads `400` here retries a crawl that has
nothing left to give.

### 3.2 Diagnostic power preserved rather than flattened

The easy version of this fix collapses every empty outcome into one message. Three
distinct causes were kept distinguishable instead:

| Signature | Meaning | Who fixes it |
| :--- | :--- | :--- |
| `worker_bundle_empty files=0, skipped=0` | The crawl never reached its export phase — killed, stopped, or crashed | Operator re-runs |
| `worker_bundle_empty files=0, skipped=N` | Files were written; none are allow-listed | Engineer fixes `ALLOWED_BUNDLE_FILENAMES` |
| `worker_bundle_uploaded members=95, spine_present=false` | Real export, no spine | Engineer |

The first two are emitted by the daemon (`worker_daemon._upload_bundle` plus
`_empty_bundle_error`), because the daemon is the only place both counts exist —
once an empty archive reaches the cloud, the cloud cannot tell them apart. The
daemon also now stops uploading an empty archive at all and calls `report_failure`
directly. The third comes from the route, which gained `spine_present` and
`status` on its existing success log line.

This is a partial discharge of ADR 0018's follow-up ("surface a non-empty
`skipped` set to the cloud API"): the count and its interpretation now reach the
cloud as a failure reason, though the filenames themselves still exist only in the
desktop worker's log.

### 3.3 The ledger records who is supervising (`core/_process_ledger.py`, `core/process_supervisor.py`, `core/_process_orphans.py`)

`LedgerEntry` gains `supervisor_pid` and `supervisor_start_time`, written by
`launch_supervised` from `os.getpid()` and `GetProcessTimes(GetCurrentProcess())`
— the same PID + start-time identity trick the child already used, applied one
level up. The pseudo-handle from `GetCurrentProcess` needs no access rights and
cannot fail, so this adds no new failure mode to a launch path that is already
mid-`CREATE_SUSPENDED`. Both `upsert_entry` calls carry it, so the enrollment-race
window closed in cycle 0095 stays closed.

`reconcile_orphans` now checks supervisor liveness **first**. On a match it logs
`orphan_skipped_supervisor_alive` and **keeps the entry in the ledger** rather
than dropping it, so that if that supervisor later dies without cleaning up, the
next reconciliation still finds the child. Supervisor-side PID reuse is guarded by
the same `_START_TIME_TOLERANCE_S` already applied to the child: a recycled
supervisor PID now held by an unrelated process fails the start-time match and the
entry is correctly treated as unowned.

**Legacy entries carrying no supervisor marker are still reaped, deliberately.**
`_supervisor_is_alive` returns `False` when either field is `None`. The reasoning
matters more than the code: treating an absent marker as "spare it" grants
immortality to every entry written before this upgrade, and an immortal entry is a
Screaming Frog process holding a licence seat and gigabytes of JVM heap that
nothing will ever kill. Unknown ownership has to fail toward reaping, not away
from it. It also keeps pre-upgrade behaviour exactly as it was, rather than
changing it in a direction nobody can observe.

### 3.4 The test suite stops acting on this workstation (`api/server.py`, `tests/conftest.py`)

`create_app` gains `process_ledger_path: Path | None = None`, defaulting to
`Settings.process_supervisor_ledger_path`. The parameter exists because
reconciliation *kills processes*: an app built for a test must be able to name a
throwaway ledger.

`tests/conftest.py` redirects `AUDIT_LOG_PATH` and
`PROCESS_SUPERVISOR_LEDGER_PATH` into a `tempfile.mkdtemp()` directory removed by
`atexit`.

**That block sits above the imports, not in a fixture, and it has to.** This is
the part someone will try to tidy up. `get_logger` calls `setup_logging` on first
use, and first use is at *import* time — so by the time the earliest fixture could
run, a `FileHandler` on the real audit log is already open and
`src.core.celery_config` has already written a line through it. Measured: one
`celery_initialized` line per run still reached the real `logs/audit.jsonl` with
the fixture approach, and zero with the import-time block. The five `src` imports
below it carry `# noqa: E402` with the reason stated inline.

Reconciliation itself stays **switched on** under test. It is the routine that
just misfired, and disabling it under test would hide the next regression in
exactly the code that most needs watching. Only its target moved, and
`test_an_app_built_with_no_explicit_ledger_never_touches_the_repo_ledger` asserts
both halves of that: that reconciliation still ran, and that it did not run
against `REPO_ROOT / ".process_ledger.json"`.

### 3.5 An unplanned addition, flagged rather than slipped in

`WorkerJobsPanel.tsx:254` renders `job.error ?? "No reason was recorded."` for
`failed` **and** `partial` alike. A `PARTIAL` job carrying no error would
therefore have replaced a *wrong* status with a *mute* one — an operator staring
at "No reason was recorded." beside a crawl that took an hour. `mark_uploaded`
therefore gained `reason: str | None = None` on both the `WorkerDispatchStore`
protocol and `PostgresWorkerDispatchStore`, written to the existing `error` column
that `mark_failed` already uses and the dashboard already reads. No UI change was
needed; the panel already handled both statuses. The addition was outside the
brief and is recorded here rather than absorbed silently.

## 4. Bugs found and fixed

Two of these were **tests that were wrong while the code was right**.

### 4.1 A test that had only ever passed because of the bug

`tests/core/test_process_orphans.py::TestReconcileOrphansRealWindows::test_kills_a_real_orphan_via_the_named_job_object_path`
began failing the moment the supervisor check landed:

```
assert [] == [26860]
```

Its docstring claimed it reconciled "as if this were a fresh startup". It does
not. It launches a real Windows process via `launch_supervised` **from the pytest
process** and then reconciles **in that same process** — so once the supervisor is
recorded, the supervisor is demonstrably alive and the "as if" no longer holds.

That failure was the fix working. It is the production bug reproduced on a real
process, in reverse: the test had only ever passed because the reaper could not
tell a supervised process from an abandoned one. It now overwrites the entry's
supervisor with a PID that cannot exist (`999_999_999`) before reconciling, so the
simulated crashed server is honest about being a simulation.

### 4.2 A fake database that modelled no database

`tests/core/test_postgres_worker_dispatch_store.py`'s `_FakeCursor` applied a
`SET` clause like this:

```python
if "bundle_size_bytes = %s" in q:
    row["bundle_size_bytes"] = extra[0]
elif "error = %s" in q:
    row["error"] = extra[0]
```

That models Postgres as applying only the **first** assignment in a `SET` clause.
No database does that. The real `PostgresWorkerDispatchStore._transition` was
correct throughout; the fake silently discarded the second column. It went
unnoticed because no caller had ever set both at once — which is exactly what
§3.5's `mark_uploaded(..., partial=True, reason=...)` does. The fake now collects
every assignable column present in the query, orders them by their position in the
query string (`key=q.index`), and zips them against the parameters with
`strict=True`, so a future column mismatch raises instead of being dropped.

### 4.3 The production bugs

- `upload_bundle` accepted a zero-member archive as a successful crawl (§3.1).
- `reconcile_orphans` could not distinguish "alive" from "abandoned" (§3.3).
- Building an app under test reconciled the developer's real PID ledger (§3.4).
- The daemon uploaded an empty archive rather than reporting the failure it could
  already see (§3.2).

## 5. Corrections

**`WorkerJobStatus.PARTIAL`'s docstring claimed the status was unreachable.** It
said the status was "present for parity with `ScreamingFrogJobOutput`'s own
licence-degrade handling, though today's `tool.execute()` raises rather than
returning a degraded output, so this status is reachable only if a future worker
behaviour changes that". That was true only because its one caller never passed
`partial`. The docstring was corrected in this cycle, not deleted: `PARTIAL` now
has exactly one defined trigger (export files without `internal_all.csv`), and the
licence-parity sentence is kept as the second, still-unreached meaning.

No earlier build-log entry is corrected here. Build-log 0095, which shipped
`reconcile_orphans`, described PID + start-time matching accurately; what it did
not say — because it was not known — is that the match is a *liveness* test and
not an *orphan* test. That is recorded above as new information, not as a
correction to 0095.

## 6. Explicitly not done

### 6.1 Fix 4: the worker still never examines the exit status of the crawl

`ScreamingFrogControlTool.execute()` does not inspect process exit status, and
`SupervisedProcess` exposes none. A killed crawl and a clean one remain the same
code path on the worker side, which is why `tool_succeeded` was logged 28 ms after
`process_terminated` in §2. Fix 1 catches this at the cloud, not at source, and
does not cover the direct non-worker `execute()` path at all.

Two options were costed and neither was taken this cycle:

| Option | Size | Catches | Cost |
| :--- | :--- | :--- | :--- |
| Verify `internal_all.csv` exists in `bundle_dir` before returning success | ~5 lines | The failure at source, **including** the direct `execute()` path Fix 1 cannot see | Infers a kill from an absent file rather than observing it |
| Capture `GetExitCodeProcess` before `terminate()` closes both handles | ~40 lines | The kill itself | New Win32 surface; see the trap below |

The trap in the second option is worth recording before someone tries it:
`TerminateJobObject(handle, 1)` stamps exit code **1** on every process in the
job, so after our *own* termination the exit code cannot distinguish our kill from
a Screaming Frog CLI that genuinely exited 1. The load-bearing signal is
`is_running()` sampled at the **top** of the `finally` block, before anything this
engine does can change it — not the exit code.

### 6.2 `reconcile_orphans` has a cross-process read-modify-write race

It reads the whole ledger file, then writes the surviving set.
`_process_ledger._lock` is a `threading.Lock` and is documented as intra-process
only. If the worker daemon enrols a child in the window between the read and the
write, that entry is erased and the child becomes untracked — the opposite failure
to this cycle's, and equally silent. Pre-existing, not introduced here. This cycle
does make it marginally more consequential: `surviving` is now non-empty far more
often, so the write-back happens in cases where it previously did not.

### 6.3 `logs/audit.jsonl` is 510 MB with no rotation

`setup_logging` attaches a plain `FileHandler`, never a `RotatingFileHandler`.
This is true in production, not only under test. The test suite no longer feeds it
(§3.4), which removes the largest contributor but not the growth. The file was
**deliberately not deleted**: it is the evidence for this cycle, and every figure
in §2 is re-derivable from it.

### 6.4 Not changed

- `CLAUDE.md` was not edited. Its §8 register does not currently misstate anything
  this cycle touched, and the file is outside a scribe's write scope — the one
  line worth adding is named in §8 below, for the operator to apply.
- No UI file was changed. `WorkerJobsPanel.tsx` already renders both `failed` and
  `partial`; §3.5 exists so that it has something to render.
- Nothing was committed or pushed.

## 7. Files changed

All uncommitted at time of writing, alongside cycle 0112's own uncommitted work.

| File | Δ | What |
| :--- | :--- | :--- |
| `src/api/worker_routes.py` | +72/−4 | Zero members → `FAILED`, not stored; no spine → `PARTIAL`; `spine_present` on the success log |
| `src/core/_process_orphans.py` | +54/−2 | `_supervisor_is_alive`, checked first; `orphan_skipped_supervisor_alive`; entry retained |
| `src/core/process_supervisor.py` | +40/−8 | `launch_supervised` records supervisor PID + start time on both `upsert_entry` calls |
| `src/core/_process_ledger.py` | +31/−4 | `LedgerEntry.supervisor_pid` / `supervisor_start_time`, both optional |
| `src/core/postgres_worker_dispatch_store.py` | +26/−4 | `mark_uploaded(..., reason=)` → the `error` column |
| `src/core/worker_dispatch_store.py` | +20/−4 | The same on the protocol |
| `src/modules/seo/screaming_frog_control/worker_daemon.py` | +36/−0 | Refuses to upload an empty archive; `_empty_bundle_error` names which of two causes |
| `src/modules/seo/screaming_frog_control/upload_manifest.py` | +16/−4 | `SPINE_FILENAME` promoted and exported |
| `src/api/server.py` | +15/−2 | `create_app(..., process_ledger_path=None)` |
| `src/core/worker_dispatch_schemas.py` | +13/−5 | `PARTIAL` docstring corrected (§5) |
| `tests/core/test_process_orphans.py` | +127/−1 | 4 new tests; §4.1's simulation made honest |
| `tests/api/test_worker_routes.py` | +88/−8 | Zero-member `FAILED`, spine-less `PARTIAL` |
| `tests/api/test_server.py` | +54/−1 | Injected ledger honoured; the default is never the repo ledger |
| `tests/conftest.py` | +46/−9 | Import-time redirect of both durable paths |
| `tests/modules/seo/screaming_frog_control/test_worker_daemon.py` | +42/−0 | Empty archive refused; both causes named |
| `tests/core/test_postgres_worker_dispatch_store.py` | +30/−4 | §4.2's fake cursor; `PARTIAL` + reason |
| `docs/adr/0019-an-export-bundle-decides-its-own-job-status.md` | new | The status contract (§8) |
| `docs/ARCHITECTURE.md`, `README.md`, `docs/build-log/README.md` | — | Step 8 |

The 11 new tests:

```
tests/api/test_server.py
  test_the_lifespan_reconciles_the_injected_ledger_path
  test_an_app_built_with_no_explicit_ledger_never_touches_the_repo_ledger
tests/api/test_worker_routes.py
  test_upload_of_a_zero_member_bundle_is_recorded_as_failed
  test_upload_missing_the_spine_file_is_recorded_as_partial
tests/core/test_postgres_worker_dispatch_store.py
  test_mark_uploaded_can_transition_to_partial_with_a_reason
tests/core/test_process_orphans.py
  test_an_entry_whose_supervisor_is_still_alive_is_never_killed
  test_an_entry_whose_supervisor_is_dead_is_still_killed
  test_a_supervisor_pid_now_held_by_another_process_is_treated_as_dead
  test_a_legacy_entry_with_no_supervisor_marker_is_still_reaped
tests/modules/seo/screaming_frog_control/test_worker_daemon.py
  test_upload_bundle_refuses_to_upload_an_empty_archive
  test_an_empty_archive_names_which_of_the_two_causes_it_was
```

## 8. Follow-ups

1. **Fix 4** (§6.1). The 5-line `bundle_dir` check is the one to take first: it
   covers the direct `execute()` path, which nothing else does.
2. **The ledger write-back race** (§6.2). A file lock, or a ledger that is
   append-only with tombstones.
3. **Log rotation** (§6.3). `RotatingFileHandler` in `setup_logging`. 510 MB is
   not a test artefact.
4. **`CLAUDE.md` §8**, for the operator to apply: the gap register should record
   that a killed crawl is still indistinguishable from a clean one on the *worker*
   side (§6.1), now that the cloud side can tell them apart. The scribe did not
   edit that file.
5. **[ADR 0019](../adr/0019-an-export-bundle-decides-its-own-job-status.md)**
   records the status contract this cycle introduced. It was written because the
   rule binds two independently deployed components — the desktop daemon decides
   what to upload, the cloud decides what the upload means — and because it makes
   a previously unreachable enum member reachable, which is the kind of change a
   future reader will otherwise reverse by accident.
