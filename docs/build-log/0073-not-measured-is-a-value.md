# Cycle 0073: Not measured is a value — the `AuditDataset` contract and the issue catalogue as data

- **Date**: 2026-09-08
- **Scope**: Phase 0 work items P0-1 (contract models) and P0-2 (catalogue as data)
  of `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md`, under ADR 0011. A new package
  `src/modules/seo/contracts/` and nothing else.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1813 passed`, coverage 93.64%; UI `226 passed` / 20 files —
  green in the docs-scribe run at 14:51. The implementer's own run at hand-off was
  **red** on the UI stage (`treeOverlay.test.ts`, 1 failed / 216 passed); see the
  gate-status note in §1 for why the two runs differ and what that means.

**Cycle number.** The plan (P0-8) and one test comment call this entry "build-log
0072". While it was being written, another session claimed 0072 in the index
(`0072-a-list-is-not-an-export.md`, the bare-URL-list cross-check). Numbers are
never reused (`README.md` in this directory, rule "never create a collision"), so
this cycle is 0073. The stale references are listed in §5 and §8.

---

## 1. Gate results

Two gate runs matter here, and they do not agree.

### 1.1 Implementer's run (as reported in the feature-builder hand-off; not re-run by docs-scribe)

```
Format:     271 files already formatted            PASSED
Lint:       All checks passed!                     PASSED
Type check: Success: no issues found in 63 files   PASSED
Tests:      1801 passed, coverage 93.56%           PASSED
UI:         FAILED
  rankuno-ui/src/lib/treeOverlay.test.ts > buildTreeOverlay > gathers OTHERS across locale roots
  AssertionError: expected [ 'FLAT_URLS' ] to deeply equal [ 'HOMEPAGE', 'UNKNOWN' ]
  1 failed | 216 passed
```

### 1.2 Docs-scribe run, 2026-09-08 14:49–14:51 (`scripts/verify.ps1`, no `-Fix`)

```
=== Format ===
272 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 63 source files
PASSED: Type check

=== Tests ===
Name                                                           Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------------------------
src\api\server.py                                                633     25    120     13    95%   310, 405, 723-724, 904-905, 976-980, 1072-1073, 1145-1146, 1158-1159, 1173, 1287, 1488, 1536, 1549, 1624, 1656->1655, 1686, 1713, 1728, 1816
src\modules\seo\page_classifier\url_rules.py                     191      4     72      6    96%   363, 711, 719, 818->820, 841->843, 888
src\modules\seo\performance\gsc_export.py                        171      9     54      6    93%   163, 166, 176, 178, 289-290, 308, 411, 431
----------------------------------------------------------------------------------------------------------
TOTAL                                                           7232    369   1800    133    94%

29 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 93.64%
1813 passed, 1 warning in 108.29s (0:01:48)
PASSED: Tests

=== UI Component Tests ===
 ✓ src/lib/treeOverlay.test.ts (13 tests) 215ms
 Test Files  20 passed (20)
      Tests  226 passed (226)
   Start at  14:50:52
   Duration  36.57s
PASSED: UI Component Tests

ALL GATES PASSED.
EXIT=0
```

(Per-file coverage rows other than the three above were `100%` and are elided;
the `TOTAL` line is verbatim.)

### 1.3 This package alone

```
pytest tests/modules/seo/test_audit_contract.py tests/modules/seo/test_catalogue.py
65 passed in 0.15s

