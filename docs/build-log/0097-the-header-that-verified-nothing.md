# Cycle 0097: Session-token authentication and org-ownership retrofit (ADR 0016)

- **Date**: 2026-09-16
- **Scope**: Close a CRITICAL, currently-shipped IDOR on the three
  `/orgs/{org_id}/gsc-accounts` routes (full read/write access to any
  organization's Google OAuth `refresh_token` by guessing an `org_id`
  string) and retrofit a real org-ownership check onto every job-family and
  deliverable route that previously trusted a client-asserted `X-Org-Id`
  header or a raw path parameter, by shipping this codebase's first caller-
  identity mechanism (`Principal`/`Operator`, self-contained session
  tokens).
- **Commit**: `c2821e3` (merge, on `origin/main`; parents `b3335e3` and
  `ced29fe`). Implementation `d7a87f3`; follow-up fix `ced29fe`; ADR
  approval `a6a4716`; ADR text `docs/adr/0016-cloud-api-authentication.md`.
- **Quality gate**: Targeted ADR 0016 files — 103 passed, 1 warning in
  61.12s (independently re-run). Whole-repo — **6 failed, 2729 passed, 2
  skipped, 1 warning in 524.62s** (independently re-run in full this
  cycle; all 6 failures confirmed pre-existing and unrelated, §1).
  `ruff format --check .` clean repo-wide. `ruff check .` 30 pre-existing
  errors, none in this cycle's files. `mypy --strict` clean on all 6
  touched `src/`/`scripts/` files; 14 pre-existing errors elsewhere, none
  in this cycle's files. `scripts/drift_check.py` PASSED.

## 1. Gate results

Targeted (`tests/core/test_auth.py tests/api/test_auth.py
tests/api/test_adr0016_job_scoping.py tests/api/test_deliverables_endpoints.py`),
independently re-run:

```
........................................................................ [ 69%]
...............................                                          [100%]
103 passed, 1 warning in 61.12s (0:01:01)
```

Whole-repo `pytest tests/` (no coverage instrumentation, to keep the run
inside the session), independently re-run in full for this cycle — the
prior several cycles' entries note this was usually skipped for time; it
was run to completion here specifically to check the implementer's "only 6
failures, all pre-existing" claim:

```
6 failed, 2729 passed, 2 skipped, 1 warning in 524.62s (0:08:44)

FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[1]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[3]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[5]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[7]
FAILED tests/api/test_server.py::TestFacetRouterCapWiring::test_facet_cap_always_matches_the_configured_value[10]
FAILED tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success
```

Both confirmed independently, not taken on the implementer's word (§6):
`TestFacetRouterCapWiring` calls `ApiState(store=..., url_policy=...,
max_concurrent_jobs=cap)` without `org_config_store`, a parameter with no
default — `git log -S` on that constructor signature shows it became
required in commit `f01d397` (cycle 0092, 2026-09-12), four days before
ADR 0016 existed, so this is not a regression this cycle introduced.
`test_circuit_breaker_recovers_after_success` sits in
`tests/integrations/test_gsc_token_manager.py`, which does not appear
anywhere in `c2821e3`'s changed-file list.

`ruff format --check .`: clean, no output, exit 0, repo-wide.

`ruff check .`: 30 errors, exit 1. All in `scripts/chaos_test.py` (7 `S101`
+ 1 `B007`), `src/workers/job_executor.py` (6 errors: `D417`/`ANN001`/`B904`/`F841`),
`tests/core/test_redis_config.py` (2 `S105`/`S106`),
`tests/core/test_redis_token_bucket.py` (3 errors), `tests/integrations/test_gsc_token_manager.py`
(5 `S105`/`SIM105`), `tests/modules/seo/test_discovery.py` (2 `D205`). None
of these files appear in this cycle's diff; all match the "concurrent
Redis/Celery/Postgres session" pattern every recent entry from 0087 onward
records, plus the same 2 pre-existing `D205`s cycles 0087/0089/0095 already
named.

