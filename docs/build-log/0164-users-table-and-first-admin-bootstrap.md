# Cycle 0164: Users table and first-admin bootstrap (multi-user auth, Phase 1)

- **Date**: 2026-10-20
- **Scope**: Phase 1 of multi-user auth. A `users` table (migration 014), a `UserStore` protocol with a Postgres implementation, and an admin bootstrap that creates the first admin in one guarded statement. No request authentication, login, sessions, sign-up, SMTP or Google sign-in.
- **Commit**: uncommitted at time of writing. The gate is red for reasons that predate this cycle, so the commit decision belongs to the user.
- **Quality gate**: RED on 11 tests that predate this cycle (10 golden snapshot tests and `test_an_abandoned_level_keeps_its_link_charge`); everything else green. Output in §1, reported by the implementing agent and not re-run by the scribe.

---

## 1. Gate results

### 1.1 Implementer's run (transcribed, not re-run)

The scribe did not re-run `verify.ps1` or any pytest command. The figures below are the feature-builder's, reported at the close of the cycle.

```
format   ruff format --check    : 750 files already formatted
lint     ruff check             : All checks passed
mypy     --strict               : passed, 198 files
verify.ps1 tests               : 11 failed, 5003 passed, 2 skipped   (exit 1)
coverage                       : 93.96%  (floor 85% met)
UI                             : 858 passed
targeted schema + user store   : pytest tests/core/test_postgres_schema.py tests/core/test_postgres_user_store.py -> 66 passed
tests/core                     : pytest tests/core -> 1019 passed, exit 0
```

The `postgres_user_store.py` coverage is 91%. The uncovered lines are the connect-failure path.

### 1.2 The 11 failures

Reported as pre-existing, and reproduced identically on a clean HEAD worktree:

- 10 golden snapshot tests on `$.tool.gsc.complete` under `tests/modules/seo/`.
- `test_an_abandoned_level_keeps_its_link_charge` (161 vs 113).

Two things this entry does not establish:

- The implementer cited build-log 0122 as the reference for these failures. That reference was **not verified**. The 0122 index row describes a PDF-button fix and mentions no golden snapshot or link charge. This entry does not rely on it.
- The cause of the golden failures is not established here. Build-log 0155 regenerated the snapshot after a weight calibration. Build-log 0156 and 0159 both recorded 10 golden-snapshot failures as pre-existing without naming a cause. The same 10 recur now.

### 1.3 A discrepancy this cycle did not resolve

Reading the committed HEAD statically, `tests/core/test_postgres_schema.py` asserts `script.get_heads() == ["012"]` (test `test_single_head_is_012_and_follows_011`). Committed migration `0013_job_gsc_queries_payload.py` has `revision = "013"` and `down_revision = "012"`, so the head at HEAD is `013`. By that reading the test fails at HEAD. The implementer's list of 11 HEAD failures does not include it.

Either the implementer's HEAD reproduction did not run this test, or the static reading is wrong. This cycle did not run the test at HEAD to settle it. The fix to the assertion is in §5. A reader should run `pytest tests/core/test_postgres_schema.py -k single_head` on a clean HEAD worktree to settle which is right.

### 1.4 Drift check