--cov=src/modules/seo/contracts
Name    Stmts   Miss Branch BrPart  Cover   Missing
TOTAL     257      0     18      0   100%
```

### 1.4 Gate status note — read before treating this cycle as complete

The difference between 1.1 and 1.2 is **not** this cycle's work. Nothing under
`src/modules/seo/contracts/`, its tests, or its fixture changed between the two
runs. What changed is another session's uncommitted work in the same working tree:

| Change by the other session | Effect on the gate |
| :--- | :--- |
| `rankuno-ui/src/lib/treeOverlay.test.ts` edited at 14:50:06 (46 s before the UI stage of run 1.2 began) | the failing assertion in 1.1 no longer fails; 13/13 in that file |
| `src/modules/seo/page_classifier/bare_url_list.py` + `tests/modules/seo/test_bare_url_list.py` (untracked), `screaming_frog_merge.py`, `screaming_frog_reconciler.py` and their tests (modified) | +12 Python tests (1801 → 1813); +1 file formatted (271 → 272) |
| `ReconcilePanel.tsx` / `.test.tsx`, `adapterInterface.ts`, `navTree.test.ts` (modified) | +10 UI tests (216 → 226) |

So: the gate is green on the tree as it stood at 14:51, and the `contracts`
package passes on its own at 100% coverage. But the green result **depends on
uncommitted edits that belong to cycle 0072**. If this cycle's files are
committed without that session's `treeOverlay.test.ts` edit, the UI stage will be
red again, for a reason unrelated to this cycle. The `treeOverlay` failure was
never this cycle's bug and is not recorded in §4; it belongs to whoever owns
`rankuno-ui/src/lib/treeOverlay.ts` (last modified 2026-09-07 17:42, i.e. cycle
0069/0070 work).

`scripts/drift_check.py` output is in §1.5.

### 1.5 Drift check

Run before this entry existed, the check reported the same 12 broken relative
links in build-logs 0058, 0060 and 0061 that every cycle since 0062 has carried
(paths such as `tests/modules/seo/page_classifier/test_gsc_e2e.py` and
`rankuno-ui/src/components/gsc/GscMetricsCard.tsx` that were never created under
those names). Nothing new from this cycle.

Run again after the other session began editing those three old entries and
added its 0072 index row, the check reported only the not-yet-written
`0072-a-list-is-not-an-export.md` (two links: the index and `README.md`). The
final output after this entry was indexed is in the closing report for this
cycle; it is not pasted here because the other session's file may land between
this sentence and the commit.

---

## 2. What landed

Four modules, two test files, one fixture. No existing file under `src/` or
`tests/` was modified.

### 2.1 `src/modules/seo/contracts/issue_ids.py` (178 lines)

`IssueCategory` (16), `Severity` (`ISSUE > WARNING > OPPORTUNITY`), `Priority`
(`HIGH > MEDIUM > LOW`) and `IssueId` (110 members), all `StrEnum` with UPPER
names and values equal to names, matching `HierarchyLevel` and `SearchIntent`
(CLAUDE.md ruling 3). `IssueId` names are category-prefixed
(`CANONICALS_MISSING`, `H1_MISSING`, `HREFLANG_MISSING`) because the bare label
`Missing` recurs in six categories.

This module is not in the plan's §3 file list. It exists because the plan's layout
was circular: `catalogue.py` rows need the grading enums, and `audit.py` needs
`IssueId` for its `Mapping` keys, while the plan put `IssueId` in `catalogue.py`
and the grading enums in `audit.py`. Both `catalogue.py` and `audit.py` re-export
what they import, so every name the plan lists is importable from the module the
plan names; the extra file changes nothing for callers.

### 2.2 `src/modules/seo/contracts/catalogue.py` (382 lines)

`IssueSpec(StrictModel)` — `id`, `category`, `label`, `severity`, `priority`,
`sf_sources: tuple[str, ...]`. `ISSUE_CATALOGUE` is a tuple of 110 rows laid out
as a table under `# fmt: off`, in RAE's original row order, grouped by category.
`ISSUE_SPECS` is the same rows keyed by id in a `MappingProxyType`. `RaeLabel` and
`RAE_LABELS` keep RAE's original category and label spellings — including
`"Strucured Tags"`, `"Redability Difficult"` and `"Custom Search "` with its
trailing space — for the differential check (P0-7) only.

The catalogue is Python, not JSON or CSV, so that a test can pin every value and
a diff shows one row per line. RAE kept it in a database table, in two copies.

### 2.3 `src/modules/seo/contracts/audit.py` (188 lines)

`Coverage` (`MEASURED` / `NOT_MEASURED`), `AuditSource`
(`Literal["engine", "screaming_frog"]`), `AuditPage`, `AuditLink`, `AuditDataset`,
and `external_urls_note(issue)`. The three invariants from plan §3 are one
`model_validator(mode="after")`:

1. `coverage` holds a key for every `IssueId`, or construction fails naming the
   missing ids.
2. Every URL in every `issues` set is in `pages`, unless `notes` contains the
   exact string `external_urls_note(issue)` for that issue. The note is generated,
   not free-typed, so the validator can match it exactly and an adapter cannot
   admit external URLs for one issue by writing a note about another.
3. An issue whose coverage is `NOT_MEASURED` has an empty set.

`validate_assignment=True` re-runs the validator on field assignment, so a
dataset cannot be made invalid after construction either (tested).

