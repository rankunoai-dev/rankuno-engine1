# Cycle 0085: A CLI for a pipeline that already existed

- **Date**: 2026-09-09
- **Scope**: Chain the already-shipped deliverables pieces (loaders, rulebook,
  scoring, workbook) into one function and one operator CLI, closing the
  deliverables pipeline that Phase 0/1/2a/2b built individually but never
  connected end to end.
- **Commit**: uncommitted at time of writing
- **Quality gate**: whole-repo `verify.ps1` **RED**, pre-existing/concurrent
  failures only (none in the files this cycle touched); targeted deliverables
  suite green, 106 passed; two new files at 100% coverage in isolation

## 1. Gate results

Origin: before this cycle, `AuditDataset` could be built two ways
(`load_screaming_frog_bundle` or `to_audit_dataset`), themed with
`apply_rulebook`, scored with `score_dataset`, and rendered with
`build_workbook` — but nothing called all four in sequence. An operator
wanting a client workbook had to hand-wire a script from four separate
imports every time. This cycle closes that gap with one function
(`run_deliverable_pipeline`) and one CLI (`scripts/build_deliverable.py`).

Full whole-repo `verify.ps1` output (verbatim tail, as run by the implementing
agent this session):

```
=== Lint ===
S106 Possible hardcoded password assigned to argument: "redis_password"
  --> tests\core\test_redis_config.py:53:34
S105 Possible hardcoded password assigned to: "password"
   --> tests\core\test_redis_config.py:107:54
Found 2 errors.
FAILED: Lint

=== Type check ===
src\core\postgres_store.py:22: error: Cannot find implementation or library stub for module named "psycopg"  [import-not-found]
src\core\redis_config.py:63: error: Unused "type: ignore" comment  [unused-ignore]
Found 2 errors in 2 files (checked 82 source files)
FAILED: Type check

=== Tests ===
ERROR collecting tests/api/test_idempotency.py
ImportError: cannot import name 'make_app' from 'src.api.server'
FAILED: Tests

=== UI Component Tests ===
Test Files 22 passed (22)
Tests 248 passed (248)
PASSED: UI Component Tests

VERIFICATION FAILED: Lint, Type check, Tests
```

None of the three failure categories reference `pipeline.py`,
`build_deliverable.py`, or their tests. All three are inside files this
cycle never touched: `tests/core/test_redis_config.py`,
`src/core/postgres_store.py`, `src/core/redis_config.py`,
`tests/api/test_idempotency.py`. `git status --porcelain` before and after
this cycle's work shows only `src/core/rate_limiter.py` (modified) and
`tests/core/test_redis_token_bucket.py` (new) changing outside this cycle's
four files — a concurrent multi-tenant/Redis/Celery/idempotency session's own
in-flight work, per the scope boundary this cycle was given. Recorded honestly
per CLAUDE.md §1.6: the whole-repo gate is **not** green, while this cycle's
own deliverable is clean in isolation.

Targeted verification, independently re-run by this build-log entry's author
rather than taken on trust from the implementing agent's report:

```
$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables -v
...
tests\modules\seo\deliverables\test_pipeline.py .....                    [ 35%]
tests\modules\seo\deliverables\test_build_deliverable.py .........       [100%]
14 passed in 3.22s   (the new tests, isolated)

$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables
106 passed in 4.99s   (whole deliverables suite, all files)

$ .venv/Scripts/python.exe -m pytest tests/modules/seo/test_import_boundary.py -v
9 passed in 0.37s

$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables \
    --cov=src.modules.seo.deliverables.pipeline --cov-report=term-missing
TOTAL   16 stmts, 0 miss, 2 branch, 0 partial   Cover 100%

$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables \
    --cov=scripts.build_deliverable --cov-report=term-missing
scripts\build_deliverable.py   55 stmts, 1 miss (line 132, the
  `if __name__ == "__main__": raise SystemExit(main())` guard), 97% cover
```

Both new source files match the implementer's claimed line counts exactly
(`pipeline.py` 90 lines, `build_deliverable.py` 132 lines; test files 170 and
230 lines respectively — `wc -l` confirms all four).

## 2. What landed

