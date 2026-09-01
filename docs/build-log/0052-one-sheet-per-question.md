# Cycle 0052: One sheet per question

- **Date**: 2026-09-01
- **Scope**: `reconciliation.xlsx` — the cross-check as a workbook.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1579 passed`, UI `135 passed`. See §6 on the two files
  blocking a full green run, neither of them from this cycle.

## 1. What was wrong with the report

A real gep.com cross-check is **17,640 rows in one sheet**. Opened in Excel it
starts at row 16,345 of `rankuno_only` / `SITEMAP_ORPHAN`, and the reader has no
idea what they are looking at or where the interesting part went.

The interesting part is small: **15 pages the crawl actually missed** — the
engine's own defect — and **801 orphans**, which is the finding the whole
cross-check exists to produce. Both were buried under 16,337 rows of differences
that are explained, expected, and need no action.

## 2. This reverses a decision, and the earlier reasoning still holds

Cycle 0028 chose one flat table with a `found_by` column, and said why:

> One flat table rather than two, with a `found_by` column, because the question
> is per URL: *which crawler saw this, and why did the other one not?* Splitting
> the two sides into separate files makes the reader do a join to answer it.

That argument is about **separate files**, and it is correct about them. Sheets
in one workbook are not separate files: nothing has to be joined, nothing can be
mislaid, and every list is one click from every other. The objection does not
reach this design, which is why the CSV keeps its shape rather than being
changed to match.

Both downloads now exist. The workbook is the artefact to hand somebody; the CSV
is the one to feed another tool.

## 3. The sheets, and why in that order

```text
Summary                  the counts, and every reason with what it means
Missed pages          15 live, in-scope pages this crawl never reached
Orphans              801 published, no internal link — the finding
Screaming Frog only  16,337 explained differences
Rankuno only          1,215 explained differences
```

**Smallest and most actionable first.** The order is the argument of the report:
15 rows are the work, 17,552 are the evidence that the rest is accounted for.
Reversed, it reads as a list of 17,640 problems.

## 4. Bugs found and fixed

**`freeze_panes` is silently discarded by a write-only worksheet** when it is
set after the first row is appended. openpyxl accepts the assignment, drops it,
and raises nothing:

```text
write_only=True   -> freeze_panes=None
write_only=False  -> freeze_panes='A2'
```

The first version of this endpoint did exactly that and produced a 16,337-row
sheet whose header scrolled away — the single thing the workbook exists to fix,
undone silently. Setting it *before* the first `append` works in both modes.
Caught by reading the generated file back rather than by trusting the write.
There is now a test asserting every sheet keeps its header.

`write_only` is worth the care: normal mode builds a cell object per value.
Measured on a comparable 20,000-row sheet it costs 4.3 seconds and 21 MB, which
is survivable but is paid on every download.

**A test assertion looked for the wrong word.** The gloss reads "…did not reach
it"; the assertion searched for "reached". The code was right and the test was
sloppy — it now matches the phrase that actually carries the meaning.

## 5. Design decisions

**Column widths are guessed from the header name**, not measured from the data.
Measuring means reading every row twice, and a URL column at the default width
shows about eight characters — the difference between a usable report and one
the reader resizes before they can start.

**Sheet names are truncated to 31 characters.** Excel refuses longer ones and
openpyxl raises rather than truncating, so a future sheet with a long name would
fail the download rather than shorten a title.

**The helper is generic.** `_workbook_response` takes `(name, headers, rows)`
tuples, so the performance downloads can move to workbooks without a second
implementation.

## 6. Explicitly not done

- **The gate does not run green**, and neither cause is from this cycle:
  `split_sheets.py`, an untracked one-off script at the repo root, fails `T201`;
  and `docs/build-log/0051-a-file-behind-every-number.md`, a parallel session's
  in-progress entry, has a fenced block `ruff format` wants to rewrite — which
  is the markdown trap documented in cycle 0042 §4. Both belong to somebody
  else's working tree and were left alone. Ruff and format pass on everything
  else; 1,579 Python and 135 UI tests pass.
- **`matched.csv`, `unmatched.csv` and `opportunities.csv` are still CSVs.**
  They are single tables and do not have this problem, though the performance
  report has the same shape of argument waiting: a summary, an actionable list,
  and a long tail.
- **No formatting beyond widths and a frozen header.** No colour, no filters, no
  conditional formatting. A spreadsheet that arrives pre-styled is one the
  recipient fights.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/api/server.py` | `_workbook_response`, `_column_widths`, `reconciliation.xlsx` |
| `tests/api/test_server.py` | 3 new tests |
| `ReconcilePanel.tsx`, `jobs.css` | the workbook link, CSV demoted |

## 8. Follow-ups

1. Move the performance downloads to the same helper.
2. Pagination, still waiting on `url_rules.py` (cycle 0050 §7).
