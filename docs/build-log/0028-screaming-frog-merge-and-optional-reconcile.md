# Cycle 0028: Merging Screaming Frog's missed pages, without making it compulsory

- **Date**: 2026-08-19
- **Scope**: Act on the reconciliation cycle 0027's module produces — classify
  the pages Screaming Frog reached and this engine did not, place them by the
  real placement rules, and expose it through an endpoint and a CLI. Optional at
  every layer.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1280 passed, 1 warning in 135.10s` / `Total coverage: 95.21%`

---

## 1. Gate results

```
165 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 44 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.21%
1280 passed, 1 warning in 135.10s (0:02:15)
PASSED: Tests
ALL GATES PASSED.
```

---

## 2. What landed

`screaming_frog_reconciler` already existed and already sorted every
disagreement into an exclusive reason. Nothing consumed it. This cycle adds the
consumer.

### `screaming_frog_merge.merge_reconciled_urls`

Takes a crawl result and an `internal_html.csv`, and returns a **new** result
with the missed pages folded in. Four decisions carry the design:

* **Only `MISSED_PAGE` is merged.** The other frog-side reasons are differences,
  not defects: a redirect source is not a page, an off-site URL is out of scope,
  a media URL is refused deliberately. Merging any of them would re-import the
  exact noise cycles 0020 and 0021 exist to reject, under the banner of a fix.
* **Placement re-runs `reparse_placement` rather than inserting nodes.**
  Placement is a contested decision between the header menu and each page's own
  breadcrumb (`_better_trail`). Hand-inserting would put a second placement
  implementation in the codebase to disagree with the first — a failure this
  repository has already paid for twice (the two `NON_PAGE_SUFFIXES` lists, and
  `nav_coverage` in cycle 0022).
* **A merged page keeps its low confidence.** An export carries no HTML, so the
  five structural parsers cannot run and the cascade returns `UNKNOWN` at 0.00.
  That is left visible rather than papered over: a merged page and a crawled
  page are not equally well evidenced and must not look identical in the tree.
  One signal *is* genuinely gained — Screaming Frog's `Unique Inlinks`, which it
  counted by following links this engine never saw.
* **No gap means no change.** An export that finds nothing to merge returns the
  input object itself, not a copy. Pushing a no-op through `reparse_placement`
  would rewrite `trail_source` across the whole crawl, so a merge asked only to
  *check* would quietly alter what it was checking.

### `POST /jobs/{id}/reconcile/screaming-frog`

Synchronous and offline, like reparse: no worker thread, no concurrency slot, no
network. Creates a new job when anything merges and echoes the source id when
nothing does, so a report-only run does not litter `.jobs/` with duplicates.

### `scripts/reconcile_screaming_frog.py`

Reports by default; merges only with `--merge`/`--out`. Accepts a job id or a
path, because the id is what the UI shows and the path is what a scripted run
has, and forcing a translation between them is the friction that stops a
cross-check being run at all.

---

## 3. Design decisions

**`text/csv` body, not `multipart/form-data`.** The plan specified multipart.
FastAPI's file upload requires `python-multipart`, which is **not installed and
not a declared dependency**. Starlette hands over the raw request body with no
package at all, and the browser can read a file and POST its text. Adding a
dependency to accept one file, when the framework already offers the same
capability, is a poor trade.

**CSV only; XLSX deliberately not supported.** `openpyxl` is present in this
environment but is not declared in `pyproject.toml` — it arrived transitively.
Building on it would fail a clean checkout with an `ImportError` rather than a
message. This was tried the other way first: an earlier draft of this cycle
wrote a `screaming_frog_parser.py` with a lazy `openpyxl` import and a new
`reconcile` extra. It was deleted, see §5.

**The optionality is structural, not a promise.** No module on the crawl path
imports the reconciler or the merge layer; verified by grep, not by assertion:

```
$ grep -rn "screaming_frog" src/ --include=*.py \
    | grep -v "page_classifier/screaming_frog" | grep -v "api/server.py"
  (no matches)
