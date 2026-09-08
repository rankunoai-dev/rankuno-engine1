# Cycle 0076: A PDF is not an orphan

- **Date**: 2026-09-08
- **Scope**: Engine-only URLs in the Screaming Frog cross-check that end in a
  document suffix get their own reason — `PDF_FILE`, `PRESENTATION_FILE`,
  `SPREADSHEET_FILE`, `OTHER_FILE` — and their own workbook sheet, instead of
  being filed as sitemap orphans.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1964 passed, 1 skipped` Python / `232 passed` UI /
  `Total coverage: 93.86%`

---

## 1. Gate results

Run by docs-scribe while closing the cycle, stage by stage rather than through
`verify.ps1`, because ruff had to exclude five test files that belong to
another Claude session's in-flight work and must not be touched by this one:
`tests/integrations/test_gsc_token_manager.py`,
`tests/integrations/test_gsc_client.py`, `tests/core/test_config.py`,
`tests/modules/seo/test_screaming_frog_adapter.py`,
`tests/modules/seo/test_screaming_frog_bundle.py`. Every other stage ran over
the whole tree.

```
> ruff format --check .   (five exclusions above)
277 files already formatted
> ruff check .            (five exclusions above)
All checks passed!
> mypy src               (--strict via pyproject)
Success: no issues found in 67 source files
> pytest --cov=src --cov-report=term-missing
src\api\server.py                                                644     25    124     13    95%
src\modules\seo\page_classifier\bare_url_list.py                  51      1     14      1    97%
src\modules\seo\page_classifier\screaming_frog_reconciler.py     274      6     60      2    98%   334-335, 484, 488-489, 621
TOTAL                                                           7667    379   1920    138    94%
31 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 93.86%
1964 passed, 1 skipped, 1 warning in 187.06s (0:03:07)
> npx vitest run
 Test Files  21 passed (21)
      Tests  232 passed (232)
> npx tsc --noEmit
exit 0
```

The main session's earlier `verify.ps1` run (which the brief reports as
green) is not reproduced here; its coverage figure is discussed in §5.

Test deltas against cycle 0072: +151 Python tests and +6 UI tests in the
working tree, of which this cycle's are 20 test functions in
`TestEngineFiles` (three of them parametrised over suffix lists), 2 in
`tests/api/test_server.py`, and 1 in `ReconcilePanel.test.tsx`. The remainder
belong to the other session's GSC-account and deliverables work.

---

## 2. What landed

### 2.1 The request, and what the data said

The user's words: "for the report generation of ours which screaming frog
missed and our engine finds i want more distinction if we can like .pdf, .ppt,
.xls and if other variant i want all separate as sheets/tabs like query
variant orphans".

Phase A measured before designing. Across the 11 saved reconciliation
sidecars, taking the extension of each engine-only URL's path
(case-insensitive, query and fragment ignored):

| Job | engine_only | filed `SITEMAP_ORPHAN` | `.pdf` | `.ppt` | `.xls` | `.doc` | `.asx/.asf/.rm` | `.html/.aspx/.htm` | `.com` |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| infosys `51767987` | 8,383 | 8,123 | 7,610 | 70 | 41 | 2 | 24 | 558 | 9 |
| gep.com (several) | — | — | 1–19 | 0 | 0 | 0 | 0 | — | — |
| highradius | — | — | ≤1 | 0 | 0 | 0 | 0 | — | — |

Of infosys's 7,610 PDFs, 7,356 were filed as orphans and 254 as
`REPEATED_SUFFIX_TRAP`. The 558 `.html`/`.aspx`/`.htm` URLs are real pages.
The 9 `.com` URLs are e-mail addresses and bare domains that discovery
resolved as path segments (`…/techcompass/name@infosys.com`) — real, and not
files. That last finding is why the rule is an allowlist (§3.1).

### 2.2 `screaming_frog_reconciler.py`

Four new `EngineGapReason` members and four suffix tuples:

| Reason | Suffixes |
| :--- | :--- |
| `PDF_FILE` | `.pdf` |
| `PRESENTATION_FILE` | `.ppt .pptx .pptm .pps .ppsx .odp .key` |
| `SPREADSHEET_FILE` | `.xls .xlsx .xlsm .csv .ods` |
| `OTHER_FILE` | `NON_PAGE_SUFFIXES` + `.doc .docx .docm .rtf .odt .txt .epub .asx .asf .rm .wmv` |

`_engine_reason` now tests, in order: `MALFORMED_MARKUP`,
`REPEATED_SUFFIX_TRAP`, the four file buckets, `QUERY_VARIANT`,
`SITEMAP_ORPHAN`. Only `urlsplit(url).path.lower()` is judged, so
`REPORT.PDF`, `report.pdf?page=2` and `deck.pptx#slide=3` all land where
their plain spellings do. Existing members are untouched; every one of the
11 stored sidecars still loads with only known reason names (checked at
close of cycle).