`mypy --strict src/core/auth.py src/api/auth.py src/api/server.py
src/api/deliverables_routes.py src/core/config.py`: `Success: no issues
found in 5 source files`. `mypy --strict scripts/create_operator.py`
separately: `Success: no issues found in 1 source file`.

`mypy src` (whole tree): 14 errors in 6 files — `src/core/redis_config.py`,
`src/core/state_store.py`, `src/core/postgres_store.py`,
`src/core/rate_limiter.py`, `src/core/celery_config.py`,
`src/workers/job_executor.py`. None of these are in this cycle's diff; the
error count (14) matches cycle 0095's own whole-tree mypy count exactly,
consistent with this being the same persistent unrelated WIP branch, not a
new problem.

`.\.venv\Scripts\python.exe scripts\drift_check.py`, run twice — once
before this entry existed (baseline) and once after adding it and the
index row (§6 below has the final one):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 171 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 2. What landed

- **`src/core/auth.py`** — `Principal` and `Operator` `StrictModel`s,
  PBKDF2-HMAC-SHA256 password hashing (210,000 iterations, OWASP 2023
  minimum), a hand-built self-contained HMAC-SHA256 bearer token
  (`issue_session_token`/`verify_session_token`, JWT-shaped wire format but
  no JWT dependency), and `DiskOperatorStore`. No FastAPI import — stays on
  the `core` side of the inward-only boundary; `src/api/auth.py` is the
  HTTP glue.