```

A crawl with no export behaves exactly as it did before. The endpoint is an
extra pass, the CLI is a separate script, and neither is reachable from
`PageClassificationTool.run`.

---

## 4. Bugs found and fixed

### `MergeOutcome` documented three attributes that were not documented

It began as a plain class with `__slots__` and string literals under each
assignment in `__init__`. Those are not docstrings — they are no-op string
expressions that no tool reads. Ruff caught the adjacent `D107` (missing
`__init__` docstring); the string-literal problem was the real one behind it.
Replaced with a frozen slotted dataclass, which has real class-level attribute
documentation and no `__init__` to document.

### The CLI printed mojibake on Windows

Em dashes and ellipses rendered as `?` in the console: Windows defaults to
cp1252. A report full of replacement characters reads as corrupted output rather
than as typography. The printed strings are now ASCII, with a docstring saying
why so the next reader does not "tidy" them back.

### Import insertion left the block unsorted

Patching `server.py` by string replacement put `Request` and the merge import in
place but broke `I001`. Caught by the gate, fixed with `ruff --fix`. Worth
recording as the cost of scripted edits to a sorted import block.

---

## 5. Corrections

**A duplicate parser was written and deleted inside this cycle.** Work began
with `screaming_frog_parser.py` — CSV/XLSX reading, a row model, and noise
filtering — built against the assumption that no reconciler existed. One did:
`screaming_frog_reconciler.py` was written concurrently and is the better
module, because its thresholds are *measured* against a real highradius.com
export (`MIN_TAIL_REPEATS = 25`, chosen because the two real loops repeated 650
and 624 times while the highest legitimate tail repeated 7). The deleted version
had no export to calibrate against and guessed.

Both files defined URL normalisation, noise filtering and a row model. Two
implementations of the same comparison is precisely the defect this integration
exists to detect — a normalisation that disagrees by a trailing slash reports
thousands of phantom gaps — and having it *inside the detector* would have been
the worst possible place for it. Deleted rather than merged.

**The plan's "~50 ms to process, match, and merge" is wrong by 25x.** Measured
on the stored kinsta.com crawl: merging 250 pages into 27,656 takes **1,219 ms**,
nearly all of it re-running placement over the combined set. Parsing and
matching alone are indeed fast; the merge is not, and it grows with the crawl
rather than with the export. Still comfortably interactive, and worth stating
because the endpoint is synchronous on that basis.

---

## 6. Explicitly not done

- **No real Screaming Frog export was used in this cycle.** There is none in the
  repository. Every number here comes from synthetic exports built to the real
  column names, plus the stored kinsta crawl. The reconciler's own thresholds
  were calibrated against a real highradius export in cycle 0027; the *merge*
  has never seen one.
- **No UI.** There is no upload control, no gap panel, and no way to reach this
  from the dashboard. It is an endpoint and a script. The plan's manual
  verification step — "verify merged navigation tree in UI" — was not performed
  because there is nothing to click.
- **XLSX is not supported**, per §3. `.xlsx` will be read as CSV and produce
  either a parse error or zero rows.
- **Screaming Frog CLI integration is not started.** That is the stated next
  phase; this cycle is the CSV workflow only.
- **A merged page is never re-fetched.** It enters the tree classified from its
  URL and Screaming Frog's inlink count alone. Fetching it would give a real
  classification and is the obvious next improvement, but it turns an offline
  merge into a crawl with all the governance that implies.
- **`reconcile` and `merge` both parse the export.** `merge_reconciled_urls`
  calls `load_screaming_frog_csv` and then `reconcile`, which the API layer
  calls once — but a caller wanting both a report and a merge parses twice.
  Harmless at these sizes, and not worth an API that can be misused.
- **The merged job is not marked as merged in its result.** Only the label says
  so (`(+250 from Screaming Frog)`). A machine reading the result cannot tell
  merged pages from crawled ones except by their zero confidence.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/screaming_frog_merge.py` | New — classify, place, resummarise |
| `src/api/server.py` | `POST /jobs/{id}/reconcile/screaming-frog`, `ReconciliationSummary` |
| `scripts/reconcile_screaming_frog.py` | New — report-by-default CLI |
| `tests/modules/seo/test_screaming_frog_merge.py` | New — 17 tests |
| `tests/api/test_server.py` | `TestScreamingFrogEndpoint` — 6 tests |

## 8. Follow-ups

- Wire the upload into the dashboard: a drop target on the jobs row, and a panel
  showing the two gap directions. Without it this is invisible to the operator
  the feature was built for.
- Obtain a real Screaming Frog export for kinsta or highradius and re-run the
  merge against it. The reconciler is calibrated; the merge is not.
- Consider re-fetching merged URLs behind an explicit flag, so they can be
  classified from a body rather than a URL.
- `docs/build-log/README.md` carries **two rows numbered 0022**, from concurrent
  sessions. The numbering rule in that file says numbers are never reused; this
  needs resolving by whoever owns those two entries.
