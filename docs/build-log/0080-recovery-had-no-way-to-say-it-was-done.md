# Cycle 0080: Recovery had no way to say it was done

- **Date**: 2026-09-09
- **Scope**: Bug fix in `src/api/server.py`: startup's orphan recovery ran on a fire-and-forget daemon thread with no way for anything to observe its completion, so three tests in `tests/api/test_server.py` raced it and failed nondeterministically. Added `ApiState.recovery_done` (`threading.Event`), set in a `finally` block by the background recovery function; the three tests now wait on it instead of racing.
- **Commit**: uncommitted at time of writing.
- **Quality gate**: **GREEN** — `2020 passed, 1 skipped, 1 warning` Python / `232 passed` UI / `Total coverage: 93.92%`. `ALL GATES PASSED.` This is the first green gate in the chain started by build-log 0078.

**Origin.** [0078 §1.2](0078-the-fields-that-never-left-the-call-site.md) first flagged three nondeterministic tests in `tests/api/test_server.py` — `TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup`, `TestCancel::test_cancelling_frees_the_slot`, `TestCancel::test_the_reason_says_the_thread_may_survive` — attributing them at the time to another session's uncommitted edits to `lifespan` ([0078 §8.1](0078-the-fields-that-never-left-the-call-site.md)). [0079 §1.2](0079-sixteen-measured-ninety-four-not.md) reran the file five times in isolation and found the nondeterminism persisted (a different member of the trio failed each time it failed), and [0079 §1.3 / §5.7](0079-sixteen-measured-ninety-four-not.md) noted that those `server.py` / `test_server.py` edits had since landed on `HEAD` via `b3d7105`, so the failure was no longer "another session's" to fix — it was this repository's. [0079 §8.6](0079-sixteen-measured-ninety-four-not.md) handed the diagnosis (daemon-thread orphan recovery racing the tests) to the owner of `server.py`. This cycle is that handoff, closed.

---

## 1. Gate results

### 1.1 Pre-fix reproduction (bug-fixer's run, against `b3d7105` / `1be2309`)

Running the three named tests repeatedly against the pre-fix code failed nondeterministically — a different one of the three failed in 3 of 8 consecutive runs:

```
=== run 3 ===  FAILED tests/api/test_server.py::TestCancel::test_cancelling_frees_the_slot
=== run 4 ===  FAILED tests/api/test_server.py::TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup
=== run 7 ===  FAILED tests/api/test_server.py::TestCancel::test_the_reason_says_the_thread_may_survive
```

(runs 1, 2, 5, 6, 8 passed). This matches the pattern in [0079 §1.2](0079-sixteen-measured-ninety-four-not.md): the failing member of the trio varies between runs, which is the signature of a race rather than a deterministic bug in any one test.

### 1.2 Root cause

`src/api/server.py`'s `lifespan` starts orphan recovery on a fire-and-forget daemon thread and returns via `yield` immediately, with no way to observe when the thread finishes:

```python
def _recover_in_bg() -> None:
    try:
        orphans = resolved_store.recover_orphans()
        if orphans:
            _logger.warning("recovered_orphaned_jobs", extra={"count": len(orphans)})
    except Exception as e:
        _logger.error("orphan_recovery_failed", extra={"error": str(e)})

threading.Thread(target=_recover_in_bg, daemon=True).start()
yield
```

`TestClient(app)` entering the context runs startup only up to that `yield`; it does not wait for the thread. All three tests raced it — either reading store state right after startup, or calling `store.mark_running()` right after entering the client context, which can be seen and failed out from under the test by the still-in-flight `recover_orphans()` scan as a false orphan.

### 1.3 Post-fix repeated-run evidence (bug-fixer's run)

Verbose run of the three named tests: 3 passed. 20 consecutive repeats of the same three tests: all 20 exit 0. 8 consecutive repeats of the whole `tests/api/test_server.py` file (117 tests): all exit 0, no `FAILED` lines. `pytest-randomly` is not installed in this environment; repeated full/targeted runs were used in its place to surface ordering-sensitive failures.

### 1.4 Independent verification (docs-scribe, this cycle)