The security-auditor's conditions on the plan's Step 5 answers were applied:
`site` must match a bare lowercase hostname regex (no scheme, port or path);
`produced_at` must be timezone-aware; `str_strip_whitespace` on every string
field; and length ceilings of 253 (hostname), 2048 (URL) and 500 (note or theme).

### 2.4 Tests and fixture

- `tests/modules/seo/test_audit_contract.py` — 20 tests: the three invariants
  each failing-then-passing, lossless JSON round trip
  (`AuditDataset.model_validate(ds.model_dump(mode="json")) == ds`),
  `extra="forbid"`, whitespace stripping, a formula-like note `"=SUM(A1)"`
  round-tripping unchanged (formula *escaping* is a Phase 2 write-side concern,
  and the contract must not silently alter data), and the security conditions.
- `tests/modules/seo/test_catalogue.py` — 45 tests: enum ↔ rows 1:1, no blank
  grade representable, every `sf_sources` name present in the reference listing,
  no filename shared by two rows, D3 wiring, the D1 table of all 30 disagreements
  with one parametrised case per row, a re-derivation of rule (c) from the raw
  cells so the table itself is checked, and the two-rows-blank-in-both-tables
  judgement (§4.5).
- `tests/fixtures/deliverables/sf_export_filenames.txt` — one provenance comment
  line and 118 filenames from a real Screaming Frog 19.4 export directory. Names
  only; no data.

---

## 3. Design decisions

### 3.1 D1 is applied per field, not per row

Plan D1 gives three rules and says they cover 10 + 2 + 18 = 30 rows. Applied per
*row*, they do not: `CONTENT_EXACT_DUPLICATES` has a blank severity in the
dashboard table but a priority in both (`High` vs `Medium`). Rule (a) resolves its
severity (the silent table yields → `ISSUE`) and rule (c) resolves its priority
(stricter wins → `HIGH`). Per-field application is the only reading that
reproduces the plan's 10/2/18 split, and the test table records that row as
rule `"a+c"`.

### 3.2 A local `_AuditModel` base rather than a change to `StrictModel`

CLAUDE.md ruling 4 says `str_strip_whitespace` is "to be added" to `StrictModel`
with test coverage. It was not added there in this cycle because (a) a global
change to the base of every boundary model is out of scope for a two-item Phase 0
cycle, and (b) it would break `RaeLabel`, which must preserve `"Custom Search "`
with its trailing space for the differential check. `audit.py` therefore defines
`_AuditModel(StrictModel)` with the extra config, and `catalogue.py` stays on
plain `StrictModel`.

### 3.3 `AuditSource` is a `Literal`, not a `StrEnum`

The plan wrote it as a `Literal` and the cycle followed the plan. The
feature-builder's hand-off flags this for reconsideration before the Screaming
Frog adapter lands (§8).

### 3.4 Which file names to use for the ten D3 rows and six inlinks rows

Where RAE's wiring and the real export disagreed, the real export won, because
P0-2's acceptance criterion is "every `sf_sources` filename matches the reference
export listing". Where both a `security_mixed_content.csv` and a bare
`mixed_content.csv` exist, RAE's wiring (`security_`) was kept so the
differential check compares like with like.

### 3.5 What was read to build this, and what was not

The security-auditor asked that this be recorded. The only thing read under
`RAE - Copy/` was the directory listing of
`rankuno-reports/f85971e2-3f74-4810-90ec-ef86a6c18460/` — filenames only. No file
under that tree was opened, no `.env`, nothing modified. Catalogue rows came from
the `ISSUES` and `CRAWL_OVERVIEW_ROWS` tables in RAE's
`masterfile_overview_report.py` (lines 20–147) via the session scratchpad CSVs
prepared during the plan review. No RAE code was copied (ADR 0011, consequence 5).
Filenames are pinned to Screaming Frog 19.4.

---

## 4. Bugs found and fixed

### 4.1 The invariants were declared before they were enforced (red-then-green)

The three invariant tests, and three siblings, were written first and run against
a model with the fields but no validator. All six failed with `DID NOT RAISE
ValidationError`:

```
test_invariant_1_missing_coverage_key_is_rejected
test_invariant_1_empty_coverage_is_rejected
test_invariant_2_unknown_url_is_rejected
test_invariant_2_note_admits_external_urls_for_that_issue_only
test_invariant_3_not_measured_with_members_is_rejected
test_validate_assignment_re_runs_invariants
```

The `model_validator` in §2.3 turned them green. This is the acceptance criterion
of P0-1 ("each invariant has a failing-then-passing test") met literally.

