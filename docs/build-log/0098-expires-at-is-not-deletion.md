# Cycle 0098: `expires_at` is not deletion

- **Date**: 2026-09-16
- **Scope**: Implement ADR 0015 (Cloud + Local Desktop Worker Architecture for
  Screaming Frog Dispatch) on top of ADR 0016's session-token auth: worker
  identity, the dual approval gate (cloud-side preview/confirm plus a
  worker-independently-verified signed dispatch assignment), at-rest bundle
  encryption, and untrusted-upload validation.
- **Commit**: `bf02a93` — clean fast-forward directly on top of `571cdd6`
  (verified: `git merge-base --is-ancestor 571cdd6 bf02a93` succeeds, and
  `git log --oneline 571cdd6..bf02a93` shows exactly one commit).
- **Quality gate**: Targeted — 130 passed, 0 failed (independently re-run,
  exit 0). Coverage on this cycle's 12 new/touched `src/` modules — 92.19%
  (independently re-run). `ruff format --check` and `ruff check` — clean on
  all 16 touched files (independently re-run). `mypy --strict` — clean on
  14 of 15 touched files; the 15th (`postgres_worker_dispatch_store.py`)
  fails on `psycopg` not being installed in this venv at all, reproduced
  identically on the untouched, pre-existing `postgres_store.py` — confirmed
  pre-existing, not a regression. Whole-repo: the same six pre-existing
  failures reproduced identically across three independent full-suite runs
  (see §1); a whole-repo aggregate pass count could not be captured this
  session (§1) — no number is asserted for it here that was not directly
  observed.

---

## 1. Gate results

Targeted suite, this cycle's 9 new test files, independently re-run:

```
.venv\Scripts\python.exe -m pytest tests/api/test_worker_routes.py \
  tests/core/test_postgres_worker_dispatch_store.py tests/core/test_worker_auth.py \
  tests/core/test_worker_bundle_crypto.py tests/core/test_worker_consumed_ledger.py \
  tests/core/test_worker_dispatch_signing.py tests/integrations/test_worker_cloud_client.py \
  tests/modules/seo/screaming_frog_control/test_upload_manifest.py \
  tests/modules/seo/screaming_frog_control/test_worker_daemon.py

130 passed, 1 warning in 34.35s
```

Coverage on this cycle's own source files, independently re-run:

```
Name                                                        Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------------------------------------
src\api\worker_routes.py                                      150     13     12      1    91%
src\core\postgres_worker_dispatch_store.py                    140     24     12      2    83%
src\core\worker_auth.py                                       101      3     10      0    97%
src\core\worker_consumed_ledger.py                             48      3      4      0    94%
src\core\worker_dispatch_signing.py                            54      4      8      0    94%
src\integrations\worker_cloud_client.py                        55      0      4      1    98%
src\modules\seo\screaming_frog_control\upload_manifest.py      77      7     30      5    89%
src\modules\seo\screaming_frog_control\worker_daemon.py       118     13     18      3    87%
-------------------------------------------------------------------------------------------------------
TOTAL                                                         933     67    104     12    92%

4 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 92.19%
```

`ruff format --check` on all 16 touched files: `16 files already formatted`.
`ruff check` on the same 16 files: `All checks passed!`.

`mypy --strict` on the 15 touched non-test `src/` files:

```
src\core\postgres_worker_dispatch_store.py:61: error: Cannot find implementation or
  library stub for module named "psycopg"  [import-not-found]
Found 1 error in 1 file (checked 15 source files)
```

Reproduced on the pre-existing, untouched `src/core/postgres_store.py` (same import,
same error), and confirmed `psycopg` is not installed in this venv at all
(`ModuleNotFoundError: No module named 'psycopg'`). Not a regression.

Whole-repo `pytest -q` was run three independent times this session — twice via
`run_in_background` with output redirected to a file, once in the foreground. All
three produced byte-identical failure lists:

```
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[1]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[3]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[5]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[7]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[10]
FAILED tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success
```

