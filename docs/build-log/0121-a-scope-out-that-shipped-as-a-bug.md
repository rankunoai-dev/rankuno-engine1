# Cycle 0121: A scope-out that shipped as a bug

- **Date**: 2026-09-29
- **Scope**: Fix a live production bug — a user could not download a Screaming
  Frog reconciliation report — by completing `PostgresJobStore.write_reconciliation`/
  `read_reconciliation`/`write_performance`/`read_performance` against real
  Postgres, closing the gap ADR 0022 decision 5 deliberately left open.
- **Commit**: `f7e9e4e`.
- **Quality gate**: targeted tests independently re-run green (255 passed); ruff
  format/check clean on all 3 touched non-test files; mypy --strict clean on
  `src/core/postgres_store.py` and the new migration file; whole-repo `verify.ps1`
  **not run** this cycle. See §1.

## 1. Gate results

### 1.1 Regression tests, independently reproduced fail-then-pass

This is the load-bearing verification for this cycle and is recorded first. I
swapped in the pre-fix version of `src/core/postgres_store.py` via
`git show <pre-fix-commit>:src/core/postgres_store.py` in an isolated worktree
and ran the two new regression tests:

```
pytest tests/core/test_postgres_store.py -k regression
```

Both `test_reconciliation_regression_postgres_backed_job_survives_round_trip`
and `test_performance_regression_postgres_backed_job_survives_round_trip`
**FAILED** against the pre-fix file — `AssertionError` comparing a `MagicMock`
to the expected dict, which is exactly the observed production symptom: a read
that returns nothing real. I then restored the fixed file and re-ran:

```
tests/core/test_postgres_store.py -k regression
..                                                                       [100%]
```

Both pass. This was independently re-run by me, not taken on the implementer's
report.

### 1.2 Targeted suite, independently re-run

```
pytest tests/core/test_postgres_store.py tests/core/test_state_store.py tests/api/test_server.py
255 passed, 1 warning in 27.87s
```

Matches the implementing agent's reported figure exactly.

### 1.3 Format, lint, types — independently re-run

```
ruff format --check src/core/postgres_store.py \
  alembic/versions/0008_reconciliation_performance_payloads.py \
  tests/core/test_postgres_store.py
3 files already formatted

ruff check <same files>
All checks passed!

mypy --strict src/core/postgres_store.py
Success: no issues found in 1 source file

mypy --strict alembic/versions/0008_reconciliation_performance_payloads.py
Success: no issues found in 1 source file
```

`tests/core/test_postgres_store.py` is not covered by `mypy --strict` in this
gate run — consistent with this repo's existing test-file mypy posture, but not
independently confirmed against `verify.ps1`'s exact suppression list.

### 1.4 Migration, independently generated

Offline SQL via the `alembic.config.Config` API with an overridden
`sqlalchemy.url` (the repo's `alembic.ini` placeholder URL fails standalone —
a known tooling quirk, not a bug, recorded already in build-log 0118 §1.4).

`command.upgrade(cfg, "008", sql=True)`, revision 007→008:

```sql
ALTER TABLE job_payloads ADD COLUMN reconciliation JSON;
ALTER TABLE job_payloads ADD COLUMN performance JSON;
```

`command.downgrade(cfg, "008:007", sql=True)` reverses it exactly:

```sql
ALTER TABLE job_payloads DROP COLUMN performance;
ALTER TABLE job_payloads DROP COLUMN reconciliation;
```

Both directions clean and symmetric, matching the implementer's claim. No live
Postgres test exists for this or any store in this repo — same posture as
every prior Postgres-backed-store cycle (build-log 0118 §1.4).

### 1.5 Whole-repo gate

**Not run this cycle.** Only targeted commands were executed, by the
implementing agent and confirmed by me. Do not read §1.2–1.4 as a full
`verify.ps1` pass.

## 2. What landed

- `src/core/postgres_store.py` — `write_reconciliation`/`read_reconciliation`/
  `write_performance`/`read_performance` now follow the same pattern every
  other method in the class already uses: circuit-breaker check, `SELECT 1
  FROM jobs WHERE id = %s` existence check, `INSERT ... ON CONFLICT (job_id)
  DO UPDATE` upsert into `job_payloads`, `record_success`/`record_failure`,
  fall back to disk only once the breaker opens. Never raises, matching
  `DiskJobStore`'s existing contract.
- `alembic/versions/0008_reconciliation_performance_payloads.py` — adds
  nullable `reconciliation` and `performance` JSON columns to the existing
  `job_payloads` table (the same table migration 0006/build-log 0118 already
  uses for `result`/`checkpoint`/`homepage_html`). No data migration; existing
  rows get `NULL` in both, which is the correct "no saved report" answer.
- `docs/adr/0022-postgres-backed-job-store.md` — gained an "Amendment"
  section (not a new ADR) reversing decision 5 and recording that decision
  5's original scope-out is what caused this bug.
- `tests/core/test_postgres_store.py` — the two regression tests plus
  coverage for the new upsert/read paths, circuit-open fallback, and the
  not-found/malformed-payload branches.
- `DiskJobStore` (`src/core/state_store.py`) was **not** touched. It remains
  correct as-is for local/no-Postgres dev.

## 3. The bug

Confirmed live in production, reported by the user with screenshots and a
browser Network log: `POST /jobs/{id}/reconcile/screaming-frog` returned 200
with a real, correctly-computed `ReconciliationSummary`, but every subsequent
`GET .../reconciliation`, `.../reconciliation.xlsx`, `.../reconciliation.csv`
returned 404.