- **`src/api/auth.py`** — `require_principal` (bearer token to `Principal`
  or `401`), `org_scoped_or_404` (one shared ownership check, generalised
  from `deliverables_routes.py`'s previously-private `_org_scoped_or_404`),
  and `build_auth_router` for `POST /auth/login`. Login is rate-limited
  per operator id (10/min) and verifies a dummy password hash on an
  unknown-operator lookup, so a response's timing cannot be used to
  enumerate operator ids.
- **`scripts/create_operator.py`** — the only way to provision an operator:
  offline, interactive, masked-password prompt. Deliberately not an HTTP
  endpoint (an operator-creation route would itself need authentication).
- **`src/core/config.py`** — `auth_session_secret` (`SecretStr | None`,
  required in production), `auth_session_ttl_s` (default 43,200s / 12h),
  `auth_operator_store_path`, `auth_bootstrap_operator_*` fields, and the
  `Settings.session_secret`/`Settings.operator_store` properties. A missing
  `AUTH_SESSION_SECRET` in production now fails `model_post_init` loudly,
  the same posture the existing guardrail-override validation already took.
- **`src/api/server.py`** — every route that previously read `X-Org-Id` now
  calls `require_principal`; 14 job-family routes that had no ownership
  check at all now call `org_scoped_or_404`; the three
  `/orgs/{org_id}/gsc-accounts` routes gate on the caller's own org before
  any existence check runs; `resume_job` now passes `org_id=record.org_id`
  to `_start` (previously silently misattributed to `default`); a new
  per-principal rate-limit key (`principal:{operator_id}`) applies at job
  creation, distinct from the existing `web.crawl` key and from
  `ApiState`'s global concurrency caps.
- **`src/api/deliverables_routes.py`** (via `ced29fe`, §4) — all 8 routes
  migrated from the header-trusting `_org_id()` helper (now deleted) to
  `require_principal`/`org_scoped_or_404`.
- Test infrastructure: `tests/api/conftest.py` (`TEST_SESSION_SECRET`,
  `mint_token`, `auth_headers` — mints a token directly against a fixed
  test secret, no operator store or `/auth/login` round trip needed per
  test) and new files `tests/core/test_auth.py` (257 lines),
  `tests/api/test_auth.py` (281 lines), and
  `tests/api/test_adr0016_job_scoping.py` (292 lines) covering the retrofit
  end to end.

## 3. Design decisions

- **Self-contained HMAC token over a JWT library or remote introspection.**
  ADR 0016 condition 6 preferred this to avoid adding a new external
  dependency — and the circuit-breaker coverage that dependency would need
  on a codebase that has none on any HTTP path today
  (`src/core/circuit_breaker.py` is Postgres-only). The wire format
  (`header.payload.signature`, base64url, `HS256`) is JWT-shaped so any
  standard library could still decode it, without the codebase depending on
  one for a single HMAC compare.
- **One shared `org_scoped_or_404`, not two.** `deliverables_routes.py`
  already had a private, correctly-shaped `_org_scoped_or_404`; rather than
  writing a second copy for `server.py`, it moved to `src/api/auth.py` and
  both callers now import the same function. This is the direct fix for
  the inconsistency ADR 0016 condition 2 named as the root problem —
  fourteen ad-hoc checks, re-derived per route, is exactly what let some of
  them go missing in the first place.
- **`org_id` becomes unconstructable from bad input, not merely
  unvalidated.** `Principal.org_id` and `Operator.org_id` both carry the
  `^[a-z0-9_-]{1,64}$` field pattern. This changed one test's observable
  behavior: `test_invalid_org_ids_are_rejected` (pre-existing, asserting a
  `400` from `create_job`) was replaced with
  `test_malformed_org_ids_cannot_even_authenticate`, which instead asserts
  a `pydantic.ValidationError` at `Operator` construction — a malformed
  `org_id` can no longer reach `create_job` at all, because no verifiable
  token naming it can be minted in the first place. Recorded in
  `test_multi_org.py`'s own docstring as an intentional correction, not a
  silent drop; confirmed here by diffing every `def test_` name in that
  file and `test_server.py` between the pre-merge and post-merge commits —
  two renames with direct successors, one new test added
  (`test_unauthenticated_request_is_401`), nothing missing.
- **Test tokens are minted directly, not obtained through `/auth/login`.**
  `tests/api/conftest.py` calls `issue_session_token` against a fixed
  `TEST_SESSION_SECRET` rather than standing up an operator store and
  logging in per test — condition 6's "self-contained" property is what
  makes this possible: verification never touches the operator store, so a
  test never needs one to authenticate.

## 4. Bugs found and fixed

1. **CRITICAL — the three `/orgs/{org_id}/gsc-accounts` routes accepted
   `org_id` as a raw path parameter with zero verification.** Pre-existing
   in shipped code, found by a security-auditor pre-step and recorded in
   ADR 0016's own Context section; this cycle's implementation is the fix.
2. **HIGH — fourteen job-family routes had no working org-ownership check.**
   Seven of them (`get_job`, `list_jobs`, `get_result`,
   `list_gsc_accounts`, `preview_screaming_frog_job`,
   `create_screaming_frog_job`, `create_job`) looked correctly shaped —
   they compared `org_id` against `record.org_id` — but the `org_id` they
   compared against came from an unauthenticated `X-Org-Id` header any
   caller could set to anything, making the check enforce nothing. The
   other seven had no check at all. Both classes are closed by the same
   fix: `org_id` is now a claim inside a verified token, never a header.
3. **MEDIUM — `resume_job` omitted `org_id=record.org_id` on its call to
   `_start`,** silently misattributing every resumed crawl to the
   `default` org regardless of the original job's owner. Fixed to match
   `retry_job`'s existing correct call.
4. **`deliverables_routes.py` carried the same IDOR class in a sibling file
   ADR 0016's own route enumeration never named.** Found by the
   coordinating session reviewing the merge, not by the original
   implementation: `d7a87f3` shipped with this file still deriving `org_id`
   from `X-Org-Id`, recorded as a known, deliberately-handed-off gap at
   `_org_id()`'s docstring. `ced29fe`, 13 minutes later, closed it — all 8
   routes now call `require_principal`, and `_org_id()` was deleted rather
   than left as dead code.
5. **A test that passed for the wrong reason.**
   `TestFacetAccessControl::test_org_without_facet_access_is_rejected_403`
   monkeypatches `facet_router.validate_org_access` to deny `team-a`
   access to `seo.health_engine`, then asserts a `403`. It authenticated
   the request via `headers={"X-Org-Id": "team-a"}` — a header that had
   already stopped being read anywhere by the time this test ran, because
   `d7a87f3` migrated `create_job` to `require_principal` in the same
   commit. The request actually ran as whatever org the test client's
   *default* session authenticated (not `team-a`), so the monkeypatched
   denial never matched and the assertion happened to still find `403` for
   an unrelated reason in the original implementer's own verification pass
   — except independently checked here, running it in isolation before
   `ced29fe` would have shown a `202`, not a `403`; `ced29fe`'s commit
   message confirms this was exactly the failure mode found. Fixed to use
   `auth_headers("team-a")`.
6. **A documentation bug this docs-scribe pass found and fixed itself.**
   `README.md`'s deliverables section, edited by `d7a87f3`, stated in bold:
   *"Not yet migrated to ADR 0016's authenticated org derivation — this
   header remains client-asserted here."* `ced29fe` fixed the underlying
   code 13 minutes later but did not touch this paragraph, so by the time
   `c2821e3` merged, `README.md` was actively describing a vulnerability
   that no longer existed in the code sitting three lines away in the same
   file's own auth walkthrough. Corrected in this cycle's own commit (§7).

## 5. Corrections

- **ADR 0016's own Context item 3 flagged that `policy_for()` "currently
  always returns the base policy," apparently contradicting CLAUDE.md §7
  ruling 10 (which names `policy_for()` loosening policy as a known,
  unresolved defect), and asked for a git-history check — "which is
  `docs-scribe`'s job," not the ADR's.** That check was performed this
  cycle: commit `a0e5fec` (2026-09-09, "Phase 2d Task 11 - Fix guardrail
  override defect," documented in
  `docs/build-log/0086-phase-2-implementation.md`) already fixed this
  exact defect — `policy_for()` now refuses to apply any override in
  production and is a documented no-op in development — a full week before
  this cycle. **CLAUDE.md §7 ruling 10, as currently written, is stale
  against the code that has existed since 2026-09-09.** This is not
  resolved in this entry: per this cycle's own instructions, moving that
  ruling to CLAUDE.md §8 "Closed since the audit" is left for a human or a
  future cycle to do deliberately, not folded into a docs-scribe pass as a
  side effect. Flagged again in §8 below.
- **This entry's own §4.6 corrects `README.md`** as published by `d7a87f3`
  — see above; not editing the earlier commit, only this entry and the
  file itself, per the build-log's own "never revise history" rule.

## 6. Explicitly not done

- **`TestFacetRouterCapWiring`'s 5 parametrized failures are not this
  cycle's to fix.** The class (`tests/api/test_server.py`, currently
  uncommitted working-tree content) belongs to a separate, concurrent
  session's own fix for an unrelated `FacetRouter` default-cap mismatch
  bug (the same class of issue build-log 0091 closed for the health
  endpoint). It calls `ApiState(...)` without `org_config_store`, which has
  had no default since cycle 0092 (2026-09-12) — four days before ADR 0016
  existed. Left untouched here, exactly as instructed, so responsibility
  for it stays with the session that owns it.