Both are confirmed pre-existing and not this cycle's responsibility: `tests/api/test_server.py`
is itself an uncommitted, modified file belonging to the separate concurrent
Redis/Celery/Postgres session (`git status` shows `M tests/api/test_server.py`), and
`TestFacetRouterCapWiring` is the same class build-log 0091 already documented as a
regression test for a since-fixed `ApiState.__init__` default-mismatch bug — its
continued presence in a *different*, still-uncommitted form is a known, ongoing issue,
not a new one (see §6). `test_circuit_breaker_recovers_after_success` is an unrelated,
long-standing GSC timing test, also not touched by this cycle.

None of the three whole-repo runs printed pytest's own final aggregate summary line
(`N failed, M passed, K skipped in Ts`) — including a bare `pytest -q --collect-only`,
which also stopped short of its own "N tests collected" line. This reproduced
identically with `PYTHONIOENCODING=utf-8` forced, so it is not an encoding fix. The
per-file dot/F progress output and the full `FAILED` list are present and identical
across all three runs; only the trailing one-line aggregate is missing, in this shell
session, on the whole-repo run specifically (a run of the same command against a much
smaller subset — the targeted suite above — prints its summary line normally). This
looks like an output-buffering artifact of very large redirected output in this
Windows/git-bash environment, not a test-suite defect, but it is reported here rather
than silently worked around: **no whole-repo pass/fail/skip total is asserted in this
entry that was not directly observed.** The six failures above are directly observed
and were reproduced three times. Cycle 0097's own last independently-verified
whole-repo figure was `6 failed, 2729 passed, 2 skipped in 524.62s`, against a
codebase that did not yet contain this cycle's 130 additive tests or the separate
session's further uncommitted changes; it is cited here as the last verified baseline,
not re-asserted as still current.

`.\.venv\Scripts\python.exe scripts\drift_check.py`:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 172 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

This PASS is real but conditional on the working tree's current uncommitted state —
see §6 on the `0086-a-pattern-is-not-a-verdict.md` link.

## 2. What landed

- **`src/core/worker_auth.py`** — `Worker`/`WorkerPrincipal`/`DiskWorkerStore`, a
  distinct credential type from ADR 0016's operator sessions, reusing
  `core.auth.hash_password`/`verify_password` (PBKDF2) rather than a second hashing
  scheme. Verified directly: `from src.core.auth import hash_password, verify_password`
  at the top of the module, and a dummy-hash constant-time comparison
  (`_DUMMY_SECRET_HASH`) used even when a `worker_id` is unknown, so an unknown-worker
  lookup and a wrong-secret lookup take the same code path — the same enumeration-oracle
  avoidance `AuthenticationError` already uses elsewhere in this codebase.
