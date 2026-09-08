# Cycle 0072: A list is not an export

- **Date**: 2026-09-08
- **Scope**: A one-column file of URLs — a masterfile tab headed `HTML Pages`,
  or a headerless dump — is accepted by the Screaming Frog cross-check as a
  declared bare list: the set comparison runs, every frog-only URL is
  `UNKNOWN`, nothing merges, and the report says which kind of file it was.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1813 passed` Python / `226 passed` UI / `Total coverage: 93.64%`

---

## 1. Gate results

Two runs are recorded, because the first was not green and the reason matters
(§5).

**feature-builder's run**, `verify.ps1 -Fix`, verbatim tail as reported:

```
=== Format ===   PASSED: Format
=== Lint ===     All checks passed!   PASSED: Lint
=== Type check === Success: no issues found in 63 source files   PASSED: Type check
=== Tests ===
TOTAL                                                           7232    369   1800    133    94%
Required test coverage of 85.0% reached. Total coverage: 93.64%
1813 passed, 1 warning in 131.59s (0:02:11)
PASSED: Tests
=== UI Component Tests ===
 FAIL  src/lib/treeOverlay.test.ts > buildTreeOverlay > gathers OTHERS across locale roots, not only the node named OTHERS
AssertionError: expected [ 'FLAT_URLS' ] to deeply equal [ 'HOMEPAGE', 'UNKNOWN' ]
      Tests  1 failed | 216 passed (217)
FAILED: UI Component Tests
```

**Main session, after re-applying the lost cycle-0069 test changes** (§5):

```
> npx vitest run
 Test Files  20 passed (20)
      Tests  226 passed (226)
> npx tsc --noEmit
exit 0
```

**docs-scribe's own run** of `verify.ps1` (no `-Fix`) while closing the cycle,
so the numbers below are not taken from anyone's memory:

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
src\modules\seo\page_classifier\bare_url_list.py                  51      1     14      1    97%   74
src\modules\seo\page_classifier\screaming_frog_reconciler.py     251      6     52      2    97%   291-292, 441, 445-446, 578
TOTAL                                                           7232    369   1800    133    94%
Required test coverage of 85.0% reached. Total coverage: 93.64%
1813 passed, 1 warning in 121.57s (0:02:01)
PASSED: Tests
=== UI Component Tests ===
 Test Files  20 passed (20)
      Tests  226 passed (226)
PASSED: UI Component Tests
ALL GATES PASSED.
```

The three test files this cycle touched, run alone: 88 passed (12 in
`test_bare_url_list.py`, 55 in `test_screaming_frog_reconciler.py`, 21 in
`test_screaming_frog_merge.py`); 32 of the 88 are new. `ReconcilePanel.test.tsx`
alone: 16 passed, 2 new.

---

## 2. What landed

### 2.1 The defect, from a real upload

A one-column workbook headed `HTML Pages` — a masterfile tab, the shape the
untracked `RAE - Copy/` workbooks use — was dropped on the Cross-check dialog
and came back `400 this sheet has no 'Address' column`. The refusal was correct.
It was also useless: the list is a perfectly good second opinion on *which*
URLs exist, and the set comparison needs nothing more than that.

What the list cannot do is explain a gap. On gep.com the `Internal → HTML`
export's Status Code, Indexability and Content Type columns turned 16,337
"missed" URLs into 16,162 media files and 234 dead links (cycle 0052). A bare
list has none of those columns, so a rule that called any of its URLs a missed
page would be inventing evidence.

### 2.2 `bare_url_list.py` — new, 121 lines

`bare_url_list(body) -> tuple[str, ...] | None`. Pure grid readers for CSV text
and for `.xlsx` (sniffed by the `PK` ZIP header, same as the export loader).
Detection is strict on purpose: exactly one populated column, every value an
absolute `http(s)` URL with a host. A first row whose only cell is not a URL is
a header and is dropped; a first row that is a URL means headerless.

Anything else returns `None` — a two-column sheet, a Search Console `Top pages`
export with its click counts, a column of paths without a scheme, a header-only
file — and the caller keeps its original refusal. The module imports nothing
from the reconciler, so there is no cycle.

An unreadable workbook or a missing `openpyxl` returns an empty grid rather
than raising, because this reader runs *after* the export loader has already
refused the file, and that refusal names the real problem.

### 2.3 The reconciler: the format is declared, not inferred

