# Cycle 0078: The fields that never left the call site

- **Date**: 2026-09-08
- **Scope**: Bug fix in `src/core/logger.py`: `get_logger()` returned a stock `logging.LoggerAdapter(..., {})`, whose `process()` on Python 3.11 replaces the caller's `extra=` dict with the adapter's empty one, so no structured field logged anywhere under `src/` ever reached a `LogRecord`. Replaced with a 12-line merging adapter; six regression tests; one line in CLAUDE.md §8.
- **Commit**: uncommitted at time of writing
- **Quality gate**: **RED** — `3 failed, 1967 passed, 1 skipped` Python (all three in `tests/api/test_server.py`, none touching the logger; see §1.2) / `232 passed` UI / `Total coverage: 93.81%`. Per CLAUDE.md §1.6 this task is **not complete**.

**Origin.** Build-log [0074 §4.3](0074-absent-is-not-empty.md) found the defect while trying to verify the Screaming Frog adapter's logging contract; the docs-scribe reproduced it there with a probe call. 0077 §4.3 and §8.3 re-reported it and handed it to `core`. This cycle is that handoff.

---

## 1. Gate results

`verify.ps1` after `-Fix` (the fix only re-wrapped the `process` signature). Verbatim from the bug-fixer's run:

```
PASSED: Format
All checks passed!
PASSED: Lint
PASSED: Type check
TOTAL                                                           7676    384   1920    138    94%
Required test coverage of 85.0% reached. Total coverage: 93.81%
FAILED tests/api/test_server.py::TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup
FAILED tests/api/test_server.py::TestCancel::test_cancelling_frees_the_slot
FAILED tests/api/test_server.py::TestCancel::test_the_reason_says_the_thread_may_survive
3 failed, 1967 passed, 1 skipped, 1 warning in 113.89s (0:01:53)
FAILED: Tests
 Test Files  21 passed (21)
      Tests  232 passed (232)
PASSED: UI Component Tests
VERIFICATION FAILED: Tests
```

### 1.1 The logger tests