### 4.2 Spec bug: the plan's §3 file layout was circular

Described in §2.1. Fixed by adding `issue_ids.py`; the plan's public names all
still resolve from the modules the plan names.

### 4.3 Spec bug: six Internal Links rows named files that do not exist

RAE's source data wires the six `- Inlinks` rows to `client_error_(4xx)_inlinks.csv`
and the like. A real export writes `internal_client_error_(4xx)_inlinks.csv`,
`internal_server_error_(5xx)_inlinks.csv`, `internal_redirection_(3xx)_inlinks.csv`,
`internal_no_response_inlinks.csv`, `internal_blocked_by_robots_txt_inlinks.csv`,
`internal_blocked_resource_inlinks.csv`. The catalogue uses the real names, pinned
by `test_inlinks_rows_use_the_filenames_screaming_frog_actually_writes`. This is
plan §8's "source filenames hard-coded and partly wrong" reaching beyond the ten
Security rows D3 covers.

### 4.4 Spec bug: D3's files are not all `security_*`

Three of the ten D3 rows are produced under names without the prefix:
`form_url_insecure.csv`, `unsafe_crossorigin_links.csv`,
`protocolrelative_outlinks.csv`. The catalogue uses those; the test
`test_d3_security_rows_are_wired_to_real_files` pins them.

### 4.5 Spec gap: two rows are blank in both RAE tables, so D1 cannot resolve them

`Unsafe Cross Origin Links` and `Missing X-Frames-Options Header` have no severity
or priority in either of RAE's catalogues and are absent from the 30-row
disagreement list D1 was written against. D1 rule (a) needs one table to speak;
here neither does. They were assigned `WARNING` / `LOW` to match every sibling
Security header-and-link row, pinned by
`test_two_rows_blank_in_both_rae_tables_follow_their_security_siblings`.

**This is a judgement call awaiting human confirmation.** It is not a
mechanical application of D1 and should not be read as one. If a reviewer
disagrees, the change is two enum values and one test.

---

## 5. Corrections

1. **Plan §3, "RAE's twelve blank strings are unrepresentable".** The twelve are
   the 10 rows D1 rule (a) covers plus the 2 rows in §4.5 that D1 does not cover.
   The plan's sentence is true (the enums make blanks unrepresentable) but D1 as
   written did not resolve all twelve.
2. **Plan P0-5, "the real export's 115 filenames".** The reference directory holds
   118 entries: 115 CSVs plus `crawl.log`, `crawl.seospider` and `raw_files.zip`.
   The fixture lists all 118 so that a future `.seospider` decision (ADR 0011 §3)
   has the name in front of it.
3. **The feature-builder brief, "`security_*.csv` x11".** The listing has 10 files
   with that prefix.
4. **Plan §3 file list** omits `issue_ids.py` (§2.1). The ADR does not name a file
   layout and is unchanged.
5. **Plan P0-8 and `test_catalogue.py` line 292** say "build-log 0072". This entry
   is 0073 (header note). Plan P1-5's "build-log 0073" will likewise need to become
   0074 or later.
6. **The launching brief for this entry** described the gate as red on
   `treeOverlay.test.ts`. That was true of the implementer's run and is no longer
   true of the tree at 14:51, for reasons that are not this cycle's (§1.4). Both
   states are recorded; neither is edited away.
7. **`README.md` status table** listed `core/state_store.py` as "Not started". It
   has existed since cycle 0012 and CLAUDE.md §8 ruled the gap closed in cycle
   0020; the README row had not caught up. Split into two rows in this cycle.
8. **`docs/ARCHITECTURE.md` §5 ADR table** stopped at 0007 although ADRs 0008 and
   0010 have existed since cycles 0012 and 0053. Rows for 0008, 0010 and 0011 added.

---

## 6. Explicitly not done

- **P0-3 through P0-8 beyond the docs of P0-8.** No `deliverables/` package, no
  Screaming Frog adapter, no engine adapter (`audit_export.py`), no synthetic SF
  bundle fixture, no `test_import_boundary.py`, no `scripts/diff_against_rae.py`.
  Nothing in the repository produces an `AuditDataset` yet. The "a test enforces
  it" sentence in ADR 0011 decision 1 describes P0-6, which is **not written**;
  today the import direction of `contracts/` is a docstring promise checked by
  reading `grep -n "^from" src/modules/seo/contracts/*.py` (only `src.core.schemas`
  and siblings).
