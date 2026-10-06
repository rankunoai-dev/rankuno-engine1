# Cycle 0140: A local crawl copied to the cloud

- **Date**: 2026-10-07
- **Scope**: A finished local crawl can be copied into the operator's cloud org as an
  already-terminal, provenance-stamped job: CLI `scripts/push_job_to_cloud.py` → `POST
  /api/v1/jobs/import` → `JobStore.import_terminal` (disk and Postgres, migration 009). The UI
  badges imported jobs, hides Resume and Run again for them, and links crawled URLs only through
  a new `safeHref()` at all 8 link sites.
  ([ADR 0034](../adr/0034-a-local-crawl-reaches-the-cloud-as-a-terminal-provenance-stamped-import.md))
- **Commit**: backend `952c8a7`, UI `2c69c91`, on `origin/main` `b86196d`, branch `job-import`.
  This entry and the docs fixes in §7 are uncommitted at time of writing. Not pushed, not
  deployed.
- **Quality gate**: GREEN — lead's run, builder's run and UI engineer's run (§1).

**Numbering note**: the highest build-log entry is `0139` in this worktree, on `origin/main`, on
every local branch, in every worktree under `.claude/worktrees/`, and in the main checkout.
`0140` was free everywhere. ADR `0034` was added by the builder in `952c8a7`; the highest ADR on
`origin/main` is `0033`.

## 0. Background

The user's words: "i have ran this recent groundguys crawl on the local can we do something which
can populate this crawl on the cloud one". The crawl is local job
`42de4ed7b5ff44e8a592922aa99dfaeb` (groundsguys.com, 8,238 pages), run through the cycle 0138
local site because the Railway container cannot hold crawls that size. The user approved the
plan.

ADR 0032 rules out the shortcut of pointing the local process at the production database. The
copy therefore travels over the authenticated HTTPS API and is validated as hostile input.

The pre-implementation security audit returned **PASS WITH CONDITIONS** (1-10). The findings that
shaped the design:

| Finding | Severity | Consequence for the design |
| :--- | :--- | :--- |
| F1 Stored XSS: URL fields are plain `str` with no scheme check; React 18 warns about but does not block `javascript:` in `href`; the session token is in `localStorage` | HIGH | Server-side URL scheme walk over the whole bundle, and `safeHref()` at all 8 UI link sites |
| F2 Building an import on `create()`/`finish()` would charge the $0.50 ledger, require budget, fall back to disk, and pass through `queued`/`running`, where `recover_orphans` would fail it | HIGH | A separate, atomic `JobStore.import_terminal` |
| F3 An imported checkpoint would feed resume unvalidated | | v1 carries no checkpoint; retry and resume answer 409 |
| F4 | | Store only the validated model's dump, never the uploaded bytes |
| F5 Gzip bomb | | Capped streaming body; bounded inflate with an absolute cap, not a ratio |
| F6 422s echo input | | Sanitised 422: error count plus the first 10 `loc` paths, no values |
| F7 No formula neutralisation in `_workbook_response`, the CSV routes, or `urls.xlsx` | | Not fixed here (§6) |
| F8 The session token is 12 h, not "short-lived" | | Correction (§5.3) |
| F9 No role model | | Any authenticated operator may import into their own org |
| F10 A local "Copy to cloud" button | | Deferred: it needs an ADR 0032 amendment (§6) |

Measured before deciding (auditor, on the real groundsguys job): `result.json` 19.2 MB, gzip
0.70 MB (27x); validates against `PageClassificationOutput` in 0.5 s, ~51 MB traced. The largest
local result is 93 MB.

---

## 1. Gate results

LEAD GATE (run by the lead on commit `2c69c91` in this worktree, main venv, `import src` resolved to the worktree):

```
ruff format --check .            -> 640 files already formatted
ruff check .                     -> All checks passed!
mypy src                         -> Success: no issues found in 175 source files
export_ui_contract.py --check    -> UI contract is up to date.
pytest --cov=src                 -> Required test coverage of 85.0% reached. Total coverage: 93.40%
                                    4238 passed, 2 skipped, 1 warning in 1259.67s (0:20:59)
rankuno-ui: npx tsc --noEmit     -> exit 0
rankuno-ui: npx vitest run       -> Test Files 52 passed (52), Tests 682 passed (682), exit 0
```