Before the fix, against the committed `logger.py` (bug-fixer's run):

```
E       AttributeError: 'LogRecord' object has no attribute 'job_id'
E       KeyError: 'job_id'
E       AssertionError: assert 'adapter' == 'caller'
E       KeyError: 'job_id'
E       AssertionError: assert 'ctx-trace' == 'explicit'
FAILED tests/core/test_logger.py::test_caller_extra_reaches_record
FAILED tests/core/test_logger.py::test_caller_extra_reaches_json_output
FAILED tests/core/test_logger.py::test_caller_keys_win_over_adapter_keys
FAILED tests/core/test_logger.py::test_trace_id_falls_back_to_context
FAILED tests/core/test_logger.py::test_explicit_trace_id_extra_wins_over_context
========================= 5 failed, 1 passed in 0.15s =========================
```

The one that passed before the fix is `test_adapter_extra_survives_call_without_extra`: the stock adapter does forward its *own* dict, it just never had anything in it.

After (bug-fixer's run; re-run by the docs-scribe, `......` 6 passed):

```
collected 6 items
tests\core\test_logger.py ......                                         [100%]
============================== 6 passed in 0.04s ==============================
```

`tests/core`: `253 passed in 0.85s`. `mypy --strict src/core/logger.py tests/core/test_logger.py`: `Success: no issues found in 2 source files`.

### 1.2 The three red tests are not this cycle's

All three failures are in `tests/api/test_server.py`. Neither that file nor `src/api/server.py` was touched in this cycle; both carry **uncommitted edits from another session** (`git status`: ` M src/api/server.py`, ` M tests/api/test_server.py`; 129 insertions, 7 deletions across the two). The three test functions exist unchanged in `HEAD` (lines 366, 857, 879) and in the working tree (367, 858, 880).

Evidence gathered by the bug-fixer and the docs-scribe, in order:

| Run | `logger.py` | Selection | Result |
| :--- | :--- | :--- | :--- |
| bug-fixer | committed | full gate | `test_cancelling_frees_the_slot` fails |
| bug-fixer | committed | full gate | `test_the_reason_says_the_thread_may_survive` fails |
| bug-fixer | fixed | `test_server.py` alone | 113 passed, including `test_orphaned_jobs_are_failed_on_startup` and `test_the_reason_says_the_thread_may_survive` |
| bug-fixer | fixed | full gate | the 3 failures in §1 |
| docs-scribe | fixed | the 3 tests only | `test_cancelling_frees_the_slot` fails (`assert 409 == 200`); 2 pass |
| docs-scribe | fixed | the 3 tests only, again | `test_cancelling_frees_the_slot` and `test_the_reason_says_the_thread_may_survive` fail |
| docs-scribe | fixed | the 3 tests only, `-o addopts=""` | `3 passed in 0.87s` |

The project's `addopts` is `-q --strict-markers --strict-config`; it does not affect ordering, so the three docs-scribe runs differ only in timing. The uncommitted `server.py` `lifespan` moved orphan recovery from an inline call to a daemon thread:

```diff
-        orphans = resolved_store.recover_orphans()
-        if orphans:
-            _logger.warning("recovered_orphaned_jobs", extra={"count": len(orphans)})
+        # Recover orphans asynchronously so startup does not block on large job stores.
+        def _recover_in_bg() -> None:
+            ...
+        threading.Thread(target=_recover_in_bg, daemon=True).start()
```

A test that marks a job RUNNING and then cancels it now races a background recovery of that same job, which is what a `409` on cancel and a flaky startup-recovery assertion look like. That is a diagnosis from the diff, not a proven root cause; the owner of those edits has the handoff (§8.1). What *is* established: the same tests fail on the committed logger and pass with the fixed one in some orderings, so `logger.py` is neither necessary nor sufficient for the failures.

### 1.3 Drift check

Bug-fixer's run, before this entry existed:

```
PASSED: no drift detected across 140 markdown files.
```

Docs-scribe's run after this entry and the README / ARCHITECTURE edits (`.\.venv\Scripts\python.exe scripts\drift_check.py`, exit 0):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

The count did not move from 140 to 141 when this entry was added because `drift_check.py` enumerates `git ls-files "*.md"` (line 52): **tracked files only**. Every untracked entry — 0072 through 0078 at time of writing, all `??` in `git status` — is outside both its count and its relative-link check. The two links this cycle added (`0074-absent-is-not-empty.md` from this entry; `docs/build-log/0078-...` from `README.md`) were checked by hand and resolve. The checker will cover them once the entries are committed. A checker that also walks untracked files is a small follow-up (§8.5).

---

## 2. What landed

### 2.1 `src/core/logger.py` — `_MergingAdapter`

```python
class _MergingAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        """Merge adapter and caller extras. Caller keys win: the call site is more specific."""
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs
```

`get_logger()` now returns `_MergingAdapter(logging.getLogger(f"rankuno.{name}"), {})`. The annotated return type (`logging.LoggerAdapter[logging.Logger]`) and every call site are unchanged; no caller was edited. The class is private because nothing outside `logger.py` should need to name it; the tests build a second adapter via `type(get_logger(...))` rather than importing it.

Why a subclass rather than `merge_extra=True`: that keyword exists only on Python 3.13+, and the project floor is 3.11 (this workstation runs 3.11.9). Passing it on 3.11 is a `TypeError`.

### 2.2 `tests/core/test_logger.py` — 6 tests, new file

| Test | Asserts |
| :--- | :--- |
| `test_caller_extra_reaches_record` | `record.job_id` exists after `log.info("m", extra={"job_id": "j1"})` |
| `test_caller_extra_reaches_json_output` | `JsonFormatter` emits `job_id` and `rows` from the caller's `extra` |
| `test_caller_keys_win_over_adapter_keys` | adapter `{"k": "adapter", "only": 1}` + caller `{"k": "caller"}` → `k == "caller"`, `only == 1` |
| `test_adapter_extra_survives_call_without_extra` | adapter-level keys still forwarded when the call passes no `extra` |
| `test_trace_id_falls_back_to_context` | `trace_context("ctx-trace")` still supplies `trace_id` when the caller does not |
| `test_explicit_trace_id_extra_wins_over_context` | an explicit `extra={"trace_id": ...}` beats the context var |

The last two exist because `JsonFormatter` already had a `trace_id` fallback to the context variable, and it was never exercised by a caller-supplied `trace_id` before, since none could arrive.

### 2.3 `CLAUDE.md` §8 "Closed since the audit", line 195

One bullet added by the bug-fixer, verified present by the docs-scribe:

> `src/core/logger.py` — `get_logger` dropped every caller `extra=` field on Python 3.11 (stock `LoggerAdapter.process` replaced it); now merged, caller keys win (6 tests).

### 2.4 Seen in real output

While re-running the `test_server.py` failures (§1.2), the captured stderr of the FastAPI app under test showed the fix working on an unmodified production call site:

```
{"ts": "2026-09-08T12:01:20.292786+00:00", "level": "WARNING", "logger": "rankuno.core.state_store", "message": "orphaned_jobs_recovered", "count": 1}
{"ts": "2026-09-08T12:01:20.292786+00:00", "level": "WARNING", "logger": "rankuno.api.server", "message": "recovered_orphaned_jobs", "count": 1}
```

Before this cycle those lines ended at `"message"`.

---

## 3. Design decisions

### 3.1 Caller keys win over adapter keys

`{**self.extra, **caller_extra}`: the call site is the more specific of the two. An adapter's `extra` is a namespace-wide default; a call that names the same key is overriding it on purpose. The alternative (adapter wins) would make it impossible for a call to override a namespace default, and would also break the explicit `trace_id` case in §2.2. This matches what CPython 3.13's `merge_extra=True` does.

### 3.2 A private subclass, not a public one, and no change to `get_logger`'s return type

The return annotation stays `logging.LoggerAdapter[logging.Logger]`. Widening it to `_MergingAdapter` would export a private name and change nothing for callers, who only call `.info(...)` and friends. Keeping the annotation also means no caller file had to be touched, which keeps this cycle's diff to two files plus one CLAUDE.md line.

### 3.3 Fix the adapter, not the formatter

`JsonFormatter` and `_RESERVED_ATTRS` were suspected first (they are where the fields are read). Setting `job_id` directly on a `LogRecord` proved the formatter emits it; the loss happens earlier, in `process()`. Changing the formatter would have been the wrong layer.

---

## 4. Bugs found and fixed

### 4.1 `get_logger()` discarded every caller `extra=` (present since the initial commit)

`git log -- src/core/logger.py` shows one commit: `8fb66b1 chore: initial commit - governance foundation and Phase 1 safety core`. The defect shipped with the file and has been live through all 77 prior cycles.

Pre-fix `src/core/logger.py:167`:

```python
return logging.LoggerAdapter(logging.getLogger(f"rankuno.{name}"), {})
```

Python 3.11.9 stdlib, `logging/__init__.py`, `LoggerAdapter.process`:

```python
def process(self, msg, kwargs):
    kwargs["extra"] = self.extra
    return msg, kwargs
```

`self.extra` is `{}`, so the caller's dict is overwritten before `Logger._log` builds the record. Observed with a capturing handler on `rankuno.probe`:

```
has job_id: False | adapter.process -> ('m', {'extra': {}})
json: {"ts": "...", "level": "INFO", "logger": "rankuno.probe", "message": "probe"}
```

Consequence, stated plainly: every `extra=` payload anywhere under `src/` — the guardrail audit trail (`tool`, `risk_class`, `status`), crawl telemetry counts, job-store `job_id`s, the GSC client's request accounting, the Screaming Frog adapter's `rows_read` / `urls_retained` — has been dropped from the JSON audit log since the first commit. The test suite did not notice because tests assert on `caplog` records or on recording stubs, and the tests that did exercise the adapter end-to-end asserted on `message` alone.

`JsonFormatter` and `_RESERVED_ATTRS` are sound and were not changed: with `record.job_id = "j1"` set directly, the formatter emitted `"job_id": "j1"`.

### 4.2 No bug in the specification

The `get_logger` docstring and the module docstring describe structured JSON logging with caller-supplied fields. The contract was right; the implementation never met it.

---

## 5. Corrections

1. **Build-log 0074 §4.3** ("no structured field reaches the JSON output"; "the brief's acceptance criterion 'log records carry counts' ... cannot be met at the output until this is fixed") — **superseded** by this cycle. The statement was true when written and is left intact. The Screaming Frog adapter's counts now reach the output without any change to the adapter.
2. **Build-log 0077 §4.3 and §8.3** — same statement, same status: superseded, not edited.
3. **`README.md` implementation-status table** — the row "`core/logger.py` — structured `extra=` fields on log records: Dropped on Python 3.11 ... Found in cycle 0074, not fixed" was true until this cycle. Updated in this cycle to "fixed", pointing here.
4. **`docs/ARCHITECTURE.md` "not yet built" table** — the row "`core/logger.py` `extra=` on records ... Found in build-log 0077 §4.3" cited 0077 where the finding was 0074 §4.3 (0077 repeated it). The row is removed in this cycle because the defect is closed; the provenance is recorded here instead.
5. **Earlier cycles that said logs "carry" a field** (for example 0012 job store, 0016 telemetry, 0024 provenance) were describing the call site, not the output. No earlier entry pasted a JSON log line showing a structured field, so none is numerically wrong; but any reader who inferred that the audit trail on disk held those fields was misled until now.

---

## 6. Explicitly not done

- **No `merge_extra=True`.** It needs Python 3.13; the floor stays 3.11. If the floor is ever raised to 3.13, `_MergingAdapter` can be deleted and `get_logger` can pass `merge_extra=True`; the tests in `tests/core/test_logger.py` are written against `get_logger`'s behaviour, not the class, so they would still hold.
- **No changes to `JsonFormatter`, `_RESERVED_ATTRS`, `trace_context`, or `setup_logging`.** Examined and found correct (§3.3).
- **No caller was edited.** The fix is invisible at the call site by design.
- **No sweep of historical logs.** Anything written to the JSON audit trail before this fix is missing its structured fields and cannot be reconstructed.
- **No audit of which tests assert on log output.** §4.1 says why the suite missed this; a test-engineer pass to add output-level assertions to the guardrail and job-store tests is the systematic fix and was outside this brief.
- **Not committed.** The gate is red (§1, §1.2) and the working tree carries another session's uncommitted edits to `src/api/server.py`, `tests/api/test_server.py`, `treeOverlay.*`, `gsc_*`, and `screaming_frog_*`. Committing the logger fix alone would need a partial stage that this cycle did not attempt.
- **The three `test_server.py` failures were not fixed**, and must not be from this cycle: they belong to the other session's edits (§1.2, §8.1).

---

## 7. Files changed

```
src/core/logger.py              +18 -1   _MergingAdapter; get_logger returns it; MutableMapping import
tests/core/test_logger.py       new      6 tests
CLAUDE.md                       +1       §8 "Closed since the audit", line 195
README.md                       ~1 row   implementation-status row for core/logger.py
docs/ARCHITECTURE.md            -1 row   "not yet built" table row for core/logger.py
docs/build-log/README.md        +1 row   index
docs/build-log/0078-the-fields-that-never-left-the-call-site.md   this entry
```

---

## 8. Follow-ups

1. **To the owner of the uncommitted `src/api/server.py` / `tests/api/test_server.py` edits**: `TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup`, `TestCancel::test_cancelling_frees_the_slot`, `TestCancel::test_the_reason_says_the_thread_may_survive` fail nondeterministically under the full gate and in isolation (§1.2 table). `test_cancelling_frees_the_slot` returns `409` where `200` is asserted. The daemon-thread orphan recovery in the new `lifespan` is the likely cause; the tests need either a deterministic recovery (join the thread before `yield`, or keep it synchronous under test) or a fixture that waits for it.
2. **Bug-fixer's side note on `tests/api/test_server.py`**: the bug-fixer reported an em dash rendered as `�` in a comment, suggesting a non-UTF-8 write. The docs-scribe checked the bytes: the file decodes as UTF-8 without error and contains no U+FFFD; every em dash is the correct three-byte sequence `\xe2\x80\x94` (lines 100, 158, 202, 226, 736, 748, 790, 868, 1251, 1252 among others). The `�` was a console rendering artefact (a cp1252 terminal displaying UTF-8), not a defect in the file. **No action needed**; recorded so the next reader does not re-investigate.
3. **Test-engineer**: add output-level assertions (`JsonFormatter().format(record)`) to at least one guardrail-engine test and one job-store test, so a regression of this class is caught by the suite rather than by a reader of the logs (§6).
4. **When the Python floor reaches 3.13**: replace `_MergingAdapter` with `merge_extra=True` (§6).
5. **`scripts/drift_check.py`** checks tracked markdown only (§1.3). In a working tree with seven uncommitted build-log entries, "no drift" says nothing about their links. Consider unioning `git ls-files` with `git ls-files --others --exclude-standard`.
