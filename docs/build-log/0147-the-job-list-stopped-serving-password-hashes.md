# Cycle 0147: The job list stopped serving password hashes

- **Date**: 2026-10-08
- **Scope**: SECURITY FIX, step 1 of 7 of the approved per-job delete-password plan. Stop returning `JobRecord.password_hash` to clients.
- **Commit**: (uncommitted at time of writing)
- **Quality gate**: `verify.ps1` ended "ALL GATES PASSED", exit 0 (implementer's run; not re-executed by the scribe). UI 53 files / 695 tests. The Python test count and coverage percentage were NOT captured (only the tail of the output was kept, and `tests/api -q --no-cov` printed dots with no summary line), so none is quoted here.

## 1. Why this cycle exists

The user asked for "a password to delete a job, set at the time of creation of the job" and could not find the option on the New crawl form. Investigation found the feature half-shipped by cycles 0145/0146: hashing (`src/core/auth.py`, `pbkdf2_sha256$210000$salt$digest`), create-path hashing in `server.py`, a DELETE route that enforces it, and `DeleteJobModal`. There is no field on `LiveCrawlModal.tsx`; `deletion_password` is hard-coded null in `adapterInterface.ts`.

A read-only security audit returned FAIL. Findings:

| ID | Severity | Finding |
| :--- | :--- | :--- |
| F1 | HIGH | `password_hash` was returned to every client by routes declaring `response_model=JobRecord`: GET /jobs, GET /jobs/{id}, POST /jobs/{id}/reparse, POST /jobs/{id}/cancel, GET /deliverables, GET /deliverables/{id}. Anyone in the org, or a stolen session token, could copy the hash and crack it offline with no rate limit (minimum password length was 1). |
| F2 | HIGH | `PostgresJobStore` never persists `password_hash` (INSERT, `_JOB_COLUMNS`, `_row_to_job_record` omit it; no migration). On Postgres every job is undeletable. |
| other | - | Rate limiter runs before authentication, keyed by job id only (an unauthenticated caller can lock an owner out); running jobs are deletable; `JobStoreUnavailableError` returns 500; retry/resume/reparse/SF/import jobs get no hash; no operator override; plaintext `deletion_password` is a plain `str`; a bundle could carry it; 422 bodies echo input. |

Decisions by the user: password REQUIRED, min 8 chars; Run again/Resume/Reparse inherit the parent's hash; old/imported/Screaming Frog jobs deletable only through an audited operator-only action; operator-only audited delete for forgotten passwords; only terminal jobs deletable; remove `deletion_password` from the shared `PageClassificationInput` (create-only model); Postgres breaker open means create is refused with 503; lockout keyed per (operator, job); the operator delete script ships in the same deploy as the stricter delete route. Work starts with F1 because it is the only finding fixable in isolation.

## 2. What landed

- `src/api/job_view.py` (72 lines, new): `JobView(StrictModel)` carries every `JobRecord` field except `password_hash`, plus `has_delete_password: bool`. `JobView.from_record()` and a `job_views()` list helper.
- `src/api/server.py`: GET /jobs, GET /jobs/{id}, reparse and cancel now declare `response_model` `JobView` / `list[JobView]`.
- `src/api/deliverables_routes.py`: GET /deliverables and GET /deliverables/{id} likewise.
- `rankuno-ui/src/adapters/httpAdapter.ts`: wire interface mirrors `JobView`, with optional `has_delete_password`. Nothing in `rankuno-ui/src` reads `password_hash`.
- `tests/api/test_job_view.py` (new).
- `docs/ARCHITECTURE.md`: `job_view.py` added to the `src/api/` tree.

`JobRecord` is deliberately unchanged. Marking the field `Field(exclude=True)` was rejected: `DiskJobStore` serialises the record with `model_dump`, so that would silently stop persisting the hash and make every disk job undeletable.

A re-grep of `response_model` / `JobRecord` across `src/api` found no other leaking route. Retry, resume and crawl-activity return `JobAccepted` / `CrawlActivityView`; import returns `JobImportAccepted`.

## 3. Tests

| Test | Asserts |
| :--- | :--- |
| `test_job_view_has_no_password_hash_field` | `JobView` has no `password_hash` field |
| `test_job_view_has_delete_password_true_when_hash_set` / `_false_when_none` | flag mirrors the hash |
| `test_every_jobrecord_route_omits_password_hash` | walks `app.routes` for any `response_model` that is or contains `JobRecord`; calls the six routes and asserts `password_hash` and the `pbkdf2_sha256$` prefix are absent from `response.text` |
| `test_disk_store_still_persists_hash` | the disk store round-trip keeps the hash |
| field-coverage test | every `JobRecord` field except `password_hash` exists on `JobView` |
| list-order test | `job_views()` preserves order |

## 4. Bugs found and fixed

- F1 itself: the hash leak through six routes (above). Fixed by `JobView`.
- Design trap avoided: `Field(exclude=True)` on `JobRecord` would have fixed the leak and broken persistence in the same stroke. The disk-persistence test exists to pin that.
- No test was found wrong and no specification bug was found in this step.

## 5. Corrections

- Build-log 0145 says password is "optional at creation (backward compatible)" and lists its acceptance criteria as met. The audit shows the feature served its own hash to every client, so the criteria were not met in the security sense. Superseded by the user's decision: password required, min 8.
- Build-log 0146 presents the feature as complete. It is not: the UI cannot set a password.
- Docs note, flagged and NOT investigated: `CLAUDE.md` section 8 says idempotency keys are "not implemented anywhere", but `server.py` contains `_check_idempotency_key` and `_store_idempotency_key` in `create_job`. One of the two is wrong; a later cycle should settle it.

## 6. Explicitly not done

Steps 2-7 of the plan are not started. Do not read the user-facing feature as working.

1. Postgres persistence and migration 0010. On Postgres jobs are STILL undeletable and the hash is still never stored there (F2 is open).
2. Required, min-8 `SecretStr` validation and the create-only model; removing `deletion_password` from `PageClassificationInput`.
3. Stripping input echo from 422 bodies; stripping `deletion_password` from bundles.
4. Authentication before the rate limiter, per-(operator, job) keys, persistent lockout (migration 0011), terminal-only delete, 503 mapping for `JobStoreUnavailableError`, 503 on create when the Postgres breaker is open.
5. Inheriting the parent's hash on Run again, Resume, Reparse and Screaming Frog merge.
6. The UI password field on `LiveCrawlModal` (the user still cannot set a password) and `has_delete_password` wiring in the UI mapping.
7. The operator-only audited delete script, and the ADR for the whole feature (no ADR number is assigned yet).

Consequences to carry:

- Hashes already served must be treated as exposed. Rotating them needs the operator path, which is not built. The leak is closed only once this change is deployed.
- The guard is route-by-route. A future route returning a `JobRecord` without a declared `response_model` would leak again, and the walk test would not catch it.
- `JobView` is hand-written and not in the generated UI contract (`npm run contract` reports up to date). Adding it to `scripts/export_ui_contract.py` is an optional follow-up.
- Pre-existing, not touched: `fallback_recovery.py` discards disk-fallback jobs after logging.

## 7. Gate output

Implementer's report, not re-run by the scribe: `verify.ps1` "ALL GATES PASSED", exit 0; UI 53 files / 695 tests; the UI stage did not hit the known `ScreamingFrogView` flake. Python summary and coverage: not captured.