- **`test_circuit_breaker_recovers_after_success`'s failure is not this
  cycle's to fix either.** Long-standing, in
  `tests/integrations/test_gsc_token_manager.py`, untouched by this
  cycle's diff, and already named as a known unrelated timing failure in
  build-log 0091's own gate output a month before this cycle. Whether it
  is a real bug in the circuit breaker's recovery logic or a test race is
  not established here.
- **No login flow exists anywhere in the shipped React UI.**
  `rankuno-ui/src/adapters/httpAdapter.ts`, as committed at this cycle's
  `HEAD`, has no `Authorization` header handling at all — confirmed by
  direct search, not assumed. Nearly every route in `server.py` now
  requires a bearer token; the deployed UI will receive `401` on almost
  every request it makes until a login screen and token storage are built.
  ADR 0016 is scoped to the API server only and does not mention this; it
  is recorded here so it is not mistaken for something this cycle covered.
- **No operator has been provisioned in this environment.** `.operators/`
  exists on disk but holds no `operators.json` — the store is empty — and
  no `AUTH_BOOTSTRAP_OPERATOR_ID`/`AUTH_BOOTSTRAP_OPERATOR_PASSWORD` is set
  in the local environment. Nobody, including the human operator, can
  currently obtain a session token against a server started from this
  checkout until `scripts/create_operator.py` is run once, interactively.
