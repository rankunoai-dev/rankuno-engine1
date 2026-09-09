# Cycle 0084: Phase 2a/2b — Scoring Engine and Client Workbook Generator

- **Date**: 2026-09-09
- **Scope**: Per-category penalty totals over an `AuditDataset` (Phase 2a) and a
  four-sheet client workbook built from those totals (Phase 2b), closing
  `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §10 (added by this entry).
- **Commit**: uncommitted at time of writing
- **Quality gate**: targeted deliverables suite green — 29 new tests (12 scoring +
  17 workbook), 100% coverage on both new files. Whole-repo `verify.ps1` is **not**
  a meaningful statement this cycle; see §1.2.

**Origin**: `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` new §10 (Phase 2a/2b, added by
this entry) and ADR 0011 decision D2 — per-category penalty totals, explicitly no
single site score.

---

## 1. Gate results

### 1.1 Targeted suite (this cycle's own files, run directly, not from memory)

```
$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables/test_scoring.py tests/modules/seo/deliverables/test_workbook.py -v --no-header
============================= test session starts =============================
collected 29 items

tests\modules\seo\deliverables\test_scoring.py ............              [ 41%]
tests\modules\seo\deliverables\test_workbook.py .................        [100%]

============================= 29 passed in 0.93s ==============================
```

12 scoring + 17 workbook = 29, matching the implementer's report exactly.

### 1.2 Wider targeted run, with coverage

```
$ .venv/Scripts/python.exe -m pytest tests/modules/seo/deliverables/ tests/modules/seo/test_import_boundary.py tests/core/test_config.py -q --cov=src/modules/seo/deliverables --cov-report=term-missing
........................................................................ [ 56%]
........................................................                 [100%]
ERROR: Coverage failure: total of 80 is less than fail-under=85

Name                                                     Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------------------
src\modules\seo\deliverables\_bundle.py                    154     81     42      5    41%   70, 98, 100, 107-110, 113, 116-120, 123-124, 133-140, 147-159, 163-186, 189-197, 200, 213-214, 223, 226-227, 234-238, 250-252
src\modules\seo\deliverables\screaming_frog_adapter.py     171     27     50     16    81%   129-130, 133-134, 149, 156, 160, 167-168, 171-172, 175-176, 194, 202, 204-205, 207-208, 236-237, 240, 242, 254->252, 257, 268, 286, 292->294, 296
----------------------------------------------------------------------------------------------------
TOTAL                                                      639    108    164     21    80%

4 files skipped due to complete coverage.
FAIL Required test coverage of 85.0% not reached. Total coverage: 80.20%
```

All tests pass; the 80.20% figure and "4 files skipped due to complete coverage" are
real and match the implementer's report exactly. The four skipped files —
`scoring.py`, `workbook.py`, `__init__.py`, `rulebook.py` — are the ones at 100%. The
80% total is a denominator artefact of this narrow selection: `_bundle.py` and
`screaming_frog_adapter.py` are P0-3/P0-5 modules exercised by their own test files
(`test_bundle.py`, `test_screaming_frog_adapter.py`, not included in this command),
not by anything from this cycle. Confirmed real in build-log 0077, where those files
were built and gated on their own suite. This is not a coverage gap in this cycle's
work; it is an artefact of the command scope.

### 1.3 Isolated format / lint / type checks on the two new files

```
$ .venv/Scripts/python.exe -m ruff format --check src/modules/seo/deliverables/scoring.py src/modules/seo/deliverables/workbook.py
2 files already formatted

$ .venv/Scripts/python.exe -m ruff check src/modules/seo/deliverables/scoring.py src/modules/seo/deliverables/workbook.py
All checks passed!