- **`src/core/worker_dispatch_signing.py`** — gate (b) of the dual approval gate:
  `issue_dispatch_assignment`/`verify_dispatch_assignment`, a self-contained
  HMAC-SHA256, JWT-shaped artifact (header.payload.signature, b64url), deliberately
  duplicating `core.auth.issue_session_token`'s construction rather than importing it
  (that module's helpers are private). Verified directly: the claims embed
  `worker_id`+`org_id`, and `verify_dispatch_assignment` refuses a token bound to a
  different `worker_id` or `org_id` than the caller's own, even with a valid signature.
  The module's own docstring is explicit about condition 4's limit — signing defends
  against network-path tampering and spoofing, not a compromised cloud process, because
  the signing key lives inside that trust boundary; gate (a), not this module, is what
  limits blast radius. Quoted directly from the file: *"Signing defends against
  network-path tampering and a third party spoofing either side. It does **not** defend
  against a compromised cloud process, because the signing key lives inside that trust
  boundary. Gate (a) — not this module — is what limits the blast radius of a
  compromised cloud API."*
- **`src/core/worker_consumed_ledger.py`** — the worker daemon's own disk-backed,
  `threading.Lock`-guarded single-use ledger (`ConsumedJobLedger.try_consume`), read
  directly: the check and the write happen inside one lock acquisition, so a concurrent
  call cannot observe "not yet consumed" twice. This is what survives a daemon restart;
  the cloud's own atomic `QUEUED -> DISPATCHED` transition (`claim_next_job`) covers the
  normal case but not a crashed-and-restarted daemon re-polling nothing (there is
  nothing left to re-poll) after already having claimed but not yet finished a job.
- **`src/core/worker_bundle_crypto.py`** — hand-rolled, stdlib-only HMAC-SHA256
  encrypt-then-MAC (two independently-derived subkeys, `HMAC(secret, b"enc")` and
  `HMAC(secret, b"mac")`, an HMAC-as-keyed-PRF counter-mode keystream, constant-time tag
  verification before decryption). The module's own docstring names this a deliberate,
  documented trade against adding `cryptography`/`pynacl` as a new dependency this
  cycle, not a claim that hand-rolled crypto is generally preferable — read directly and
  confirmed accurate: *"a deliberate trade... not a claim that hand-rolled crypto is
  generally preferable to a vetted library — it is not, and replacing this with
  `cryptography`'s `AESGCM`/`Fernet` is named as follow-up work."*
- **`src/core/worker_dispatch_store.py`** / **`postgres_worker_dispatch_store.py`** —
  gate (a): a `WorkerDispatchStore` Protocol plus the one Postgres implementation. No
  in-process fallback on a store outage — `DispatchStoreUnavailableError` maps to `503`
  at the route layer, never silently approves, matching condition 5's explicit
  requirement ("approval silently fails, nothing runs" is the *safe* failure).
- **`src/api/worker_routes.py`** — the cloud HTTP surface, verified directly against the
  route decorators: `POST /workers` and `GET /workers` (human session-token
  authenticated, via `require_principal`), `POST /workers/{id}/dispatch/preview` and
  `POST /workers/{id}/dispatch` (human-authenticated, worker ownership checked via
  `_owned_worker`), `GET /workers/dispatch/poll` (worker-credential authenticated, via
  `require_worker_principal` — `worker_id`/`org_id` come only from the verified
  credential, never a request field), `POST /workers/jobs/{id}/upload` and
  `.../failed`, `GET /workers/jobs` and `GET /workers/jobs/{id}`.
- **`src/modules/seo/screaming_frog_control/worker_daemon.py`** — the poll/verify/run/
  report loop. `make_approval_callback` is a top-level, independently testable function
  (confirmed: `tests/modules/seo/screaming_frog_control/test_worker_daemon.py` calls it
  directly, five separate tests, without launching Screaming Frog). Read directly: the
  callback re-verifies the artifact's signature *and* atomically consumes it
  (`ledger.try_consume`) inside the exact function `CallbackApprovalProvider` wraps and
  `GuardrailEngine.authorize()` calls — never a bare boolean, and never earlier than the
  moment approval is actually asked for, so a job later refused for an unrelated reason
  never burns the single-use mark first.
- **`src/modules/seo/screaming_frog_control/upload_manifest.py`** — untrusted-upload
  validation: `ALLOWED_BUNDLE_FILENAMES` is derived mechanically from
  `export_manifest.py`'s own `SPINE_TAB`/`EXPORT_TABS`/`BULK_EXPORT` constants via the
  same naming transform that module already documents, rather than a second, hand-typed
  list that could drift.
- **`src/integrations/worker_cloud_client.py`** — a `BaseAPIClient` subclass (confirmed:
  `class WorkerCloudClient(BaseAPIClient)`), `rate_limit_key = "worker.cloud_dispatch"`
  — this resolves ADR 0015's own Step 5 answer 2, which had named a per-worker rate
  limit key as "an open implementation item, not resolved by this ADR," as a design
  decision (see §3).
- **`alembic/versions/0002_worker_dispatch_schema.py`** — three tables
  (`worker_dispatch_previews`, `worker_jobs`, `worker_job_uploads`), correctly chained
  (`down_revision = "001"`).
- **`src/core/config.py`** — 13 new `Settings` fields and 3 new properties (both counts
  verified directly against the commit's diff: `git show bf02a93 -- src/core/config.py`
  shows exactly 13 new `Field(` declarations and exactly 3 new `def` properties —
  `worker_store`, `dispatch_signing_secret`, `bundle_encryption_secret`), plus two new
  production-mandatory checks: `WORKER_DISPATCH_SIGNING_SECRET` and
  `WORKER_BUNDLE_ENCRYPTION_SECRET` must both be set outside `ENVIRONMENT=development`,
  read directly at lines 529-544.
- **`src/api/server.py`**, **`src/api/auth.py`** — `ApiState` wiring, router
  registration, `require_worker_principal`, and an extended type union on
  `org_scoped_or_404`.
- **README.md**, **docs/ARCHITECTURE.md** — the implementer's own diff also backfilled
  ADR 0016's missing row in the ARCHITECTURE.md ADR-index table (confirmed: line 405,
  `[0016](../adr/0016-cloud-api-authentication.md) | ... [build-log 0097]`), which had been
  absent despite ADR 0016 already being two commits ahead at merge time.

