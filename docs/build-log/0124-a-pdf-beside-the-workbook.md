# Cycle 0124: A PDF beside the workbook

- **Date**: 2026-09-29
- **Scope**: New feature — `GET /jobs/{id}/urls.pdf`, a printable PDF sibling
  of the existing `GET /jobs/{id}/urls.xlsx` (build-log 0102), plus the
  job-row menu entry and server/ADR/dependency work behind it. Design
  approved in an earlier Phase A this session. Interleaved in the same
  working tree, same file (`src/modules/seo/page_classifier/reports.py`),
  same session as [cycle 0123](0123-a-status-cell-that-was-a-url-cell.md)'s
  HTTP Status column bug fix — see §8.
- **Commit**: uncommitted at time of writing.
- **Quality gate**: **GREEN**, independently re-run by the scribe in full —
  see §1.

## 1. Gate results

### 1.1 Whole-repo gate, re-run by the scribe

```
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Run to completion (6m40s for the Python stage, 39.14s for the UI stage):

```
=== Format ===
542 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 152 source files
PASSED: Type check

=== Tests ===
[... 15,247 statements across src/, coverage table omitted here — see
`reports.py`'s own row below ...]
src\modules\seo\page_classifier\reports.py    127     11     36      5    88%   219-224, 240-249, 253-262, 309->312, 352->351, 367-368
----------------------------------------------------------------------------------------------------------------------
TOTAL                                        15247    940   3306    274    93%

52 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 92.78%
3594 passed, 2 skipped, 1 warning in 400.99s (0:06:40)
PASSED: Tests

=== UI Component Tests ===
 Test Files  47 passed (47)
      Tests  604 passed (604)
   Start at  19:55:33
   Duration  39.14s (transform 1.35s, setup 8.48s, collect 50.50s, tests 44.35s, environment 30.19s, prepare 4.44s)

PASSED: UI Component Tests

ALL GATES PASSED.
Next: SDLC Step 8 - README & architecture drift audit.
```

Both cycles' own reported gate figures (3594 py / 92.78% cov / 604 ui) match
this re-run exactly. `reports.py`'s own coverage line (88%, uncovered lines
219–224/240–249/253–262 in `_sheet_by_indexability`'s Blocked/Unknown
branches and 309/352/367–368 in unrelated helper edge cases) shows the new
`generate_pdf`/`_pdf_row` code paths and cycle 0123's fixed lines are
exercised — none of the newly added lines appear in the uncovered set.

### 1.2 Targeted, as reported by the implementing agent (not independently
re-run in isolation by the scribe — superseded by §1.1's full run)

Backend targeted: `tests/api/test_server.py` PDF + xlsx tests combined, 9
passed. Frontend targeted: `CrawlJobsView.test.tsx`, 14 passed (1 file).
`tsc --noEmit` clean. `export_ui_contract.py --check`: "UI contract is up to
date."

## 2. What landed

- `src/modules/seo/page_classifier/reports.py` —
  `MasterURLReport.generate_pdf()` and `_pdf_row()`. Landscape A4,
  `SimpleDocTemplate` + `Table` + `Paragraph` cells (not bare strings) so a
  long URL wraps onto a second line instead of overflowing into the next
  column; every cell's text goes through `xml.sax.saxutils.escape` before
  reaching a `Paragraph`, because `Paragraph` interprets its input as a
  restricted XML/HTML-like markup subset and an unescaped `&`, `<` or `>` in
  a URL or a page title would otherwise be parsed as markup rather than
  rendered as text.
- `src/api/server.py` — `GET {API_PREFIX}/jobs/{job_id}/urls.pdf`, a sibling
  of `download_urls_workbook` with the identical auth/ownership/409
  sequence: `require_principal` → `_owned_job` → `has_result` 409 check →
  `read_result` → `PageClassificationOutput.model_validate` (409 on a
  schema-drifted result) → `MasterURLReport(...).generate_pdf()`.
- `pyproject.toml` — `reportlab>=4.0,<5.0` added to core `dependencies`
  (not the `seo` extra), plus a `[[tool.mypy.overrides]]` block for
  `reportlab.*` (no `py.typed` marker shipped, same treatment as
  `openpyxl`). See §3 and ADR 0024 for why core rather than extras.
- `docs/adr/0024-pdf-url-export-uses-reportlab-in-core-dependencies.md` —
  new. Authored by the implementing (feature-builder) cycle itself. Confirmed
  against ADRs 0021–0023, all also feature-cycle-authored with the same
  "AI Lead, Lead AI Systems Engineer" deciders line and the same
  Context/Decision/Alternatives/Consequences structure — the convention
  holds, and this entry did not need to add or fix anything in it. See §6.
- `rankuno-ui/src/adapters/adapterInterface.ts` — `downloadUrlListPdf?`,
  optional (mirroring `downloadUrlList?`) because fixture sessions have no
  server behind them to build the PDF.
- `rankuno-ui/src/adapters/httpAdapter.ts` — `downloadUrlListPdf`
  implementation, byte-identical shape to `downloadUrlList`'s
  fetch-then-blob pattern (bearer-guarded route, no `<a href>`).
- `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` — a *separate*
  `canDownloadUrlsPdf` flag, not derived from `canDownloadUrls`, gating a
  new "Download URLs (PDF)" menu entry directly below "Download URLs" —
  `canDownloadUrlsPdf && ready`, one click, no panel, same UX contract as
  the `.xlsx` sibling.
- Tests: `tests/api/test_server.py::TestUrlsPdfDownload` (subclasses
  `TestUrlsWorkbookDownload`, inheriting its fixture builder rather than
  duplicating it) — 5 tests: 404 unknown job, 409 not-finished, 200 with
  correct content-type/filename/body (decoded via a new `_pdf_text_bytes()`
  helper, stdlib `base64`+`zlib`+`re` only, no new PDF-parsing dependency),
  409 on a result predating the current output contract.
  `tests/modules/seo/page_classifier/test_reports.py::TestGeneratePdf` — 3
  tests (see §8 for how this file is shared with cycle 0123).
  `rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx` — 5 new tests (14
  total in the file, up from 9): the menu item appears/downloads, opens no
  panel, hides with no adapter method, hides for an unfinished job, and both
  `.xlsx`/`.pdf` menu items appear independently of each other.

## 3. Design decisions

### 3.1 reportlab, not weasyprint

weasyprint would have let the PDF reuse `CrawlReport.tsx`'s own markup, but
needs an OS-level GTK3 runtime (Pango, Cairo, GDK-PixBuf) with no plain `pip
install` path on Windows — a complication ADR 0004's local-workstation-first
stance exists to avoid, and it would have been the only dependency in this
project with that shape. reportlab is a pure-Python wheel, on the same
footing as every other dependency already in `pyproject.toml`. Full
reasoning in ADR 0024.

### 3.2 Core dependency, not the `seo` extra — an explicitly unresolved
question, carried forward

`reportlab` sits in `pyproject.toml`'s core `dependencies`, following
`openpyxl`'s own precedent: `reports.py` is a `modules/seo/page_classifier`
component, but `src/api/server.py` imports it directly, and `src/api` only
ever installs core. This is the **second** dependency now in core
specifically because `reports.py` is reachable from `src/api` without the
`seo` extra as a precondition — working against `pyproject.toml`'s own "keep
this list MINIMAL" comment for the second time.

ADR 0024 records this as an **open question, deliberately not resolved in
this cycle**: a third dependency landing the same way should trigger an
actual decision (lazy-import the route handlers inside
`download_urls_workbook`/`download_urls_pdf`, or declare `src/api` itself
requires the `seo` extra) rather than a third silent addition. Carried into
this entry's §7 follow-ups verbatim — not silently resolved here either.

### 3.3 No shared row-construction path with `_sheet_all_urls`

`_pdf_row()` duplicates `_sheet_all_urls()`'s per-page column logic rather
than sharing it: openpyxl accepts typed values (enums, ints, floats)
directly, `Paragraph` cells need pre-formatted text, and unifying the two
would route every workbook cell through a needless string round-trip.
Accepted risk: the two column sets can drift apart. Mitigated by
`TestGeneratePdf::test_row_matches_the_all_urls_sheet_column_for_column`
pinning them to agree — see §8.

## 4. Bugs found and fixed

None new in this cycle's own code — the PDF generator is new code with no
prior behaviour to have been wrong. It inherits (correctly, per §8)
[cycle 0123](0123-a-status-cell-that-was-a-url-cell.md)'s fix for the "HTTP
Status" column, rather than reproducing the pre-fix bug in a second export
format.

## 5. Corrections

None. This cycle does not revise any earlier entry's claims.

## 6. ADR 0024 — confirmed complete

Read directly (`docs/adr/0024-pdf-url-export-uses-reportlab-in-core-dependencies.md`).
Matches this repo's ADR convention: `Status`/`Date`/`Deciders` header,
`Context`/`Decision`/`Alternatives considered`/`Consequences` sections, in
the same shape as ADRs 0020–0023. It already states both open questions in
its own Decision §2 and Consequences sections (§3.2 above quotes the first;
the second is the reportlab `Table` in-memory-construction limit, carried
into this entry's §7). Nothing added or corrected by this scribe pass.

## 7. Explicitly not done

- **`reportlab` staying in core `dependencies` rather than the `seo` extra
  is not resolved**, per §3.2 / ADR 0024. This is the second instance of the
  pattern (`openpyxl` was the first); a third dependency landing in core for
  the same reason should force an actual decision, not a third silent
  addition.
- **`reportlab`'s `Table` flowable has no streaming/paginated construction
  path** (unlike the `.xlsx` export's available `write_only` `Workbook`
  option) — unmeasured against ADR 0001's 500k-URL scale ceiling. The
  `.xlsx` sibling carries the same shape of open question (build-log 0102's
  own write-only-vs-normal-`Workbook` flag); this one is now recorded for
  the PDF path rather than assumed safe by analogy.
- No browser-rendered visual check of the generated PDF was performed by
  the scribe — verification here is at the level of "starts with `%PDF`,"
  decoded content-stream text matching expected values, and file-level
  reading of the generator code, not a rendered-page visual review.
- `rankuno-ui`'s `MockAdapter` does not implement `downloadUrlListPdf` — same
  posture as `downloadUrlList`'s own absence from fixtures (build-log 0102),
  not a new gap.

## 8. How this interleaved with cycle 0123 in the same file

See [cycle 0123 §8](0123-a-status-cell-that-was-a-url-cell.md#8-how-this-interleaved-with-cycle-0123-in-the-same-file)
for the full account from the other side. Summary from this cycle's side:
`generate_pdf()` and `_pdf_row()` were added as new methods, touching no
line cycle 0123 also touched, so there was no merge conflict — both sets of
edits simply coexist in the one uncommitted working tree this session. The
one place the two cycles' work had to actually agree rather than merely
avoid touching the same lines: `_pdf_row()` calls the same
`self._extract_status_code(page)` helper and applies the same `"Unknown"`
fallback cycle 0123 introduced, so the new PDF path reports the same honest
absence the fixed workbook path does, rather than independently
reintroducing the `page.final_url` bug in a second file format.
`TestGeneratePdf::test_row_matches_the_all_urls_sheet_column_for_column`
(this cycle's test) asserts that agreement directly, including the
`"Unknown"` value. Verified by the scribe by reading the current file
directly (`src/modules/seo/page_classifier/reports.py` lines 144–157,
179–194), not taken on either cycle's report alone.

Both cycles' tests live in one new test file,
`tests/modules/seo/page_classifier/test_reports.py`: `TestAllUrlsSheetHttpStatusColumn`
(cycle 0123, 3 tests) and `TestGeneratePdf` (this cycle, 3 tests) — 6 tests
total, no duplication, no conflict.

## 9. Files changed

```
src/api/server.py                                          | +48
src/modules/seo/page_classifier/reports.py                 | this cycle's portion: generate_pdf, _pdf_row
pyproject.toml                                              | +17 (reportlab dependency + mypy override)
docs/adr/0024-pdf-url-export-uses-reportlab-in-core-dependencies.md | new
rankuno-ui/src/adapters/adapterInterface.ts                | +9
rankuno-ui/src/adapters/httpAdapter.ts                      | +25
rankuno-ui/src/components/jobs/CrawlJobsView.tsx            | +36
tests/api/test_server.py                                    | +67
rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx       | +82
tests/modules/seo/page_classifier/test_reports.py           | this cycle's portion: TestGeneratePdf, 3 tests
```

Shared with cycle 0123 in the reports.py and test_reports.py files — see §8.

## 10. Follow-ups

- Decide the core-vs-extra placement question (§3.2 / §7) before a third
  `seo`-only dependency lands the same way `openpyxl` and `reportlab` did.
- Measure `reportlab`'s in-memory `Table` construction against a
  representative large crawl (tens of thousands of rows) before treating
  the PDF export as safe at ADR 0001's 500k-URL ceiling; same open question
  as the `.xlsx` export's `write_only`-`Workbook` flag (build-log 0102).
- A stray, untracked `~$rae_defects_and_fixes.xlsx` Excel lock file sits in
  the repo root, unrelated to either this cycle or cycle 0123 — not created
  by either, not touched by either, flagged here so it is not mistaken for
  either cycle's output. It is not gitignored; whoever commits next should
  not sweep it in.