$ .venv/Scripts/python.exe -m mypy --strict src/modules/seo/deliverables/scoring.py src/modules/seo/deliverables/workbook.py
Success: no issues found in 2 source files
```

### 1.4 Full-repo `verify.ps1` — why it cannot be read as this cycle's state

Whole-repo lint was run to confirm the boundary of the concurrent session's damage:

```
$ .venv/Scripts/python.exe -m ruff check src/ tests/ --output-format=concise
Found 24 errors. [16 fixable with --fix]
```

Every file `ruff` names is one this cycle did not touch and was explicitly told not
to touch: `src\api\server.py`, `src\core\logger.py`, `src\core\schemas.py`,
`src\core\state_store.py`, `tests\api\test_multi_org.py`,
`tests\api\test_server.py`. Zero overlap with `deliverables/`, `contracts/`, or this
cycle's own `config.py` addition (§7). This is the same situation as build-log 0083
(carried from 0082): another session's large in-flight multi-tenant/facet work —
untracked `test_multi_org.py`, modified `server.py` / `state_store.py` / `schemas.py`
/ `logger.py` / `facet_router.py` / `test_server.py` — is independently causing
Format/Lint/Type-check/Test failures. Per CLAUDE.md §1.6, a task is not "complete"
without a green gate; that statement is about *this cycle's* code, and the full-repo
gate is not currently a meaningful read of it. Running `verify.ps1` end-to-end and
publishing a single pass/fail line for the whole repo right now would misattribute
someone else's in-flight failures to this change, or hide this change's own state
behind them. §1.1–§1.3 are the true, isolated state of Phase 2a/2b.

---

## 2. What landed

**`src/modules/seo/deliverables/scoring.py`** — `IssuePenalty`, `CategoryPenalty`,
`ScoringResult` (`StrictModel`s), `score_dataset(dataset, *, weights=None)`,
`get_severity_weights()`, `SEVERITY_WEIGHTS`. `score_dataset` walks
`ISSUE_CATALOGUE`, not `dataset.issues`, so every one of the 110 catalogue rows
gets an `IssuePenalty` — including the 94 rows a Phase 0 engine crawl reports
`NOT_MEASURED` for (build-log 0079) — instead of silently omitting a row the
dataset happens to have nothing for. A `NOT_MEASURED` row's penalty is `0` and is
counted in `not_measured_issue_count`, kept distinct from a measured row that
genuinely found zero affected pages (ADR 0011 §5 carried into scoring, not just
the contract).

**`src/modules/seo/deliverables/workbook.py`** — `build_workbook(dataset, scoring,
*, output_dir=None) -> Path`, four sheets in fixed order: `Overview` (per-category
penalty totals and measured/not-measured counts), `Issues` (one row per catalogue
entry, in catalogue order), `Pages` (the dataset's page spine, themes included if
`apply_rulebook` was run), `Notes` (adapter caveats and run metadata).
`MAX_PAGES_PER_WORKBOOK = 500_000`; `WorkbookBuildError` on overflow or write
failure.

**`src/core/config.py`** — `Settings.deliverables_output_dir: Path`, default
`REPO_ROOT / "deliverables" / "output"`, the directory `build_workbook()` writes
into when the caller does not pass `output_dir=`.

---

## 3. Design decisions

(Already approved by the operator this session, in the Step 3 conversation that
produced plan §10 — recorded here, not re-litigated.)

- **Scoring and the workbook shipped as one cycle**, not two. A workbook with no
  scoring behind it is not a usable deliverable, and scoring with no workbook is
  untestable as anything a client would see. `scoring.py` was gated first —
  `workbook.py` only started once `score_dataset` and its structural test were
  green — so the dependency direction (`workbook` imports `scoring`, never the
  reverse) was enforced by build order, not just by the import graph.
- **Themes ride along, they do not cut the totals.** `_write_pages` renders
  `theme_1` / `theme_2` / `language` / `business_priority` when a rulebook has been
  applied (P1-4), because a client workbook without theme columns loses information
  the operator already has. But `score_dataset` never reads a theme field —
  penalties are category-only, per D2. There is deliberately no "penalty by theme"
  sheet or breakdown anywhere in this cycle.
- **Severity weights sit behind a swappable seam.** `get_severity_weights()` wraps
  the `SEVERITY_WEIGHTS` constant, mirroring `weights.get_weight_profile()` from
  ADR 0006: the architecture is client-agnostic, the specific integers (Issue=3,
  Warning=2, Opportunity=1) are a defensible default, not a measurement. A future
  calibrated vector, or a per-client override if one is ever justified, is a change
  behind this function, not a rewrite of `score_dataset`'s loop.
- **`Workbook(write_only=True)`**, not the default openpyxl mode. Trades
  cell-by-cell styling for bounded memory regardless of row count — the same trade
  ADR 0001 already makes for the crawl itself (20k–500k URL target, no redesign
  needed for the larger path). `MAX_PAGES_PER_WORKBOOK = 500_000` is the hard stop
  matching that ceiling: a dataset over the cap raises `WorkbookBuildError` before
  any sheet is written, rather than silently truncating rows — the RAE failure mode
  (plan §8, "missing input → 0 issues") applied to output instead of input.
- **The upload endpoint is explicitly deferred**, not built and not designed in
  this cycle. It gets its own future cycle with its own Step 3 (architecture
  review, HITL) and its own Step 5 (security/cost audit), with
  `security-auditor` running as the **pre-step**, exactly as ADR 0011 §3 requires
  for anything that adds a network surface to this boundary. Nothing in `scoring.py`
  or `workbook.py` opens a socket, reads `os.environ` directly, or is reachable from
  `src/api/server.py` — `build_workbook` and `score_dataset` are pure functions over
  local models and a local path.

### 3.1 Security finding: openpyxl classifies formulas by leading character alone

This was read directly out of the openpyxl 3.1 source, not assumed from a style
guide. `Cell.value`'s setter (via `Cell._bind_value` / the `data_type` inference in
`openpyxl.cell.cell`) classifies any string whose **first character** is one of
`= + - @` (plus a tab or carriage return, per the broader OWASP CSV-injection set)
as a live formula — `data_type` becomes `"f"` — regardless of what follows. There is
no parsing of the rest of the string; the classification is purely positional.

From Rankuno's side of the boundary, a client's own page title or URL is untrusted
input: it was authored by whoever runs the client's CMS, not by Rankuno, and it
flows into this workbook via the Screaming Frog adapter or the engine adapter
without ever being reviewed. A page titled `=HYPERLINK("http://evil","click")` or a
URL fragment beginning with `-` or `@` would, unguarded, become a formula that
executes when a client (or Rankuno staff) opens the file in Excel.

**Mitigation**: `_safe_cell()` in `workbook.py` prefixes a value with `'` before it
reaches `ws.append()` whenever the first character of a `str` value is in
`_FORMULA_TRIGGER_CHARS = {"=", "+", "-", "@", "\t", "\r"}`. Every sheet writer —
`_write_overview`, `_write_issues`, `_write_pages`, `_write_notes` — routes every
value through `_append_row`, which calls `_safe_cell` on each element with no
exemption. `Notes` was the one sheet that could plausibly have been treated as
"operator-authored, therefore trusted" (it also carries adapter-generated caveat
strings, not just raw crawl data); it is not exempted, because a workbook-wide
guarantee is only as strong as its narrowest carve-out.

