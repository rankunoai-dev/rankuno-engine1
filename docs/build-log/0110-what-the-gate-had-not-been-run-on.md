# Cycle 0110: 62 lint, 16 type and 3 test failures cleared; two of the three failing tests were wrong

- **Date**: 2026-09-27
- **Scope**: whole-tree quality gate returned to green, with every suppression scoped and justified in `pyproject.toml`; two incorrect tests corrected, one real product bug fixed.
- **Commit**: uncommitted at time of writing
- **Quality gate**: **GREEN** as reported by the operator's run — 62 ruff errors → 0, 16 mypy `--strict` errors → 0, 3 failing tests → 0, coverage **88.40%** against the unchanged 85% floor, UI 473/473. See §1 for what was and was not independently reproduced here.
- **Session thread**: entry 5 of 6 — see [0106 §0](0106-a-pattern-that-never-reaches-the-form.md)

## 1. Gate results

The operator ran the full gate in this working tree concurrently with this entry
being written. The four figures above are that run's, reported as theirs. They
were **not** independently re-run here, and the reason is specific rather than
generic: a second `pytest` in the same tree overwrites `.coverage`, and a second
`mypy` shares `.mypy_cache`, so re-running either would have corrupted the run
whose numbers are being recorded.

Independently verified here, statically:

| Measurement | Value | How |
| :--- | :--- | :--- |
| Per-file ruff ignores added | 4 blocks (`tests/**` extended, `scripts/chaos_test.py`, `src/modules/seo/deliverables/masterfile_*.py`) | `git diff pyproject.toml` (+38/-1) |
| mypy overrides added | 1 (`celery.*`, `ignore_missing_imports`) | same |
| `type: ignore` comments added to `src/` | **2**, both `[untyped-decorator]` in `src/workers/job_executor.py` | `git diff` |
| `# type: ignore` comments **removed** from `src/` | 3 bare ones (`rate_limiter.py` ×2, `redis_config.py` ×1) | `git diff` |
| `tests/core/test_circuit_breaker.py` | exists, 20 test functions | `ls`, `grep -c` |
| `src/core/circuit_breaker.py` callers | 3 — `core/postgres_store.py`, `core/worker_dispatch_signing.py`, `integrations/gsc_token_manager.py` | `grep -rln` |

## 2. What landed

Lint, typing and the three failures, each with the smallest change that makes the
check true rather than silent:

- **Bare `# type: ignore` replaced by a scoped module override.** `celery` ships
  no `py.typed` and no bundled stubs (the published ones are the third-party
  `celery-types` distribution, not a declared dependency), so
  `mypy --strict` cannot resolve `Celery` or `Task` however they are annotated.
  One `[[tool.mypy.overrides]] module = "celery.*"` replaces the blanket ignores,
  and `job_executor.py` keeps exactly two narrow
  `# type: ignore[untyped-decorator]` on the two `@app.task` decorators, with the
  wrapped functions fully annotated (`self: Task`, `-> dict[str, str]`).
- **`redis.Redis` annotations lose their `# type: ignore`** in `rate_limiter.py`
  and `redis_config.py` — the same override pattern already covered them.
- **`dict` → `dict[str, object]`** in `celery_config.py` and `state_store.py`,
  and `DiskOrgConfigStore._persist` stops assigning `_convert_secrets()`'s
  `object` return back over a `dict` name, because the recursion cannot promise
  it hands back a mapping.
- **`raise self.retry(exc=err) from err`**, preserving the cause on the path
  where `retry` returns rather than raises.
- **`import httpx  # noqa: E402`** in `scripts/register_worker.py`, where the
  import must follow a `sys.path` insertion.

Suppressions, recorded plainly because an unexplained suppression is how a gate
stops meaning anything:

| Suppression | Scope | Why |
| :--- | :--- | :--- |
| `D102` | `src/modules/seo/deliverables/masterfile_*.py` | The only undocumented public member is the `metadata` property, which overrides an already-documented abstract property and whose body is a single literal. Ruff has no inherited-docstring awareness; 21 copies of "Return the metadata" would make the convention mean less everywhere else |
| `S105`, `S106` | `tests/**` | A test for `SecretStr` masking has to pass a literal secret in to check it comes back masked. Scoped to tests so the rule keeps full force over `src/**`, the only place a literal credential is a leak |
| `S101` | `scripts/chaos_test.py` only | `assert` is that harness's assertion mechanism, as it is under pytest. Scoped to the one file so a real script cannot smuggle an `assert` into a path that runs under `python -O` |
| `celery.*` `ignore_missing_imports` | one module | as above |

## 3. Design decisions

**Scope every suppression to the narrowest unit that works.** `S101` went to one
file, not to `scripts/**`; `D102` to one filename glob, not to the package. The
alternative — a global `ignore` entry — is indistinguishable from the rule not
existing.

**Fix the test when the test is wrong.** Two of the three failures were defects
in the tests (§4). Changing the code to satisfy them would have broken
documented behaviour in one case and made a timing bound louder in the other.