`tests/api/test_server.py` alone, verbatim tail:

```
........................................................................ [ 61%]
.............................................                            [100%]
================== 117 passed, 1 warning in 71.44s (0:01:11) ==================
```

(1 pre-existing, unrelated `StarletteDeprecationWarning` about `httpx`/`starlette.testclient`.)

Full gate (`verify.ps1`, no `-Fix`), verbatim:

```
=== Format ===
293 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 68 source files
PASSED: Type check

=== Tests ===
...
Required test coverage of 85.0% reached. Total coverage: 93.92%
2020 passed, 1 skipped, 1 warning in 125.37s (0:02:05)
PASSED: Tests

=== UI Component Tests ===
...
 Test Files  21 passed (21)
      Tests  232 passed (232)
   Start at  12:06:38
   Duration  9.70s (transform 3.21s, setup 9.11s, collect 35.76s, tests 21.15s, environment 31.97s, prepare 5.43s)

PASSED: UI Component Tests

ALL GATES PASSED.
Next: SDLC Step 8 - README & architecture drift audit.
```

`2020 passed` here versus `2012 passed` in [0079 §1](0079-sixteen-measured-ninety-four-not.md) is not this cycle's tests alone — the working tree also carries the GSC account-profile / deliverables-boundary work from `b3d7105` and an uncommitted `max_concurrent_crawls` settings change (§6) that neither the bug-fixer nor this entry authored; the three test edits in this cycle add no new test functions (they add assertions to existing tests), so the count moved for reasons outside this cycle's scope.

`drift_check.py`, verbatim:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 151 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

---

## 2. What landed

### 2.1 `ApiState.recovery_done` — `src/api/server.py:724`

A `threading.Event`, created unset in `ApiState.__init__` alongside the existing `_tasks` set. Costs nothing while unused; gives anything that must not race startup recovery (a test, or in principle any other caller) a way to know recovery has finished rather than guessing from timing.

### 2.2 `_recover_in_bg` signals on exit, success or failure — `src/api/server.py:870-882`

```python
def _recover_in_bg() -> None:
    try:
        orphans = resolved_store.recover_orphans()
        if orphans:
            _logger.warning("recovered_orphaned_jobs", extra={"count": len(orphans)})
    except Exception as e:
        _logger.error("orphan_recovery_failed", extra={"error": str(e)})
    finally:
        state.recovery_done.set()

threading.Thread(target=_recover_in_bg, daemon=True).start()
yield
```

The `finally` block sets the event whether recovery succeeds or raises: "recovery is done" and "recovery succeeded" are different claims, and a waiter only needs the former to know it is safe to touch job state. `threading.Thread(...).start()` and `yield` are unchanged — startup still does not block on a large job store.

### 2.3 The three tests now wait instead of racing — `tests/api/test_server.py:427, 930, 954`

`TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup` (line 427), `TestCancel::test_cancelling_frees_the_slot` (line 930), `TestCancel::test_the_reason_says_the_thread_may_survive` (line 954) each now do:

```python
assert app.state.api.recovery_done.wait(timeout=5), "recovery did not finish in time"
```

before touching job state (reading `store.get(job_id).status`, or calling `store.mark_running()`). This also pins the fix as a regression test without a separate new test file: the assertion references an attribute (`recovery_done`) that does not exist on the pre-fix `ApiState`, so these three tests cannot pass against the pre-fix code.

---

## 3. Design decisions