**Verification, not just design**: `test_no_cell_anywhere_is_a_formula` seeds a
formula-trigger payload into every text field across all four sheets and asserts
zero cells anywhere in the resulting workbook have `data_type == "f"` — a
whole-workbook assertion, not a spot check of one field.

---

## 4. Bugs found and fixed

No pre-existing bug in `scoring.py` or `workbook.py` surfaced during this cycle —
both are new files with no prior behaviour to regress. The one finding of note is
§3.1: it did not correct a bug already written, it is the reason `_safe_cell` exists
in the first place. It is recorded as a security finding rather than a "bug fixed"
because there was no working-then-broken state — the guard was designed in before
any cell was ever written, once the openpyxl source was read.

No bug in the specification (plan §10, ADR 0011 D2) or in a pre-existing test was
found or fixed this cycle.

---

## 5. Corrections

`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §6 (question 7, Step 5 audit, written at
Phase 0/1 time) stated formula injection would be mitigated with
`write_string` for every text cell. That was the anticipated openpyxl API before
this cycle chose `write_only=True` mode. `Workbook(write_only=True)` sheets do not
expose a `write_string` method at all — the only way to add a row is
`ws.append(iterable)`, which infers each cell's type from the Python value. The
actual mitigation is `_safe_cell()` applied to every value before it reaches
`ws.append()` (§3.1), not a call to `write_string`. The outcome the plan wanted —
no client-supplied string becomes a live formula — holds; the named mechanism in
the plan does not match what was built, because the write-mode decision came after
that line was written. This is a correction of an implementation detail in an
approved plan, not of a decision.

No other previously published number or claim was found to be wrong in this cycle.

---

## 6. Explicitly not done

- **No per-theme scoring cut.** `score_dataset` never reads `theme_1` / `theme_2` /
  `language` / `business_priority`. Penalties are category totals only, per D2.
  Anyone wanting "penalty by theme" needs a new decision, not an extension of this
  module.
- **No upload endpoint.** Not designed, not built, not stubbed. `build_workbook`
  returns a local `Path`; nothing moves that file off the workstation. Parked for
  its own future cycle with its own Step 3 (architecture/HITL) and Step 5
  (security/cost audit, `security-auditor` as pre-step) — see §3 and plan §10.
  There is no P2-c row for it in the plan; it is named as parked, not scheduled.
- **No caller wires `score_dataset` / `build_workbook` into anything yet.** Not
  `src/api/server.py` (untouched this cycle, and off-limits per this cycle's
  brief), not a CLI, not the tool registry. These are library functions with tests,
  reachable only by import, exactly like `audit_export.py` and
  `screaming_frog_adapter.py` before them (build-log 0079 §6, build-log 0074 §6).
- **No calibrated severity-weight vector.** `SEVERITY_WEIGHTS` is a defensible
  default (§3), not a measurement. Adaptive or per-client weighting is out of scope,
  same stance as ADR 0006 on classification weights.
- **`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §10 is this cycle's own work.**
  The plan document did not have a Phase 2a/2b section before this entry; adding it
  is documentation authored in this build-log cycle (docs-scribe), not something
  `feature-builder` wrote or should be cited for.