- **`links` stays empty by default** (D4). No adapter fills it.
- **No `-Fix` on the gate.** Formatting was already clean.
- **No edits to any file belonging to the other session's uncommitted work**
  (`ReconcilePanel.*`, `adapterInterface.ts`, `screaming_frog_merge.py`,
  `screaming_frog_reconciler.py` and their tests, `bare_url_list.py`,
  `test_bare_url_list.py`, `navTree.test.ts`, `treeOverlay.test.ts`,
  `rae_defects_and_fixes.xlsx`, build-logs 0058/0060/0061/0069) and nothing under
  `RAE - Copy/`.
- **`str_strip_whitespace` not added to core `StrictModel`** (§3.2). Ruling 4 in
  CLAUDE.md is unchanged.
- **No uniqueness check on `pages[].url`.** It is not one of the three invariants;
  handed to P0-3 (§8).
- **Fixture provenance line taken as supplied.** "Screaming Frog SEO Spider 19.4,
  reference crawl f85971e2, 2026-08-28" was not verified by opening `crawl.log`,
  because opening files under `RAE - Copy/` was ruled out (§3.5).
- **The 12 pre-existing broken links in build-logs 0058/0060/0061 were not fixed
  by this cycle.** Rule 4 of the build-log README forbids editing old entries.
  The other session has those three files open with edits at time of writing;
  that is its call to justify, not this cycle's.
- **The ADR's decision text is unchanged.** Its status was already `APPROVED`;
  only the plan's line 6 still said `(PROPOSED)` and was corrected.
- **The two-row `WARNING/LOW` assignment (§4.5) is not confirmed by a human.**

---

## 7. Files changed

Created (no existing file under `src/` or `tests/` was modified):

```
src/modules/seo/contracts/__init__.py                     44 lines   re-exports
src/modules/seo/contracts/issue_ids.py                   178 lines   IssueCategory, Severity, Priority, IssueId (110)
src/modules/seo/contracts/catalogue.py                   382 lines   IssueSpec, RaeLabel, ISSUE_CATALOGUE, ISSUE_SPECS, RAE_LABELS
src/modules/seo/contracts/audit.py                       188 lines   Coverage, AuditSource, AuditPage, AuditLink, AuditDataset, external_urls_note
tests/modules/seo/test_audit_contract.py                 190 lines   20 tests
tests/modules/seo/test_catalogue.py                      300 lines   45 tests (30 parametrised D1 cases)
tests/fixtures/deliverables/sf_export_filenames.txt      119 lines   1 provenance comment + 118 names
```

Documentation (this cycle's Step 8):

```
docs/build-log/0073-not-measured-is-a-value.md           this entry
docs/build-log/README.md                                 index row
docs/DELIVERABLES_IMPLEMENTATION_PLAN.md                 line 6: ADR "(PROPOSED)" -> "(APPROVED)"
README.md                                                contracts/ row; state_store.py row corrected (§5.7)
docs/ARCHITECTURE.md                                     contracts/ in the tree; planned-not-built row for P0-3..P0-7; ADR rows 0008/0010/0011
```

No ADR was added: ADR 0011 already records the decisions this cycle implemented,
and the one deviation from the plan (`issue_ids.py`) is a file layout, not a
ruling.

---

## 8. Follow-ups

1. **Human confirmation of §4.5** — `SECURITY_UNSAFE_CROSS_ORIGIN_LINKS` and
   `SECURITY_MISSING_X_FRAME_OPTIONS_HEADER` at `WARNING` / `LOW`.
2. **P0-3 (feature-builder)**: consider a `pages[].url` uniqueness validator, and
   whether `AuditSource` should become a `StrEnum` before the Screaming Frog
   adapter depends on it.
3. **P0-6 before anything imports `contracts/` from `page_classifier`** — the
   import-boundary test is the mechanism ADR 0011 promises; until it exists the
   direction is unenforced.
4. **Renumber references**: plan P0-8 and P1-5, and the comment at
   `tests/modules/seo/test_catalogue.py:292`, say 0072; this is 0073.
5. **Owner of `treeOverlay.ts` / cycle 0072**: the gate depends on the uncommitted
   `treeOverlay.test.ts` edit (§1.4). Commit it with 0072, or this cycle's commit
   will show a red UI stage that is not its own.
6. **The other session's `README.md` edit** currently renders the reconcile CLI
   line as `scripts` followed by a line break and `econcile_screaming_frog.py`
   (a `\r` where `\reconcile` was meant). Not touched here; it is in that
   session's diff.