- `src/modules/seo/deliverables/pipeline.py` (90 lines) —
  `run_deliverable_pipeline(dataset, *, normalize, rulebook_path=None,
  rulebook_lenient=False, weights=None, output_dir=None) -> Path`. Applies
  the rulebook if `rulebook_path` is given, scores with `score_dataset`,
  renders with `build_workbook`. Imports only `contracts.audit`,
  `contracts.catalogue`, `contracts.url_normalizer`, `deliverables.rulebook`,
  `deliverables.scoring`, `deliverables.workbook` — no `page_classifier`
  import, confirmed by `tests/modules/seo/test_import_boundary.py` (still 9
  passed, unchanged in count, meaning this file did not add a new violation
  for that test to catch).
- `scripts/build_deliverable.py` (132 lines) — the operator CLI. Two
  subcommands, `sf-bundle <bundle_path>` and `engine-crawl
  <job-id-or-result.json>`, both converging on one call to
  `run_deliverable_pipeline`. `_load_result()` reads a crawl result from a
  path or a job id under `.jobs/`, duplicated from
  `reconcile_screaming_frog.py` rather than imported — see §3.

## 3. Design decisions

**`pipeline.py` never loads a source; loading dispatch stays in the script**
(decided in Step 3 this session, before implementation). The two loaders —
`screaming_frog_adapter.load_screaming_frog_bundle` (bundle path + optional
timestamp) and `page_classifier.audit_export.to_audit_dataset` (a sequence of
`FullPageIntelligenceProfile` + optional timestamp) — take different argument
shapes and live on opposite sides of the ADR 0011 d.1 import seam. Only one of
them (`to_audit_dataset`) can be reached without importing `page_classifier`.
A `Callable[[], AuditDataset]` injected into `pipeline.py` would look like it
erased that asymmetry, but would not: the caller would still have to import
`page_classifier` to build the callable in the `engine-crawl` case, which
would just move the forbidden import one frame further out rather than remove
it. The import boundary belongs at the loaders, not inside the pipeline, so
`scripts/build_deliverable.py` — the one layer allowed to import both
packages, the same pattern `scripts/diff_against_rae.py` already uses — is
where the two loaders' outputs converge into the one `AuditDataset` shape
`run_deliverable_pipeline` accepts.

**Rulebook omission vs. a missing rulebook file are different outcomes.**
Omitting `--rulebook` entirely means no theming was ever intended for this
run — `rulebook_path=None` skips `apply_rulebook` silently, no error, nothing
to report. A `--rulebook` path that is given but does not exist on disk is a
hard `RulebookMissingError`, propagated from `Rulebook.from_xlsx`, unless
`--lenient-rulebook` is passed explicitly (`rulebook_lenient=True`). This
mirrors ADR 0011 point 6 and the existing `rulebook.py` contract from
build-log 0083 — this cycle did not change that contract, only wired a CLI
flag onto it.

**`_load_result` is duplicated, not imported, from
`reconcile_screaming_frog.py`.** That script's own docstring states nothing
else depends on it. Importing a helper across two operator-facing scripts
that was never designed to be shared would make a change to either script
silently risk breaking the other. The duplication is 14 lines; the coupling
it avoids was judged the worse cost.

## 4. Bugs found and fixed

None found in `pipeline.py`, `build_deliverable.py`, or the modules they call
— the four functions they chain (`load_screaming_frog_bundle`,
`to_audit_dataset`, `apply_rulebook`, `score_dataset`, `build_workbook`) were
each already tested in prior cycles (0074, 0077, 0079, 0083, 0084) and this
cycle is orchestration, not new logic. No spec bugs found in
`DELIVERABLES_IMPLEMENTATION_PLAN.md` either.

## 5. Corrections

The implementing agent's final report claimed "Full tests/modules/seo/deliverables
suite: 115 passed (14 new + 101 pre-existing)" and that "pipeline.py and
build_deliverable.py [are] both among '38 files skipped due to complete
coverage'" in a full-suite run. Both numbers do not hold up under an
independent re-run:

