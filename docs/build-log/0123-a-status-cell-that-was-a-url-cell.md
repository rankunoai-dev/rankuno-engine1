# Cycle 0123: A status cell that was a URL cell

- **Date**: 2026-09-29
- **Scope**: Production bug fix — the "All URLs" sheet's "HTTP Status" column
  in `GET /jobs/{id}/urls.xlsx` was populated with `page.final_url`, not a
  status code. Interleaved in the same working tree, same file
  (`src/modules/seo/page_classifier/reports.py`), same session as
  [cycle 0124](0124-a-pdf-beside-the-workbook.md)'s PDF export — see §8.
- **Commit**: uncommitted at time of writing.
- **Quality gate**: see §1. Full whole-repo gate re-run by the scribe, not
  just the implementer's targeted run.

## 1. Gate results

### 1.1 Targeted reproduction, as reported by the implementing agent

Reproduced failing on the pre-fix file (git-stashed `reports.py` in
isolation):

```
FAILED test_http_status_column_is_never_the_row_url - AssertionError: assert 'https://e.com/blog/' != 'https://e.com/blog/'
FAILED test_http_status_column_is_an_honest_unknown_marker - AssertionError: assert 'https://e.com/blog/' == 'Unknown'
FAILED test_matches_the_by_http_status_sheet_convention - AssertionError: assert ['https://e.com/blog/'] == ['Unknown']
```

Not independently re-stashed by the scribe — doing so during this session
would have meant reverting a file two concurrently-landing cycles were both
editing, mid-gate-run, which is a worse risk than trusting a fail-then-pass
pair that is fully consistent with reading the pre-fix code directly (§3
below shows exactly why the assertion failed). The scribe instead verified
the *current*, fixed file directly — see §1.2.

### 1.2 Current file, read directly, independently confirmed

