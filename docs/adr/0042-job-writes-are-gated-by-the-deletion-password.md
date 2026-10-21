# ADR 0042: Every write to a crawl job is gated by its deletion password

- **Status**: Accepted
- **Date**: 2026-10-20
- **Deciders**: AI Lead, Lead AI Systems Engineer. The coordinator approved decisions D1 to D8
  in this cycle. Two of them were adjusted during implementation (see "Deviations from the
  approved plan").
- **Relates to**: [ADR 0016](0016-cloud-api-authentication.md) (the org-scoped principal every
  gate sits behind), [ADR 0034](0034-a-local-crawl-reaches-the-cloud-as-a-terminal-provenance-stamped-import.md)
  (imported jobs refuse re-runs; unchanged here)

---

## Context

A crawl job can be deleted irreversibly, and until now only deletion was guarded. A caller
who could reach the job's other write routes (cancel, retry, reparse, resume, the Search
Console and Screaming Frog attachments, and the deliverable builds) could change or re-run a
job whose owner had protected it with a deletion password. Those writes were gated by the
session alone.

Two gaps were open before this change:

1. **The password was optional and never set from the UI.** The Start-crawl form had no
   field, so every operator-started crawl was unprotected and undeletable.
2. **Creation kept the plaintext until the hash was computed in the request path**, and both
   the create-time hash and the delete-time verify ran PBKDF2 (210,000 iterations, about a
   quarter second) on the event loop.

Commit `129cabd` on `main` had already authenticated deletes before the rate limiter and added
a per-job lock with an escalating window. That lock is a disk sidecar, kept off `JobRecord`
on purpose (see `_DeleteLockout` in `src/core/state_store.py`): a field on `JobRecord` would be
dropped by the Postgres row mapper, so the failure count would reset on every request. This
ADR extends that lock to every job-scoped write rather than inventing a second one.

## Decision

1. **A job's deletion password gates every job-scoped write, not only delete.** Delete,
   cancel, retry, reparse, resume, reconciliation against Screaming Frog, the GSC query fetch,
   the GSC performance upload, and the three deliverable builds (`POST /jobs/{id}/deliverable`,
   and the two masterfile routes on a native crawl) all run one check,
   `require_job_password` in `src/api/job_password_gate.py`.
2. **Only a hash is stored.** Creation hashes the password with `hash_password` in a worker
   thread, then clears the plaintext from the payload before it is stored or dispatched. The
   stored request never contains a password key. The response returns only
   `has_delete_password`, from `JobView`.
3. **A job with no hash is not gated (D1).** Existing jobs keep today's write behaviour, so a
   legacy running crawl can still be cancelled. Delete alone refuses such a job, with `403`.
   Such a job can never be deleted, and nothing in the API sets a password after creation.
4. **Derived jobs inherit the hash (D3).** Retry, reparse, resume and the reconciliation that
   merges a Screaming Frog export create a new job. Each passes the source job's hash to the
   new record. The caller has just proven the password, so the hash is copied and no plaintext
   is needed. The new record starts with no lock state, which is safe because creating it
   required the right password.
5. **Lock after repeated failures (D8).** Five wrong passwords on one job lock every gated
   write on it for 15 minutes. Each later lock doubles the window, capped at 24 hours. A
   correct password clears the count. A locked job refuses the correct password too, and a
   dummy PBKDF2 check runs on the locked path so the response time does not reveal the lock.
   **The lock bounds the guessing rate. It does not stop repeat-locking.** See "Known residual"
   below.
6. **The password travels in a header on non-delete routes.** `X-Deletion-Password` is used
   because `performance/gsc` and `reconcile/screaming-frog` take a raw file or CSV body, and a
   query string would reach access logs. Delete keeps its JSON body, so its contract is
   unchanged. A header longer than the 256-character maximum is refused with `422` before any
   hashing or bucket: creation caps a password at that length, so such a value can never match.
   A store that cannot hold the lock counter refuses the write with `503`, and checks no
   password, rather than running the write with no lock (see check order below).
7. **The floor is twelve characters at creation only (D7, amended by decision A).** The password must be
   printable ASCII, because the header cannot carry anything else. A password outside that set
   would leave its owner unable to act on their own job, so it is refused at creation.
8. **Check order, shared by every route** (`enforce_job_password`):
   401 (`require_principal`) → 404 (no such job) → 403 "access denied" (another org; no
   password is looked at) → 429 (per-job and per-operator buckets, keyed on the verified
   operator) → 403 "job password required" (no password supplied; not a guess, so no lock
   count) → 503 "job lock unavailable" (the store has no lock counter; fails closed, so no
   password is checked) → 429 with `Retry-After` (locked) → 403 "incorrect password" (counted).
   A missing or short password is refused by validation (`422`) before auth, which reveals
   only the schema. An oversize header is refused `422` in the route, after the org check and
   before the gate.

## Deviations from the approved plan

The coordinator approved the plan at `156321c`. `origin/main` had moved on, and the
implementation follows the shipped code where it already solved the problem:

