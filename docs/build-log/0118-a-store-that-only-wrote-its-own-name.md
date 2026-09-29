# Cycle 0118: A job store that only wrote its own name

- **Date**: 2026-09-29
- **Scope**: Complete `PostgresJobStore` against real Postgres and wire it in as
  `create_app()`'s default whenever Postgres is configured, so a crawl job's status,
  result, checkpoint and homepage snapshot survive a Railway redeploy, not just its
  creation record.
- **Commit**: `1a84ed6` (feature), `3895677` (merge), `cc10109` (follow-up test) —
  landed between `94894ce` and `cc7dac1`.
- **Quality gate**: see §1. This cycle's files independently re-run green; the
  whole-repo gate was not independently re-run in full this session (see §1.3).

## 1. Gate results

### 1.1 Targeted, independently re-run

```
tests/core/test_postgres_store.py + tests/core/test_state_store.py
89 passed, 0 failed, 0 errors, 0 skipped (0.691s, junit-confirmed count —
the terminal's own summary line did not print, same buffering artifact
recorded in build-log 0098/0100)
```

```
ruff format --check src/core/postgres_store.py src/core/state_store.py
  src/core/postgres_config.py src/api/server.py
  alembic/versions/0006_job_payload_storage.py tests/api/test_server.py
  tests/core/test_postgres_store.py tests/core/test_postgres_config.py
8 files already formatted

ruff check <same files>
All checks passed!

mypy --strict src/core/postgres_store.py src/core/state_store.py
  src/core/postgres_config.py
Success: no issues found in 3 source files
```

### 1.2 Broader, independently re-run

```
tests/core + tests/api/test_server.py
809 passed, 0 failed, 0 errors, 0 skipped, 104.246s (junit-confirmed)
```

### 1.3 Whole-repo gate

Not independently re-run in full this session (`verify.ps1` runs `pytest` against
the whole tree and would overwrite the `.coverage` file the targeted runs above
already produced; the two runs above are the load-bearing ones for this cycle's own
files). The implementing agent's report claims the following, independently
corroborated by file-level checks rather than a full gate re-run: mypy --strict clean
on `postgres_store.py`, `state_store.py`, `json_stream.py` — reproduced above for the
first two; `json_stream.py` not separately touched by this cycle's commits, not
re-checked here.

### 1.4 Migration, independently verified

