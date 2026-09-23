# Cycle 0102: A click that carries its own auth

- **Date**: 2026-09-23
- **Scope**: One-click `.xlsx` export of a job's full URL list from the
  job-row `...` menu — `GET /jobs/{id}/urls.xlsx`, a new optional adapter
  method, and a new "Download URLs" menu entry. No panel opens; the click is
  the whole flow.
- **Commit**: uncommitted at time of writing. `git status` shows the seven
  touched files (`src/api/server.py`, `tests/api/test_server.py`,
  `tests/api/test_adr0016_job_scoping.py`, `rankuno-ui/src/adapters/
  adapterInterface.ts`, `rankuno-ui/src/adapters/httpAdapter.ts`,
  `rankuno-ui/src/components/jobs/CrawlJobsView.tsx`, `rankuno-ui/src/
  components/jobs/CrawlJobsView.test.tsx`) as modified but not staged,
  alongside three files from an unrelated, already-broken Postgres/Redis/
  Celery working-tree state — see §1 and §5.
- **Quality gate**: this cycle's own files are clean in isolation — ruff
  format/check and `mypy --strict` pass on `src/api/server.py`; 218/218 pass
  across `tests/api/test_adr0016_job_scoping.py` +
  `tests/api/test_performance_endpoints.py` + `tests/api/test_server.py` run
  together, exit 0; 390/390 UI tests pass, `tsc --noEmit` clean. The
  whole-repo `verify.ps1` gate is **RED**, independently reproduced —
  `1 failed, 3024 passed, 2 skipped` in 389.73s, 93.63% total coverage, plus
  1 pre-existing format finding, 29 pre-existing lint errors, 16
  pre-existing type errors — all confirmed on files this cycle did not
  touch (§1.3/§1.5), none of them this cycle's own `server.py`/`reports.py`.

---

## 1. Gate results

### 1.1 This cycle's files, in isolation (independently re-run, not copied
from the implementer's report)

```
$ .venv/Scripts/python.exe -m pytest tests/api/test_server.py -k "urls or xlsx" -q
.....                                                                    [100%]
5 passed

$ .venv/Scripts/python.exe -m pytest tests/api/test_adr0016_job_scoping.py -v
collected 37 items
tests\api\test_adr0016_job_scoping.py .................................. [ 91%]
...                                                                      [100%]
======================= 37 passed, 1 warning in 19.78s ========================

$ .venv/Scripts/python.exe -m pytest tests/api/test_adr0016_job_scoping.py \
    tests/api/test_performance_endpoints.py tests/api/test_server.py -q
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
exit code 0   (37 + 29 + 152 = 218)

$ .venv/Scripts/python.exe -m ruff format --check src/api/server.py tests/api/test_server.py tests/api/test_adr0016_job_scoping.py
3 files already formatted

$ .venv/Scripts/python.exe -m ruff check src/api/server.py tests/api/test_server.py tests/api/test_adr0016_job_scoping.py
All checks passed!

$ .venv/Scripts/python.exe -m mypy --strict src/api/server.py
Success: no issues found in 1 source file

$ .venv/Scripts/python.exe -m pytest tests/api/test_server.py tests/api/test_adr0016_job_scoping.py \
    --cov=src.modules.seo.page_classifier.reports --cov=src.api.server --cov-report=term-missing -q
Name                                         Stmts   Miss Branch BrPart  Cover
src\api\server.py                             1045    316    180     16    67%   (restricted to
                                                                                   these two test files only)
src\modules\seo\page_classifier\reports.py     103     11     34      5    85%
```

`server.py`'s 67% above is an artefact of running only two test files
against it — `tests/api/` as a whole covers far more of its routes. Run
against the full `tests/api/` directory:

```
$ .venv/Scripts/python.exe -m pytest tests/api/ --cov=src.api.server --cov-report=term-missing -q
Name                Stmts   Miss Branch BrPart  Cover
src\api\server.py    1045     57    180     20    94%
TOTAL                1045     57    180     20    94%
Required test coverage of 85.0% reached. Total coverage: 93.55%
```