## 3. Design decisions

- **Postgres over Redis for gate (a)'s store (condition 5).** The ADR left this open
  with a recommendation; the implementation followed the recommendation
  (`postgres_worker_dispatch_store.py`, reusing `postgres_config.py`) rather than
  defaulting silently to Redis, which the ADR had explicitly warned against ("the
  choice must be named, not defaulted").
- **Polling over WebSocket for transport (§2 of the ADR).** Followed the ADR's stated
  recommendation (`GET /workers/dispatch/poll`, no WebSocket path added anywhere in this
  codebase); the ADR called this "not itself a decision" pending operator sign-off — the
  implementation proceeded on the recommendation without a recorded sign-off event
  distinct from the ADR's own approval. Not flagged as a defect, since ADR 0015's
  overall status is APPROVED and its recommendation was explicit, but the sign-off
  itself is not separately evidenced anywhere this session could find.
- **Retention window default: 30 days**, resolving another open ADR question
  (`Settings.worker_bundle_retention_days`, `ge=1`, configurable). The ADR had
  explicitly deferred this as "an operator policy decision, not an engineering one" and
  set no number. A default was chosen during implementation rather than left unset —
  reasonable as a starting point, but see §6: the number currently has no enforcement
  behind it at all.
- **Rate-limit key resolved during implementation**, not left as the ADR's own named-but-
  unresolved item (`rate_limit_key = "worker.cloud_dispatch"`, scoped per worker
  identity as the ADR's Step 5 answer 2 specified, not per org).

## 4. Bugs found and fixed

None found in this cycle's own code during this docs-scribe pass's independent review —
the security-critical paths (signing, the approval callback, the consumption ledger)
read exactly as documented and the targeted test suite is green. The bugs of note this
cycle are two gaps found *in the surrounding documentation*, not in the shipped code
(see §5 and §6).

## 5. Corrections

- **ADR 0015's own Context section understates `circuit_breaker.py`'s actual reach.**
  The ADR states the primitive "is scoped to Postgres connections specifically, and
  nothing in the codebase wires it — or any circuit breaker — to an outbound
  HTTP/WebSocket dispatch path." Verified independently: `src/integrations/
  gsc_token_manager.py` also wires `core.circuit_breaker.CircuitBreaker` into its own
  OAuth token-refresh HTTP call (`self._circuit_breaker = CircuitBreaker(...)`,
  `is_open()`/`record_success()`/`record_failure()` around the refresh request), and
  this wiring predates the ADR by three days (`git log -S "CircuitBreaker(failure_threshold"`
  finds it in commit `f01d397`, dated 2026-09-12; the ADR is dated 2026-09-15). The
  ADR's narrower point stands — nothing wires a circuit breaker to *this cycle's new*
  worker-dispatch channel specifically, which is what condition 10 actually accepts as a
  gap — but "scoped to Postgres connections specifically" is not accurate as a
  description of the whole codebase at the time the ADR was written. Not a defect in
  this cycle's shipped code; a correction to a claim recorded in the ADR's prose.
- **`docs/ARCHITECTURE.md`'s "Planned, not yet implemented" table still lists
  `core/circuit_breaker.py`** as if the file does not exist at all, which was already
  false before this cycle (`CircuitBreaker` has shipped and been wired into
  `postgres_store.py` since cycle 0084, and into `gsc_token_manager.py` since
  2026-09-12) and remained uncorrected through this cycle's own ARCHITECTURE.md diff,
  which touched the file above that table without touching the table itself. Fixed in
  this entry's own ARCHITECTURE.md edit (§ Drift below) — this is a table-row
  correction, not a re-derivation; the underlying fact was already known to ADR 0015's
  own Context section, just not propagated to this table.
- **CLAUDE.md §8's "`src/core/circuit_breaker.py` — does not exist" is stale**, a fact
  ADR 0015's own Context section already recorded as a correction rather than this entry
  discovering it fresh. Per this cycle's scope boundary (this session was not authorized
  to edit CLAUDE.md itself — that edit belongs to a deliberate, separately-approved
  maintenance pass, the same posture cycle 0097 took toward CLAUDE.md §7 ruling 10's own
  staleness), it is recorded here rather than edited directly.

## 6. Explicitly not done

- **No React UI for any of this.** No cloud dashboard, no worker-registration screen, no
  worker-management view, no dispatch-preview/confirm UI. Every capability described
  above is reachable only by calling the API directly — confirmed by `git show bf02a93
  --stat -- rankuno-ui/`, which returns nothing; not one frontend file was touched by
  this commit. This is the same category of gap build-log 0097 flagged honestly for ADR
  0016 ("no login flow exists... isn't yet usable end-to-end despite being correct and
  complete on the server side") — here, an operator with a valid session token can drive
  the entire worker lifecycle by hand today, but nobody without direct API access can.
- **Uploaded-bundle retention is enforced by filtering, not deletion.** Condition 11
  requires "a retention window with automatic expiry for uploaded bundles." Verified
  directly against `postgres_worker_dispatch_store.py`: `store_upload` writes an
  `expires_at` column (`datetime.now(UTC) + timedelta(days=retention_days)`), and
  `read_upload` filters reads with `WHERE ... expires_at > %s` — but there is no
  `DELETE`, no purge method, and no scheduled job anywhere in this file or its tests
  (`grep`-checked for `purge`/`cleanup`/`delete_expired`/`scheduled`/`cron` across both
  the module and its test file — no matches). An expired row becomes unreadable through
  this API but is never actually removed from Postgres; it stays there, encrypted,
  indefinitely. This is a real gap between the ADR's own stated requirement and what
  shipped — not previously documented anywhere in README.md or ARCHITECTURE.md before
  this entry.
- **The polling-vs-WebSocket and Postgres-vs-Redis choices, though both followed the
  ADR's stated recommendation, have no separately recorded operator sign-off distinct
  from the ADR's own approval event** — see §3. Whether the ADR's own APPROVED status is
  sufficient sign-off for its own recommendations, or whether a distinct confirmation
  was expected, is not resolved by anything this session could find.
- **No circuit breaker for the worker↔cloud channel** — condition 10's own accepted gap,
  substituted with bounded exponential backoff in `worker_daemon.py`'s poll loop. Named
  here only to keep this entry's own §5 correction from being misread as claiming the
  gap is closed; it is not.
- **The `docs/build-log/0086-a-pattern-is-not-a-verdict.md` link in README.md is not
  this cycle's responsibility and is not fixed here.** `scripts/drift_check.py` reports
  PASS right now (§1) because that file currently exists on disk — but it is untracked
  (`git status` shows `?? docs/build-log/0086-a-pattern-is-not-a-verdict.md`) and has
  never been committed to any branch (`git log --all -- "docs/build-log/0086-a-pattern-
  is-not-a-verdict.md"` returns nothing). The link itself was introduced by the
  *previous* docs-scribe cycle (`git log -S` traces it to commit `815fa38`, "cycle 0097
  build-log for ADR 0016"), not by this cycle's commit, and the file that would satisfy
  it belongs to a separate, still-uncommitted concurrent session's working tree. This
  cycle's own commit (`bf02a93`) neither introduced nor references this link. Flagged
  for whoever commits that concurrent session's work next: committing the file under
  this exact name closes the gap; committing it under a different name, or not at all,
  leaves README.md's committed-tree link broken. `docs/build-log/0086-phase-2-
  implementation.md` is a separate, already-tracked file — the two are a known,
  tolerated `0086` collision (CLAUDE.md's own build-log procedure names an equivalent
  `0066` collision as precedent for not renumbering).
- **The `TestFacetRouterCapWiring` failures are not this cycle's responsibility and are
  not re-investigated here** — same underlying default-mismatch class build-log 0091
  already diagnosed and fixed in shipped code; the currently-failing copy lives entirely
  inside `tests/api/test_server.py`'s uncommitted, concurrent-session modifications, not
  in anything this cycle touched or committed.

## 7. Files changed

Per `git show --stat bf02a93` (27 files, +5,636/-11):

```
README.md                                          |   1 +
alembic/versions/0002_worker_dispatch_schema.py    | 122 ++++
docs/ARCHITECTURE.md                               |  86 ++-
src/api/auth.py                                    |  84 ++-
src/api/server.py                                  |  49 ++
src/api/worker_routes.py                           | 423 ++++++++++++++
src/api/worker_schemas.py                          | 154 +++++
src/core/config.py                                 | 185 ++++++
src/core/postgres_worker_dispatch_store.py         | 420 +++++++++++++
src/core/worker_auth.py                            | 297 ++++++++++
src/core/worker_bundle_crypto.py                   | 135 +++++
src/core/worker_consumed_ledger.py                 | 102 ++++
src/core/worker_dispatch_schemas.py                | 191 ++++++
src/core/worker_dispatch_signing.py                | 236 ++++++++
src/core/worker_dispatch_store.py                  | 182 ++++++
src/integrations/worker_cloud_client.py            | 160 +++++
.../seo/screaming_frog_control/upload_manifest.py  | 164 ++++++
.../seo/screaming_frog_control/worker_daemon.py    | 356 +++++++++++
tests/api/test_worker_routes.py                    | 650 +++++++++++++++++++++
tests/core/test_postgres_worker_dispatch_store.py  | 510 ++++++++++++++++
tests/core/test_worker_auth.py                     | 185 ++++++
tests/core/test_worker_bundle_crypto.py            |  51 ++
tests/core/test_worker_consumed_ledger.py          |  48 ++
tests/core/test_worker_dispatch_signing.py         | 145 +++++
tests/integrations/test_worker_cloud_client.py     | 158 +++++
.../screaming_frog_control/test_upload_manifest.py | 142 +++++
.../screaming_frog_control/test_worker_daemon.py   | 411 +++++++++++++
```

Plus, from this docs-scribe cycle itself (uncommitted at time of writing): this entry,
its `docs/build-log/README.md` index row, and corrections to `README.md` /
`docs/ARCHITECTURE.md` replacing the "(build-log entry pending — docs-scribe)"
placeholders with a reference to this entry, plus the `core/circuit_breaker.py`
table-row correction in `docs/ARCHITECTURE.md` (§5).

## 8. Follow-ups

- Build an actual purge job (scheduled task, or a `DELETE ... WHERE expires_at < now()`
  call wired into something that actually runs) for `worker_job_uploads` — condition
  11's "automatic expiry" is not met by read-time filtering alone (§6).
- A cloud dashboard / worker-management UI (§6) — tracked the same way build-log 0097
  tracked the missing login screen, which cycle `571cdd6` then closed one cycle later.
- Replace `worker_bundle_crypto.py`'s hand-rolled construction with `cryptography`'s
  `AESGCM`/`Fernet` the next time this codebase justifies that dependency for any other
  reason (already named as follow-up in the module's own docstring, restated here for
  visibility).
- A deliberate CLAUDE.md maintenance pass to correct §8's stale `circuit_breaker.py`
  entry (§5) — same posture as the still-open CLAUDE.md §7 ruling 10 correction build-log
  0097 already flagged and left unedited.
- Resolve the `docs/build-log/0086-a-pattern-is-not-a-verdict.md` link (§6) the next time
  the concurrent session's own work is committed.