Root cause, traced through the actual code, not guessed: `PostgresJobStore.create()`
writes a new job to Postgres only in normal operation — it never also writes a
`.jobs/{id}.json` file to disk. Pre-fix, `write_reconciliation`/
`read_reconciliation`/`write_performance`/`read_performance` unconditionally
delegated straight to the disk fallback store regardless of circuit-breaker
state — a deliberate scope-out recorded in ADR 0022 decision 5 (build-log
0118). `DiskJobStore.write_reconciliation`/`write_performance` each call
`self._read(job_id)` first to confirm the job exists on disk before writing
the sidecar file; for a Postgres-backed job that raises `JobNotFoundError`,
caught and only logged as a warning (`reconciliation_write_failed`), never
raised, so the write silently no-oped. The subsequent GET then found nothing
and 404'd. This affected every reconciliation and every GSC performance
report on every job created since `PostgresJobStore` became `create_app()`'s
default (build-log 0118) whenever Postgres is configured — production,
continuously, since that cycle shipped.

`write_performance`/`read_performance` had the identical bug for the identical
reason (GSC performance reports), confirmed by direct code reading before any
change was made — the same fix closes both.

## 4. Design decision: rejected a quick fix

Simply removing `DiskJobStore`'s existence check, or writing reconciliation to
disk unconditionally, would have "fixed" the symptom while writing the report
onto the same ephemeral container disk Railway wipes on every redeploy —
silently reintroducing the exact data-loss bug build-log 0118 was built to
close, just for a different kind of data. This was considered and rejected
before any code was written.

The user chose "add to the existing table" over "a separate table" when
asked. `job_payloads` gained two nullable columns rather than a new table,
matching the pattern already used for `result`/`checkpoint`/`homepage_html`.

## 5. Bugs found and fixed

1. **Reconciliation write silently no-ops for a Postgres-backed job**, §3.
   Fixed by the migration + the four rewritten methods.
2. **Performance write has the identical bug for the identical reason**
   (GSC performance reports). Found by direct code reading, same fix.

## 6. Corrections

Corrects the framing in ADR 0022 decision 5 and build-log 0118 §6 ("`.orgs`/
`.operators` disk stores explicitly out of scope" — that framing was correct;
the separate claim that reconciliation/performance were a *deferred feature*
rather than a live bug is what this entry corrects). ADR 0022 decision 5's own
text said the scope-out was "a documented follow-up, not an oversight" — that
statement is now known to be false: it was a production bug from the moment
`PostgresJobStore` became the default. The ADR carries its own amendment
rather than being silently edited; see `docs/adr/0022-postgres-backed-job-store.md`.

`README.md`'s `core/postgres_store.py` row and `docs/ARCHITECTURE.md`'s
`postgres_store.py` module comment both previously stated
`reconciliation`/`performance` "stay disk-only" / "delegate to the fallback
store unconditionally... out of scope for this cycle" as a stable, intended
design. Both corrected in this cycle — see §8.

## 7. Explicitly not done

- `src/api/server.py`, `ReconciliationSummary`'s shape, and every
  `rankuno-ui/` file were untouched — this was a pure storage-layer fix,
  confirmed via `git diff` scope: only 4 files changed (`postgres_store.py`,
  the migration, the ADR amendment, the test file).
- No live-Postgres integration test exists for this or any store in this
  repo — same posture as every prior Postgres-backed-store cycle
  (build-log 0118 §1.4, §6).
- The fix has **not** been confirmed against the real user's actual failing
  job in production. It closes the traced root cause; no live redeploy-and-retry
  has been observed by this session.
- Whole-repo `verify.ps1` gate not run this cycle — targeted commands only.
  State this plainly; do not imply a full gate ran.
- `.orgs`/`.operators` disk stores remain untouched, same accepted gap as
  build-log 0118 recorded.

## 8. Documentation drift closed

`docs/ARCHITECTURE.md`'s `postgres_store.py` module comment said
`write_reconciliation`/`read_reconciliation`/`write_performance`/
`read_performance` "always delegate to the fallback store unconditionally --
out of scope for this cycle." Rewritten to describe the real Postgres path
and cite this entry and the ADR amendment.

`README.md`'s `core/postgres_store.py` capability row said
"`reconciliation`/`performance` sidecars and the unrelated `.orgs`/`.operators`
stores stay disk-only, a deferred follow-up." Rewritten to state plainly that
the unconditional disk delegation was a production bug, not a deferred
feature, and that it is now fixed — while keeping the `.orgs`/`.operators`
gap, which is real and unrelated.

## 9. Files changed

```
alembic/versions/0008_reconciliation_performance_payloads.py |  58 +
docs/adr/0022-postgres-backed-job-store.md                   |  39 +
src/core/postgres_store.py                                   | 139 ++--
tests/core/test_postgres_store.py                            | 133 ++--
4 files changed, 340 insertions(+), 29 deletions(-)
```

Plus this cycle's own documentation drift closure:
`README.md` (1 row rewritten), `docs/ARCHITECTURE.md` (1 module-comment block
rewritten), `docs/build-log/README.md` (this entry indexed).

## 10. Follow-ups

- Confirm the fix against the real user's failing job in production once
  redeployed.
- Whole-repo `verify.ps1` gate has not been run since build-log 0119/0120;
  worth a clean full run before the next cycle stacks further concurrent
  session changes on top.
