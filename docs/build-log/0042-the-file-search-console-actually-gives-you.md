# Cycle 0042: The file Search Console actually gives you

- **Date**: 2026-08-21
- **Scope**: `gsc_export.py`, the upload/read/download endpoints, the
  `.performance.json` sidecar, and the `PerformancePanel` that shows it.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1526 passed, 1 warning in 116.26s`, total coverage 95.83%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.83%
1526 passed, 1 warning in 116.26s (0:01:56)
PASSED: Tests
 Test Files  10 passed (10)
      Tests  90 passed (90)
PASSED: UI Component Tests
ALL GATES PASSED.
```

45 new Python tests and 12 new UI tests. The UI total is 90 rather than 88 because a parallel session landed two audit tests during this cycle.

## 2. "Export → CSV" does not produce a CSV

The single fact that shaped this cycle. The Search Console UI's CSV export
produces a **ZIP** holding one CSV per tab — pages, queries, countries, devices,
dates, search appearance — and that archive is the file an analyst drags into an
upload box. "Export → Excel" produces a workbook with the same tabs as sheets.
Only somebody who has already unpacked the archive has a bare `.csv`.

An endpoint that accepts only the bare CSV rejects the default download and asks
for the one shape nobody has. All three are accepted.

**A ZIP and an `.xlsx` cannot be told apart by magic bytes.** Verified rather
than assumed: both start `PK\x03\x04`, because `.xlsx` *is* a ZIP. The archive is
opened and its entries inspected — a workbook contains `xl/workbook.xml`, the
Search Console archive contains `.csv` files. Guessing from the magic would send
every CSV archive into `openpyxl` and fail it as "not a readable workbook",
which is both wrong and unhelpable.

**Which tab holds the pages cannot be read from its name.** The archive is
written in the account's display language: `Pages.csv`, `Seiten.csv`,
`Páginas.csv`, `ページ.csv`. Matching names works for English accounts and fails
silently for every other one — the worst possible distribution for a bug.

The tab is chosen **by content**: the pages tab is the one whose first column
parses as addresses. Queries hold phrases, dates hold dates, countries hold
country names; none parse as URLs, so the discrimination is sharp without
knowing a word of the language. Column headers get the same treatment — keyword
match where possible, falling back to **position**, because Search Console
writes the same column order in every locale even when the words differ.

## 3. Design decisions

**CTR is read and discarded.** It is the one column that must never be used — a
section's CTR is recomputed from summed clicks over summed impressions — so
parsing its formatted percentage would be work in service of a forbidden number.

**Integers strip every separator; floats treat the last one as the decimal.**
`1,234` and `1.234` both mean 1234 for a count, in English and German
respectively, so stripping is correct in both. For position the last separator
identifies the decimal character. One input is genuinely ambiguous — a lone
comma before three digits — and it resolves to `1.234` rather than `1234`
deliberately: an average position of 1.234 is an ordinary ranking and 1234 is
barely a real one, so that reading is the plausible one. Documented in the
function rather than left as a surprise.

**The delimiter is sniffed, not assumed.** A locale that uses the comma as a
decimal separator delimits with semicolons. Read as comma-separated it yields
one column, no address is found, and a perfectly ordinary export is rejected as
"not an export".

**Two separate size limits.** `MAX_PERFORMANCE_UPLOAD` (32 MB) bounds what
arrives; `MAX_UNPACKED_BYTES` (64 MB) bounds what it becomes. A ZIP declares its
own uncompressed size, and a hostile one declares a small body that expands
without limit — the second limit is the only thing that sees that.

**Nothing about the crawl changes.** No new job, no mutated result. The report
is a sidecar the crawl knows nothing about, so a job that never sees an export
behaves exactly as it always has. This is stronger than the Screaming Frog
reconciliation, which does create a merged job.

**Re-uploading replaces.** That is how somebody corrects a wrong date range or
the wrong property, and keeping the superseded report would leave two with no
way to tell which is on screen.

**The panel's order is its argument.** Resolution quality, then coverage, then
the numbers. Every total is derived from a join, and a reader who sees section
totals without knowing a third of the export failed to resolve is reading a
confident understatement.

