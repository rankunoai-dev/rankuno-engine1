# Cycle 0148: The Postgres store forgot the password hash

- **Date**: 2026-10-08
- **Scope**: SECURITY/CORRECTNESS FIX, step 2 of 7 of the approved per-job delete-password plan (steps 1, the audit and the user's decisions are in [build-log 0147](0147-the-job-list-stopped-serving-password-hashes.md)). Closes audit finding F2 (HIGH): `PostgresJobStore` never persisted `JobRecord.password_hash`.
- **Commit**: (uncommitted at time of writing)
- **Quality gate**: implementer ran `verify.ps1 -Fix`, output to a file, exit 0. The scribe did not re-run it; the lines below are the implementer's reported output.

```
mypy:     Success: no issues found in 176 source files
coverage: TOTAL 17495 980 3788 279 93%
          Required test coverage of 85.0% reached. Total coverage: 93.49%
pytest:   4388 passed, 2 skipped, 2 warnings in 880.20s (0:14:40)
UI:       Test Files 53 passed (53), Tests 695 passed (695)
          ALL GATES PASSED.
```

## DEPLOY ORDER

Run `alembic upgrade head` (to revision `010`) BEFORE the new code serves traffic. The new `create()` INSERT and every `get`/`list_jobs`/`UPDATE ... RETURNING` name `password_hash`, so they fail on a database without the column. The migration is additive, nullable and idempotent (`IF NOT EXISTS`), and the old code ignores the extra column, so migrating first is safe.

What is known about Railway, from reading the repo only:

- `Dockerfile` line 61: `CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory src.api.server:create_app ..."]`. The migration is chained before uvicorn in the container start command, so on a Railway deploy built from this Dockerfile it runs at container start, before the new code listens.
- `railway.toml` sets `builder = "dockerfile"` and states "The start command lives in the Dockerfile CMD". It sets no `startCommand` of its own.
- Not verified: that the Railway service has no dashboard-level start command override, that the old container is drained before the new one runs the migration, and that `alembic upgrade head` has ever succeeded against the production database for this revision. No Railway or Postgres access was available. If a dashboard override exists, the migration does not auto-run and must be run by hand first.
- Rollback caveat: `downgrade` drops the column and every stored hash with it. After downgrading, the previous code runs without the column, but any hashes written meanwhile are gone.

## 1. Why this cycle exists

Audit finding F2: on Postgres (Railway) every DELETE returned 403. `PostgresJobStore.create()` accepted a `JobRecord` carrying `password_hash` and returned one, so the create response looked correct and the existing tests passed. The INSERT, `_JOB_COLUMNS` and `_row_to_job_record` never mentioned the column, so the next `get()` always returned `password_hash=None`, and the DELETE route treated the job as having no password. The loss was only visible on the following read.

## 2. What landed

- `alembic/versions/0010_job_password_hash.py` (new): revision id `"010"`, `down_revision = "009"`. The repo's real revision ids are `"001"`..`"009"`; only the filenames carry slugs. Adds nullable `password_hash TEXT` to `jobs` by raw SQL `ADD COLUMN IF NOT EXISTS`; downgrade is `DROP COLUMN IF EXISTS`. No backfill, because the plaintext was never stored and the hash was never written.
- `src/core/postgres_store.py`: `password_hash` is appended as the LAST column of `_JOB_COLUMNS` (after `bundle_sha256`), so the 15 base columns and the 9-column provenance block keep their offsets. `_BASE_COLUMN_COUNT` stays 15; new `_PROVENANCE_END = 24`. `_row_to_job_record` reads `row[15:24]` for provenance and `row[24]` for the hash. The `create()` INSERT now has 10 columns and 10 bound values, the hash bound as a parameter and never logged. `get`, `list_jobs`, every `UPDATE ... RETURNING` and the import `RETURNING` use `_JOB_COLUMNS` and picked the column up with no further edit. The import INSERT is unchanged: imported jobs get NULL, which is correct.

Offline SQL, generated through the alembic Config API (the method of [build-log 0118](0118-a-store-that-only-wrote-its-own-name.md)):

```
upgrade 009:010
BEGIN;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS password_hash TEXT;
UPDATE alembic_version SET version_num='010' WHERE alembic_version.version_num = '009';
COMMIT;

downgrade 010:009
BEGIN;
ALTER TABLE jobs DROP COLUMN IF EXISTS password_hash;
UPDATE alembic_version SET version_num='009' WHERE alembic_version.version_num = '010';
COMMIT;
```

## 3. Tests

`tests/core/test_postgres_store.py` (fake cursor extended), class `TestPasswordHashPersistence`:

| Test | Asserts |
| :--- | :--- |
| `test_create_persists_password_hash_in_insert` | the INSERT names the column and binds the hash |
| `test_row_to_job_record_roundtrips_hash` | a row with a hash at index 24 loads with it |
| `test_legacy_row_with_null_hash_loads` | NULL loads as `None` |
| `test_hash_survives_state_transitions` | the hash is intact after status updates |
| `test_all_returning_queries_use_same_column_list` | every RETURNING shares `_JOB_COLUMNS` |
| `test_hash_is_never_logged` | the hash string is absent from captured logs |

`tests/core/test_postgres_schema.py`, class `TestJobPasswordHashMigration` (file-content pattern like the existing tests): revision chain 009 to 010; single alembic head `["010"]` via `ScriptDirectory`; nullable column with `IF NOT EXISTS`; downgrade drops it; the store reads the column.

`tests/api/test_delete_job_postgres.py` (new): the real DELETE route over `PostgresJobStore` with the fake cursor. Wrong password gives 403 and the job survives; correct password gives 204 and the job is gone; a repeat gives 404; a job with no password gives 403. The job is created with `store.create` and a hash, not `POST /jobs`, which would start a crawl.

## 4. Bugs found and fixed

- F2 itself: the hash was never written or read on Postgres. Fixed above.
- Why it hid: `create()` returns the record it was given rather than re-reading the row, so the create response and any test asserting on it carried the hash. Only a read after the write exposes the loss. `test_delete_job_postgres.py` exists to exercise that read path through the real route.
- No test was found wrong and no specification bug was found in this step.

## 5. Corrections

- [Build-log 0145](0145-password-protected-job-deletion.md) and [0146](0146-delete-crawl-ui-button.md) present deletion as working. On Postgres it never worked: every DELETE was 403. Disk-backed (local) jobs were not affected.
- Correction to the cycle brief: the delete route returns 204, not 200. The new tests assert 204.

## 6. Explicitly not done

- Steps 3-7 of the plan: required min-8 `SecretStr` and a create-only model; 422 echo stripping; bundle stripping; auth before the limiter; per-(operator, job) lockout with migration 0011; terminal-only delete; 503 mapping; hash inheritance on Run again, Resume and Reparse; the password field on the New crawl form; the operator-only audited delete script; and the whole-feature ADR. The user-facing feature is still not usable.
- No backfill. Jobs created before this fix have NULL and stay undeletable through the API (403), with no operator path until step 7.
- `fallback_recovery.py` still discards disk-fallback jobs after logging, so a job created while the circuit breaker was open loses its hash on recovery too. Pre-existing, handed off. The user decided that create with the breaker open should refuse with 503; that is step 3/4 work and is not done.
- Real Postgres was not exercised. Tests use a fake cursor, which cannot validate SQL; the migration was checked only as offline SQL. Treat the first real `alembic upgrade head` as the actual test.
- The step 1 hash leak fix (commit `5e0febc`) is a separate cycle. Hashes served before it still count as exposed.
- README.md and docs/ARCHITECTURE.md were not changed: neither holds a migration table that needs a 0010 row.