The lead also regenerated the migration's offline SQL itself (`command.upgrade(cfg, "008:009", sql=True)`
against a dummy URL, no database contacted); it matches the statements below line for line.

The builder's gate (backend commit, plus the UI suite), as reported by the builder. Not re-run by
the scribe:

```
ruff format --check .            640 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 175 source files
pytest --cov=src                 4238 passed, 2 skipped; Total coverage: 93.41%
drift_check                      PASSED (237 markdown files)
export_ui_contract.py --check    UI contract is up to date
rankuno-ui tsc                   0 errors
rankuno-ui vitest                Test Files 51 passed, Tests 642 passed
```

The UI engineer's gate (UI commit), as reported:

```
tsc                              0 errors
vitest (first run)               1 file failed: 2 ScreamingFrogView tests timed out at 5000 ms
vitest ScreamingFrogView alone   25/25 passed
vitest (rerun)                   Test Files 52 passed, Tests 682 passed
export_ui_contract.py --check    UI contract is up to date
npm run build                    ok
```

`ScreamingFrogView` was not touched by this cycle. The two timeouts are recorded as a
flaky-under-load observation, not a pass.

Against cycle 0139's lead gate (4064 passed, 93.28%), +174 Python tests. The scribe counted them
with `pytest --collect-only -qq` in this worktree (main venv; `import src` resolved to
`...\.claude\worktrees\job-import\src\__init__.py`):

| File | Collected | New |
| :--- | ---: | ---: |
| `tests/api/test_job_import_routes.py` | 35 | 35 |
| `tests/core/test_bounded_gzip.py` | 10 | 10 |
| `tests/core/test_job_import_store.py` | 14 | 14 |
| `tests/integrations/test_rankuno_cloud_client.py` | 21 | 21 |
| `tests/modules/seo/test_job_bundle.py` | 55 | 55 |
| `tests/modules/seo/test_job_import.py` | 10 | 10 |
| `tests/modules/seo/test_local_job_export.py` | 12 | 12 |
| `tests/scripts/test_push_job_to_cloud.py` | 11 | 11 |
| `tests/core/test_postgres_schema.py` | 23 | +4 (19 `def test_` before, 23 after) |
| `tests/core/test_rate_limiter.py` | 39 | +2 (37 before, 39 after) |
| `tests/core/test_postgres_store.py` | 53 | 0 (42 `def test_` before and after; existing tests changed) |
| **Total** | | **174** |

**Fail-before and mutation** (builder):

| Probe | Result |
| :--- | :--- |
| `POST /api/v1/jobs/import` on `HEAD` | **405**, not 404 (§5.1) |
| Mutation A: URL walk disabled | 2 route tests and 25 `test_job_bundle.py` tests fail |
| Mutation B: route stores through `create()` + `finish()` | `test_an_import_writes_no_ledger_row` fails: `assert [('org-a', '…', 0.5, 'charged')] == []` |
| UI: link-safety tests on `HEAD`'s `RedirectTable`/`OrphanTable` | 5 failed, 1 passed |

**Offline migration SQL** (`alembic upgrade 008:009 --sql`, builder):

```
BEGIN;
-- Running upgrade 008 -> 009
ALTER TABLE jobs ADD COLUMN import_origin TEXT;
ALTER TABLE jobs ADD COLUMN source_instance_id TEXT;
ALTER TABLE jobs ADD COLUMN source_label TEXT;
ALTER TABLE jobs ADD COLUMN source_job_id TEXT;
ALTER TABLE jobs ADD COLUMN crawl_started_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN crawl_finished_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN imported_by TEXT;
ALTER TABLE jobs ADD COLUMN imported_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN bundle_sha256 TEXT;
CREATE UNIQUE INDEX uq_jobs_import_source ON jobs (org_id, source_instance_id, source_job_id) WHERE source_job_id IS NOT NULL;
UPDATE alembic_version SET version_num='009' WHERE alembic_version.version_num = '008';
COMMIT;
```