Run by the scribe after the documentation changes, with `.\.venv\Scripts\python.exe scripts\drift_check.py`:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 267 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
EXIT=0
```

---

## 2. What landed

### 2.1 `alembic/versions/0014_users.py` (revision `014`, down `013`)

Creates the `users` table:

- `role` with `CHECK (role IN ('admin', 'user'))`.
- `email` stored lower-cased. `CHECK (email = lower(email))` and `UNIQUE (email)`. The CHECK is what makes the UNIQUE mean case-insensitive uniqueness.
- `google_sub` nullable, `UNIQUE`. Google sign-in is not built, so the column is only a placeholder.
- `password_hash` nullable. The Google-only user has no password.
- `session_version INTEGER NOT NULL DEFAULT 0`, with `CHECK (session_version >= 0)`. This is the revocation counter that ADR 0040 relies on.
- `must_change_password`, `is_active`, `created_at`.
- A partial unique index `ux_users_single_admin ON users (role) WHERE role = 'admin'`. It limits the table to one admin row.

Downgrade drops the index, then the table.

Verification is limited to offline SQL. The schema tests render `upgrade` and `downgrade` with `sql=True` and check the emitted DDL. **The migration has not been executed against Postgres.**

Because `Dockerfile` CMD runs `alembic upgrade head` before uvicorn (build-log 0148), this migration runs on the next deploy that carries it. Merging this cycle is therefore a production schema change, not a code-only change.

### 2.2 `src/core/user_store.py` (198 lines): the protocol and the rules

- `UserRole`: `admin`, `user`. Lowercase, following ruling 3 in CLAUDE.md §7.
- `AdminBootstrapOutcome`: `CREATED`, `NOT_CREATED`, `NOT_CONFIGURED`.
- `UserRecord`: a `StrictModel`. `password_hash` is a `SecretStr`, so it does not render in a repr.
- `UserStore` protocol: `bootstrap_admin(email, initial_password)` and `get_by_email(email)`.
- `normalize_admin_email()`: strips and lower-cases the address, refuses anything that is not `local@domain.tld`. The refusal message does not echo the input, because the address is personal data.
- `validate_initial_password()`: at least 12 characters, and not on a known-weak list. The refusal names the rule and never the value.
- `bootstrap_admin_from_settings()`: reads `ADMIN_EMAIL` and `ADMIN_INITIAL_PASSWORD` from `Settings`. Logs a warning on every call while the password is set, whatever the outcome, and names the fact only.

### 2.3 `src/core/postgres_user_store.py` (199 lines): the Postgres store

- `bootstrap_admin` runs one statement:
  `INSERT ... SELECT ... WHERE NOT EXISTS (admin row) ON CONFLICT DO NOTHING RETURNING id`.
  The existence check and the insert are one statement, not a read followed by a write.
- Validation and password hashing run before any statement, so a refused value costs no database round trip. The password is never stored in clear.
- Each call opens a fresh connection and sits behind the existing `CircuitBreaker`.
- Database errors are logged by exception class and SQLSTATE only. The message is not logged, because a driver error can quote the row.
- An open breaker, a refused connection or a failed statement raises `UserStoreUnavailableError`. There is no disk fallback. Callers fail closed.
- `get_by_email` lower-cases its input before the lookup.

### 2.4 `src/core/config.py` (+16 lines) and `src/core/errors.py` (one class)

- `config.py`: `admin_email: str | None` and `admin_initial_password: SecretStr | None`. Neither is read anywhere outside `bootstrap_admin_from_settings()` yet.
- `errors.py`: `UserStoreUnavailableError`, with one fixed message. Same reason as the GA4 store's error: a database message can quote a row, and the row holds an email address and a password hash.

---

## 3. Design decisions

1. **Bootstrap is one guarded statement, not check-then-insert.** A check followed by an insert lets two starting processes both see "no admin" and both insert. The `WHERE NOT EXISTS` and the `ON CONFLICT DO NOTHING` (no conflict target, so it also covers the partial index and the email `UNIQUE`) make the decision in the database. **The concurrency claim is reasoned, not measured.** The tests use an in-memory fake that models the partial index and the email UNIQUE. No test ran against real Postgres under concurrent starts.
2. **`NOT_CREATED` does not say why.** "An admin already exists" and "that email is already a non-admin user" return the same outcome. Telling them apart would need a second query, and the log line must not reveal which row exists.
3. **A new migration (014) rather than an edit to 013.** Migrations already applied in production must not change.
4. **Fail closed, no disk fallback.** Users are an authentication input. Falling back to a local file would mean a store outage can admit a user the database has since disabled.
5. **Password hashed before the INSERT, validated before the hash.** A weak value fails with no network call and no hashing cost.

---

## 4. Bugs found and fixed

- **Stale head assertion.** `test_single_head_is_012_and_follows_011` asserted that the head was `012`. It is renamed `test_single_head_is_014_and_follows_013` and asserts the chain `014 -> 013 -> 012 -> 011`. The defect was in the test, not in the migration chain. Recorded as a correction in §5 because it was a stale assertion, not a new defect.
- The implementer reported no further defects in the new code.

**Limit of this section.** The store tests run against a fake. A SQL defect that the fake does not model would not have been found by this cycle's tests. The first real `alembic upgrade head` and the first real bootstrap are the actual tests of the SQL.

---

## 5. Corrections

- **Build-log 0162 and the head test.** Build-log 0162 recorded migration 012 as a single head, which was true at `6d9d6f3`. Migration 013 (`0f90c5a`, "persist the saved Search Console query fetch on the job store") then made 013 the head, and the head assertion in `tests/core/test_postgres_schema.py` was not updated. This is corrected in the test, not by editing 0162. The static reading in §1.3 also conflicts with build-log 0161's `exit 0` for the same suite. That conflict is not resolved here.
- **Numbering.** The cycle brief said the highest existing entry was 0160. The directory holds entries through 0163. This entry takes 0164, following the rule in `docs/build-log/README.md` to take the highest number on disk plus one.

---

## 6. Explicitly not done

- **Migration not executed on Postgres.** Only offline SQL was rendered and checked. Partial-index behaviour under real concurrency is not proven.
- **Bootstrap not wired into app startup.** `bootstrap_admin_from_settings()` has no caller. Nothing creates the first admin yet.
- **No request authentication, login, sessions, sign-up, SMTP or Google sign-in.** ADR 0040 describes the session behaviour; none of it is implemented.
- **ADR 0040 and ADR 0041 are Proposed.** Neither is in force until a human accepts it. ADR 0041 proposes amending CLAUDE.md §1 rule 5 to permit one class of outbound traffic (SMTP) outside `BaseAPIClient`. That amendment is **not** in CLAUDE.md and is not in force.
- **ADR 0016 is not edited.** ADR 0040 says it amends ADR 0016 for user sessions only. That amendment is recorded in ADR 0040, not in ADR 0016.
- **No refactor of `src/core/config.py`.** It is 1,504 lines, which breaches the 400-line rule in CLAUDE.md §9. This cycle added 16 lines to it and did not split it.
- **No non-admin user path.** No code inserts a user other than the bootstrap admin, and nothing populates `google_sub`.
- **Rankuno logo asset not part of this cycle.** `rankuno-ui/public/rankuno-logo.png` is untracked in the working tree and belongs to another session.

---

## 7. Files changed

Created by this cycle:

- `alembic/versions/0014_users.py`
- `src/core/user_store.py`
- `src/core/postgres_user_store.py`
- `tests/core/test_postgres_user_store.py`
- `docs/adr/0040-user-sessions-check-session-version-and-active-per-request.md` (Proposed)
- `docs/adr/0041-smtp-is-not-http-a-durable-daily-cap-and-queued-dispatch.md` (Proposed)
- `docs/build-log/0164-users-table-and-first-admin-bootstrap.md` (this entry)

Changed by this cycle:

- `src/core/config.py` (+16 lines)
- `src/core/errors.py` (one class added)
- `tests/core/test_postgres_schema.py` (head assertion 013 to 014; new `TestUsersMigration`)
- `README.md` and `docs/ARCHITECTURE.md` (the users table and the two new store modules)
- `docs/build-log/README.md` (index row)

---

## 8. Follow-ups

1. Run the `test_single_head` test on a clean HEAD worktree to settle §1.3.
2. Run the migration against a real Postgres, both directions, before any deploy that carries it.
3. Test the bootstrap's `ON CONFLICT` behaviour under two concurrent starts against real Postgres.
4. Wire `bootstrap_admin_from_settings()` into app startup, and decide whether the startup warning is enough to get `ADMIN_INITIAL_PASSWORD` removed.
5. A human decision on ADR 0040 and ADR 0041, and on the CLAUDE.md §1 rule 5 amendment.
6. Find the cause of the 10 golden snapshot failures and record it. Three entries (0155, 0156, 0159) have recorded them without a cause.