`reports.py`'s 85% (0% before this cycle — this route is its first
caller, confirmed: `grep -rn "MasterURLReport" src tests` before this
change returned only its own definition) matches the implementer's figure
exactly.

UI, independently re-run:

```
$ npx vitest run src/components/jobs/CrawlJobsView.test.tsx \
    src/components/screaming-frog/WorkerJobsPanel.test.tsx src/adapters/httpAdapter.test.ts
 Test Files  3 passed (3)
      Tests  26 passed (26)
```

```
$ npx vitest run   (full suite)
 Test Files  37 passed (37)
      Tests  390 passed (390)
```

```
$ npx tsc --noEmit -p tsconfig.json
exit 0
```

### 1.2 Correction to the implementer's own number (see §5)

The implementer's report claimed `Test Files 3 passed (3), Tests 22 passed
(22)` for the same three-file targeted run. Independently re-run twice
(once alone, once as part of the full suite) and both times it is **26**,
not 22 — matched exactly by counting `✓` lines in the raw vitest output.
Recorded as a correction, not trusted from the report; see §5.

### 1.3 Whole-repo `verify.ps1`, independently re-run, verbatim tail

```
=== Format ===
unformatted: File would be reformatted
   --> docs\build-log\0101-a-percentage-is-no-longer-invented.md:163:17
    | (reformats the MODELS tuple onto one element per line)
1 file would be reformatted, 433 files already formatted
FAILED: Format

=== Lint ===
(29 errors total, all in:)
  scripts\chaos_test.py            — 9 x S101 (assert in a non-test script), 1 x B007
  scripts\register_worker.py       — 1 x E402
  src\workers\job_executor.py      — 2 x D417, 2 x ANN001, 1 x B904, 1 x F841
  tests\core\test_redis_config.py  — 2 x S101/S105/S106-family
  tests\core\test_redis_token_bucket.py — RET503, ANN202, SIM222
  tests\integrations\test_gsc_token_manager.py — 2 x SIM105, 3 x S105
Found 29 errors.
No fixes available (6 hidden fixes can be enabled with the `--unsafe-fixes` option).
FAILED: Lint

=== Type check ===
src\core\state_store.py:871: error: Incompatible types in assignment [assignment]
src\core\postgres_worker_store.py:52: error: Cannot find implementation or library stub for module named "psycopg"  [import-not-found]
src\core\postgres_worker_dispatch_store.py:62: error: same [import-not-found]
src\core\postgres_store.py:22: error: same [import-not-found]
src\core\redis_config.py:67: error: Unused "type: ignore" comment  [unused-ignore]
src\core\rate_limiter.py:546: error: Unused "type: ignore" comment  [unused-ignore]
src\core\rate_limiter.py:575: error: Unused "type: ignore" comment  [unused-ignore]
src\core\celery_config.py:11: error: missing library stubs or py.typed marker  [import-untyped]
src\core\celery_config.py:118: error: Missing type arguments for generic type "dict"  [type-arg]
src\core\celery_config.py:143: error: same  [type-arg]
src\workers\job_executor.py:20,21,100,101: error: untyped-decorator / no-untyped-def / type-arg (x6)
Found 16 errors in 8 files (checked 119 source files)
FAILED: Type check

=== Tests ===
...
src\api\server.py                                               1045     57    180     20    94%   ...
src\modules\seo\page_classifier\reports.py                       103     11     34      5    85%   ...
TOTAL                                                          12211    663   2698    216    94%
50 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 93.63%
=========================== short test summary info ===========================
FAILED tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success
1 failed, 3024 passed, 2 skipped, 1 warning in 389.73s (0:06:29)
FAILED: Tests

=== UI Component Tests ===
 Test Files  37 passed (37)
      Tests  390 passed (390)
PASSED: UI Component Tests