### 2.3 `server.py` — three map-only hunks

`GAP_MEANINGS` and `SHEET_TITLES` gain four entries each (sheet titles
`PDF files`, `Presentations`, `Spreadsheets`, `Other files`), and the
workbook's `rank()` pins the order `Missed pages` 0, `Orphans` 1, then the
four file sheets 2–5, then everything else by size. These edits were applied
because the file was clean in the working tree at the moment of the edit;
the other session's `gsc/accounts` route and `gsc_account` validation
arrived in the same file afterwards and are not part of this cycle.

### 2.4 UI

`treeOverlay.ts` `REASON_MEANINGS` and `ReconcilePanel.tsx` `ENGINE_REASONS`
gain the four labels so the chips and the overlay tooltip never fall back to
the raw token.

### 2.5 Live acceptance on infosys `51767987`

Against the running server, a bare list of the job's `in_both` URLs was
posted to the reconcile endpoint and the workbook downloaded:

```
engine_reasons: {'SITEMAP_ORPHAN': 630, 'PDF_FILE': 7356, 'QUERY_VARIANT': 6,
                 'PRESENTATION_FILE': 70, 'SPREADSHEET_FILE': 41, 'OTHER_FILE': 26,
                 'REPEATED_SUFFIX_TRAP': 254}
sheets: ['Summary', 'Orphans', 'PDF files', 'Presentations', 'Spreadsheets',
         'Other files', 'Loop URLs', 'Query variants']
```

Orphans on infosys fall from 8,123 to 630. The 254 quarterly-report PDFs stay
under `Loop URLs`, which is the precedence rule working as designed on a
separate `_repeated_tails` false positive (§6). The way this check was run
destroyed user state; see §5.

---

## 3. Design decisions

### 3.1 An explicit allowlist, not "any dotted final segment"

The alternative — treat any path whose last segment contains a dot as a
file — was rejected by the measurement: `.html`, `.aspx`, `.htm` are pages,
and infosys publishes e-mail addresses as path segments that would have
become 9 `.com` documents. Unlisted suffixes fall through to the page rules,
so a new file type is a one-line addition and never a silent misfile.

### 3.2 Precedence: fabricated beats file, file beats query

A repeating tail is tested before the suffix because a fabricated address is
not a file whatever it ends in. The suffix is tested before the query string
because `report.pdf?page=2` is a PDF that carries a parameter, not an HTML
page whose pagination Screaming Frog collapsed; the file type is the fact an
analyst acts on.

### 3.3 Four buckets, not one, not twenty

One `DOCUMENT` bucket would have hidden the 70 decks and 41 workbooks under
7,356 PDFs, which is the opposite of the request. A sheet per extension would
have produced a workbook with a dozen one-row tabs on gep.com. PDF earns its
own sheet by volume; presentations and spreadsheets because the user named
them; everything else is one sheet.

### 3.4 No ADR

The change is a refinement of an existing classification inside a module ADR
0011 already governs (Screaming Frog is an input format). It creates no new
boundary, dependency, or contract. Recorded here only.

---

## 4. Bugs found and fixed

- **`rankuno-ui/src/types/schema.ts` was stale**, failing two cases in
  `tests/test_ui_contract.py`. The other session had added `gsc_account` to
  the crawl request model without re-running the exporter. Regenerated with
  `scripts/export_ui_contract.py`; the file now carries the field.

- **`scripts/export_ui_contract.py` wrote CRLF on Windows.** `write_text`
  without `newline=` takes the platform default, against `.gitattributes`
  `* text=auto eol=lf`, so every regeneration produced a whole-file diff.
  Pinned `newline="\n"`.

- **A Bash heredoc collapsed `\\n` to a real newline** while making the fix
  above, leaving an unterminated string literal in the exporter. Repaired by
  hand. This is the same class of failure cycle 0072 §4 hit on the README's
  CR byte; heredocs are not safe for content containing backslashes.

