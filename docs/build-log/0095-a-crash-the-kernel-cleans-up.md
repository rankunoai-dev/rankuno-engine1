# Cycle 0095: A crash the kernel cleans up

- **Date**: 2026-09-15
- **Scope**: Implement ADR 0013's approved Step 3 design — the foundational Windows Job Object process-supervision primitive (`src/core/process_supervisor.py` + private helpers), not Screaming Frog integration itself.
- **Commit**: uncommitted at time of writing
- **Quality gate**: RED overall (`verify.ps1`), but every failing line traces to files this cycle never touched. 47/47 new tests pass; `mypy --strict` clean on all 4 new source files; 92.75% total coverage (floor 85%).

## 1. Gate results

### Targeted (this cycle's files), independently re-run by docs-scribe

```
$ .venv/Scripts/python.exe -m pytest tests/core/test_process_supervisor.py tests/core/test_process_ledger.py tests/core/test_process_orphans.py tests/core/test_win32_bindings.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
collected 47 items

tests\core\test_process_supervisor.py ...................                [ 40%]
tests\core\test_process_ledger.py ............                           [ 65%]
tests\core\test_process_orphans.py ..............                        [ 95%]
tests\core\test_win32_bindings.py ..                                     [100%]

============================= 47 passed in 2.24s ==============================
```

Split: `test_process_supervisor.py` 19, `test_process_ledger.py` 12,
`test_process_orphans.py` 14, `test_win32_bindings.py` 2 (collect-only count
confirms the sum).

```
$ .venv/Scripts/python.exe -m mypy --strict src/core/process_supervisor.py src/core/_process_ledger.py src/core/_process_orphans.py src/core/_win32_bindings.py
Success: no issues found in 4 source files
```

### Full `verify.ps1`, independently re-run by docs-scribe (the implementer's own last run never completed — see §5)

```
=== Format ===
360 files already formatted
PASSED: Format

=== Lint ===
Found 33 errors.
FAILED: Lint

=== Type check ===
Found 14 errors in 6 files (checked 89 source files)
FAILED: Type check

=== Tests ===
7 failed, 2454 passed, 2 skipped, 1 warning in 444.48s (0:07:24)
FAILED: Tests
Required test coverage of 85.0% reached. Total coverage: 92.75%

=== UI Component Tests ===
Test Files  26 passed (26)
     Tests  284 passed (284)
    Errors  3 errors
FAILED: UI Component Tests

VERIFICATION FAILED: Lint, Type check, Tests, UI Component Tests
```

Every one of the 33 lint errors, 14 type errors, and 7 test failures was
checked by hand against `git log -1 -- <file>` and none touches a file this
cycle created or modified:

- **Lint (33)**: all in `scripts/chaos_test.py` (S101/B007), `src/api/server.py`
  (B904 x3), `src/workers/job_executor.py` (D417/ANN001/B904/F841),
  `tests/core/test_redis_config.py` (S106/S105), `tests/core/test_redis_token_bucket.py`
  (RET503/ANN202/SIM222), `tests/integrations/test_gsc_token_manager.py`
  (SIM105 x2, S105 x3), `tests/modules/seo/test_discovery.py` (D205 x2). Last
  touched by commits dated 2026-09-09 (a Phase 2a–2d PostgreSQL/Redis/Celery
  session) through 2026-09-13, none this session.
- **Type check (14)**: `src/core/state_store.py`, `src/core/postgres_store.py`
  (missing `psycopg` stub — an optional dependency), `src/core/redis_config.py`,
  `src/core/rate_limiter.py`, `src/core/celery_config.py`,
  `src/workers/job_executor.py`. Same concurrent session.
