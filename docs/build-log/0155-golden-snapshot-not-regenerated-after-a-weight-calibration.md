# Cycle 0155: Main went red — golden snapshot not regenerated after a weight calibration

- **Date**: 2026-10-10
- **Scope**: Test fixture only. `tests/fixtures/golden/extract_at_fetch_500.json.gz` regenerated for the signal weights changed in `5176418`. No source change.
- **Commit**: `cfad234` on branch `fix-golden-after-weights`, then merged with `origin/main` `45268e1` (`6afa603`). This entry uncommitted at time of writing.
- **Quality gate**: GREEN — lead's run on the branch merged with origin/main `2cd8ea6`: 4509 passed, 2 skipped, 93.65% (§1).

## 1. Gate results

**LEAD GATE** (run by the lead on `5713e46` = this fix + build-logs 0154/0155 merged with origin/main `2cd8ea6`; main venv; `import src` resolved to the worktree; verify.ps1's steps run directly because the worktree has no `.venv`):

```
ruff format --check .            -> 684 files already formatted
ruff check .                     -> All checks passed!
mypy src                         -> Success: no issues found in 181 source files
export_ui_contract.py --check    -> UI contract is up to date.
drift_check.py                   -> PASSED: no drift detected across 256 markdown files.
pytest --cov=src                 -> Required test coverage of 85.0% reached. Total coverage: 93.65%
                                    4509 passed, 2 skipped, 2 warnings in 594.29s (0:09:54)
```

Earlier figures below are the bug-fixer's and the scribe's, kept for the record.

Bug-fixer's gate on `0861f05` plus the regenerated snapshot (reported, not re-executed by the scribe):

| Stage | Result |
| :--- | :--- |
| ruff format | 669 files |
| ruff check | ok |
| mypy --strict | 176 source files, ok |
| pytest | exit 0; coverage 93.50% |
| drift_check | PASSED |

Targeted runs:

| Run | Result |
| :--- | :--- |
| Golden file on `0861f05` (before fix, bug-fixer) | 8 failed, 9 passed |
| Golden file after fix, `PYTHONHASHSEED` 0 / 1 / random (bug-fixer) | 17 passed each |
| `test_cascading_pipeline.py` after fix (bug-fixer) | 37 passed |
| Golden + fetch-time + cascading, seeds 0 and 7, before and after merging `45268e1` (lead) | exit 0 |
| Golden + fetch-time + cascading, seed 0, on `6afa603` (scribe; `import src` resolves to this worktree) | 72 tests, 0 failures, 0 errors, exit 0 |

## 2. What happened

Commit `5176418` (another session, "Approved calibration per brief (2026-10-09)", build-log 0150) changed `SIGNAL_WEIGHTS` in `src/modules/seo/page_classifier/schemas.py`: `SCHEMA_JSONLD` 0.15 → 0.20 and `ARIA_NAV_TREE` 0.25 → 0.20. It did not regenerate the extract-at-fetch golden snapshot (ADR 0035, build-log 0142). Its commit message said the full suite passed. On `main` 8 golden tests and 2 fetch-time-extraction tests failed.

### Root cause (bug-fixer, confirmed by control experiment)

`resolve_consensus` (`cascading_pipeline.py:127-142`) computes `confidence = sum(conf * w) / participating_weight`.

| Case | Pages | Old | New | Why |
| :--- | ---: | :--- | :--- | :--- |
| Lone `SCHEMA_JSONLD` (0.8) | 155 | 0.8 | 0.8000000000000002 | `0.8*0.2/0.2` does not round-trip in IEEE-754; `0.8*0.15/0.15` does. Float noise. |
| `SCHEMA_JSONLD` (0.8) + dissenting `LINK_IN_DEGREE` (0.35) | 131 | 0.48 | 0.5333333333333333 | 0.12/0.25 → 0.16/0.30. The intended effect. `SCHEMA_JSONLD` still wins, 0.16 vs 0.035. |

All 286 leaf differences are in `$.tool.pages[].final_confidence_score`. No page type, level, escalation or discovery value changed. The golden site carries no ARIA signals, so the `ARIA_NAV_TREE` change does not show. Control: restoring the old weights reproduces the old snapshot with 0 differences, so the weight change is the sole cause. The result is identical across `PYTHONHASHSEED` values and async completion orders.

The scribe checked the arithmetic in the venv: `0.8*0.2/0.2 = 0.8000000000000002`, `0.8*0.15/0.15 = 0.8`, `0.12/0.25 = 0.48`, `0.16/0.30 = 0.5333333333333333`.

## 3. Fix

Snapshot regenerated deliberately through the test module's `regenerate()`. `git diff --stat 45268e1 HEAD` shows the gzip as the only changed file (50,907 bytes before and after).

## 4. Bugs found and fixed

1. **Stale golden snapshot after a weight change.** Fixed by regeneration (§3). The code was right; the fixture was out of date.
2. **A merge reached `main` on red.** Cycle 0154 merged while these 10 tests were failing (0154 §5).

## 5. Corrections

1. **The lead's report to the user was wrong.** The lead said the golden test failed "only under pytest" and passed in a standalone script. False: the failure reproduces outside pytest. The lead's zero-difference scratch run was faulty, most likely because it imported a different checkout's `src` through the venv's editable `.pth`; that cause is unproven. The separate check that pytest imported this worktree's `src` was correct, so earlier gate results stand.
2. **`5176418`'s commit message** claim "Full suite: 2000+ tests, 85%+ coverage maintained" is false: the suite was over 4,400 tests (cycle 0154 pre-merge: 4471 passed, 2 skipped) and 10 failed on `main`.
3. **Build-log 0150** reports its gate as "134 tests, 85%+ coverage" and says the change "has no downstream dependencies". The golden snapshot was a downstream dependency, and the full suite was red.

## 6. Explicitly not done

1. **No guard for this failure mode.** Nothing fails clearly when `SIGNAL_WEIGHTS` changes without a snapshot regeneration; the symptom is 8 opaque diff failures. Handoff to test-engineer: e.g. pin a hash of the weights beside the snapshot and fail with "weights changed, regenerate".
2. **`final_confidence_score` is not rounded at production time.** Rounding would change every stored score, so it needs a decision first.
3. **Values such as 0.8000000000000002 remain in stored output** and in the snapshot.
4. **No ADR.** A fixture regeneration inside ADR 0006 and ADR 0035; no ruling changed.