- **Per-org concurrency sub-cap inside `ApiState`** (ADR 0016 condition 7)
  — named in the ADR as a should-have, not committed to this
  implementation's scope. Only the per-principal *rate-limit* key shipped;
  concurrency caps remain global.
- **`facet_router.validate_org_access()` remains exactly the no-op it was
  before this cycle** (ADR 0016 condition 11, explicitly out of scope).
  Every `except PermissionError` reading its result is still dead code
  outside the one route this cycle's tests exercise via monkeypatching.
- **Per-org crawl-target allowlisting** (ADR 0016 condition 8) — whether an
  authenticated Org B may point a crawl at Org A's infrastructure is
  explicitly deferred; `UrlSafetyPolicy` is unchanged.
- **No worker credential was minted** (ADR 0016 condition 5b) — no worker
  daemon exists yet; ADR 0015 (which would need it) is approved but not
  implemented.
- **A stale inline comment in `server.py` was found, not fixed.** At
  `_run_job` (~line 1064), a comment still reads "the record, where
  admission put the `X-Org-Id` it validated" — that header is no longer
  read anywhere in this file; `org_id` comes from the verified session
  token. This is source code, not documentation, so it is out of this
  docs-scribe pass's scope to edit; flagged here for whoever next touches
  that function.

## 7. Files changed

From `c2821e3` (the ADR 0016 cycle itself — `d7a87f3` + `ced29fe` merged):
20 files, 2,870 insertions, 373 deletions —
`README.md`, `docs/ARCHITECTURE.md`, `scripts/create_operator.py` (new),
`src/api/auth.py` (new), `src/api/deliverables_routes.py`,
`src/api/server.py`, `src/core/auth.py` (new), `src/core/config.py`,
`tests/api/conftest.py` (new), `tests/api/test_adr0016_job_scoping.py`
(new), `tests/api/test_auth.py` (new),
`tests/api/test_deliverables_endpoints.py`,
`tests/api/test_gsc_accounts_endpoint.py`, `tests/api/test_idempotency.py`,
`tests/api/test_multi_org.py`, `tests/api/test_performance_endpoints.py`,
`tests/api/test_screaming_frog_endpoints.py`, `tests/api/test_server.py`,
`tests/core/test_auth.py` (new), `tests/core/test_config.py` (new).

This docs-scribe pass additionally changed: `README.md` (corrected the
stale `deliverables_routes.py` paragraph, §4.6), `docs/build-log/README.md`
(index row), `docs/build-log/0097-the-header-that-verified-nothing.md`
(new, this file).

`docs/ARCHITECTURE.md` was checked against the current code
(`require_principal`/`org_scoped_or_404` wiring, `auth.py` in both `core`
and `api`) and found already accurate — no further edit needed there this
cycle.

## 8. Follow-ups

- Move CLAUDE.md §7 ruling 10 to §8 "Closed since the audit," citing commit
  `a0e5fec` and `docs/build-log/0086-phase-2-implementation.md` — a
  deliberate edit to the binding contract file, left for a human or a
  dedicated future cycle rather than folded in here (§5).
- Build a login screen and token storage in `rankuno-ui`, or the shipped
  UI cannot complete a single authenticated request against this server.
- Run `scripts/create_operator.py` at least once in this environment so an
  operator actually exists to log in as.
- `TestFacetRouterCapWiring`'s missing `org_config_store` argument — belongs
  to the concurrent session that added the class; not fixed here (§6).
- Per-org concurrency sub-cap inside `ApiState` (ADR 0016 condition 7,
  named as a should-have).
