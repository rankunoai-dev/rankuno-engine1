# Cycle 0051: A file behind every number

- **Date**: 2026-09-01
- **Scope**: Per-figure downloads on the Screaming Frog cross-check, and keeping
  the agreement list that was being computed and thrown away.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1576 passed` Python / `135 passed` UI / `Total coverage: 94.66%`
  — Lint red on an untracked scratch file, see §1.

---

## 1. Gate results

```
PASSED: Format
FAILED: Lint
Success: no issues found in 51 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 94.66%
1576 passed, 1 warning in 115.84s (0:01:55)
PASSED: Tests
 Test Files  12 passed (12)
      Tests  135 passed (135)
PASSED: UI Component Tests
```

**Lint fails on `split_sheets.py`, an untracked one-off script at the repository
root that this cycle did not create.** Twelve `T201 print found` plus an over-long
line. Scoped to the tracked tree the check is clean:

```
> ruff check src/ tests/ scripts/
All checks passed!
```

`CLAUDE.md` §4 states that scratch analysis scripts must be deleted before the
gate is run, and this is exactly the failure that rule exists to prevent. It was
left in place rather than deleted, because it is somebody's working file and
removing it is not this cycle's call. Recorded here rather than quietly worked
around: the gate is red, and a build log that pasted a green block would be
inventing one.

Two unrelated lint errors *were* fixed, both one-liners blocking everything
behind them: `B007` in `server.py` (an unused loop variable in a PDF helper from
a parallel session) and an import order in `split_sheets.py` itself.

---

## 2. What the panel could not do

The cross-check header shows four figures. On gep.com:

```
7,078  Found by both     23,500  Rows in export
   15  Pages we missed      801  Sitemap orphans
```

Every one is a list of addresses, and none of them could be obtained. The whole
cross-check downloaded as one file of ~17,500 rows covering the two *gap*
directions, and an analyst wanting the 15 pages the crawl missed had to filter
it out of that.

Worse, one figure had no list at all to give.

---

## 3. The agreement was computed and discarded

`reconcile()` held this:

```	ext
in_both=len(frog_by_key.keys() & engine_by_key.keys()),
```

The intersection was built, measured, and dropped on the same line. So of the
four figures, `Found by both` was the one number on the panel a reader had to
take entirely on trust — there was no way to answer "which 7,078?" at all.

`ReconciliationReport` now carries `in_both_urls`, and the sidecar stores it.

**In the engine's spelling, not Screaming Frog's.** The two disagree about
`www.`, scheme and trailing slash constantly — that is what `normalise()` exists
to absorb — and the export is only useful if it joins against the crawl result
without being normalised again.

**Sorted**, because a set's iteration order is not stable and an export that
reshuffles itself between two runs over the same inputs cannot be diffed against
last week's.

---

## 4. Design decisions

### 4.1 A button per figure, and a stated reason where there cannot be one

Four figures, and they do not all have files:

| Figure | File | Why |
| :--- | :--- | :--- |
| Found by both | ✅ new | §3 |
| Rows in export | ❌ never | It is the analyst's own upload |
| Pages we missed | ✅ | Already stored |
| Sitemap orphans | ✅ | Already stored |

`Rows in export` will not get one. Storing 23,500 raw rows to hand back the file
the operator uploaded ten seconds earlier would roughly double the sidecar to
reproduce something they already have. The tile says `your own export` instead.

A tile with no button and no explanation reads as a defect in the app, and a
disabled button is a quieter version of the same thing. Both non-downloadable
cases say why in words.

### 4.2 Old cross-checks say "not recorded", never "none"

Every sidecar written before this cycle omits `in_both`. The TypeScript field is
therefore **optional**, and its absence renders `re-run the cross-check to list
these` rather than a button that would produce an empty file. An empty file is a
claim about the site; a missing one is a fact about the record.

This is the same failure as cycle 0035's blank dashboard — a field the API does
not serve for older data, read as though it must be there — and it is handled the
same way, by making absence a case the type system forces the caller to consider.

### 4.3 The two gap tables got downloads too

They are the same shape of ask: a heading, a count, and a list a person acts on.
Each carries `url, reason, meaning`, with the reason spelled out in words for the
same reason the whole-file CSV does it — the person who acts on the row is
usually not the person who ran the cross-check.

### 4.4 The lists were already crossing the wire

`GET /jobs/{id}/reconciliation` has always returned the URL lists. The panel
fetched them, kept `saved.summary`, and dropped the rest one line later. Holding
the whole object is the entire client-side change; nothing new is requested.

After a *fresh* upload the reconcile response carries counts only, so the panel
re-reads the sidecar the server has just written rather than widening that
response shape. A failure there costs the download buttons, not the result.

---

## 5. Bugs found and fixed

**A CSS class collision, caught before it shipped.** The "why there is no file"
hint was first written as `.jb-stat-hint` — a class `jobs.css` already defines
further down for the denominator under a performance stat. Two rules, two
different jobs, one name: the later definition wins for the properties they
share, so the new text would have half-applied and nobody would have known which
half. Renamed to `.jb-stat-why`.

This is the same class of defect as cycle 0045, found this time by grepping for
the class name before adding the rule rather than after a third report of an
invisible control.

---

## 6. Corrections

Nothing published in an earlier entry is corrected here.

---

## 7. Explicitly not done

- **Stored cross-checks are not backfilled.** The three saved gep.com sidecars
  have no `in_both` list and cannot get one without re-uploading the export —
  the export itself is not kept. §4.2 is what the panel does about it.
- **`Rows in export` will never be downloadable.** §4.1.
- **The whole-file CSV is unchanged.** It still lists only the disagreements,
  with the counts as pseudo-rows at the top. Adding 7,078 agreement rows to it
  would treble a file whose stated purpose is the gap.
- **No `.xlsx`.** Same as every export in this project: CSV opens in Excel and
  needs no dependency.
- **The sidecar grows.** gep.com's would gain ~7,078 lines, on top of the 16,337
  `frog_only` rows already there. Acceptable at this scale and unmeasured beyond
  it.
- **`split_sheets.py` was not deleted.** §1.

---

## 8. Files changed

```
src/modules/seo/page_classifier/screaming_frog_reconciler.py  in_both_urls
src/api/server.py                                   sidecar stores in_both;
                                                    B007 fix (unrelated)
rankuno-ui/src/adapters/adapterInterface.ts         SavedReconciliation.in_both
rankuno-ui/src/components/jobs/ReconcilePanel.tsx   holds the lists; Stat gains
                                                    a download; GapDownload
rankuno-ui/src/components/jobs/jobs.css             .jb-stat-dl, .jb-stat-why
tests/modules/seo/test_screaming_frog_reconciler.py  +4
rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx  +4
split_sheets.py                                     import order only
```

---

## 9. Follow-ups

1. **Decide `split_sheets.py`'s fate** so the gate can be green again.
2. **A re-reconcile from a stored export**, which would let old cross-checks gain
   the agreement list — and would need the export kept, which it currently is
   not.
3. The panel locale grouping from cycle 0046 remains the largest open item.