- **Tests (7)**: 1 in `tests/api/test_idempotency.py` (`KeyError: 'id'` on an
  org-admission rejection), 5 parametrized cases in
  `tests/api/test_server.py::TestFacetRouterCapWiring`
  (`ApiState.__init__() missing 1 required positional argument:
  'org_config_store'` — a multi-org `ApiState` signature change in flight,
  the test's own fixture not yet updated to match), 1 in
  `tests/integrations/test_gsc_token_manager.py::TestCircuitBreaker::test_circuit_breaker_recovers_after_success`
  (`GscAuthenticationError: ... Token endpoint unreachable and stale token
  expired`). None of the 47 process-supervisor tests are in this list — they
  are part of the 2454 that passed.
- **UI (3 "errors", 0 failed tests)**: three unhandled promise rejections
  surfaced by Vitest from `src/components/gsc/GscAccountForm.test.tsx`
  (antd form validation promises settling after the test body returns); all
  284 individual UI tests report passed. No file under `src/components/gsc/`
  was touched this cycle — this cycle shipped no UI at all (§6).

No orphaned `ping.exe`/`python.exe` test child processes were found running
after either this run or the earlier stalled one
(`Get-Process ping, python, pythonw`; the two `python.exe` processes present
are the live dev API server, confirmed via
`Get-CimInstance Win32_Process | Select CommandLine` ->
`...\.venv\Scripts\python.exe -m src.api.server`, unrelated to any test).

## 2. What landed

Four `src/core/` modules, split more finely than the original one-file brief
suggested — a reasonable decomposition once the win32-import-deferral
requirement (below) forced a seam anyway:

- **`process_supervisor.py`** (291 lines) — the public entry point.
  `launch_supervised(argv, *, ledger_path, job_id=None) -> SupervisedProcess`
  and `SupervisedProcess` (`.pid`, `.is_running()`, `.terminate(timeout_s=5.0)`).
  Re-exports `reconcile_orphans` from `_process_orphans.py` so callers only
  import one module.
- **`_process_ledger.py`** (118 lines) — `LedgerEntry` (`StrictModel`: `pid`,
  `process_start_time`, `job_object_name | None`), `read_ledger`/`write_ledger`
  (atomic, `tempfile` + `os.replace`, matching every other durable file in
  `core/`), `upsert_entry`/`remove_entry` under an intra-process `threading.Lock`.
- **`_process_orphans.py`** (228 lines) — `reconcile_orphans(ledger_path) ->
  list[int]`. Named-Job-Object reopen first
  (`OpenJobObject(JOB_OBJECT_TERMINATE, ...)` + `TerminateJobObject`), a
  `CreateToolhelp32Snapshot` descendant-walk fallback when there is no job name
  to reopen (raw `ctypes`, not pywin32 — see §3). Every candidate is matched on
  PID **and** `process_start_time` before anything is killed.
- **`_win32_bindings.py`** (83 lines) — `load_win32()` returns a frozen
  `Win32Handles` dataclass wrapping `win32api`/`win32con`/`win32event`/
  `win32job`/`win32process`/`pywintypes`, imported only inside the function
  body. `ProcessSupervisorError` / `ProcessSupervisorUnavailableError`
  (`RankunoError` subclasses).

Tests: `test_process_supervisor.py` (19: validation, orchestration ordering
against a mocked win32, plus the real-OS `@pytest.mark.integration` class),
`test_process_ledger.py` (12: round-trip, atomic-write crash safety, lock
behaviour), `test_process_orphans.py` (14: named-job path, tree-walk fallback,
PID-reuse refusal, already-gone entries), `test_win32_bindings.py` (2: the
unavailable-on-non-Windows error path, and the happy path via a monkeypatched
`sys.modules`). `tests/core/conftest.py` is new: the shared `fake_win32`
fixture (a `MagicMock`-backed `Win32Handles`) every orchestration test in this
cycle depends on.

## 3. Design decisions

- **Same-process supervisor, not a separate watchdog** (ADR 0013 condition 3).
  The Job Object's `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` guarantee is enforced
  by the kernel the instant the handle closes — including when it closes
  because *this* process crashed and the OS force-closed every handle it
  held. The guarantee does not depend on the supervisor staying alive, which
  is exactly what makes a separate watchdog process unnecessary for condition
  1 and 2's requirements. `TestRealWindowsKillOnJobClose::test_kill_on_job_close_survives_an_unclean_supervisor_exit`
  is the proof: it spawns a real child Python interpreter, has it call
  `launch_supervised` on a disposable `ping -t` process, then calls
  `os._exit(1)` inside that child interpreter — which skips every `atexit`
  hook and every `finally` block, including `SupervisedProcess.terminate()`.
  The outer test then checks, from a third process, whether the `ping`
  process is still alive. It is not, and no Python cleanup code of ours ran
  to make that true — the kernel did it via kill-on-close. This is the
  load-bearing proof for the whole feature, not just one of the 47.
- **PID recorded before the Job Object exists.** `launch_supervised` writes
  the ledger entry with `job_object_name=None` immediately after
  `CreateProcess(..., CREATE_SUSPENDED, ...)` returns a PID, before
  `CreateJobObject`/`AssignProcessToJobObject` run. A crash in that narrow
  window still leaves the PID discoverable at next startup;
  `test_pid_is_recorded_before_job_object_assignment_completes` asserts the
  ordering directly via a spy on `AssignProcessToJobObject`'s side effect.
- **`CREATE_SUSPENDED` until the Job Object assignment succeeds.** The child
  runs zero instructions of its own code until `ResumeThread`, the last step.
  If ledgering or Job Object assignment fails, the still-suspended child is
  killed with `TerminateProcess` and its ledger entry removed — no work is
  lost (nothing ran) and no governance gap is left behind. Both
  `test_job_object_assignment_failure_kills_the_suspended_child` and
  `test_create_job_object_failure_also_kills_the_suspended_child` cover this.
- **PID + `process_start_time`, never PID alone**, for both `terminate()`'s
  implicit contract and `reconcile_orphans`'s matching. Windows reuses a PID
  the instant its previous holder exits; a bare PID match risks killing an
  unrelated process that happens to have inherited the number.
  `_START_TIME_TOLERANCE_S = 0.001` in `_process_orphans.py` is looser than a
  JSON float round-trip needs (exact) and tight enough that only the same
  process's creation time can match by coincidence.
- **Named-Job-Object reopen before the Toolhelp32 tree walk**, in
  `reconcile_orphans`. The named path is tree-safe by construction (same
  mechanism as `SupervisedProcess.terminate()`); the walk is a fallback for
  the one window where no job exists yet — a crash between `CreateProcess`
  and `AssignProcessToJobObject`. pywin32 does not wrap
  `CreateToolhelp32Snapshot`/`Process32First`/`Process32Next` (confirmed by
  inspection of `win32process`/`win32api`), so this one path uses raw
  `ctypes` rather than pywin32 — the only place in the module that does.
- **`Local\` Job Object namespace**, not the global (`Global\`) namespace.
  Session-local naming needs no `SeCreateGlobalPrivilege`, appropriate for a
  per-user desktop tool on a single workstation (ADR 0004) that never needs
  cross-session visibility.
- **Deferred `pywin32` import in every module**, via `_win32_bindings.load_win32()`.
  pytest imports every test module at collection time regardless of `-m`
  filters; an unconditional `import win32job` at module scope would turn
  "pywin32 is a Windows-only extra" into a collection error for the *whole*
  suite on `ci.yml`'s `ubuntu-latest` runners, not a scoped failure. Calling
  any function here without pywin32 raises `ProcessSupervisorUnavailableError`
  cleanly instead.
- **`_JOB_ID_PATTERN = r"^[A-Za-z0-9_-]{1,200}$"`.** A caller-supplied
  `job_id` becomes both a ledger key and a Windows kernel object name; the
  restricted charset is what stops it from injecting a `\` namespace
  separator into `Local\rankuno-process-supervisor-<job_id>`.

## 4. Bugs found and fixed

The implementer's own bug-discovery narrative was lost — the agent stalled
mid final-verification and its last message predates any "what broke along
the way" account. What follows is reconstructed from the code and tests
themselves, which document several genuine Windows API pitfalls the design
defends against (not live test failures docs-scribe can attribute a fix
timeline to, but real, specific, and verifiable in the source):

- **`GetExitCodeProcess() == STILL_ACTIVE` (259) is not a safe liveness
  check.** 259 is also a value a process can legitimately exit with, which
  makes the naive comparison a false negative waiting to happen.
  `SupervisedProcess.is_running()` uses a zero-timeout
  `WaitForSingleObject(handle, 0) == WAIT_TIMEOUT` instead — the documented
  idiom, with no sentinel-value ambiguity.
- **`OpenProcess` succeeding does not mean the process is still running.** A
  PID stays "reserved" — `OpenProcess` keeps succeeding — for as long as
  *any* handle to it remains open anywhere, even after the process has
  actually exited. The real-OS test helper `_pid_is_alive` (used only by the
  integration tests) checks the signaled state via `WaitForSingleObject`
  rather than merely whether `OpenProcess` succeeds, to avoid a false
  "still alive" reading in the test itself.
- **A bare PID match in orphan reconciliation is a live hazard, not a
  theoretical one.** Killing whatever now holds a recycled PID would kill a
  process this engine never launched. `reconcile_orphans` refuses to act on
  any ledger entry whose observed `process_start_time` does not match the
  recorded one within `_START_TIME_TOLERANCE_S`, and
  `test_orphan_pid_reused_or_vanished`-style cases in
  `test_process_orphans.py` assert the refusal.
- **Enrollment-race window between `CreateProcess` and
  `AssignProcessToJobObject`** — named explicitly as ADR 0013 condition 2's
  concern. Closed by writing the ledger entry (with `job_object_name=None`)
  immediately after the PID exists, before the Job Object is even created,
  so a crash in that window still leaves something for `reconcile_orphans`
  to find (via the Toolhelp32 fallback, since there is no job name yet).

## 5. Corrections

The implementing agent was killed by a watchdog mid-way through its own final
`verify.ps1` re-run, after already reporting "all tests passing" in an
earlier message. That earlier message is not treated as the record. The
coordinator independently re-verified afterward and reported (mid-session,
not as a committed document) "one test failure in
`tests/integrations/test_gsc_token_manager.py`" as the sole pytest failure in
the full gate. **docs-scribe's own independent full `verify.ps1` run (§1)
found 7 failing tests, not 1** — the same `test_gsc_token_manager.py` circuit
breaker test the coordinator named, plus 1 in `test_idempotency.py` and 5
parametrized cases in `test_server.py::TestFacetRouterCapWiring`. All 7 were
individually checked against `git log -1 -- <file>` and confirmed to predate
this session (2026-09-09 through 2026-09-13, a concurrent PostgreSQL/Redis/
Celery/multi-org session) and to touch no file this cycle created or
modified. The conclusion the coordinator reported — gate RED, nothing in this
cycle's files — holds; the count of pre-existing failures they cited did not.
Per CLAUDE.md's "paste real gate output, do not summarise from memory,"
extended here to "and do not trust a stalled agent's unfinished claim, or a
mid-session verbal summary, over a fresh independent run."

## 6. Explicitly not done

Per ADR 0013's own scope boundary — conditions 4 through 8 are unaddressed by
this cycle and deferred to follow-on cycles against the same approval:

- No `src/modules/seo/screaming_frog_control/` package. This cycle ships the
  primitive Screaming Frog control would be built on, not that control
  itself.
- No tool or facet registration — nothing calls `launch_supervised` from a
  `BaseTool` yet.
- No CLI flag / `.seospiderconfig` field mapping (ADR 0013 condition 5).
- No license-failure detection or the named `JobRecord.error` string ADR
  0013 condition 6 requires.
- No pre-flight `UrlSafetyPolicy.validate()` gate on a seed URL (ADR 0013
  condition 4) — there is no seed URL yet; nothing calls this module with an
  operator-supplied target.
- No UI changes. `argv` in this cycle's tests is always `ping` or a disposable
  test fixture, never anything reachable from the React app.
- No separate watchdog process — this is the explicit decision recorded in
  §3, not an omission.
- No `RiskClass.WRITE` tool exists yet to wrap this primitive, and therefore
  the "Open question this ADR does not resolve" (how a `MANDATORY_HITL`
  approval is actually supplied, given `GuardrailEngine.authorize()` calls a
  synchronous, blocking `ApprovalProvider.request_approval()` and no real
  provider has ever been wired for any tool in this codebase) remains open.
  This cycle does not touch `guardrails.py` or any `ApprovalProvider`.

**Documentation gap, noted rather than silently accepted**: ADR 0013's own
status line states its companion Step 3 design document was presented in the
same conversation as the ADR but was never separately committed to the
repository as its own file. The design rationale currently exists only in
that session's conversation history and in the ADR's own restatement of it
(the ADR text itself, §"Decision" and the numbered conditions). Whether that
restatement is sufficient, or a standalone design doc should still be
committed, is left as a follow-up (§8) rather than resolved here.

## 7. Files changed

New, uncommitted at time of writing:

- `src/core/process_supervisor.py` (291 lines)
- `src/core/_process_ledger.py` (118 lines)
- `src/core/_process_orphans.py` (228 lines)
- `src/core/_win32_bindings.py` (83 lines)
- `tests/core/test_process_supervisor.py` (326 lines)
- `tests/core/test_process_ledger.py` (132 lines)
- `tests/core/test_process_orphans.py` (248 lines)
- `tests/core/test_win32_bindings.py` (36 lines)
- `tests/core/conftest.py` (64 lines) — new, shared `fake_win32` fixture
- `pyproject.toml` — `pywin32` extra (`pywin32>=306; sys_platform=='win32'`,
  with an ADR 0013 rationale comment) and a `[[tool.mypy.overrides]]` block
  for `win32api`/`win32con`/`win32event`/`win32job`/`win32process`/`pywintypes`
  (no type stubs, Windows-only, so `mypy src` on `ubuntu-latest` needs the
  override)
- `docs/adr/0013-screaming-frog-cli-process-governance-exception.md` — governs
  this cycle; its **Status** line was updated to APPROVED earlier this session
  (operator's explicit "approved"), predating this implementation cycle. Not
  authored by this cycle, but part of the same uncommitted change set.
- This entry: `docs/build-log/0095-a-crash-the-kernel-cleans-up.md`
- `docs/build-log/README.md` — index row added
- `README.md`, `docs/ARCHITECTURE.md` — drift updates (§8 of this entry's own
  procedure; see the diff for exact wording)

## 8. Follow-ups

All scoped to ADR 0013's remaining conditions, none started:

- ADR 0013 condition 4: pre-flight `UrlSafetyPolicy.validate()` on the seed
  URL, explicitly documented as covering only the seed — Screaming Frog's own
  subsequent redirects and discovered links are not validated by this
  engine's SSRF guard.
- ADR 0013 condition 5: the full UI-to-Screaming-Frog CLI /
  `.seospiderconfig` field mapping table, every entry marked verified /
  needs-verification / no-mapping.
- ADR 0013 condition 6: license-failure detection surfaced as a distinct,
  named `JobRecord.error`, never retried, never silently degraded.
- The `RiskClass.WRITE`, `MANDATORY_HITL` tool itself — `src/modules/seo/screaming_frog_control/`,
  a `BaseTool` subclass calling `launch_supervised`, and the still-open
  question of how a real `ApprovalProvider` gets wired for the first time in
  this codebase.
- UI work to trigger and monitor a Screaming Frog run from the React app —
  entirely unstarted.
- The documentation gap noted in §6: decide whether the Step 3 design detail
  needs its own committed file, or whether ADR 0013's restatement is judged
  sufficient as the binding record.