**Raise no floor, lower no floor.** Coverage came out at 88.40% against the 85%
floor; the floor was left alone. Raising it in the same cycle that repaired the
gate would make the next unrelated change look like a regression.

## 4. Bugs found and fixed

### 4.1 Two failing tests that were wrong, and code that was right

**The GSC circuit-breaker recovery test asserted recovery with zero elapsed
time.** It opened the circuit with five `record_failure()` calls and then
expected a successful refresh to close it, in the same instant. The design
forbids exactly that: `is_open()` is what moves `OPEN → HALF_OPEN` once
`recovery_timeout_s` (30s) has passed, and `record_success()` closes only from
`HALF_OPEN`. `tests/core/test_circuit_breaker.py` already pins the opposite
behaviour, so the suite contained two tests asserting contradictory contracts.
Corrected by rewinding the recorded failure time instead of sleeping 30s, and
split into two tests so both halves of the contract are stated: the circuit
**stays open inside the window even when the endpoint would answer**
(`mock_post.assert_not_called()`), and a probe **after** the window closes it.

**A `url_filter` performance test was bounded at 0.1s against a 4–15ms loop.**
Under `pytest --cov`, tracing overhead alone can exceed the margin, so the test
failed for reasons that have nothing to do with the code under test. A bound the
profiler can trip measures the profiler. Raised to 1.0s, which still catches an
accidental O(n²) and no longer reports the coverage plugin as a defect.

**A dead local function in `test_redis_token_bucket.py`** —
`register_script_side_effect`, containing the condition
`if "org:1" in script_text or True:` — was never called and was flagged by lint.
Deleted rather than annotated; `mock_redis.register_script.side_effect` was
already set by the line below it.

### 4.2 A real product bug the gate caught

**`validateDomain` accepted `example..com` and `example-.com` as valid crawl
targets.** The old pattern — written below with spaces inserted at each `]` `(`
boundary, because `scripts/drift_check.py`'s link regex reads that adjacency as a
markdown link and would report this line as a broken one —

```
^[a-z0-9] ( [a-z0-9-]* \. )* [a-z0-9] ( [a-z0-9-]* )?$
```

lets a label match the empty string, so any run of consecutive dots passed, and it never
constrained the last character of a label. Replaced with a per-label pattern
repeated after each dot (RFC 1123 §2.1: a label is non-empty and neither starts
nor ends with a hyphen). Verified here against both regexes directly:

| Input | Old | New |
| :--- | :--- | :--- |
| `example..com` | accepted | rejected |
| `example-.com` | accepted | rejected |
| `-example.com` | rejected | rejected |
| `www.example.com` | accepted | accepted |
| `a.b` | accepted | accepted |

### 4.3 The proof the gate had not been run

`tests/modules/seo/deliverables/test_masterfile_response_codes.py` declares

```python
__all__ = ["test_response_codes_empty_export", "test_response_codes_with_data"]
```

in its first commit, `2a6b6cc`. There has never been a
`test_response_codes_with_data` in that file — the third test is
`test_response_codes_with_response_csv`. Ruff's `F822` (undefined name in
`__all__`) is enabled in this repository, so the gate could not have been run
green at that commit, or at any commit since, until this cycle. That single line
is stronger evidence than any count of failures: the "green gate" attached to
`2a6b6cc` was not observed.

## 5. Corrections

### 5.1 `CLAUDE.md` §8 lists a file that exists and is in use

§8 "Known gaps — do not describe these as working" opens with:

> `src/core/circuit_breaker.py` — does not exist.

It exists. Measured in this tree: `src/core/circuit_breaker.py` (4,279 bytes, dated
2026-09-09), imported by `src/core/postgres_store.py`,
`src/core/worker_dispatch_signing.py` and
`src/integrations/gsc_token_manager.py`, with 20 test functions in
`tests/core/test_circuit_breaker.py`. `docs/ARCHITECTURE.md` already corrected
this in cycle 0098 and records the nuance that matters: nothing wires a breaker
to the ADR 0015 worker-dispatch HTTP channel, which is an accepted v1 gap (ADR
0015 condition 10) and is *not* the same statement as the file not existing.

This is the same drift class the register exists to prevent, and it is at the top
of the register. **This entry does not edit `CLAUDE.md`**: that file is the
operating contract, and a scribe run is not the right authority to rewrite it.
The exact change needed is one line moved out of §8's gap list and into "Closed
since the audit":

> - `src/core/circuit_breaker.py` — exists (`CLOSED`/`OPEN`/`HALF_OPEN`, 5-failure
>   threshold, 30s recovery). Wired into `core/postgres_store.py`,
>   `core/worker_dispatch_signing.py` and `integrations/gsc_token_manager.py`; 20
>   tests. Nothing wires a breaker to ADR 0015's worker-dispatch HTTP channel —
>   that remains an accepted v1 gap (ADR 0015 condition 10), which is a different
>   statement (build-log 0098, 0110).