New in `screaming_frog_reconciler.py`:

| Name | What it is |
| :--- | :--- |
| `FrogGapReason.UNKNOWN` | The only reason a bare list can produce for a frog-only URL |
| `ExportFormat` | `StrEnum`: `INTERNAL_HTML`, `BARE_URL_LIST` |
| `NotAnExportError(ValueError)` | Raised at both existing "no `Address` column" sites; message text unchanged |
| `CrossCheckInput` | `StrictModel`: `rows`, `source_format` |
| `load_cross_check_input(body)` | Tries the export loader; on `NotAnExportError` only, tries the bare-list reader; re-raises the original refusal otherwise |
| `ReconciliationReport.source_format` | Defaults to `INTERNAL_HTML` |
| `reconcile(..., source_format=ExportFormat.INTERNAL_HTML)` | Same default, so every existing caller is unchanged |

`source_format` is recorded on the report rather than inferred from the
reasons, because a bare list whose every URL the crawl already holds produces
no `UNKNOWN` row at all — and the reader would otherwise take a set comparison
with no status evidence for a full export that found nothing.

`NotAnExportError` is a subclass rather than a bare `ValueError` so the loader
can tell "wrong export tab" (where a bare list is worth trying) from "not a CSV
at all" or "not a workbook" (where it is not). That is the whole reason the
retry is narrow.

### 2.4 The merge: an explicit no-op

`screaming_frog_merge.py` now calls `load_cross_check_input`, passes
`source_format` through, and returns `MergeOutcome(output, report, 0)` for a
bare list before looking at `missed_pages`. The guard is explicit rather than
left to `missed_pages` being empty, because that emptiness is a property of the
reason rules and this module must not depend on it silently.

### 2.5 The panel says what it compared against

`ReconcilePanel.tsx`: the intro copy offers a plain URL list and states it
carries no status, indexability or content type and never merges; `UNKNOWN`
has a label; a warning banner precedes the counts on a bare-list result,
because on a bare list "Pages we missed: 0" is true and misleading; and the
"nothing to merge" description reads "A bare list is never merged" instead of
"Every live, in-scope page in the export was already in the crawl", which
would be false.

`isBareList()` checks `summary.source_format === "BARE_URL_LIST"` first and
falls back to `"UNKNOWN" in summary.frog_reasons`. The fallback exists because
the API summary does not forward the marker yet (§6).

---

## 3. Design decisions

### 3.1 Set comparison only, reasons `UNKNOWN`, never merged

The alternative was to run the bare list through the same reason rules with
every status field at its default. That would have labelled every in-scope URL
`MISSED_PAGE` — the one reason that describes a defect — on no evidence, and
then merged them into a new job as low-confidence pages. The list would have
manufactured up to 16,000 findings on gep.com. `UNKNOWN` says exactly what is
known: the URL was written down somewhere and the crawl did not fetch it.

### 3.2 Try the export first; the list only after the specific refusal

The bare-list reader is consulted only after `NotAnExportError`. A file that is
not a CSV at all, or a workbook that cannot be opened, keeps the loader's own
message. Trying the list reader on every failure would have replaced a precise
refusal with a vaguer one.

### 3.3 The reconciler decides, not the UI

The panel's inference from `UNKNOWN` is a stopgap for one missing field in
`server.py` (§6), not the design. The engine's report is the record of what
was compared, and it carries the format so that a stored cross-check re-read
later still says which kind of file it came from.

### 3.4 ADR 0011 applies; no new ADR

ADR 0011 §3 rules that Screaming Frog is an input format, never a subprocess.
This cycle adds a second, weaker input format under that same ruling, with
nothing new spawned or fetched. The one rule that is arguably consequential —
**a bare list never merges** — is recorded here and flagged as an amendment
candidate for ADR 0011 (§8). That file is untracked and open in the other
session, so it was not edited.

---

## 4. Bugs found and fixed

- **The refusal that described the wrong problem.** A masterfile tab is a
  legitimate input and was rejected as "not a Screaming Frog export". Fixed by
  accepting it under its own name rather than by loosening the export loader.