- **No `JobRecord` lock fields and no migration `0014` (plan D5).** The lock counter stays
  the disk sidecar `<id>.delete_lockout.json` from `129cabd`. A `JobRecord` field would be
  dropped by the Postgres row mapper, and its count would reset on every request. Under
  Postgres the sidecar lives on the disk fallback store, as delete already does.
  **Consequence:** the lock is not shared across hosts, and a hosted deployment relies on the
  per-process limiter, as `129cabd` already states.
- **The base window is 15 minutes, not 60 seconds (plan D8).** The shipped base was 60 s.
  Raised to the approved value. Lock ladder: 900, 1800, 3600, 7200, 14400, 28800, 57600, then
  the 86400 cap. The soft cap (50 lifetime failures) pins every later window at the cap.

## Accepted trade-offs

- **Any operator in the org can lock a job's writes.** Five wrong guesses lock cancel, retry
  and the rest for up to 24 hours, and the locked job refuses its owner's correct password
  until the window passes. The org is one trust boundary, so this does not cross it. The
  alternative is a permanent lock, which the design rules out.
- **The hash sits on disk.** `.jobs/*.json` and the Postgres `jobs.password_hash` column hold
  the PBKDF2 hash, as the operator password table does. Excluding it would make a job
  undeletable after a restart, so it stays. `.jobs/` is gitignored.
- **Each gated attempt costs about a quarter second of CPU** on a worker thread. The per-job
  bucket (5 a minute) and the per-operator bucket (20 a minute) bound it. These buckets also
  count successful gated writes, not only failures, as the delete bucket already did.
- **Idempotency keys are still not implemented.** A double-submitted create still makes two
  jobs. This change does not address that.

## Known residual: the repeat-lock loop

The lock slows guessing. It does not stop it. The mechanism, from
`DiskJobStore.record_failed_delete` in `src/core/state_store.py`:

1. Five wrong passwords lock the job for a window. Setting the lock resets the current
   failure count to zero. The lifetime count is kept.
2. When the window expires, the next five wrong passwords set another lock, with a longer
   window. The window doubles each time, to a cap of 24 hours.
3. Only a correct password clears the count. A guesser never has one.

So a guesser who keeps going is never refused for good. Each window gives five guesses. After
`DELETE_LOCK_SOFT_CAP` (50) lifetime failures every window is the 24-hour ceiling, so a
sustained guesser gets five guesses a day against one job, which is about 1,800 a year. The
guard bounds the guessing rate. It does not bound the total number of guesses.

This is accepted as a residual, not a control. The 12-character floor makes exhaustive guessing
infeasible. Dictionary guessing by an org member is not, and the org is the trust boundary this
ADR names. Any operator who guesses a job's password also locks that job's writes for its
owner, which is the trade-off in "Accepted trade-offs". Nothing in this change moves the
residual; a permanent lock is ruled out for the reason above.

## Prerequisite for hosted or multi-worker deployment

The lock counter is a disk sidecar, `<id>.delete_lockout.json`, in one process's job directory,
serialised by that process's lock. Two workers, or two hosts, keep separate counters, so N
workers give a guesser N times the budget. The per-process rate limiter has the same multiplier.
On Postgres the sidecar lives on the disk fallback, which is per container, so a redeploy or a
second replica does not share it.

Hosted deployment is therefore blocked until the lock counter is in shared state: a Postgres
column, or a shared cache, written through the store that holds the job. It is not built here.
ADR 0004 keeps the local deployment first, and CLAUDE.md §8 already lists the rate limiter and the
cost ledger as blocking for hosted deployment. The lock counter joins that list.

## Not decided here

- **PBKDF2 iteration count** (`src/core/auth.py`, 210,000). The same function hashes operator
  logins. Changing it needs a migration path for stored hashes, so it is a separate ADR, not
  yet numbered, and not part of this change.
- **Existing protected jobs with a password under twelve characters.** The length of a
  stored password is not recoverable from its hash. The local store holds 1,661 job records
  and none has a hash. No Postgres database was reachable to check. Such a job, if one
  exists, is NOT locked out: the twelve-character floor applies only at creation. The delete
  request accepts any password from one to 256 printable-ASCII characters, so a legacy job
  stays deletable with its own password (decision A, operator-approved). The lock and the
  auth-first order are unchanged.

## Consequences

- `JobView` and the job list show `has_delete_password`. The UI prompts before each gated
  action on a protected job and disables Delete on an unprotected one with its reason.
- Adding a gated route means calling `require_job_password` after the org check. The
  drift check does not enforce that, so a reviewer must.
- Tests: `tests/api/test_job_password_gate.py` (new), `tests/api/test_delete_job_lockout.py`,
  `tests/api/test_delete_job_postgres.py`, `tests/api/test_job_view.py`,
  `tests/modules/seo/page_classifier/test_tool_deletion_password.py` (new), and the UI tests
  `LiveCrawlModal.test.tsx`, `CrawlJobsView.test.tsx`, `DeleteJobModal.test.tsx` (new),
  `JobPasswordPrompt.test.tsx` (new), `httpAdapter.test.ts`.