**Coverage is shown with its denominator.** The trap the match rate cannot
catch: the Search Console UI caps a download at 1,000 rows, so against a large
site every row resolves — a perfect match rate — while the report describes a
sliver of the site. Confirmed live below at **0.9%**.

## 4. Bugs found and fixed

**`ruff format` rewrites fenced `python` blocks inside build-log markdown, and
it corrupted a quotation.** Cycle 0041 quoted `cascading_pipeline.py:322` as:

```text
depth_from_l0=depth_of(evidence.normalized_path),
```

Running the gate this cycle silently reformatted that committed file to
`depth_from_l0 = (depth_of(evidence.normalized_path),)` — a line the source does
not contain, in a document whose entire purpose is to be accurate about the
source. Caught by reading the diff rather than by any check.

Reverted, and the fence changed to `text`. **Every future build log quoting a
partial line is exposed to this**, and the convention is now: quote source
fragments in a `text` fence, never a `python` one.

**A page could be reported as both an orphan and an underperforming sibling.**
Cycle 0041 made orphan and buried mutually exclusive and missed the third
pairing. "Nothing links here" and "a sibling with four links outranks you" are
the same instruction delivered twice, and the orphan finding says it with more
force. Caught by an API integration test, not by the scorer's own suite — the
unit tests never had one page qualifying for both.

**Invented CSS class names, twice, and `tsc` caught neither.** The panel was
first written against `rc-drop-title` and `rc-alert`, neither of which exists;
the real ones are `jb-*`. Then a parallel session's UI-wide sweep rewrote this
file's download button to `rk-btn rk-btn-primary` — a class that exists only in
that session's **uncommitted** working tree, and is scoped `.rk-dash .rk-btn`,
which a modal rendered in a portal is not inside. Committing it would have
produced an unstyled link with a dependency on unstaged work.

`className` takes any string, so a type check can never see either mistake. The
button now uses `perf-download`, defined in `jobs.css` beside it. Borrowing a
class across feature folders made this component's appearance depend on a
refactor happening in another one, which is a coupling neither side can see.

**Download links ignored the machine-local API base.** This machine runs the
engine on 8001, because port 8000 belongs to a different project — a "RankUno
Crawl Toolkit API" that answers `/` with 200 and every engine route with 404.
`.env.local` redirects the UI, and `App.tsx` reads it, but the panels imported
`DEFAULT_API_BASE` directly for their anchor `href`s.

So the Download CSV button pointed at another application's server. Not a
diagnosable 404 either: the host answers, with someone else's routes. Found by
starting the server rather than by any test, since a hard-coded constant in an
`href` is exactly what a component test cannot see.

`API_BASE` now resolves the override once in `httpAdapter`, and both this panel
and `ReconcilePanel` use it — the reconciliation download had the same defect
and has had it since cycle 0029.

**Two of my own test fixtures were wrong, and both taught something.** A bare
decimal comma in a comma-delimited CSV is a sixth column, not a decimal — which
is precisely why the locales that write it that way use semicolons, and the test
now says so. And a fixture with two junk rows out of three was rejected wholesale
by the address-share gate; the ratio was unlike any real export, but the refusal
it triggered is the queries-protection this parser needs, so both behaviours now
have their own test.

## 5. Corrections

**Cycle 0041's §2 quotation of `cascading_pipeline.py:322` was, for a few hours
in the working tree, wrong** — see §4. It was never committed in the wrong form.
The finding it supports is unaffected: `depth_from_l0` still holds path depth
offset by two.

Nothing else previously published turned out to be wrong.

## 6. Verification beyond the unit tests

Driven end to end against the **real `.jobs` store**, using the largest stored
crawl — 100,687 pages — with a synthetic export built the way the UI builds one:
a ZIP of four **localised** tabs, the pages tab named `Seiten.csv`, 968 rows,
plus 60 URLs Google "has" that the crawl never held and 8 crawl loops.