- **Test count**: the full `tests/modules/seo/deliverables` suite is **106
  passed**, not 115. `--collect-only -q` breaks it down as
  `test_build_deliverable.py: 9`, `test_diff_against_rae.py: 13`,
  `test_pipeline.py: 5`, `test_rulebook.py: 50`, `test_scoring.py: 12`,
  `test_workbook.py: 17` — 9+13+5+50+12+17 = 106. The 14 new tests (5+9) are
  correct; the pre-existing count is 92, not 101, and 92+14=106, not 115.
  Where the extra 9 came from is not established — it does not match any
  combination of the files present in the directory today.
- **`build_deliverable.py` coverage claim**: `pyproject.toml`'s
  `[tool.coverage.run]` sets `source = ["src"]`. `scripts/` is outside that
  source root, so `scripts/build_deliverable.py` is **not measured at all**
  by the coverage config `verify.ps1` runs — it cannot appear among any
  "N files skipped due to complete coverage" list produced by that gate,
  full-suite or otherwise. Measured explicitly with `--cov=scripts.build_deliverable`,
  it is 97% covered (55 statements, 1 miss — the `if __name__ == "__main__":`
  guard on line 132, which is expected to be unreachable under pytest).
  `pipeline.py`, which *is* under `src/`, is independently confirmed at 100%
  (16 statements, 0 miss).

Neither correction changes the substance of the cycle — the new code is
tested and the boundary is enforced — but the specific numbers reported were
not reproducible and are corrected here per CLAUDE.md §2's rule against
publishing a number that was not independently checked.

## 6. Explicitly not done

- **No HTTP endpoint.** `run_deliverable_pipeline` and
  `build_deliverable.py` are local-only. Wiring a `POST` route that would let
  the API build and return a workbook is deferred to its own cycle, with
  `security-auditor` running first per CLAUDE.md §2 Step 5 (this pipeline
  writes files and would need its own network/cost/security review before
  being exposed over HTTP).
- **`pipeline.py` does not own source-loading.** This is the Step 3 design
  decision in §3, not an oversight: the loaders stay asymmetric and the
  import boundary stays at the script layer.
- **`_load_result` is not consolidated with `reconcile_screaming_frog.py`'s
  copy.** Deliberate, per §3 — left as two copies rather than one shared,
  undocumented dependency.

## 7. Files changed

```
src/modules/seo/deliverables/pipeline.py                    | new, 90 lines
scripts/build_deliverable.py                                 | new, 132 lines
tests/modules/seo/deliverables/test_pipeline.py               | new, 170 lines, 5 tests
tests/modules/seo/deliverables/test_build_deliverable.py      | new, 230 lines, 9 tests
README.md                                                     | drift update, this cycle
docs/ARCHITECTURE.md                                          | drift update, this cycle
docs/build-log/README.md                                      | index entry, this cycle
```

Not part of this cycle's diff, present in `git status` as another session's
in-flight work: `src/core/rate_limiter.py` (modified),
`tests/core/test_redis_token_bucket.py` (new).

## 8. Follow-ups

- **Handoff to the owner of the Redis/Celery/idempotency work**: the
  whole-repo gate is red on three unrelated fronts —
  1. Lint: `S106`/`S105` possible hardcoded password in
     `tests/core/test_redis_config.py` (lines 53, 107).
  2. Type check: `psycopg` has no library stub, breaking
     `src/core/postgres_store.py:22`; an unused `# type: ignore` in
     `src/core/redis_config.py:63`.
  3. Tests: `tests/api/test_idempotency.py` fails to collect —
     `ImportError: cannot import name 'make_app' from 'src.api.server'`. This
     one specifically blocks the whole-repo test count from being read at
     all and should be the first of the three fixed.
- A side note on process, not a defect: the implementing agent ran
  `verify.ps1 -Fix`, which twice reformatted `alembic/versions/0001_initial_schema.py`
  (an unrelated pre-existing formatting inconsistency in another team's file)
  as a side effect of the auto-fix pass. Both times it was reverted with
  `git checkout -- alembic/versions/0001_initial_schema.py` rather than left
  as stray formatting noise in a file this cycle had no business touching.
  Worth recording as the right call, not corrective action.
- No ADR added. This cycle orchestrates already-decided pieces (ADR 0011 and
  its d.1 boundary, the rulebook contract from build-log 0083, the scoring
  and workbook contracts from build-log 0084); it makes no new ruling.