`src/modules/seo/page_classifier/reports.py` line 149 (inside `_pdf_row`,
[cycle 0124](0124-a-pdf-beside-the-workbook.md)'s addition) and line 185
(inside `_sheet_all_urls`, this cycle's fix) both read:

```python
str(status_code) if status_code is not None else "Unknown"
```

`status_code` comes from `self._extract_status_code(page)`, which
(confirmed by reading it directly) always returns `None` — see §3. Sheet 3
(`_sheet_by_http_status`) already used the literal string `"Unknown"` for
the same absence before this cycle; sheet 1 now matches it.

### 1.3 Whole-repo gate, re-run by the scribe

```
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Verbatim output pasted in [cycle 0124 §1](0124-a-pdf-beside-the-workbook.md#1-gate-results)
— the two cycles share one working tree and one gate run; recording it twice
would risk two different numbers if the tree changed between pastes. This
entry's test file (`tests/modules/seo/page_classifier/test_reports.py`) and
this entry's fix are both covered by that single run.

## 2. What landed

- `src/modules/seo/page_classifier/reports.py` — `_sheet_all_urls()` now
  writes `str(status_code) if status_code is not None else "Unknown"` for
  the "HTTP Status" column, reusing the existing `_extract_status_code()`
  helper and matching `_sheet_by_http_status()`'s (sheet 3) pre-existing
  convention for the same absence.
- `_extract_status_code()`'s docstring rewritten. It still always returns
  `None` — no behaviour change — but the docstring now says this is a
  deliberate, permanent architectural decision (see §3), not a stale TODO.
  The old `# TODO: Add http_status field...` comment was removed: no such
  field is planned, and an unnumbered TODO is against this repo's own style
  rule (`CLAUDE.md` §9).
- `tests/modules/seo/page_classifier/test_reports.py` — **new file**. No
  test file for `reports.py` existed before this session (`MasterURLReport`
  shipped with zero test coverage in cycle 0102, per that entry's own §4).
  `TestAllUrlsSheetHttpStatusColumn` (3 tests, this cycle) plus
  `TestGeneratePdf` (3 tests, cycle 0124) share the file — see §8.

## 3. The bug

Confirmed live against production: three real jobs, via a user-supplied
bearer token, direct `GET /jobs/{id}/urls.xlsx` calls. Every row's "HTTP
Status" cell exactly duplicated that row's "URL" cell.

Root cause, traced through the full pipeline
(`discovery.py::SiteGraph.record_fetch` → `signal_parsers.py::indexability_of`
→ `PageEvidence` → `FullPageIntelligenceProfile`): **no per-page HTTP status
code reaches the report anywhere in the pipeline.** The raw HTTP status is
read once, at fetch time, and is deliberately discarded immediately after
`indexability_of()` derives an `Indexability` enum member plus a reason
string from it. `FullPageIntelligenceProfile` has no field to carry the raw
code — not even for the 3xx/4xx cases where `indexability_reason` happens to
mention it in prose.

This is not an oversight. It is tied to ADR 0001's 20k–500k URL
memory-footprint target: a crawl already holds its entire graph, including
page HTML, in RAM (`CLAUDE.md` §8), and retaining a raw status code per page
for the lifetime of the crawl is exactly the kind of per-page retention that
target is meant to bound. It is also not a `CLAUDE.md` §8 listed gap — no
existing entry there described a status field as available.

Given that, `reports.py::_extract_status_code()` was already correctly
`None` on every call. The bug was one level up: `_sheet_all_urls()` wrote
`page.final_url` into the "HTTP Status" column instead of using that
(always-`None`) result at all — an apparent copy-paste of the adjacent "URL"
column's source expression into the wrong column's row-construction code.

## 4. Design decision: honest absence, not invented data

Two branches were available:

1. **Add a real per-page status field.** Rejected without implementation —
   it reopens the ADR 0001 RAM-footprint question and was out of this
   cycle's scope; flagged as a possible future cycle in §6, not decided
   here.
2. **Report the absence honestly** (`"Unknown"`), reusing the exact
   convention `_sheet_by_http_status()` already established for the same
   data gap. **Taken.** Zero new surface area, and it makes sheet 1 and
   sheet 3 agree with each other instead of one inventing a wrong answer and
   the other admitting it does not know.

## 5. Bugs found and fixed

1. **"HTTP Status" column duplicates the URL column** (§3). Fixed per §4.
2. **Spec/comment bug, not a code bug**: the removed `# TODO: Add
   http_status field...` comment asserted a field was coming. No such field
   exists in `FullPageIntelligenceProfile`'s schema and none is planned —
   the comment was itself wrong, not merely stale. Corrected by replacing it
   with the actual architectural reasoning (§3), not by re-adding a TODO
   with an issue number, because there is no issue to number: this is a
   closed decision, not an open one.

## 6. Corrections

None to a prior published entry. Build-log 0102 §4 (cited by this cycle's
new test file's module docstring) had already recorded both defects
correctly as findings — `_extract_status_code()` always returns `None`, and
the "HTTP Status" column is actually `page.final_url` — without fixing
either. This cycle closes that gap; it does not correct 0102's account of
it.

## 7. Explicitly not done

- **No per-page HTTP status field was added to `FullPageIntelligenceProfile`
  or anywhere in the pipeline.** `"Unknown"` is what every row will show
  until (if ever) a future cycle decides the RAM-footprint tradeoff in §4
  option 1 is worth taking. Do not read this fix as "status is now tracked."
- `_sheet_by_indexability()`'s own indexability grouping (Indexable /
  Blocked / Unknown, keyed off the same always-`None`
  `_extract_status_code()`) was not touched. Every page in every crawl
  currently lands in that sheet's "Unknown" bucket; this was true before
  this cycle and remains true after it. Not this cycle's scope, and not
  silently fixed as a side effect.
- The PDF export's own use of the same fixed logic (`_pdf_row`, line 149) is
  [cycle 0124](0124-a-pdf-beside-the-workbook.md)'s work, not this cycle's —
  see §8 for how the two interleaved.

## 8. How this interleaved with cycle 0124 in the same file

This cycle and [cycle 0124](0124-a-pdf-beside-the-workbook.md) (the PDF URL
export) landed in the same working tree, in the same session, both editing
`src/modules/seo/page_classifier/reports.py`, without a merge conflict —
they were never committed separately or rebased against each other; both
sets of edits simply coexist in one uncommitted working tree. This worked
because the two changes touch disjoint regions of the file: this cycle
edited `_sheet_all_urls()` and `_extract_status_code()`'s docstring; cycle
0124 added `generate_pdf()` and `_pdf_row()` as new methods.

The interesting overlap is in `_pdf_row()`: cycle 0124 wrote it to call
`self._extract_status_code(page)` and apply the *same* `"Unknown"` fallback
this cycle introduced in `_sheet_all_urls()`, rather than reproducing the
old `page.final_url` bug in the new PDF code path. `tests/modules/seo/page_classifier/test_reports.py::TestGeneratePdf::test_row_matches_the_all_urls_sheet_column_for_column`
(cycle 0124's test) asserts the PDF row and the workbook row agree
column-for-column for the same page, *including* that both show `"Unknown"`
for HTTP Status — which is the cross-check proving the PDF feature picked up
this cycle's fix rather than independently reproducing the bug in a second
file format. Verified directly by reading the current file (§1.2), not
taken on trust from either cycle's own report.

Both cycles' tests live in the one new test file, `TestAllUrlsSheetHttpStatusColumn`
(this cycle, 3 tests) and `TestGeneratePdf` (cycle 0124, 3 tests) — 6 tests
total, no file added twice, no conflict.

## 9. Files changed

```
src/modules/seo/page_classifier/reports.py               | edited (this cycle's portion: _sheet_all_urls, _extract_status_code docstring)
tests/modules/seo/page_classifier/test_reports.py         | new (this cycle's portion: TestAllUrlsSheetHttpStatusColumn, 3 tests)
```

Shared with cycle 0124 in the same two files — see §8.

## 10. Follow-ups

- Whether a real per-page HTTP status field is ever worth adding, against
  ADR 0001's RAM-footprint target, is an open question this cycle
  deliberately did not decide (§4, §7).
- `_sheet_by_indexability()`'s grouping is permanently "everything Unknown"
  under the current pipeline — worth a future cycle's attention if that
  sheet is ever relied on for real triage.
