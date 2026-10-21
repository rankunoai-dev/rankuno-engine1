# 0166 — Every job write is gated by its deletion password (ADR 0042)

- **Date**: 2026-10-21
- **Branch**: `feat/job-delete-password`, rebased onto `main` at `75dbab9`
- **Decision record**: [ADR 0042](../adr/0042-job-writes-are-gated-by-the-deletion-password.md)
  (renumbered from the draft 0040, which collided with the user-sessions ADR on `main`)

---

## 1. Gate results

Full gate, `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`, run in the worktree
after the last code change. **Result: RED, exit 1, one test, inherited from `main` (§1.1).**
Everything else in the gate passes. Excerpts are copied from the run log:

```
749 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 198 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 94.02%
FAILED tests/core/test_postgres_schema.py::TestJobPasswordHashMigration::test_single_head_is_012_and_follows_011
1 failed, 5013 passed, 2 skipped, 4 warnings in 710.93s (0:11:50)
FAILED: Tests
 Test Files  64 passed (64)
      Tests  870 passed (870)
PASSED: UI Component Tests
VERIFICATION FAILED: Tests
GATE_EXIT=1
```

Drift check, `.\.venv\Scripts\python.exe scripts\drift_check.py`:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 267 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

### 1.1 The one failure that is not this branch's

`tests/core/test_postgres_schema.py::TestJobPasswordHashMigration::test_single_head_is_012_and_follows_011`
fails on this branch, and it fails on committed `main` (`75dbab9`) too. Migration `0013`
(`job_gsc_queries_payload`) was committed without updating this test, which still asserts head
`012`. Run on a `git archive` of `75dbab9`: `assert ['013'] == ['012']`, 1 failed, 33 passed.

Main's uncommitted user-store work already rewrites this test to expect `014`. The branch cannot
go green until that work, or an equivalent test correction, lands on `main`. This branch does not
edit that test, because the file belongs to another change in progress on `main`.

---

## 2. What landed

### 2.1 The gate covers every job-scoped write

Cancel, retry, reparse, resume, the GSC attachments, reconciliation, and the three deliverable builds
now call `require_job_password` after the org check (ADR 0042 §1). Before this, a caller with the
session could change a protected job. The check is one function, `src/api/job_password_gate.py`, so
a route cannot skip the lock by drift.

### 2.2 This round: three fixes to the gate

1. **The lock fails closed for an unknown store** (`_lockout_store`). The function used to return
   `None` for any store that was not disk-backed, and the gate then ran with no lock at all. A
   `PostgresJobStore` over a non-disk fallback, or any other store, is now refused with `503` before
   a password is checked. This was reachable: `PostgresJobStore.fallback_store` is typed as any
   `JobStore`.
2. **The header value is bounded** (`header_password`). A value longer than
   `MAX_DELETION_PASSWORD_LENGTH` (256) is refused with `422` before hashing or a bucket. Creation
   caps a password at 256 (`server.py`, `tool.py`), so such a value can never match. Before this,
   every oversize attempt was hashed in full and counted as a guess.
3. **The ADR is renumbered to 0042 and records the residual.** Every `ADR 0040` in the branch's
   code, tests, UI and docs now reads `ADR 0042`. The draft's pointer to "ADR (0041)" for a future
   PBKDF2 change is removed, because 0041 is the SMTP ADR on `main`.

---

## 3. Design decisions

- **Refuse, do not degrade.** A store that cannot hold the counter refuses the write. The rate
  limiter alone was judged not enough: it spends per minute, and a lock is what makes a guesser
  wait.
- **Refuse the oversize value in the route, not in the gate.** An oversize value is never right, so
  there is no guess to count, and refusing it before hashing costs nothing. Routing it through the
  gate would have spent a bucket and a PBKDF2 for a value that cannot succeed.
- **No new lock state on the job record.** Unchanged from `129cabd`: the counter stays a disk
  sidecar. A field on `JobRecord` would be dropped by the Postgres row mapper.

---

## 4. Bugs found and fixed

Each was reproduced on the code before the fix (the gate module reverted in a scratch copy, the new
tests run against it):

| Test | Before the fix |
| :--- | :--- |
| `test_job_password_gate.py::test_an_oversize_header_password_is_refused_before_any_hash` | `assert 403 == 422`: the oversize value was counted as a wrong guess |
| `test_job_password_gate.py::test_header_password_bound_is_inclusive_at_the_maximum` | `header_password` returned a value for 257 characters (no `HTTPException` raised) |
| `test_delete_job_lockout.py::test_a_store_that_cannot_hold_the_lock_refuses_every_guess_fail_closed` | `assert 403 == 503`: a wrong password got `incorrect password`, so the write ran with no lock |

Before the fix, 28 other tests in those two files passed. After it, all 31 pass.

### 4.1 A test that was wrong for the store it stood for

`tests/api/test_delete_job_postgres.py` built its `PostgresJobStore` over a `MagicMock` fallback.
The fail-closed change correctly refuses that store: it has no disk sidecar, so the two delete
tests got `503` instead of `403` and `204`. Production builds the store over a `DiskJobStore`
(`PostgresJobStore`'s default), so the mock modelled a configuration that does not run. **The code
was right and the test was wrong.** The fixture now uses `DiskJobStore(tmp_path / "jobs")`, the
production fallback, and the test asserts the same behaviour as before.

---

## 5. Explicitly not done

### 5.1 The repeat-lock loop is a residual, not a control

The lock slows a guesser. It does not stop one. After a window expires the failure count restarts,
so five more guesses lock the job again. Windows double to a 24-hour cap, and after 50 lifetime
failures every window is 24 hours. A sustained guesser therefore gets five guesses a day against
one job, about 1,800 a year. ADR 0042 "Known residual" states this, and this entry does not describe
the lock as preventing it.

### 5.2 The lock counter is not shared state

The counter is a disk sidecar in one process's job directory. Two workers or two hosts keep separate
counters, and on Postgres the sidecar sits on a per-container disk. **Hosted or multi-worker
deployment is blocked on moving the counter into shared state.** ADR 0004 keeps the local deployment
first, and CLAUDE.md §8 lists the rate limiter and cost ledger as blocking for hosted deployment. The
lock counter joins that list. Nothing in this cycle moves it.

### 5.3 Other gaps the ADR already lists

- Idempotency keys are not implemented. A double-submitted create still makes two jobs.
- A protected job whose password is under twelve characters remains deletable. The floor is
  creation-only (ADR 0042, decision A, operator-approved). An earlier draft applied the floor at
  delete too; that was corrected before merge.

---

## 6. Corrections to the draft ADR

- The draft ADR was numbered `0040`. On `main` that number belongs to the user-sessions ADR, so the
  file is now `0042`. Every reference in the branch was renumbered; no reference to the other ADR was
  changed.
- The draft said the PBKDF2 change would be "ADR 0041". `0041` is the SMTP ADR on `main`. The text now
  says "a separate ADR, not yet numbered".
- The draft did not state the lock's limit. ADR 0042 now states the repeat-lock residual and the
  shared-state prerequisite.