VERIFICATION FAILED: Format, Lint, Type check, Tests
Do not report this task as complete.
```

This run's aggregate summary line printed cleanly, unlike build-log
0098/0100's session, where the same `verify.ps1` invocation never printed
its own final tally due to an output-buffering artifact those entries
recorded rather than guessed past. No correction needed here — this is a
different session's run producing a complete line, not a contradiction of
the earlier entries' honest "did not print" report.

`src/api/server.py` (this cycle's touched file) sits at 94% and
`src/modules/seo/page_classifier/reports.py` (0% before this cycle) at 85%
inside the full 3,024-test run — both numbers match §1.1's isolated
figures exactly.

### 1.4 The one test failure, reproduced in isolation

```
$ .venv/Scripts/python.exe -m pytest tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success -q
FAILED tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success
src.core.errors.GscAuthenticationError: Integration 'google.search_console' failed:
Authentication failed: Token endpoint unreachable and stale token expired
```

Matches build-log 0100 §"handoffs" — the circuit-breaker half-open logic
gap flagged there, not fixed here, still present.

### 1.5 Isolation evidence beyond grep — file modification times

`git status` shows `alembic/env.py`, `api.err`, and `src/core/
postgres_config.py` modified but not part of this cycle. Confirmed two
ways, not just by reading the diff content:

- `git diff --stat` on those three files shows Postgres/Redis/Celery
  content (env-var handling in `postgres_config.py`, an Alembic env tweak,
  and 1,838 lines added to a log file), nothing touching `server.py`,
  `reports.py`, or any UI file.
- Filesystem mtimes (`ls -la --time-style=full-iso`) place every file in the
  reported failure set at least a day, and in most cases well over a week,
  before this session's own edits:

  | File | mtime |
  | :--- | :--- |
  | `alembic/env.py` | 2026-09-21 16:38 |
  | `src/core/postgres_config.py` | 2026-09-21 16:38 |
  | `api.err` | 2026-09-17 18:52 |
  | `scripts/chaos_test.py` | 2026-09-09 19:38 |
  | `scripts/register_worker.py` | 2026-09-22 13:39 |
  | `src/core/postgres_worker_dispatch_store.py` | 2026-09-22 13:39 |
  | `src/core/postgres_worker_store.py` | 2026-09-21 18:05 |
  | `src/core/celery_config.py` | 2026-09-18 11:22 |
  | `src/core/redis_config.py` | 2026-09-18 11:21 |
  | `src/core/rate_limiter.py` | 2026-09-09 19:14 |
  | `src/core/state_store.py` | 2026-09-12 00:21 |
  | `src/workers/job_executor.py` | 2026-09-09 19:29 |
  | `tests/core/test_redis_config.py` | 2026-09-09 19:11 |
  | `tests/core/test_redis_token_bucket.py` | 2026-09-09 19:29 |
  | `tests/integrations/test_gsc_token_manager.py` | 2026-09-13 01:56 |
  | `src/api/server.py` (this cycle) | **2026-09-23 15:10** |
  | `tests/api/test_server.py` (this cycle) | **2026-09-23 15:22** |

  Every failing/pre-existing-drift file predates this cycle's own edits by
  at least several hours (`register_worker.py`, same calendar day but
  13:39 vs. 15:10+) and up to two weeks. This is stronger evidence than a
  content grep alone: it rules out a same-session edit to those files that
  happened to leave no lexical trace. It does **not** by itself prove the
  Postgres/Redis/Celery breakage was present before *today's own first
  commit* (`00abf65`, 2026-09-23, landed before this cycle started) — the
  `git status`-visible files are uncommitted working-tree edits, and git
  does not record when an uncommitted edit was made, only the filesystem
  mtime, which this session did not create. Reported as strong but not
  absolute evidence, per the brief's own instruction not to guess past what
  the data shows.

## 2. What landed

- **`src/api/server.py`** — `GET {API_PREFIX}/jobs/{job_id}/urls.xlsx`
  (`download_urls_workbook`), same shape as `opportunities.xlsx`/
  `reconciliation.xlsx`: `require_principal` + `_owned_job(job_id,
  principal.org_id, "result")` (ADR 0016), `record.has_result` ->
  409, `PageClassificationOutput.model_validate(stored)` -> 409 on a
  pre-contract result, `MasterURLReport(crawl).generate()` streamed back as
  a `Response` with `Content-Disposition: attachment;
  filename="urls-{job_id[:8]}-{stamp}.xlsx"`. Confirmed by direct diff read
  (§ below) — the route is inserted immediately after the `_owned_job`
  helper, matching the report.
- **`src/modules/seo/page_classifier/reports.py`** — no code change.
  `MasterURLReport` (openpyxl, 3 sheets: All URLs, By Indexability, By HTTP
  Status) existed with zero callers anywhere in the codebase before this
  cycle — confirmed directly: `git log --all -- .../reports.py` shows it
  landed in a much earlier cycle (`30f9284`/`e71e506`), and `grep -rn
  "MasterURLReport" src tests` before this change matched only the class's
  own definition inside `reports.py` itself. This route is its first
  exerciser, taking coverage on that file from 0% to 85%.
- **`rankuno-ui/src/adapters/adapterInterface.ts`** —
  `downloadUrlList?(jobId): Promise<Blob>`, optional like
  `reconcileScreamingFrog`, for the same reason: UI fixtures have no server
  behind them to build a real workbook, so the menu item is absent, not
  present-and-failing, when unset.
- **`rankuno-ui/src/adapters/httpAdapter.ts`** — implementation, bypassing
  the JSON `request()` helper for a binary body, same pattern as
  `downloadWorkerBundle`.
- **`rankuno-ui/src/components/jobs/CrawlJobsView.tsx`** — a
  `downloadUrls(row)` handler (fetch blob -> `saveBlob` from
  `lib/download.ts`, `message.error` on failure) and a "Download URLs" menu
  entry gated on `canDownloadUrls && ready` — `ready` is the same
  `status === "succeeded" || status === "partial"` guard already used for
  Search Console/Cross-check. The click fetches and saves; no panel opens.
  Confirmed by direct diff read: the new menu item's `onClick` goes
  straight to `onDownloadUrls`, with no intervening `setState` that would
  open a dialog.

## 3. Design decisions

- **Blob-fetch-then-save, not `<a href>`.** `urls.xlsx` is bearer-guarded
  (ADR 0016); a plain anchor the browser navigates to carries no
  `Authorization` header. `reconciliation.xlsx` gets away with an `<a
  href>` only because the UI only ever renders that link inside an
  already-open panel that has already authenticated the fetch behind it —
  a closed dropdown has no such panel, so this route reuses the
  `downloadWorkerBundle`/`saveBlob` shape instead. This is the one
  consequential decision in the cycle; see §4 of this entry for why no ADR
  is warranted for it anyway.
- **No new sheet, no column change to `MasterURLReport`.** The brief's
  explicit do-not. Confirmed: `git diff -- src/modules/seo/page_classifier/
  reports.py` is empty for this cycle.

## 4. Bugs found and fixed

None introduced or fixed in this cycle's own code — it is additive wiring
of an already-shipped report generator to a new route. Two pre-existing
defects in `reports.py` were found (by the implementer) and are recorded,
not fixed, as out of scope:

- `_extract_status_code()` always returns `None` — confirmed by reading the
  method directly: "the current data model doesn't store HTTP status
  explicitly," so `By HTTP Status` sheet grouping is nominal only.
- The "All URLs" sheet's "HTTP Status" column is actually populated with
  `page.final_url`, not a status code — confirmed at reports.py line 74,
  with an inline comment ("Will be empty for most; actual status comes from
  HTTP response") that itself does not match what the column header claims.
  A genuinely mislabeled column, pre-existing, not introduced this cycle.

## 5. Corrections

- The implementer's report quoted the whole-repo coverage line as `TOTAL
  12211 666 2698 216 94%` (666 missed statements). This independent run's
  same line is `TOTAL 12211 663 2698 216 94%` — 663, not 666, a
  3-statement difference that does not move the rounded 94%/93.63% headline
  figure. Not investigated further; recorded as a small discrepancy rather
  than silently repeated as an exact match.
- The implementer's report claimed 22 passing tests for the targeted
  three-file vitest run (`CrawlJobsView.test.tsx` +
  `WorkerJobsPanel.test.tsx` + `httpAdapter.test.ts`). Independently
  re-run twice, it is **26**, not 22 — both a solo run and as part of the
  390-test full suite agree on 26. The full-suite total the implementer
  reported (390) is correct and independently reproduced; only the
  three-file subset figure was wrong. Left uninvestigated further beyond
  the recount itself — plausibly a stale number carried from an earlier
  point in the implementer's own session before the last test was added,
  but that is a guess, not a verified cause.

## 6. Explicitly not done

- **The whole-repo `verify.ps1` gate is not green**, and this cycle does
  not fix any of the causes (§1.3/§1.5): the Postgres/Redis/Celery
  migration's 16 mypy errors and most of the 29 lint errors, the
  `chaos_test.py`/`register_worker.py` script-lint findings, the
  `test_gsc_token_manager.py` circuit-breaker half-open gap, and
  `docs/build-log/0101-*.md`'s own ruff-format drift (which CLAUDE.md
  forbids hand-editing to fix — old build-log prose is never revised).
  Raised as handoff #1 below.
- **`reports.py`'s two pre-existing defects (§4) are not fixed.** Recording
  them accurately, per this cycle's brief, without expanding scope into an
  unrelated bug-fix.
- **`MasterURLReport.generate()`'s performance at scale is not load-tested.**
  It builds a normal (non-`write_only`) openpyxl workbook with per-cell
  `Font`/`Fill` styling and a full-column rescan in `_auto_fit_columns`,
  unlike `server.py`'s own `_workbook_response` helper, which is
  deliberately `write_only` "because its sheets run to tens of thousands of
  rows." Unverified at the 500k-URL end of ADR 0001's stated scale target.
  Raised as handoff #2 below.

## 7. Files changed

```
rankuno-ui/src/adapters/adapterInterface.ts        | 10 +
rankuno-ui/src/adapters/httpAdapter.ts             | 26 +
rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx | 84 ++-
rankuno-ui/src/components/jobs/CrawlJobsView.tsx   | 56 ++-
src/api/server.py                                  | 57 +
tests/api/test_adr0016_job_scoping.py              | 10 +
tests/api/test_server.py                           | 94 ++-
7 files changed, 329 insertions(+), 8 deletions(-)
```

Plus, from this docs-scribe pass: this entry, its `docs/build-log/
README.md` index row, a new `reports.py` line in `docs/ARCHITECTURE.md`'s
`page_classifier/` module tree (it had never been documented there, cycle
or no cycle, before this one gave it a real caller), a line noting `GET
/jobs/{id}/urls.xlsx` in the same file's `api/server.py` entry, and a
paragraph in `README.md`'s "The local API and the React UI" section.

## 8. Follow-ups (handoffs raised, neither resolved here)

1. **Non-blocking / build-CI hygiene.** The whole-repo `verify.ps1` gate is
   red independent of any single task (§1.3/§1.5). Target: whoever owns the
   Postgres/Redis/Celery migration. Do not hand-edit `docs/build-log/
   0101-*.md`'s prose to fix its format drift — CLAUDE.md forbids revising
   old build-log text; if the format drift itself needs fixing, that is a
   `ruff format` pass on that one file's embedded fence, not a prose edit,
   and still belongs to whoever owns that migration's cleanup, not this
   cycle.
2. **Optional / performance.** `MasterURLReport.generate()` is not
   `write_only` and does a full-column rescan per sheet; not load-tested at
   the 500k-URL end of ADR 0001. `_extract_status_code()` always returns
   `None` and the "All URLs" sheet's "HTTP Status" header is populated with
   `page.final_url` — both pre-existing, described in §4, not fixed.

## 9. ADR

None. This cycle wires an already-shipped, already-designed report
generator (`MasterURLReport`, shipped with a prior cycle, zero callers
until now) to a new route using an existing pattern
(`downloadWorkerBundle`/`saveBlob`) already established for a
bearer-guarded, no-open-panel download. No new architectural boundary, risk
class, schema, or cross-module dependency is introduced. The one real
design choice (blob-fetch vs. `<a href>`, §3) is a consequence of ADR 0016
already in force, not a new decision needing its own record.