The `ALTER TABLE` lines after the first were abbreviated in the report the scribe received ("...
source_instance_id TEXT; source_label TEXT; ..."); they are written out here from the column list
in that report and in `alembic/versions/0009_job_import_provenance.py`. Railway applies the
migration through the `Dockerfile`'s `alembic upgrade head`. It has not been applied to any real
Postgres.

**CLI on the real job** (read-only, dry run, builder):

```
--list --target groundsguys.com   1 finished crawl: 42de4ed7… succeeded 2026-10-06 18:12 UTC, 7,897 fetched
--job 42de4ed7… --dry-run         8,238 pages; Bundle 19.4 MB -> 0.83 MB gzip; passed every check; nothing sent
```

The 0.83 MB includes the 1.07 MB homepage HTML, which the auditor's 0.70 MB figure for
`result.json` alone did not.

**End to end** (in-process app over a temporary `DiskJobStore`, no network):

| Step | Result |
| :--- | :--- |
| First push | 201, `succeeded`, 8,238 pages, `duplicate=False`, 0.6 s |
| Second push, same bytes | 200, same job id, `duplicate=True` |
| `GET /result` | 200 |
| `urls.xlsx` | 200, 0.88 MB, 8,239 rows |
| Workbook deliverable | 202, then `succeeded`, 4 sheets |
| Retry | 409 |
| Resume | 409 |

**Memory and time** (builder, development workstation):

| Input | Inflated | Gzip | Peak working set above baseline | Time |
| :--- | ---: | ---: | ---: | ---: |
| Largest local result, 100,687 pages | 88.8 MiB | 3.3 MiB | ~1.08 GiB | 6.5-11.6 s |
| groundsguys | 19.2 MB | 0.70 MB | 139 MiB | 0.7 s |
| At the 128 MiB cap | 128 MiB | | ~1.5 GiB **extrapolated, not measured** | |

`model_dump_json` re-serialises the 88.8 MiB result to 141.5 MiB, because defaults are filled in.

---

## 2. What landed

From `git show --numstat`: backend `952c8a7` 33 files, UI `2c69c91` 16 files; 49 files,
+4,511 / -55 together.

**`src/api/job_import_routes.py`** (new, 217 lines). `POST /api/v1/jobs/import`. Checks run
cheapest first: `require_principal` (401) → per-operator bucket `import:{operator}`, 6 per hour,
burst 2 (429) → `Content-Type: application/gzip` (415) → process-wide `state.import_lock`,
acquired without blocking (429, never queued) → `read_capped_body` at 32 MiB, on
`Content-Length` and on the stream (413) → on a worker thread, `prepare_import` then
`store.import_terminal`. Answers 201 new, 200 duplicate, 409 changed source or org not
provisioned, 400 bad gzip, 413 over a cap, 422 contract or URL audit failure (error count and the
first 10 locations, no values), 503 store unavailable.

**`src/core/bounded_gzip.py`** (new, 102 lines). `gunzip_capped` inflates one gzip member through
`decompressobj` with `max_length`, so the cap applies while inflating, and returns sha256 over
the inflated bytes. The hash is over inflated bytes because gzip headers carry a timestamp.

**`src/core/job_provenance.py`** (new, 76 lines). `JobProvenance`: import origin, random source
instance id (`li-<24 hex>`), optional source label, source job id, crawl start and finish,
`imported_by`, `imported_at`, `bundle_sha256`. No path or hostname.

**`src/core/state_store.py`** (+159). `JobRecord.provenance: JobProvenance | None`.
`JobStore.import_terminal` on the protocol and on `DiskJobStore`.

**`src/core/postgres_store.py`** (+150 / -3). `PostgresJobStore.import_terminal`: one transaction
inserts the terminal `jobs` row and its `job_payloads` row. No ledger row, no `org_configs` lock,
no disk fallback: an open circuit or a database error raises `JobStoreUnavailableError` (503).
`UniqueViolation` is caught before `DatabaseError`, then the existing row is re-read to decide
duplicate (200) or changed source (409). `ForeignKeyViolation` becomes 409 "org not provisioned".

**`alembic/versions/0009_job_import_provenance.py`** (new, 72 lines). Revision `009` on `008`:
nine nullable columns and the partial unique index `uq_jobs_import_source`.

**`src/core/rate_limiter.py`** (+34). `TokenBucket.per_hour` and a registry
`get_or_create_per_hour`, for a rate slower than one per second.

**`src/core/config.py`** (+39). `cloud_import_base_url` (CLI only; the server never reads it),
`job_import_max_compressed_bytes` (32 MiB), `job_import_max_decompressed_bytes` (128 MiB),
`job_import_per_hour` (6), `job_import_burst` (2).

**`src/api/server.py`** (+27). `ApiState.import_lock`; router included; `_refuse_imported()`
makes `retry` and `resume` answer 409 for any job with provenance. `reparse` is not refused.

**`src/api/worker_route_helpers.py`** (+11 / -3). `read_capped_body` takes a `log_prefix`, so a
refused import is not logged as a refused worker upload.

**`src/modules/seo/page_classifier/job_bundle.py`** (new, 240 lines). `JobImportBundle`
(versioned, `extra="forbid"`, no field for org, job id, `has_*` flags or telemetry) and
`audit_url_schemes`. Every field in `STRICT_URL_FIELDS` must be http(s) with a host. A test fails
when a new URL-named string field is not classified. `canonical_url` is refused only for a real
non-http scheme, parsed the WHATWG way (§3).

**`src/modules/seo/page_classifier/job_import.py`** (new, 172 lines). `prepare_import`: capped
gunzip → `model_validate_json` → URL audit → a `PreparedImport` holding the re-serialised result
and an `ImportedJob` (`state_store.py`) built from server-side facts
(org and `imported_by` from the session, telemetry rebuilt from the result, `tool_name` and
`facet_id` fixed to `seo.page_classifier`, `created_at` = import time).

**`src/modules/seo/page_classifier/local_job_export.py`** (new, 213 lines). CLI side. Lists and
selects finished local jobs through `DiskJobStore` only, never `src.api.server`; creates
`.jobs/.instance-id` on the first real push (not on `--dry-run`); encodes deterministically
(gzip `mtime=0`), so a retry sends identical bytes.

**`src/integrations/rankuno_cloud_client.py`** (new, 222 lines). Login and upload under
`BaseAPIClient` (key `rankuno_cloud_import`). `require_secure_base_url` (https, or http to
loopback only), `follow_redirects=False`, `verify=True`, any 3xx a hard error. Refusals raise
`GuardrailViolationError` so they are not retried; 429, 5xx and transport errors retry the same
bytes. The token is held in memory only.

**`scripts/push_job_to_cloud.py`** (new, 234 lines). `--list`, `--job`, `--latest --target`,
`--dry-run`, `--cloud-url` (overrides `CLOUD_IMPORT_BASE_URL`). The password is read by
`getpass` only, and only when stdin is a terminal. Runs every server check locally before sending.

**UI** (`2c69c91`).
- `rankuno-ui/src/lib/safeHref.ts` (new, 42 lines): parses with `new URL()` and no base, admits
  only `http:`/`https:` with a non-empty host, otherwise returns `null` and the caller renders
  plain text. Protocol-relative and relative values throw and are refused rather than resolved
  against the app's origin.
- Applied at 8 sites: `DuplicateTable.tsx` (2), `RedirectTable.tsx` (2: URL and destination),
  `OrphanTable.tsx` (1), `GscIntegratedReport.tsx` (1), `VirtualizedTree.tsx` (2: page and
  defaulter rows). This protects native crawls too; it is not import-specific.
- `CrawlJobsView.tsx`: an "imported from local" `Tag` with a tooltip (source label, import time,
  "run it again locally"), focusable and with the same text as its accessible name.
  `canRerunHere = canRelaunch && row.importedFrom === null` gates the Resume and Run again menu
  items.
- `httpAdapter.ts` maps `provenance` to `importedFrom` (source label and import time only). The
  raw `JobRecord` type declares `provenance?: JobProvenance | null`, optional, so a server that
  predates the field still parses.

---

## 3. Design decisions

ADR 0034 records the reasoning. The rulings the lead made during the cycle:

| Question | Ruling | Why |
| :--- | :--- | :--- |
| Which schemes may `canonical_url` carry? | No scheme, or http/https. Any other scheme is refused, read the WHATWG way: tabs and newlines removed, C0 controls stripped, so `java\tscript:` is `javascript:` | `canonical_url` is the site's own claim, recorded verbatim; 10 of 1,333 local results carry values like `www.http://…`. Refusing them would refuse real crawls |
| What is `www.http:`? | A dotted "scheme" is treated as a broken host and accepted as text | No dangerous scheme contains a dot, and no browser executes one |
| Other-org access to an imported job | 403, unchanged | Same as every job route (§5.2) |
| Masterfiles on imported jobs | 409 | They 409 for every native crawl already (§5.4) |
| Caps | 128 MiB inflated, concurrency 1 | The 93 MB largest result fits with room; one at a time bounds memory, which the ADR 0031 budget does not count |
| CLI shape | `--list`, `--job`, `--latest --target`; `--cloud-url` overrides `CLOUD_IMPORT_BASE_URL`; instance id in `.jobs/.instance-id` | |
| `created_at` | Import time; the crawl's own times go in provenance | The job record is a cloud fact; when the crawl ran is a provenance fact |
| Reparse | Allowed, with its usual charge | It is offline and goes through `create()` |

**Refuse the whole bundle, never rewrite it.** A bundle with one bad URL is refused. A crawl with
its URLs silently rewritten would not be the crawl that ran.

**Two independent link defences.** The server audit stops a bad URL entering through an import.
`safeHref()` stops one rendering as a link whatever its source, including native crawls, which
were never audited.

---

## 4. Bugs found and fixed

### 4.1 Building an import on `create()`/`finish()` would have charged for it (F2)

The obvious implementation reuses the native path. The audit showed it would charge the $0.50
ledger, require budget, fall back to disk on a Postgres fault (lost on the next Railway redeploy
after the client was told it landed), and pass through `queued`/`running`, where a restart's
`recover_orphans` would fail it. `import_terminal` exists for this reason. Mutation B (§1) shows
the ledger test catches a regression to the native path.

### 4.2 `read_capped_body` would have logged a refused import as a refused worker upload

The helper's log event names were hard-coded `worker_upload_rejected_*`. It now takes a
`log_prefix`.

### 4.3 A test leaks a temp file into the working directory (not fixed)

During the builder's full pytest run, `tmp2n715y7t.tmp` containing `{}` appeared in the worktree
root. Some existing test writes a temp file into the cwd. Not identified; handed to
`test-engineer` (§8). It was not present when this entry was written.

### 4.4 `ScreamingFrogView` tests time out under load (not fixed)

Two tests in an untouched file timed out at 5,000 ms in the UI engineer's first full vitest run,
passed 25/25 alone, and passed in the rerun (§1). Flaky under load, not caused by this cycle.

---

## 5. Corrections

### 5.1 The brief expected 404 for the new route on `HEAD`; it is 405

The fail-before probe on `HEAD` answered **405 Method Not Allowed**, not 404, because
`GET /jobs/{job_id}` matches the path `/jobs/import`. A fail-before that asserted 404 would have
failed for the wrong reason.

### 5.2 `org_scoped_or_404` returns 403

`src/api/auth.py` `org_scoped_or_404` raises `403 "access denied"` for a record another org owns
(line 211). The name says 404. ADR 0016 condition 2 and `docs/ARCHITECTURE.md` cite the helper by
that name; build-log 0133 already records cross-org as 403 for the read routes. The plan's
assumption that an imported job in another org would 404 was wrong; it is 403, as for every job.
The function was not renamed.

### 5.3 The operator session token is 12 hours, not "short-lived"

ADR 0016 condition 5(a) calls the operator credential "a short-lived, server-verified token".
`Settings.auth_session_ttl_s` defaults to 43,200 s (12 h), and the token is not checked against
the operator store again before expiry. The import CLI holds such a token in memory for its run.
README and ADR 0034 now say 12 hours. ADR 0016 was not edited.

### 5.4 Masterfiles never worked on native crawls

The plan listed "no masterfiles" as a limitation of imported jobs. `deliverables_routes.py`
refuses every native crawl id with 409 (around line 690); only Screaming Frog worker jobs with an
uploaded bundle are accepted. Build-log 0115 §4 recorded the same route behaviour. Imported jobs
lose nothing that native crawls have.

### 5.5 README and ADR 0034 described the UI work as not done

The backend commit `952c8a7` wrote README's status row and ADR 0034 "Explicitly not done" before
the UI commit `2c69c91` landed, so both said the badge, hidden Retry/Resume and `safeHref()` were
pending ("Until `safeHref()` lands, the URL audit is the only defence"). The scribe corrected both
in this change, before either was merged. The button the UI hides is labelled **Run again**, not
"Retry"; the API route is `retry`.

---

## 6. Explicitly not done

- **Not run against production.** Nothing has been pushed or deployed; migration 009 has not run
  on a real Postgres; the groundsguys job is still only local.
- **No "Copy to cloud" button in the local UI** (F10). It would make the local server call the
  cloud, which needs an ADR 0032 amendment.
- **No checkpoint, reconciliation or performance report travels in v1.** An imported job's
  `/checkpoint` is 404. Not carrying a checkpoint is also what keeps resume from consuming
  unvalidated data (F3).
- **Imported jobs cannot be retried or resumed** in the cloud (409, and hidden in the UI).
- **Import memory is not counted by the ADR 0031 crawl memory budget.** ~1.08 GiB measured for
  the 88.8 MiB result; ~1.5 GiB at the 128 MiB cap is extrapolated, not measured. Concurrency 1
  is the only bound.
- **F7, spreadsheet formula injection**, is not fixed: no neutralisation in
  `_workbook_response`, the CSV routes or `urls.xlsx`. Imports widen who can supply that text.
- **No role model** (F9). Any authenticated operator can import into their own org.
- **No job deep link** in the UI.
- **No component tests** for link safety in `DuplicateTable`, `GscIntegratedReport` or
  `VirtualizedTree`; only `RedirectTable`, `OrphanTable` and `safeHref` itself are tested.
- **CLAUDE.md §8 is not updated.** The proposed lines (import memory uncounted, figures above;
  imported jobs cannot be retried or resumed) are for the lead.
- **No end-to-end test over real HTTP.** The E2E in §1 ran in-process against a temporary
  `DiskJobStore`; `PostgresJobStore.import_terminal` is covered only through the `_FakeDB` fake
  from `tests/core/test_postgres_store.py`, never a real Postgres server.
- **`verify.ps1` still cannot gate a worktree.** Carried from 0138.

---

## 7. Files changed

From `git show --numstat 952c8a7`:

| File | Change |
| :--- | :--- |
| `.env.example` | +5 |
| `README.md` | +43 |
| `alembic/versions/0009_job_import_provenance.py` | new, 72 lines |
| `docs/ARCHITECTURE.md` | +48 / -1 |
| `docs/adr/0034-a-local-crawl-reaches-the-cloud-as-a-terminal-provenance-stamped-import.md` | new, 113 lines |
| `rankuno-ui/src/types/schema.ts` | +22 |
| `scripts/export_ui_contract.py` | +2 |
| `scripts/push_job_to_cloud.py` | new, 234 lines |
| `src/api/job_import_routes.py` | new, 217 lines |
| `src/api/server.py` | +27 |
| `src/api/worker_route_helpers.py` | +11 / -3 |
| `src/core/bounded_gzip.py` | new, 102 lines |
| `src/core/config.py` | +39 |
| `src/core/job_provenance.py` | new, 76 lines |
| `src/core/postgres_store.py` | +150 / -3 |
| `src/core/rate_limiter.py` | +34 |
| `src/core/state_store.py` | +159 |
| `src/integrations/rankuno_cloud_client.py` | new, 222 lines |
| `src/modules/seo/page_classifier/job_bundle.py` | new, 240 lines |
| `src/modules/seo/page_classifier/job_import.py` | new, 172 lines |
| `src/modules/seo/page_classifier/local_job_export.py` | new, 213 lines |
| `tests/api/test_job_import_routes.py` | new, 375 lines |
| `tests/core/test_bounded_gzip.py` | new, 59 lines |
| `tests/core/test_job_import_store.py` | new, 216 lines |
| `tests/core/test_postgres_schema.py` | +43 |
| `tests/core/test_postgres_store.py` | +60 / -1 |
| `tests/core/test_rate_limiter.py` | +18 |
| `tests/integrations/test_rankuno_cloud_client.py` | new, 227 lines |
| `tests/modules/seo/job_bundle_factory.py` | new, 125 lines |
| `tests/modules/seo/test_job_bundle.py` | new, 246 lines |
| `tests/modules/seo/test_job_import.py` | new, 121 lines |
| `tests/modules/seo/test_local_job_export.py` | new, 129 lines |
| `tests/scripts/test_push_job_to_cloud.py` | new, 204 lines |

From `git show --numstat 2c69c91`:

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/lib/safeHref.ts` | new, 42 lines |
| `rankuno-ui/src/lib/safeHref.test.ts` | new, 45 lines |
| `rankuno-ui/src/adapters/adapterInterface.ts` | +17 |
| `rankuno-ui/src/adapters/httpAdapter.ts` | +14 |
| `rankuno-ui/src/adapters/httpAdapter.test.ts` | +82 |
| `rankuno-ui/src/adapters/mockAdapter.ts` | +3 |
| `rankuno-ui/src/components/audit/DuplicateTable.tsx` | +23 / -13 |
| `rankuno-ui/src/components/audit/OrphanTable.tsx` | +11 / -5 |
| `rankuno-ui/src/components/audit/OrphanTable.test.tsx` | +23 |
| `rankuno-ui/src/components/audit/RedirectTable.tsx` | +24 / -13 |
| `rankuno-ui/src/components/audit/RedirectTable.test.tsx` | +38 |
| `rankuno-ui/src/components/crawl-results/GscIntegratedReport.tsx` | +14 / -9 |
| `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` | +40 / -3 |
| `rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx` | +97 |
| `rankuno-ui/src/components/jobs/jobs.css` | +5 |
| `rankuno-ui/src/components/tree/VirtualizedTree.tsx` | +9 / -4 |

This cycle (docs, uncommitted):

| File | Change |
| :--- | :--- |
| `docs/build-log/0140-a-local-crawl-copied-to-the-cloud.md` | this entry |
| `docs/build-log/README.md` | index row |
| `README.md` | status row: UI work moved from "Not yet" to landed; "Copying a finished local crawl" section: badge, hidden Resume/Run again, what is not copied |
| `docs/ARCHITECTURE.md` | ADR 0034 row: UI badge, hidden actions, `safeHref.ts`, link to this entry |
| `docs/adr/0034-…` | "Explicitly not done": UI items that shipped in `2c69c91` removed from the list (§5.5) |

CLAUDE.md is unchanged.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| lead | Push, deploy (migration 009 runs on boot), then run the real groundsguys import and record the result |
| lead | CLAUDE.md §8: import memory uncounted by ADR 0031 (~1.08 GiB measured at 88.8 MiB, ~1.5 GiB at 128 MiB extrapolated); imported jobs cannot be retried or resumed |
| `test-engineer` | Find the test that leaks `tmp*.tmp` containing `{}` into the cwd (§4.3) |
| `test-engineer` | `ScreamingFrogView` timeouts under a full vitest run (§4.4) |
| `ui-engineer` | Link-safety component tests for `DuplicateTable`, `GscIntegratedReport`, `VirtualizedTree` |
| `ui-engineer` | Job deep link |
| `security-auditor` / `feature-builder` | F7 formula neutralisation in workbook, CSV and `urls.xlsx` exports |
| lead | "Copy to cloud" button: needs an ADR 0032 amendment first (F10) |
| lead | Rename `org_scoped_or_404`, or accept the name (§5.2) |