- **README.md carried a carriage return inside a path.** At `e71e506`, both
  `scripts\reconcile_screaming_frog.py` command lines in the README's
  cross-check section hold a literal `0x0D` byte where `\r` was interpreted
  by whoever wrote them, so the path rendered as `scripts` + line break +
  `econcile_screaming_frog.py`. Repaired to the literal backslash while
  editing that section for the bare-list paragraph. (The first two repair
  attempts went through a shell heredoc, which collapsed `\\` to `\` and
  wrote the same CR byte back; the third went through a script file.)

  A side effect worth knowing about: the README blob at `e71e506` is stored
  with CRLF endings although `.gitattributes` declares `* text=auto eol=lf`.
  Git skips normalisation for a working copy that contains lone CR bytes, so
  the two defective bytes were the only reason `git diff README.md` had been
  showing small diffs. With them gone, git normalises the working copy to LF
  and `git diff` shows every line changed (218 insertions, 208 deletions);
  `git diff --ignore-cr-at-eol README.md` shows the real change, 15
  insertions and 5 deletions, of which 3 and 1 are the other session's
  `contracts/` and `state_store` rows. The working copy is left as LF, which
  is what the next commit will store regardless. This is a one-time
  renormalisation, not a rewrite of the README.

- **Twelve broken links in build-log entries 0058, 0060 and 0061.** Those
  entries link to `src/...`, `tests/...` and `rankuno-ui/...` as if from the
  repository root, but live in `docs/build-log/`, so `drift_check.py` had
  been failing on them since they were written. Every target exists.
  Prefixed each with `../../`. This is a path repair, not a content edit —
  the entries say the same things they said before.

No test was found to be wrong. The stale UI expectation in §5 was a test that
had been correct, was lost, and was restored.

---

## 5. Corrections

- **Handoff 1 from feature-builder — "treeOverlay.test.ts fails on main" —
  was not a bug in `treeOverlay.ts`.** The failing expectation was the stale
  one. Cycle 0069 §4b (2026-09-07) regrouped OTHERS by URL folder and changed
  that test's expectation to `["FLAT_URLS"]`. The parallel session's
  `git stash` and history rewrite (`30f9284` → `e71e506`) committed the
  pre-change test files while the source change (`navTree.ts`,
  `othersTrail`) survived. The main session re-applied the three lost pieces
  on 2026-09-08: the `FLAT_URLS` expectation in `treeOverlay.test.ts`, the
  `othersTrail` / `buildNavTree and OTHERS` describes in `navTree.test.ts`
  (9 tests), and §4b of build-log 0069 itself — which is why that entry
  shows as modified in this cycle's working tree. The correction is recorded
  in 0069 §4b as well; it is repeated here because this is the cycle in which
  the loss surfaced as a red gate.

- **README.md at `e71e506` said "CSV only; `.xlsx` is not supported
  (build-log 0028)".** That has been false since cycle 0031 shipped native
  `.xlsx` reading. The sentence now cites 0031 and describes both formats.

- **`drift_check.py` has not been passing.** Entries 0070 and 0071 do not
  paste its output; the 12 broken links in §4 predate both and would have
  failed it. Its output is pasted in the closing report for this cycle and
  in §9 below.

---

## 6. Explicitly not done

- **`server.py` was not touched.** Another session has it open. The API's
  `ReconciliationSummary` therefore does **not** carry `source_format`, and
  the reconcile endpoint does not forward `report.source_format.value`. The
  UI infers a bare list from the `UNKNOWN` reason, which only that format
  produces — and cannot infer it at all for a bare list whose every URL the
  crawl already holds. Two lines; handed to `api-data-engineer` (§8).
  Verified that the three label lookups in `server.py` — `GAP_MEANINGS.get`,
  `SHEET_TITLES.get`, and the workbook `rank()` map — all supply a default,
  so `UNKNOWN` reaching them today cannot raise.

- **A bare list is never merged, and no option was added to merge it.** A URL
  with no status is not evidence of a live page (§3.1).

- **Paths without a scheme are refused.** `/about/`, `about/` and `about`
  are not a bare list. Prepending the crawl's base URL was considered and
  rejected for this cycle: it would silently attach a host to values whose
  host the file never stated.

- **Multi-sheet workbooks read the active sheet only**, as the export loader
  already did. A masterfile with several tabs must be exported one tab at a
  time.

- **The CLI `scripts/reconcile_screaming_frog.py` was not changed.** It goes
  through `merge_reconciled_urls`, so a bare list works there by construction,
  but no test exercises it from the CLI and its help text does not mention
  lists.

- **`screaming_frog_reconciler.py` is 798 lines** (695 before), against the
  400-line target. Its "CSV only, deliberately" docstring section was already
  stale before this cycle (native `.xlsx` shipped in 0031) and is still
  present. Handed to `refactorer` (§8).

- **ADR 0011 was not edited or created anew.** Amendment candidate noted in §8.

- **`docs/ARCHITECTURE.md` was not changed.** It does not list
  `screaming_frog_reconciler.py`, `screaming_frog_merge.py` or the new
  `bare_url_list.py` in its module tree, and it does not describe the
  cross-check input; the brief limited edits to where the input is described.
  Adding the three reconciler modules to the tree is a small follow-up (§8).

---

## 7. Files changed

```
src/modules/seo/page_classifier/bare_url_list.py              new, 121 lines
src/modules/seo/page_classifier/screaming_frog_reconciler.py  +ExportFormat, NotAnExportError,
                                                              CrossCheckInput, load_cross_check_input,
                                                              FrogGapReason.UNKNOWN,
                                                              ReconciliationReport.source_format,
                                                              reconcile(source_format=)
src/modules/seo/page_classifier/screaming_frog_merge.py       load_cross_check_input; bare-list no-op
rankuno-ui/src/components/jobs/ReconcilePanel.tsx             list copy, UNKNOWN label, isBareList(),
                                                              warning banner, corrected no-merge text
rankuno-ui/src/adapters/adapterInterface.ts                   ReconciliationSummary.source_format?: string
tests/modules/seo/test_bare_url_list.py                       new, 12 tests
tests/modules/seo/test_screaming_frog_reconciler.py           +TestBareUrlList (7 functions, parametrised)
tests/modules/seo/test_screaming_frog_merge.py                +TestABareListNeverMerges (4)
rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx        +2
rankuno-ui/src/lib/treeOverlay.test.ts                        FLAT_URLS expectation restored (§5)
rankuno-ui/src/lib/navTree.test.ts                            9 lost tests restored (§5)
docs/build-log/0069-cross-check-overlay-and-full-screen-tree.md   §4b restored (§5)
docs/build-log/0058-*.md, 0060-*.md, 0061-*.md                12 links prefixed ../../ (§4)
README.md                                                     cross-check section: both formats,
                                                              bare list, CR byte repaired
docs/build-log/README.md                                      index row 0072
```

Present in the working tree but **not part of this cycle** (the other
session's uncommitted work, untouched): `.gitignore`,
`src/modules/seo/contracts/`, `docs/adr/0011-*.md`,
`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md`, `tests/fixtures/deliverables/`,
`tests/modules/seo/test_audit_contract.py`, `tests/modules/seo/test_catalogue.py`,
`rae_defects_and_fixes.xlsx`, and the README/ARCHITECTURE rows for `contracts/`.

---

## 8. Follow-ups

1. **api-data-engineer**, once `server.py` is free: add
   `source_format: str = "INTERNAL_HTML"` to `ReconciliationSummary` and
   `source_format=report.source_format.value` in the reconcile endpoint. Then
   the panel's `UNKNOWN` fallback can go.
2. **refactorer**: `screaming_frog_reconciler.py` at 798 lines; the loaders
   (`load_screaming_frog_csv`, `_rows_from_xlsx`, `load_screaming_frog_export`,
   `load_cross_check_input`) are a natural split, and the "CSV only" docstring
   section must go with them.
3. **ADR 0011 amendment candidate** (not applied — the file is untracked and
   open elsewhere): add to §3 that a bare URL list is a recognised input
   format with the rule *set comparison only; every frog-only URL `UNKNOWN`;
   never merged; format declared on the report*. The rule is consequential
   because it decides that absence from a crawl is not, by itself, a finding.
4. **ARCHITECTURE.md module tree**: list `screaming_frog_reconciler.py`,
   `screaming_frog_merge.py` and `bare_url_list.py` under `page_classifier/`.
5. **CLI**: mention the list input in `reconcile_screaming_frog.py --help`
   and add one test that runs a bare list through it.

---

## 9. Drift audit

Output of `.\.venv\Scripts\python.exe scripts\drift_check.py` after the link
repairs in §4, pasted at close of cycle:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

Before the §4 link repairs the same command reported `FAILED: 12 documentation
drift issue(s) detected`, all of them in 0058, 0060 and 0061.

Numbering: 0072 was the first free number when this entry was started (0071
was the highest). The parallel session took 0073 while this entry was being
written; both rows are in the index and there is no collision.