```
POST -> 200
  read from      : Seiten.csv
  rows           : 968
  match rate     : 92.98%  reliable=True
  site covered   : 900 / 100687 pages
  clicks         : 1391 attributed, 180 not
  found          : {'indexed_crawl_trap': 8}
  skipped        : {'orphan_with_traffic': 'inbound_links_unreliable',
                    'underperforming_sibling': 'inbound_links_unreliable'}
GET performance -> 200
GET opportunities.csv -> 200 | 11 lines
```

Four things worth reading off that run:

* The German tab was found inside the archive **by content**, with no name match
  available.
* 92.98% is correct, not a defect: the 68 URLs that do not resolve are the ones
  deliberately planted as absent.
* **0.9% site coverage against a 93% match rate** is the case §3 exists for. The
  match rate looks healthy and the report describes almost none of the site.
* The inbound-link guard from cycle 0041 fired on this crawl — it is the one
  with 98.7% zero-inbound pages — so the two link-based kinds were refused with
  a named reason instead of producing 99,000 artefacts.

The synthetic sidecar this wrote into `.jobs/` was deleted afterwards; it was
invented data and would have appeared in the UI as a real report.

## 7. Explicitly not done

- **No GA4 ingestion.** `Ga4PageMetrics` and the aggregator's GA4 path exist and
  are tested, and **nothing can supply them**. The GA4 export is a different
  shape and needs its own parser.
- **No connector.** Data arrives only by manual upload. There is still no
  `google_search_console.py`, no OAuth, no scheduled refresh, and no
  `QuotaLimiter`.
- **The raw export rows are not stored**, only the derived report. Recomputing
  after a reparse, or with different thresholds, needs the file again.
- **The sidecar carries every match and failure**, one entry per export row.
  Fine at 1,000 rows; a 50,000-row API export would produce a large file. Not
  bounded, because nothing can produce that yet.
- **No per-section drill-in in the panel.** Only depth-1 sections are listed —
  the rollup holds 928 rows on a 12,787-page crawl and a flat table of all of
  them is not something anyone reads. The tree already exists for going deeper,
  and is not yet joined to this data.
- **The date range is unknown and unshown.** A Search Console export carries no
  date range, so the panel cannot label its own numbers with a period. Two
  uploads from different ranges are indistinguishable once saved.
- **The real match rate against a real export is still unmeasured.** Fourth
  cycle running. Every figure above uses rows derived from the crawls' own URLs.

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/gsc_export.py` | new — the parser |
| `src/api/server.py` | upload, read and CSV-download endpoints; `PerformanceSummary` |
| `src/core/state_store.py` | `write_performance` / `read_performance` sidecar |
| `src/modules/seo/performance/opportunity_scorer.py` | orphans excluded from the sibling finding |
| `tests/modules/seo/test_gsc_export.py` | new — 26 tests |
| `tests/api/test_performance_endpoints.py` | new — 19 tests |
| `rankuno-ui/src/adapters/adapterInterface.ts` | performance types + two optional methods |
| `rankuno-ui/src/adapters/httpAdapter.ts` | `uploadGscExport`, `getPerformance` |
| `rankuno-ui/src/store/useCrawlStore.ts` | `uploadGscExport` action |
| `rankuno-ui/src/components/jobs/PerformancePanel.tsx` | new — the panel |
| `rankuno-ui/src/components/jobs/PerformancePanel.test.tsx` | new — 12 tests |
| `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` | Search Console button |
| `rankuno-ui/src/components/jobs/jobs.css` | panel layout |
| `rankuno-ui/src/adapters/httpAdapter.ts` | `API_BASE` resolves `VITE_API_BASE` for download links |
| `rankuno-ui/src/components/jobs/ReconcilePanel.tsx`, `App.tsx` | use the resolved base |
| `docs/ARCHITECTURE.md`, `docs/build-log/` | this entry, index, module tree |

## 9. Follow-ups

1. **One real Search Console export.** Now more valuable than ever: the parser
   is written against the documented shapes and a real file is the only thing
   that confirms the tab-picking heuristic on a live account.
2. GA4 ingestion, so the aggregator's other half becomes reachable.
3. Join the performance data to the tree, so a section can be opened rather than
   only totalled.
4. Fix `depth_from_l0` (0041), locate the duplicate-profile emission (0039).
5. ADR 0010 for the GSC/GA4 architecture, owed since 0039.