`README.md`'s own `core/circuit_breaker.py | ❌ Not started` row carried the same
falsehood and **has** been corrected in this session, since README is a drift
target rather than the contract.

### 5.2 A gate reported green was not a gate that ran

Three separate commits in the recent history assert a passing gate:
`8d606db` ("Quality Gate: PASS", corrected in cycle 0109 §5.1), `0d26e26`
("Complete … parity", corrected in cycle 0107 §5.1) and `2a6b6cc` (§4.3 above).
The tree those commits describe had 62 ruff errors, 16 mypy errors and 3 failing
tests in it when this cycle started. The count is not the interesting part; the
pattern is — "green" was asserted in a commit message rather than pasted from a
run, which is the practice CLAUDE.md §4 and the build-log's rule 5 both exist to
stop.

## 6. Explicitly not done

- **`scripts/chaos_test.py` validates nothing, and was not fixed.** At lines
  164–170 it sets `job_count = 1` and `charge_count = 1` and then asserts each
  equals 1; the loop above those lines computes a different value that is
  discarded. Its condition on line 154,
  `if idempotency_key not in {idempotency_key: "seen"}`, is a literal built from
  the key it tests, so it is constant. One of its five checks asserts nothing at
  all. This cycle made it *lint-clean* (`S101` scoped, `main()` typed to return
  an exit code) and deliberately did not rewrite it — making a harness that
  proves nothing pass a linter is exactly the pattern this session is about, and
  it is recorded here rather than quietly tidied. It is also not in the gate, so
  nothing depends on it.
- **`src/core/celery_config.py` violates CLAUDE.md §1.3 and was not fixed.**
  Lines 127 and 152 do a function-local `import os` and read
  `os.getenv("REDIS_URL") or os.getenv("REDIS_PRIVATE_URL")` directly, instead of
  going through `get_settings()` — which the same module already imports and uses
  at line 35. Out of scope for a gate repair (it needs a `Settings` field and a
  test), and recorded so it is not found a third time.
- **`src/core/postgres_store.py` cannot be type-checked here.** `psycopg` is not
  installed in the local venv, unchanged since build-log 0098.
- **No coverage floor raise.** 88.40% measured, 85% floor kept (§3).
- **The `D102` exemption is a real loss.** If a masterfile service ever gives
  `metadata` a non-trivial body, nothing will require it to be documented.
- **Three UI test files remain timing-fragile** and are worked around at the
  harness level rather than hardened — see cycle 0111 §6.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `pyproject.toml` | +38/-1 — per-file ruff ignores with rationale, `celery.*` mypy override |
| `src/workers/job_executor.py` | +26/-7 — annotated tasks, 2 narrow `type: ignore`, `raise ... from err` |
| `src/core/celery_config.py` | +2/-2 — `dict[str, object]` |
| `src/core/rate_limiter.py` | +2/-2 — bare ignores removed |
| `src/core/redis_config.py` | +1/-1 — bare ignore removed |
| `src/core/state_store.py` | +6/-5 — typed `serializable`, `_convert_secrets` result not reassigned |
| `scripts/register_worker.py` | +1/-1 — scoped `noqa: E402` |
| `scripts/chaos_test.py` | +7/-3 — lint only; see §6 |
| `rankuno-ui/src/lib/validation.ts` | +10/-2 — `validateDomain` per-label pattern |
| `tests/integrations/test_gsc_token_manager.py` | +43/-11 — recovery test corrected and split |
| `tests/core/test_redis_token_bucket.py` | -4 — dead local removed |
| `tests/modules/seo/test_url_filter.py` | perf bound 0.1s → 1.0s |
| `tests/modules/seo/deliverables/test_masterfile_response_codes.py` | +5/-1 — `__all__` corrected |
| `tests/modules/seo/deliverables/test_masterfile_registry.py` | +5/-3 |
| `README.md` | `core/circuit_breaker.py` row corrected (§5.1) |

## 8. Follow-ups

1. Apply the `CLAUDE.md` §8 edit in §5.1. Until then the operating contract tells
   every new agent that a file three modules depend on does not exist.
2. Rewrite `scripts/chaos_test.py` so each check derives its value from the system
   under test, or delete it. A harness that asserts a literal it just assigned is
   worse than no harness, because it is named `chaos_test`.
3. Route `celery_config.py`'s Redis URL through `get_settings()`.
4. Four code comments in this session's work cite "cycle 0104" / "build-log 0104"
   — `src/modules/seo/deliverables/masterfile_base.py:220`,
   `src/modules/seo/deliverables/masterfile_source.py:8`,
   `tests/api/test_masterfile_endpoints.py:1` and
   `tests/modules/seo/deliverables/test_masterfile_source.py:1`. 0104 is an
   existing committed entry (`0104-masterfile-framework-and-phase-1-foundation.md`);
   the work they mean is cycle **0107**. Not changed here because source files were
   off-limits during the operator's gate run; the one occurrence in a test
   docstring that also carried a wrong design claim was corrected (cycle 0108 §5).
