# Cycle 0083: A rulebook that never says Low

- **Date**: 2026-09-09
- **Scope**: `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §5, Phase 1 (P1-1 through P1-4) — the
  rulebook engine that turns a client's URL-pattern spreadsheet into `theme_1` /
  `theme_2` / `language` / `business_priority` on every `AuditPage`.
- **Commit**: `04a8b15` (`feat(core,api): Phase 1 Tool Registry & Facet Router for
  multi-facet isolation`) — this cycle's files (`src/modules/seo/deliverables/rulebook.py`,
  `src/modules/seo/deliverables/__init__.py`, `tests/modules/seo/deliverables/test_rulebook.py`)
  landed inside that commit, made by another in-flight session working the facet-router
  cycle (build-log 0082) in parallel. Three further tests were added to
  `test_rulebook.py` after that commit and are uncommitted at time of writing (see §1).
- **Quality gate**: rulebook module in isolation — 50 tests, 100% line/branch coverage,
  green. Whole-repo gate — **RED**, 6 failures, all in `tests/api/test_server.py`, all
  pre-existing and unrelated (confirmed independently, §1).

## Origin

Plan §5 P1-1 through P1-4 (`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md`), under
[ADR 0011](../adr/0011-deliverables-boundary-and-screaming-frog-input.md) (the
`deliverables` package never imports `page_classifier`; the two are joined by
`AuditDataset` alone) and ruling S1 in the plan's §1 (rulebook themes live on
`AuditPage`, applied by `deliverables`, never added to `FullPageIntelligenceProfile`
— that contract is canonical per ADR 0002 and stays untouched).

## 1. Gate results

**Rulebook module, re-run independently this cycle** (not taken on the implementer's
word — CLAUDE.md §1.6):

```
tests\modules\seo\deliverables\test_rulebook.py ..................................... [100%]
50 passed
```

```
Name    Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------
TOTAL     186      0     54      0   100%
Required test coverage of 85.0% reached. Total coverage: 100.00%
```

**The 6 whole-repo failures, re-run independently this cycle**, confirming the
implementer's claim rather than trusting it:

```
tests/api/test_server.py::TestConcurrencyCap::test_excess_jobs_are_refused_with_429
tests/api/test_server.py::TestConcurrencyCap::test_a_refused_job_leaves_no_record
tests/api/test_server.py::TestConcurrencyCap::test_releasing_a_reservation_decrements_active_count
tests/api/test_server.py::TestConcurrencyCap::test_reserving_is_atomic
tests/api/test_server.py::TestConcurrencyCap::test_releasing_frees_a_slot
tests/api/test_server.py::TestPerFacetConcurrency::test_page_classifier_has_its_own_concurrency_cap
```

Representative failure (`test_excess_jobs_are_refused_with_429`):

```
>       assert response.status_code == 429
E       assert 202 == 429
E        +  where 202 = <Response [202 Accepted]>.status_code
tests\api\test_server.py:1647: AssertionError
```

`git grep -c "rulebook|deliverables" tests/api/test_server.py` returns zero matches —
the file has no path through which this cycle's code could cause these failures. All
six live in `TestConcurrencyCap` / `TestPerFacetConcurrency`, which assert the *old*
single-semaphore concurrency model against code (`src/api/server.py`,
`src/core/facet_router.py`) mid-migration to a per-facet semaphore model in the same
commit, under another session's in-flight, uncommitted-elsewhere work (build-log 0082,
which recorded the same 6 failures as its own gate's RED). Per this cycle's explicit
scope, `src/api/server.py`, `src/core/facet_router.py`, `src/core/registry.py`,
`src/core/schemas.py`, `src/core/state_store.py` and `tests/api/test_server.py` are
untouched here.

**Whole-repo gate, as run by the implementing session** (pasted verbatim, not
re-run in full this cycle — the isolated re-runs above are the independent check):

```
=== Format ===        PASSED
=== Lint ===           PASSED
=== Type check ===     Success: no issues found in 74 source files — PASSED
=== Tests ===
6 failed, 2096 passed, 1 skipped, 1 warning in 297.47s (0:04:57)
FAILED: Tests
Required test coverage of 85.0% reached. Total coverage: 93.56%
=== UI Component Tests ===  PASSED (21 files, 232 tests)
VERIFICATION FAILED: Tests
```

Recorded honestly per CLAUDE.md §1.6: the whole-repo gate is not green. This cycle's
own deliverable — `rulebook.py` and its 50 tests — is 100% covered and fully green in
isolation, and is not the cause of the 6 failures.

## 2. What landed

`src/modules/seo/deliverables/rulebook.py` (new, 465 lines):

- **`RuleType`** — `StrEnum`, domain-taxonomy UPPER values (CLAUDE.md ruling 3):
  `CONTAINS`, `STARTS_WITH`, `ENDS_WITH`, `EXACT`, `REGEX`, `FALLBACK`.
- **`Rule`** (`StrictModel`) — one rulebook row. A `model_validator(mode="after")`
  makes a bad regex or a rule/pattern mismatch a load-time failure, never a
  mid-classification surprise.
- **`Rulebook`** (`StrictModel`) — `rules: tuple[Rule, ...]`, plus `source_path` and
  `empty_due_to_missing_file` so `apply_rulebook` can write a dataset note without
  `from_xlsx` needing a dataset to write onto. Compiles every `REGEX` pattern once at
  construction (`model_validator`), so "compiled at load" is true for a `Rulebook`
  built by hand in a test, not only one built from a file.
- **`Rulebook.from_xlsx(path, *, lenient=False)`** — reads the `Rulebook` sheet,
  auto-detects the header row in the first five rows by locating a `URL Pattern`
  cell, tolerates the `Language`/`Languuage`/`Lang` header-name variants, and
  recognises a fallback row by rule-type marker (`—`, `-`, `fallback`) or by pattern
  text `"no match"`. A missing file raises `RulebookMissingError` unless
  `lenient=True`.
- **`Rulebook.classify(url) -> Classification`** — collects every matching rule
  before picking a winner, so the result never depends on row order: `EXACT` wins
  outright; otherwise the longest matching pattern wins, with pattern text and rule
  type as further tie-breaks, making the ordering total even when two rules are
  otherwise equal. No match and no fallback row → `theme_1="Others"`,
  `business_priority="N/A"` — never `"Low"`.
- **`apply_rulebook(dataset, rulebook, *, normalize)`** — returns a new
  `AuditDataset` with every page's `theme_1`/`theme_2`/`language`/`business_priority`
  set. `normalize` is an injected `UrlNormalizer` (the same contract
  `screaming_frog_adapter.py` already uses), not an import — `deliverables` never
  imports `page_classifier` (ADR 0011 d.1).

`src/modules/seo/deliverables/__init__.py` — edited to re-export the new public
names, following the existing `screaming_frog_adapter` pattern; no restructuring.

`tests/modules/seo/deliverables/test_rulebook.py` (new, 50 tests) — no binary
`.xlsx` fixture; every test workbook is built at test time with `openpyxl` into
`tmp_path` (Step 3 decision 5, §3 below).

## 3. Design decisions (Step 3, operator: gaurav.doshi@rankuno.com, this session)

Five confirmations obtained before/alongside implementation, all followed as given:

1. **Exception types.** `RulebookError` / `RulebookMissingError` are local
   `ValueError` subclasses, matching the sibling adapters' stance
   (`ScreamingFrogBundleError`, `AuditExportError`) rather than
   `core.errors.RankunoError`. Keeps `deliverables` consistent with itself; `core`
   stays domain-agnostic (CLAUDE.md §5).
2. **Field naming.** `Classification`'s fourth field is `business_priority`, matching
   `AuditPage` exactly (so `apply_rulebook` assigns straight across, no renaming
   step) and avoiding a name collision with `contracts.catalogue.Priority`, an
   unrelated enum on the issue catalogue.
3. **Header names.** The proposed xlsx headers — `Rule Type`, `Theme 1`, `Theme 2`,
   `Business Priority` (plus `URL Pattern`, and a tolerant `Language` group) — were
   accepted as-is. No real client rulebook file exists anywhere in this repository or
   its fixtures to confirm the names against; matching is trimmed and
   case-insensitive so a close-but-not-exact real file has a chance of loading
   without a schema change (§6 below records this is still unverified against a real
   file).
4. **Fail-loud scope.** A malformed-but-present workbook (unreadable file, absent
   `Rulebook` sheet, no header row found, unrecognised rule type, invalid regex)
   always raises, even with `lenient=True`. Only a genuinely absent path is
   swallowed by `lenient=True`. This matches ADR 0011 point 6 ("fail loud") exactly:
   lenient mode is an opt-out for "no rulebook was supplied", not for "a rulebook was
   supplied and it's broken".
5. **No fixture file.** No binary `.xlsx` is committed to the repository. Every test
   workbook is constructed at test time via `openpyxl.Workbook()` written into
   `tmp_path`, keeping the fixture readable as Python and avoiding a binary diff in
   version control for a file whose entire content is re-derivable from the test
   that builds it.

## 4. Bugs found and fixed

- **The bug the whole module exists to structurally prevent** (spec bug, RAE
  original): a missing rulebook silently gave every page `Low` priority — a client
  reading `Low` cannot distinguish "genuinely low priority" from "nobody classified
  this". `PRIORITY_NOT_APPLICABLE = "N/A"` and the `RulebookMissingError` default
  make that distinction structural rather than a documentation note (plan P1-2,
  P1-4).
- **The bug the classification algorithm exists to structurally prevent** (spec bug,
  RAE original): row order in the spreadsheet could let a shorter, less specific
  pattern shadow a longer, more specific one, depending on which row a human
  happened to enter first. `classify()` computes precedence from rule shape (exact
  match, then longest pattern, with a deterministic tie-break), never from list
  position. Concretely proven by
  `TestClassifyPrecedence::test_exact_wins_over_a_longer_non_exact_pattern` and its
  neighbouring case: a rule for `/services` and a rule for
  `/services/annotation-services` classify a `/services/annotation-services` URL
  correctly regardless of which row appears first in the sheet — the longer pattern
  always wins because it is a strict superset match, never because it happened to be
  read second.
- **Coverage gap found and closed, not a functional bug**: the three tests added to
  `test_rulebook.py` after the initial commit —
  `test_recognised_rule_type_with_empty_pattern`, `test_not_a_readable_workbook`, and
  `test_ends_with_match` — closed three branches that existing tests did not
  exercise (a recognised rule type with a blank pattern cell; `openpyxl` raising on
  a non-workbook byte stream; the `ENDS_WITH` match arm of `_matches`). The code
  paths were already correct; coverage was not yet 100% before these were added. Now
  100%, confirmed independently this cycle (§1).

## 5. Corrections

None. This is the first entry to document `rulebook.py`; `docs/ARCHITECTURE.md`
listed it as "not started" until this cycle (see §Drift below), which was accurate
at the time it was written and is corrected here, not retroactively edited there.

## 6. Explicitly not done

- **No site scoring, no per-category penalty totals.** Plan D2 puts this in Phase 2.
  `rulebook.py` produces per-page labels only; nothing sums them.
- **Not consuming a real rulebook file yet.** No client rulebook `.xlsx` exists in
  this repository or has been used to confirm the header names (Step 3 decision 3).
  The header-detection logic is tested against synthetic workbooks built with the
  documented header names and variants, not against a file a client has actually
  produced.
- **Nothing wires `apply_rulebook` to an endpoint, CLI, or job pipeline.** Per plan
  §2, Phase 0/1 are pure functions over files and models; the upload endpoint and
  workbook generation are Phase 2, with their own Step 5 audit.
- **No formula-injection guard on any written cell** — none is written yet; this
  module only reads and returns models. Recorded as a hard Phase 2 requirement in
  plan §6 item 7.

## 7. Files changed

- `src/modules/seo/deliverables/rulebook.py` — new (465 lines).
- `src/modules/seo/deliverables/__init__.py` — edited, re-exports added.
- `tests/modules/seo/deliverables/test_rulebook.py` — new, 50 tests (three added
  after the initial commit, uncommitted at time of writing).

Not touched by this cycle, despite appearing in `git status` at its start (another
session's in-flight work): `src/api/server.py`, `src/core/config.py`,
`src/core/registry.py`, `src/core/schemas.py`, `src/core/state_store.py`,
`src/modules/seo/page_classifier/tool.py`, `src/core/facet_router.py`,
`src/modules/seo/health_engine/`, `src/modules/seo/theme_classification/`,
`tests/api/test_server.py`, `tests/core/test_config.py`,
`tests/core/test_registry.py`, `tests/core/test_state_store.py`.

## 8. Follow-ups / handoffs

- **To the owner of the concurrency-cap work** (build-log 0082's session): the 6
  `tests/api/test_server.py` failures (`TestConcurrencyCap` x5,
  `TestPerFacetConcurrency` x1) are not caused by this cycle and remain open against
  the facet-router migration. Re-confirmed failing, unchanged, at the end of this
  cycle.
- **To whoever starts Phase 2**: the header-name confirmation in Step 3 decision 3
  is provisional — first real client rulebook file should be checked against
  `_HEADER_RULE_TYPE` / `_HEADER_THEME_1` / `_HEADER_THEME_2` /
  `_HEADER_BUSINESS_PRIORITY` before this is treated as validated.