**`threading.Event`, not a synchronous/blocking startup.** Alternatives considered: (a) join the recovery thread before `yield` — rejected, because it reintroduces the exact cost the fire-and-forget design exists to avoid (startup blocking on `recover_orphans()` over a large job store, CLAUDE.md's memory/scale posture in ADR 0001); (b) run recovery synchronously under test only (e.g. a `sync_recovery` flag) — rejected, because it would test a different code path from production and the race would remain live in production, only hidden in the suite; (c) `threading.Event`, set in a `finally` — chosen: zero cost when nobody waits on it, does not change the non-blocking startup contract, does not change the cancel endpoint's contract (still `200`/`404`/`409` on the same conditions), and gives callers — test or otherwise — an explicit, race-free signal instead of an inferred one.

---

## 4. Bugs found and fixed

1. **The orphan-recovery race itself** (§1.2, §2). `lifespan` started `recover_orphans()` on a daemon thread and returned via `yield` with no observability into the thread's completion. `TestClient` entering the app context runs startup only to the `yield`, not through the thread, so any test that touched job state immediately after entering the client context could be seen and mutated by the still-running scan. This is the root cause underlying all three failures named in [0078 §1.2](0078-the-fields-that-never-left-the-call-site.md) and reproduced again in [0079 §1.2](0079-sixteen-measured-ninety-four-not.md). Fixed by making completion observable (§2) rather than by removing the concurrency.

No bugs were found in the tests' own logic or in the specification of the cancel/startup-recovery contracts — the three tests were asserting the right thing, they were only asserting it before the system under test had reached a stable state.

---

## 5. Corrections

1. **The ruff-format-on-markdown-fence defect in [0079](0079-sixteen-measured-ninety-four-not.md), found and fixed in this cycle.** Not a fault of 0079's authoring — this is a formatter behaviour discovered while gating this cycle's diff (`verify.ps1` gates the whole tree, so a stray markdown fence anywhere fails the same `Format` step as a code change). The bug-fixer's own `verify.ps1` run failed on `Format` alone, isolated to `docs/build-log/0079-sixteen-measured-ninety-four-not.md` at two `python` fences (then lines 237 and 247) illustrating real multi-line source with the surrounding lines deliberately elided — a kwarg inside a multi-line constructor call (`cascading_pipeline.py:316`) and a tuple element inside a multi-line return (`signal_parsers.py:713`):

   ```
   canonical_url=evidence.canonical_url or evidence.url,
   f"Answered {status_code}. A page that errors is not indexed.",
   ```

   Running `ruff format docs/build-log/0079-sixteen-measured-ninety-four-not.md` to clear the failure rewrote both fences into single-element tuple literals — syntactically valid Python, and wrong:

   ```
   canonical_url = (evidence.canonical_url or evidence.url,)
   (f"Answered {status_code}. A page that errors is not indexed.",)
   ```

   Ruff's markdown-embedded-code formatter formats each fence in isolation; without the surrounding multi-line call or return it has, it read the trailing comma as a one-element tuple constructor rather than as a continuation into the next (elided) argument or list element. Diffing against the real source (`cascading_pipeline.py:316`, `signal_parsers.py:713`, both quoted in full above and in §1.2) showed the "fix" had silently changed what the illustrative snippet meant. `git checkout -- docs/build-log/0079-sixteen-measured-ninety-four-not.md` reverted it; both fences were then hand-edited to drop only the trailing comma, which reads as an accurate single-line snippet and independently passes `ruff format --check`:

   ```diff
   -canonical_url=evidence.canonical_url or evidence.url,
   +canonical_url = evidence.canonical_url or evidence.url
   -f"Answered {status_code}. A page that errors is not indexed.",
   +f"Answered {status_code}. A page that errors is not indexed."
   ```

   Named as a defect class, not a one-off: `ruff format`'s markdown fence formatter can silently corrupt the meaning of an intentionally-partial illustrative code excerpt (a kwarg or list/tuple element quoted without its enclosing call), because it formats the fence as a standalone statement. `-Fix` / auto-format should not be trusted blindly on build-log prose fences that quote a fragment of real source — when a fence is reformatted, diff it against the cited source line before accepting the change.

---

## 6. Explicitly not done

- **Recovery was not made synchronous or blocking.** Startup still returns before `recover_orphans()` finishes; large job stores still do not delay the API becoming ready. Only completion became observable (§3).
- **The cancel endpoint's contract is unchanged.** No new status code, no new response field; `200` / `404` / `409` fire on the same conditions as before this cycle.
- **`pytest-randomly` was not installed.** It is not a project dependency; repeated full-file and targeted reruns (§1.1, §1.3) were used instead to surface the ordering-sensitive race. Installing it (or an equivalent) to catch this class of bug automatically in CI is not done here.
- **The unrelated `max_concurrent_crawls` / `Settings` change already present in the working tree was not authored, reviewed, or described by this cycle.** It touches `src/api/server.py` (`DEFAULT_MAX_CONCURRENT_JOBS` 3 → 5, a `max_concurrent_jobs: int | None` param on `create_app()` that falls back to `Settings.max_concurrent_crawls`), `src/core/config.py` (`Settings.max_concurrent_crawls`, default 5, range 1–10), `tests/api/test_server.py` (`TestConcurrencyCapFromSettings`), `tests/core/test_config.py` (three new tests), `.env.example` (`MAX_CONCURRENT_CRAWLS`), `README.md`, and `docs/ARCHITECTURE.md` — the last two **already document it** (uncommitted): README's job-store section states the "5 crawls at once by default ... `MAX_CONCURRENT_CRAWLS` (1–10)" and ARCHITECTURE's tree comment for `api/server.py` names the same cap. None of this is mentioned in the bug-fixer's report and none of it is part of the orphan-recovery race fix. It is called out here only so a future reader diffing these files does not attribute it to this entry. Per this cycle's brief, README.md/ARCHITECTURE.md are edited only if they describe the gate as red or reference the flaky tests — neither does — so this entry makes no further changes to either file; the concurrency-cap feature itself is untested by *this* entry's gate run only in the sense that it lacks a build-log entry of its own, which its owner still owes it.
- **`api.err` / `api.out`** at the repository root, flagged untracked and not in `.gitignore` since [0079 §6](0079-sixteen-measured-ninety-four-not.md), are still present and still not addressed by this cycle — out of scope for a test-race fix.

---

## 7. Files changed

```
src/api/server.py           ApiState.recovery_done (threading.Event, line 724); _recover_in_bg
                             sets it in a finally block (lines 870-882). Also carries an unrelated,
                             already-present uncommitted max_concurrent_crawls/Settings change (§6)
                             that this cycle did not make.
tests/api/test_server.py    Three existing tests (lines 427, 930, 954) now wait on recovery_done
                             before touching job state, instead of racing the background thread.
                             Also carries the unrelated TestConcurrencyCapFromSettings class (§6)
                             that this cycle did not add.
docs/build-log/0079-sixteen-measured-ninety-four-not.md   Two illustrative code fences corrected
                             after a ruff-format auto-fix silently changed their meaning (§5).
docs/build-log/0080-recovery-had-no-way-to-say-it-was-done.md   this entry
docs/build-log/README.md    +1 row index
```

Also present in the working tree, all part of the unrelated `max_concurrent_crawls` change (§6), none of it made by this cycle: `src/core/config.py`, `tests/core/test_config.py`, `.env.example`, `README.md`, `docs/ARCHITECTURE.md`.

Not touched: `src/core/state_store.py`, `src/modules/**` (this is an API-layer fix only), `CLAUDE.md`.

---

## 8. Follow-ups

1. **Process handoff, docs-scribe / build-log writing.** Do not blindly trust `ruff format` / `-Fix` on markdown prose fences that contain intentionally-partial snippets of real source (a kwarg, a tuple element, a mid-call line quoted without its enclosing statement). Ruff formats each fence in isolation and can reinterpret an elided trailing comma as a complete, different, and wrong statement (§5). When `verify.ps1 -Fix` reports a markdown file's `Format` step changed, diff the fence against the file and line it cites before accepting the change.
2. **0078's and 0079's handoffs on this race are now closed.** [0078 §8.1](0078-the-fields-that-never-left-the-call-site.md) ("the tests need either a deterministic recovery ... or a fixture that waits for it") and [0079 §8.6](0079-sixteen-measured-ninety-four-not.md) ("Owner of `src/api/server.py` — 0078 §8.1 stands") are both satisfied by §2 of this entry. No further action needed on this specific race.
3. **The unrelated `max_concurrent_crawls` change (§6) still needs its own build-log entry** from whoever authored it — it is a real, tested feature already reflected in `README.md` and `docs/ARCHITECTURE.md` (both uncommitted) and in `tests/core/test_config.py`, sitting in the same files this cycle touched, but with no cycle entry recording the decision or its gate run.
