# Cycle 0062: One sheet per reason, everywhere

- **Date**: 2026-09-02
- **Scope**: The two per-table downloads on the cross-check and the whole
  recommendations report were flat files mixing several reasons into one sheet.
  Both now split, one sheet per reason.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1697 passed` Python / `143 passed` UI / `Total coverage: 95.23%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 56 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.23%
1697 passed, 1 warning in 104.31s (0:01:44)
PASSED: Tests
 Test Files  13 passed (13)
      Tests  143 passed (143)
PASSED: UI Component Tests
```

---

## 2. The defect, reported from a downloaded file

Cycle 0059 made the whole cross-check a workbook with one sheet per reason. The
per-table buttons added in cycle 0051 did **not** go through it: they built a
CSV in the browser from the rows already loaded, so `Download 3,162` produced a
single sheet holding `SITEMAP_ORPHAN` and `QUERY_VARIANT` interleaved, with the
reason repeated down every row.

That is the exact layout the workbook exists to replace, still being handed out
from the button most likely to be pressed — the one sitting on the table the
reader is looking at.

The same shape was true of the recommendations panel: five kinds, one flat CSV.

---

## 3. Design decisions

### 3.1 The gap buttons became links to the existing endpoint

Rather than teach the browser to write a workbook. The UI has five runtime
dependencies and none is a spreadsheet library; adding one to re-implement what
`_workbook_response` already does would put two writers in the project that
could disagree about sheet naming, column widths and the 31-character limit.

`reconciliation.xlsx` gained `?side=frog|engine`. Each heading's button is now
an `<a href>` to its own half, still split one sheet per reason.

### 3.2 The side filter refuses a value it does not know

`side=both`, `side=Frog`, `side=engines` — all `422`. Treating an unrecognised
value as "both" would hand someone twice the report they asked for, and nothing
on screen would say so. A download that quietly widens its own scope is worse
than one that fails.

### 3.3 A one-sided workbook omits the other side's tally

The Summary sheet is a contents page. A workbook restricted to one direction
that still lists the other's reason counts sends the reader looking for tabs it
does not contain. The two `if side != ...` guards are the whole of it.

Files are named for the half they hold — `cross-check-154dab01-rankuno-only-…`
— so two downloads from one cross-check do not arrive as `(1)` and `(2)`.

### 3.4 The recommendations report gained a workbook twin

`opportunities.xlsx`, one sheet per kind, with `opportunities.csv` kept for
anything already pointed at it. The kinds are not one job: pages earning clicks
with no internal link go to a content team, pages buried in the navigation to
whoever owns the menu, siblings ranking off page one to whoever owns internal
linking.

Sheets are ordered largest first. Unlike the cross-check there is no kind that is
*the* finding — every one is actionable — so size is the only ordering that says
anything.

**Skipped kinds moved to the contents page.** The CSV had to carry them as
pseudo-rows inside the findings list, which puts "not evaluated" among things
that were. They still travel with the file, because a list of recommendations
handed over without them invites the reader to conclude the site has no orphans
when the truth is the crawl could not tell.

### 3.5 A sheet does not repeat its own name down every row

`severity, score, url, section, clicks, impressions, position, why` — no `kind`
column, because the kind is the tab. The cross-check workbook removed the same
redundancy for the same reason.

---

## 4. Verified against real data

Not fixtures. Against the stored highradius cross-check `154dab01`:

```
side=both     Summary, Orphans, Redirect sources, Loop URLs,
              Noindex or canonicalised, Off-site, Media files,
              Query variants, Crawl traps
side=frog     Summary, Redirect sources, Noindex or canonicalised,
              Off-site, Media files, Crawl traps
side=engine   Summary, Orphans, Loop URLs, Query variants
```

`Orphans` and `Query variants` are the two the reported screenshot had mixed into
one sheet, and they are now separate tabs.

And against a stored Search Console upload `8b9d9c08`:

```
Summary  7 rows · Off page one  18 rows · Earning, buried  4 rows
```

A job whose kinds were all skipped returns a workbook of one Summary sheet
rather than an empty file — checked on `1e9dfba4`.

---

## 5. Bugs found and fixed

**A new deprecation warning, caught before it was committed.** The first version
of the refusal used `status.HTTP_422_UNPROCESSABLE_ENTITY`, which Starlette now
warns on at every reference. The gate reports a warning count, and quietly
raising it from one to two is how a suppressed-warning policy erodes. Switched
to `HTTP_422_UNPROCESSABLE_CONTENT`.

**A stale assertion in a test that was right to fail.** `PerformancePanel`'s
suite asserted `getByText("Download CSV")`, and the whole-report control is now
`Download Excel (one sheet per kind)` beside a smaller `or a single CSV`. Updated
to assert the workbook link, not deleted — the point of the test is that the
whole-report download exists beside the per-section ones.

---

## 6. Corrections

Nothing published in an earlier entry is corrected here. Cycle 0051 §4.3 said the
gap-table downloads carry `url, reason, meaning`; that was true when written and
is superseded rather than wrong — they now carry one sheet per reason and no
reason column at all.

---

## 7. Explicitly not done

- **The three stat tiles still download CSV.** `Found by both`, `Pages we missed`
  and `Sitemap orphans` are each a single-reason list, so a workbook would be one
  sheet with a contents page in front of it. The defect being fixed is *mixed*
  reasons in one sheet, and those three have none.
- **The audit view's exports are unchanged.** Orphans and duplicate sets are
  computed in the browser from the loaded crawl, and there is no server endpoint
  that could re-derive them without creating a second definition of the same
  list — the reason given in cycle 0035 §3.4 still holds. Making those workbooks
  needs either a spreadsheet library in the UI or a new endpoint, and neither is
  a decision to attach to this change.
- **`matched.csv` and `unmatched.csv` are unchanged.** Each is one table with one
  meaning; there is nothing to split.
- **The scoring ceiling is untouched.** A workbook of the recommendations holds
  the same capped rows the panel does.

---

## 8. Files changed

```
src/api/server.py                                    reconciliation.xlsx gains
                                                     ?side=; opportunities.xlsx;
                                                     OPPORTUNITY_SHEETS
rankuno-ui/src/components/jobs/ReconcilePanel.tsx    GapDownload links to the
                                                     workbook
rankuno-ui/src/components/jobs/PerformancePanel.tsx  workbook first, CSV beside
rankuno-ui/src/components/jobs/jobs.css              heading actions
tests/api/test_server.py                             +4
tests/api/test_performance_endpoints.py              +3
rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx   +1
rankuno-ui/src/components/jobs/PerformancePanel.test.tsx +2, 1 updated
```

---

## 9. Follow-ups

1. **The audit exports** (§7). The last downloads in the app still producing a
   flat file where a split would help.
2. **A `?kind=` on `opportunities.xlsx`**, so a per-section button can hand over
   one sheet without the others.