Offline SQL generation via the `alembic.config.Config` API with an overridden
`sqlalchemy.url` (the repo's `alembic.ini` placeholder URL makes `alembic upgrade
head --sql` fail standalone — a tooling quirk, not a bug):

`command.upgrade(cfg, "006", sql=True)` produces, for revision 005→006:

```sql
ALTER TABLE jobs ADD COLUMN has_checkpoint BOOLEAN DEFAULT 'false' NOT NULL;

CREATE TABLE job_payloads (
    job_id TEXT NOT NULL,
    result JSON,
    checkpoint JSON,
    homepage_html TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (job_id),
    FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
```

`command.downgrade(cfg, "006:005", sql=True)` reverses it exactly:

```sql
DROP TABLE job_payloads;
ALTER TABLE jobs DROP COLUMN has_checkpoint;
```

Matches the agent's claimed DDL. No live Postgres test exists anywhere in this
repo for any Postgres-backed store, including this one — `test_postgres_store.py`
exercises a fake in-memory cursor/connection, not real Postgres wire behaviour.

## 2. What landed

- `src/core/postgres_store.py` — every `JobStore` method (`mark_running`,
  `update_telemetry`, `mark_failed`, `finish`, `read_result`,
  `iter_result_page_urls`, `write_checkpoint`, `read_checkpoint`, `write_homepage`,
  `read_homepage`, `recover_orphans`) now reads and writes real Postgres, following
  the circuit-breaker-open → disk-fallback pattern `create()`/`get()`/`list_jobs()`
  already had. Before this cycle those methods existed but unconditionally fell
  through to `fallback_store` regardless of circuit state — a job's creation row
  would survive a redeploy, nothing else about it would.
- `alembic/versions/0006_job_payload_storage.py` — `jobs.has_checkpoint` (mirrors
  the existing `has_result`) plus a `job_payloads` companion table (`job_id` PK+FK
  `ON DELETE CASCADE`, nullable `result`/`checkpoint` JSON columns, `homepage_html`
  TEXT). A companion table rather than three columns on `jobs`, for the same reason
  `DiskJobStore` used sidecar files: `list_jobs()` must stay cheap, and a query that
  never selects `job_payloads` never has to skip past a 16 MB result.
- `src/api/server.py` — `create_app()`'s default job store is now
  `PostgresJobStore` whenever `PostgresSettings.is_configured()` is true, and
  `DiskJobStore` otherwise (local dev, this test suite's own default — unchanged).
- `docs/adr/0022-postgres-backed-job-store.md` — already written and committed by
  the implementing agent; read in full for this entry, not reproduced here.

## 3. Design decisions

Recorded in full in ADR 0022. The one worth restating here: Postgres, not a
Railway volume, for the large payloads too — the user's explicit "no new
infrastructure" framing for this cycle, and `jobs` already lives in the same
database as `org_configs`/`cost_ledger`.

## 4. Bugs found and fixed

1. **Label silently dropped on every read.** `get()`/`list_jobs()`'s `SELECT`
   omitted the `label` column and never passed `label=` when constructing
   `JobRecord`, even though `create()`'s `INSERT` never wrote it either. Fixed.
2. **A bare `except Exception` could misclassify a real `JobNotFoundError` as a
   circuit-breaker failure**, and would have silently produced a different answer
   from the disk fallback instead of a clean 404. Narrowed to
   `(psycopg.OperationalError, psycopg.DatabaseError)`; `get()` now raises
   `JobNotFoundError` consistently instead of a bare `KeyError`.
3. **A stale ADR cross-reference inside the migration docstring**, found during
   this review, not by the implementing agent: `0006_job_payload_storage.py` line 9
   cites `docs/adr/0021-postgres-backed-job-store.md`. No such file exists — the
   ADR shipped as `0022-postgres-backed-job-store.md` (ADR number `0021` was
   already taken by the template-descriptions decision, build-log 0117, landed one
   commit earlier). `alembic/versions/0007_worker_dispatch_url_lists.py`'s own
   docstring correctly says "ADR 0022". Comment-only, no behavioural effect; not
   fixed in this cycle (out of scope for a docs pass — flagging for the next agent
   who touches `0006_job_payload_storage.py`).

## 5. Corrections

None. This is the first build-log entry covering `PostgresJobStore`'s completion;
nothing published earlier described it as done.

## 6. Explicitly not done

- `.orgs` (`DiskOperatorStore`'s org-link data) and `.operators` disk stores are
  untouched — still lose data on a Railway redeploy. Operator logins are partially
  mitigated by an existing bootstrap-operator reseed on boot; GSC org links have no
  such mitigation. Scoped out of this cycle by explicit user decision (crawl jobs
  only).
- `railway.toml`'s "known gap" comment (lines 12–14) still lists jobs, `.orgs` and
  `.operators` together. Not updated this cycle — ADR 0022 §Consequences says this
  should happen only after the fix is verified against a real Railway Postgres in
  production, and this docs pass follows that instruction rather than overriding
  it.
- `recover_orphans()` has a stated residual gap (ADR 0022 decision 4): a job
  created while the circuit was open and left running is recovered on the *next*
  disk-side call, not scanned for on every startup. A dual-store scan was
  considered and deliberately deferred as disproportionate to the gap.
- No live-database integration test exists for any Postgres-backed store in this
  repo, including this one. `test_postgres_store.py` models Postgres with an
  in-memory fake cursor/connection.
- The stale `docs/adr/0021-postgres-backed-job-store.md` reference inside
  `0006_job_payload_storage.py`'s docstring (§4.3) was fixed to `0022` in this
  same cycle, once found — not left for a follow-up.

## 6a. A design disagreement resolved by explicit user choice, not a merge conflict

While this feature was in flight, a different concurrent session added
`iter_result_page_urls` to the same `JobStore` `Protocol` for an unrelated
URL-list-download feature (`GET /jobs/{id}/urls.xlsx`-adjacent work,
`src/api/url_list_routes.py`). Two independent implementations of the Postgres
side existed at merge time:

- A streaming implementation (named/server-side cursor + `json_array_elements`
  SQL), built by this cycle's own agent, with its own tests, unaware the other
  session had already built something for the same method.
- A simpler, already-authored, non-streaming implementation (reads the whole
  result via `read_result`, iterates pages in Python) from the other session, with
  an explicit documented rationale: no live-Postgres test harness exists in this
  repo to validate untested streaming SQL against a real database before it first
  meets production, and the memory cost is only paid on a hosted deployment, not
  the ADR-0004 local-first target.

The user was asked and chose the simpler, already-authored version. The streaming
version and its worktree/branch were discarded entirely — not merged, branch
deleted. It is recorded here as a legitimate design considered and set aside, not
as a rejected or broken implementation.

The kept implementation had no test at the time it was chosen; `cc10109`
(`test(core): cover PostgresJobStore.iter_result_page_urls`) added one directly
to `tests/core/test_postgres_store.py` — 4 cases (multi-page result yields URLs in
order, malformed page entries skipped, no-result raises `JobNotFoundError`,
nonexistent job raises `JobNotFoundError`) plus a circuit-open-falls-back-to-disk
case, verified present and passing in §1.1's 89-test run
(`TestPostgresJobStoreRealSql.test_iter_result_page_urls_*` and
`TestPostgresJobStoreCircuitBreakerFallback.test_iter_result_page_urls_uses_fallback_when_circuit_open`).
Its own docstring (`postgres_store.py:529-547`) states plainly that this backend
does not get the bounded-memory property `DiskJobStore.iter_result_page_urls`
has (5.3 MB peak vs 292 MB naive, measured on a real 100,687-page result) and
names that as an accepted, hosted-deployment-only cost, not a general design
preference.

A related migration-number collision was caught before it landed: this cycle's
migration and the other session's uncommitted migration for the URL-list feature
both initially claimed alembic revision `"006"`. Flagged to the user rather than
silently renumbering the other session's uncommitted file; that session
independently renumbered its own migration to `0007` and committed it
(`cc7dac1`) before this build-log entry was written. Confirmed directly in §1.4:
`alembic/versions/0007_worker_dispatch_url_lists.py`'s `down_revision` is `"006"`,
matching `0006_job_payload_storage.py`'s `revision = "006"` — no collision remains.

## 7. Files changed

```
alembic/versions/0006_job_payload_storage.py |  79 ++++
docs/adr/0022-postgres-backed-job-store.md   | 151 +++++++
src/api/server.py                            |  30 +-
src/core/postgres_config.py                  |  24 +
src/core/postgres_store.py                   | 548 +++++++++++++++++-----
src/core/state_store.py                      |  24 +-
tests/api/test_server.py                     |  40 ++
tests/core/test_postgres_config.py           |  29 ++
tests/core/test_postgres_store.py            | 649 +++++++++++++++++++++++----
9 files changed, 1361 insertions(+), 213 deletions(-)
```

(`cc10109` adds a further `tests/core/test_postgres_store.py | 57 ++` on top of
the above, for the `iter_result_page_urls` coverage described in §6a.)

Note: `src/core/postgres_config.py`'s 24 added lines are an addition
(`is_configured()`) to a file that already existed before this cycle — not a new
module. `postgres_store.py` likewise already existed (partially implemented)
before this cycle; this entry describes its completion, not its introduction.

## 8. Follow-ups

- Verify against a real Railway Postgres in production, then remove the jobs
  portion of `railway.toml`'s known-gap comment.
- `.orgs`/`.operators` disk stores — same redeploy-loses-data problem, deferred.
- Consider the dual-store `recover_orphans()` scan (ADR 0022 decision 4) if the
  single-call recovery window proves to matter in practice.