- **The whole-repo gate is not re-run to green in this cycle.** See §1.4 — that is
  explicitly handed off, not silently skipped.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/deliverables/scoring.py` | new — `IssuePenalty`/`CategoryPenalty`/`ScoringResult`, `score_dataset()`, `get_severity_weights()` |
| `src/modules/seo/deliverables/workbook.py` | new — `build_workbook()`, `_safe_cell()`, four sheet writers, `WorkbookBuildError` |
| `tests/modules/seo/deliverables/test_scoring.py` | new — 12 tests |
| `tests/modules/seo/deliverables/test_workbook.py` | new — 17 tests |
| `src/modules/seo/deliverables/__init__.py` | exports the new scoring/workbook symbols |
| `src/core/config.py` | adds `Settings.deliverables_output_dir` — **note**: the working-tree diff on this file also carries `org_config_path` / `org_config_store`, which are the concurrent session's multi-tenant work, not this cycle's (§8) |
| `.env.example` | adds the `DELIVERABLES_OUTPUT_DIR` doc block only; diff confirmed isolated |
| `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` | new §10, this entry |
| `README.md` | Component table rows for `scoring.py` / `workbook.py`; Phase 2 status row updated |
| `docs/ARCHITECTURE.md` | file tree entries for `scoring.py` / `workbook.py`; "planned, not yet implemented" row updated |

---

## 8. Follow-ups

- **To the coordinator**: re-run the full `verify.ps1` gate once the concurrent
  session's multi-tenant/facet work (server.py, state_store.py, schemas.py,
  logger.py, facet_router.py, test_server.py, test_multi_org.py) lands or
  stabilizes, for one clean end-to-end reading that actually covers this cycle's
  files alongside everything else. Right now a whole-repo run conflates two
  sessions' state.
- **Upload endpoint**: parked. Needs its own plan section, its own Step 3 stop, and
  a Step 5 audit with `security-auditor` as the pre-step before any code, per ADR
  0011 §3's governance stance on anything that adds a network surface here.
- `src/core/config.py`'s working-tree diff was checked directly and is not isolated
  to this cycle's `deliverables_output_dir` addition — see §7. Flagged, not fixed;
  fixing it would mean editing a file this cycle was told not to touch, on behalf
  of a change this cycle did not make.