- **Lint on the agent's new tests**: two D205 docstrings and one formatting
  hunk in `test_screaming_frog_reconciler.py`, one I001 import order in
  `tests/api/test_server.py`. Fixed.

- **A bug in the brief, not the code.** The prompt-generator's premise cited
  "~206 `prod/s3fs-public/files/newsroom/docs` URLs on gep `547ec81c`" as
  engine-only PDFs that the change would reclassify. Measurement showed those
  URLs were found by both crawlers and sat in `in_both`. See §5.

No test was found to be wrong.

---

## 5. Corrections

- **The brief's acceptance target was wrong.** The gep.com `547ec81c` PDFs
  the main session cited were not engine-only. gep.com jobs hold 1–19
  engine-only PDFs each and highradius at most 1. The only job on which the
  change is visible at scale is infosys `51767987`, and the acceptance target
  was moved there before Phase B.

- **The live acceptance check overwrote the user's real infosys
  cross-check.** Per the main session's report, the user had uploaded a
  genuine Screaming Frog export for `51767987` earlier on 2026-09-08 (server
  log, OPTIONS+POST 200), and the scripted acceptance POST replaced
  `.jobs/51767987….reconciliation.json` with a bare-list run. `.jobs/` is
  untracked, so there is no backup. The engine-only set is the same URLs
  under new reasons; the frog-only side of the real export and its reasons
  (`CLIENT_ERROR`, `REDIRECT`, `MEDIA_URL`, …) are gone until the user
  re-uploads the export, which is one drag-and-drop and also yields the new
  sheets.

  docs-scribe could not verify the sequence: `logs/audit.jsonl` records no
  reconcile events for that job, and the server log was not saved. What is
  on disk at close of cycle also does not match the main session's
  description of the file it left (`frog_rows 9847 = in_both`, `frog_only`
  empty). The sidecar now holds `frog_rows 15193`, `in_both 9847`,
  `frog_only 5324`, `frog_reasons {'UNKNOWN': 5324}`, `created_at
  2026-09-08T10:42:35Z`, and the engine reasons listed in §2.5 — a
  bare-list run of 15,193 URLs, still not a Screaming Frog export. Either
  the user re-uploaded a masterfile list after the scripted POST, or the
  scripted POST was not the last write. In both readings the export's
  frog-side reasons are absent.

  This is the second verification step in a week that destroyed user state
  (cycle 0072 §5 records the other session's stash loss). The rule that
  follows: an acceptance check that writes must target a throwaway job or a
  copy of the sidecar, never the user's job. Proposed for `CLAUDE.md` in §8;
  not added there by this agent.

- **The coverage drop the brief reports is not reproducible.** The brief says
  the main session's `verify.ps1` run showed full-suite coverage at 86.06%,
  down from 93.64% in cycle 0072, attributing it to the other session's
  `contracts/` and `deliverables/` packages. docs-scribe's run at close of
  cycle measured **93.86%** on 1,964 tests, with `deliverables/` and
  `contracts/` present and their tests collected. The 86.06% figure is left
  as reported and unverified; the number to cite for this cycle is 93.86%.

- **Cycle 0072 §6 and §8 said `server.py` was untouched because another
  session had it open, and left the `source_format` forwarding as follow-up
  1.** This cycle did edit `server.py` (three maps, §2.3), so "untouched" no
  longer describes the file — but follow-up 1 is still not done: the
  endpoint still does not forward `report.source_format.value`, and the
  stored sidecar shows `source_format: None`. The panel's `UNKNOWN` fallback
  remains the only signal.

- **Cycle 0072 §6 gave the reconciler as 798 lines.** It is 856 after this
  cycle.

---

## 6. Explicitly not done

- **`source_format` is still not persisted or forwarded** by `server.py`
  (cycle 0072 follow-up 1). Two lines; still handed to `api-data-engineer`.

- **The `_repeated_tails` false positive is not fixed.** 254 infosys
  quarterly-report PDFs under `documents/transcripts/<file>.pdf` repeat the
  same three trailing segments across quarters and are filed `Loop URLs`
  rather than `PDF files`. The precedence rule is right; the loop detector is
  wrong on this site. Handed to `bug-fixer`.

- **`.com`-suffixed engine URLs** from e-mail addresses and bare domains
  resolved as path segments are left as `SITEMAP_ORPHAN` (9 on infosys).
  The fix belongs in discovery, not the reconciler.

- **Extension-less download endpoints** such as gep.com's
  `/knowledge-bank/download/NNNN` cannot be caught by a suffix rule and are
  still orphans. Content-type is not available at reconcile time.

- **`download_reconciliation_workbook`'s docstring still says "Five sheets,
  smallest first"** (`server.py:1807`). It has been stale since cycle 0052
  made the workbook one sheet per reason; not edited, because the brief
  limited `server.py` to the three maps.

- **`screaming_frog_reconciler.py` is 856 lines** against the 400 target;
  the "CSV only, deliberately" docstring section is still present and still
  stale (native `.xlsx` since 0031). Handed to `refactorer`, as in 0072.

- **`scripts/export_ui_contract.py:237` fails `mypy --strict`** ("Need type
  annotation for member"). The gate types `src` only; pre-existing, not
  touched.

- **`docs/ARCHITECTURE.md` was not changed.** No new module, route or UI
  surface shipped; the reconciler modules are still absent from its module
  tree (cycle 0072 follow-up 4).

- **No ADR** (§3.4).

- **The user's real cross-check was not restored.** It cannot be; see §5.

---

## 7. Files changed

This cycle's hunks only. The working tree also carries the other session's
uncommitted GSC-account, contracts and deliverables work, which is not
described here.

```
src/modules/seo/page_classifier/screaming_frog_reconciler.py  +4 EngineGapReason members,
                                                              4 suffix tuples,
                                                              _engine_reason: 4 file branches
src/api/server.py                                             GAP_MEANINGS +4, SHEET_TITLES +4,
                                                              rank() order map
rankuno-ui/src/lib/treeOverlay.ts                             REASON_MEANINGS +4
rankuno-ui/src/components/jobs/ReconcilePanel.tsx             ENGINE_REASONS +4
rankuno-ui/src/types/schema.ts                                regenerated (+gsc_account)
scripts/export_ui_contract.py                                 newline="\n" pinned
tests/modules/seo/test_screaming_frog_reconciler.py           +TestEngineFiles (20 functions)
tests/api/test_server.py                                      +2 (sheet order; every reason titled)
rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx        +1 (PDF_FILE chip and meaning)
README.md                                                     cross-check table: engine-only side
                                                              split into orphans and file sheets
docs/build-log/README.md                                      index row 0074
```

---

## 8. Follow-ups

1. **api-data-engineer**: forward `source_format` from the reconcile endpoint
   and persist it in the sidecar (0072 follow-up 1, still open).
2. **bug-fixer**: `_repeated_tails` treats `documents/transcripts/<file>.pdf`
   repeating across quarters as a loop; 254 real PDFs on infosys.
3. **discovery**: e-mail addresses and bare domains resolved as path segments
   (`.com` URLs); 9 on infosys.
4. **refactorer**: `screaming_frog_reconciler.py` at 856 lines; split the
   loaders and delete the "CSV only" docstring section.
5. **server.py**: replace "Five sheets, smallest first" in
   `download_reconciliation_workbook` with the actual order (§2.3).
6. **Process rule for `CLAUDE.md` §4, for the user to approve**: an
   acceptance check that POSTs to a writing endpoint targets a throwaway job
   or a copy of the sidecar, never a job the user has data on. `.jobs/` is
   untracked; there is no undo.
7. **User action**: re-upload the infosys Screaming Frog export to restore
   the frog-side reasons on `51767987`.

---

## 9. Drift audit and numbering

Numbering: this entry was written as 0074, the first free number at the time
(0073 was the highest). While it was being written the parallel session
claimed 0074 (`0074-absent-is-not-empty.md`, already cited by section from
`README.md` and `docs/ARCHITECTURE.md`) and 0075. This entry was renumbered
to 0076 rather than create a second 0074; the index has no collision.

Output of `.\.venv\Scripts\python.exe scripts\drift_check.py` at close of
cycle, after the renumbering:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
FAILED: 3 documentation drift issue(s) detected:

  - docs\ARCHITECTURE.md: broken link -> build-log/0074-absent-is-not-empty.md
  - docs\build-log\README.md: broken link -> 0074-absent-is-not-empty.md
  - README.md: broken link -> docs/build-log/0074-absent-is-not-empty.md

Update the documentation to reflect the verified state of the code.
```

All three are the same target: the parallel session's cycle-0074 entry,
linked from its index row, `README.md` §Current Implementation Status and
`docs/ARCHITECTURE.md` but not yet written to disk at the moment of this
run. It is that session's file to create, and was not created here. No link
introduced by this cycle is broken; before the parallel session's rows were
added the same command passed (cycle 0072 §9).
