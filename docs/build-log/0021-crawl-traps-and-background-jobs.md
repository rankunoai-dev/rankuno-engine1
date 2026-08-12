# Cycle 0021: Crawl loop traps, site identity, and background jobs

- **Date**: 2026-08-12
- **Scope**: Refuse self-referential crawl loops and design-source files at the
  graph boundary; treat `www` and the bare host as one site; contain render
  failures; finish the concurrent-jobs UI refactor.
- **Commit**: three commits, this entry lands with the last
- **Quality gate**: `1096 passed, 1 warning in 39.92s` / `Total coverage: 95.67%`

## 1. Gate results

```
Required test coverage of 85.0% reached. Total coverage: 95.67%
1096 passed, 1 warning in 39.92s
PASSED: Tests

ALL GATES PASSED.
```

Re-run at the close of the cycle, after `CrawlNotifier` and `lib/url.ts`:

```
150 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 41 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.67%
1096 passed, 1 warning in 47.07s
PASSED: Tests
ALL GATES PASSED.
```

Frontend, from `rankuno-ui/`, run against the local `node_modules/.bin`
binaries — `npx` is not on this workstation's PATH and node lives at
`%LOCALAPPDATA%\Programs\nodejs`:

```
tsc --noEmit    TSC_EXIT=0
vite build      VITE_EXIT=0   ✓ built in 8.59s
```

The main bundle is now 1,050 kB (331 kB gzipped), up from 786 kB — antd's
`notification` and `Table` are the new weight. Vite's 2000 kB warning is not
tripped by it; the warning that does appear is the 16 MB `synthetic-20000`
fixture, unchanged from cycle 0020.

Step 8 drift audit:

```
PASSED: no drift detected across 66 markdown files.
```

## 2. What landed

### `is_spider_trap()` — the largest single defect found so far

A template that emits a *relative* href — `href="software/b2b-payments/"` with
no leading slash — resolves against whatever page it appears on. Land on the
result and the same href resolves again, one level deeper. `urljoin` is correct;
the markup is wrong; the crawler generates URLs without limit.

Two triggers: a path segment longer than three characters appearing twice, or
more than `MAX_CRAWL_DEPTH` segments. The depth rule reuses the existing
constant rather than introducing a second ceiling that would drift from it.

### `same_site()` / `site_host()`

`extract_page_links` compared `netloc` by exact string. A crawl seeded at
`https://highradius.com` therefore discarded every absolute
`https://www.highradius.com/…` link on its own homepage as external, completed,
reported success, and found one page. Which form the operator types is
arbitrary, so this was luck rather than design. Port, credentials and a leading
`www.` are now stripped before comparison; every other subdomain still counts as
a different site, because folding them turns a bounded crawl unbounded.

### `.eps`, `.ai`, `.psd`; documents kept

Design sources join the media denylist. Documents — `.pdf`, `.doc(x)`,
`.xls(x)`, `.ppt(x)`, `.csv` — stay, ruled on by the operator: a whitepaper is
an indexable B2B asset an SEO audit needs to see. That reasoning now lives in
the constant's docstring so it reads as a decision rather than an omission.
`.wmv` was a genuine gap in the list and was added.

### `ErrorBoundary`

React unmounts the whole tree when a render throws uncaught, so a defect in a
subordinate panel takes the dashboard with it. That is not hypothetical: see §4.

### The concurrent-jobs refactor, finished

`liveJobs` keyed by id replaces a single "the running crawl". `CrawlJobsView`,
`HeaderBar`, `UrlTicker`, `lib/duration.ts`, `lib/time.ts` and `useUiStore` were
already written; this cycle connected them, and `LiveCrawlProgressModal` was
deleted rather than repaired — its useful parts had already been extracted, and
it was `closable={false}` for a crawl's entire lifetime.

### `CrawlNotifier` — the completion toast

The last piece of the non-blocking design, and the one that was nearly shipped
missing: `watchJob`'s docstring already claimed a finished crawl "posts a
notification and waits to be asked", and until this component existed that
sentence was false. Nothing announced completion at all, so a background crawl
finished silently and the operator had to think to go and look.

It renders `contextHolder` and nothing else, diffing each job's previous status
to catch the single live→terminal crossing. Three details are load-bearing:

* **The map is seeded on first pass, not left empty.** A reload with a finished
  job still in `liveJobs` would otherwise fire a toast for a crawl that ended
  before the component mounted.
* **A failure toast has `duration: 0`.** A failure the operator does not see is
  a crawl they sit waiting for. Successes auto-dismiss after 8 seconds.
* **Nothing navigates on its own.** The toast carries an *Open tree* button, and
  a job that failed with a checkpoint offers *Open partial tree* via
  `loadCheckpoint`. Auto-loading would discard whatever analysis was open, which
  is the behaviour this whole cycle exists to remove.

Kept out of the store deliberately, so `useCrawlStore` stays free of antd — it
is the one part of this UI that could be tested without a DOM.

### `lib/url.ts`

`hostOf` had been written twice — once in `HeaderBar`, once in the notifier —
within an hour of each other. Extracted before the second copy could drift.

## 3. Design decisions

**The heuristic was measured before it was written.** The proposed rule was run
against 55,645 real URLs from six stored crawls:

| Site | URLs | Flagged |
| :--- | ---: | ---: |
| www.highradius.com | 33,447 | 21,242 (63.5%) |
| www.infosys.com | 17,458 | 11 (0.06%) |
| www.gep.com | 4,434 | 0 |
| rankuno.com | 181 | 0 |
| www.caeliusconsulting.com | 124 | 0 |
| www.macys.com | 1 | 0 |

All 11 infosys hits were inspected individually and every one is itself
malformed — `/content/infosys-web/en/content/infosys-web/en/services/cloud`, and
`/techcompass/tent/dam/…` where `tent` is a truncated `content`. Measured
false-positive count: **zero**. Three segments account for the HighRadius flood:
`software`, `b2b-payments`, `credit-card-surcharge`.

**`traps_skipped` is counted apart from `media_skipped`.** A site drowning in
loop artefacts has a broken template; a site full of image URLs has a media
sitemap. One number covering both would name neither. A large `traps_skipped` is
a finding about the client's site, not about the crawl.

**`is_spider_trap` is separate from `is_crawlable_url`.** One is about what a URL
addresses, the other about how it was constructed. The original plan merged
them, which would have made the report unable to distinguish the two causes.

**Suffix test, not `pathlib`.** Restated from cycle 0020 because the same
proposal recurred: on Windows `Path` is `WindowsPath` and treats a backslash as
a separator. Also, `Path(...).suffix` and `str.endswith` genuinely disagree —
`/hero.jpg/` is kept here and dropped there; `/.jpg` is the mirror case.

## 4. Bugs found and fixed

### The PDF report blanked the entire dashboard

`CrawlReport` called `.toLocaleString()` on `discovery.media_skipped`, absent
from every result saved before cycle 0020. The throw propagated with nothing to
catch it and React unmounted everything: a black page, no message. Three
distinct faults, fixed separately — no boundary (added), an intolerant read
(`count()` renders `—`), and a fixture generator that hand-wrote its `discovery`
dict and had been silently omitting every field added since it was written
(`fetch_failures` was already missing). The generator now builds a real
`DiscoveryReport` and dumps it, so a new field fails there rather than in a
browser.

The general lesson is worth stating: **generated types describe what the engine
emits today, not what is on disk.** Persisted results outlive the schema.

### Printing failed on large reports

`break-inside: avoid` on every `<tr>` reads as an obvious nicety and is ruinous
at scale — the print engine solves a pagination constraint per row, and across
3,000 rows and ~70 pages the Windows spooler aborted the job outright. Removed;
rows are single-line so there was nothing to split. `table-layout: fixed` stops
the engine measuring 3,000 rows to choose column widths. The remaining advice is
operational, not a defect: Chrome's own *Save as PDF* destination bypasses the
spooler that "Microsoft Print to PDF" goes through.

### `site_host` skipped port-stripping for IPv6 literals

The guard returned early for a bracketed host instead of splitting after the
closing bracket, so `[::1]:8000` did not reduce to `[::1]`. Caught by the test
that was written for it, before the gate.

### `BackgroundPill` had a signature its caller never matched

Declared `{ jobs: readonly LiveJob[] }`, called with `{ lead, runningCount }`.
Its comment also said "the first is the oldest still running" while the call
site passes `newestLiveJob`. The comment was corrected rather than the code:
`newestLiveJob`'s own docstring gives the reason for choosing the newest.

### The rail's "Crawl jobs" button rendered nothing

`setView("jobs")` moved the highlight and nothing else — `DashboardShell` had no
branch for it. Now renders `CrawlJobsView`, with the result-specific banners
gated to the visualizer since they describe the loaded tree. The submission
error banner stays on both: a rejected `startCrawl` has no job row to be
reported against.

## 5. Corrections

**A summary circulated during this cycle stated that a `NON_HTML_MEDIA_EXTENSIONS`
constant had been added covering `.pdf`, `.ppt`, `.xls`, `.eps`, that
`sitemap_parser.py` had been updated, and that a "Force Fresh Crawl (Bypass
Cache)" checkbox would produce clean results.** None of it was true: no such
constant or file exists, none of those extensions were blocked, and there is no
cache layer or checkbox. Recorded here because it was acted on — re-crawling
would not have removed those files, and the stale-checkpoint explanation offered
for them was right for images and wrong for documents.

**Cycle 0020 §3 said `.pdf` was excluded "flagged rather than assumed".** It has
now been ruled on: documents stay, design sources go. Not a contradiction, but
the earlier entry described an open question that is now closed.

## 6. Explicitly not done

- **No `KNOWLEDGE_DOCUMENT` page type.** PDFs enter the graph and classify as
  UNKNOWN or on URL patterns alone. `PrimaryPageType` is fixed at 14 members by
  `CLAUDE_HANDOFF_DIRECTIVE` §5.2, so adding one is a Step 3 decision.
- **Existing stored results and checkpoints are not re-filtered.** Traps and
  media already on disk stay there; the filters run at discovery time. Reports
  opened from an old job will still show them.
- **No content-type verification.** A page served at an extensionless URL with
  an image content type still enters the graph.
- **The trap rule does not detect a repeated *cycle*, only a repeated segment.**
  A cycle detector would be stricter and slower; the measured false-positive
  count of the simpler rule was zero, so the complexity is not yet earned.
- **No cancel.** The plan specified a *Cancel crawl* action on every row. There
  is no endpoint behind it: the API exposes `POST /jobs`, `GET /jobs`,
  `GET /jobs/{id}`, `/result` and `/checkpoint`, and nothing else. Cancelling
  needs cooperative interruption inside a crawl loop that runs in a worker
  thread under `asyncio.run`, which is engine work with its own tests and an
  ADR, not a button. A control that looks clickable and silently does nothing is
  the specific failure `NavigationRail` already refuses, so the column ships
  with *View tree* alone. **A running crawl currently cannot be stopped from the
  UI** — it ends when it ends, or when the server is killed.
- **The 2-second poll in the plan was not adopted.** `httpAdapter` keeps its
  existing 500ms→5s backoff. A fixed 2s interval is ~7,000 requests across a
  multi-hour 20,000-page crawl, and the backoff was a deliberate cycle-0016
  decision; overriding it from a UI plan would have reverted that reasoning
  silently.
- **Nothing was verified against a live crawl.** The gate, typecheck and build
  all pass, and the whole feature is about behaviour over a crawl's lifetime —
  concurrent jobs, the badge count, toast timing, the pill's `+N`. None of that
  has been watched against a running engine. The manual verification in the plan
  was not performed.
- **`CrawlNotifier` has no tests.** There is no frontend test runner in this
  repository at all; `tsc` and `vite build` are the only automated frontend
  checks, and neither executes a component.
- **Live telemetry does not survive a reload.** `liveJobs` is in memory. After a
  refresh a still-running crawl shows its server status with an empty progress
  column, because the job-list endpoint returns metadata and not progress. The
  jobs table says `—` rather than guessing.
- **Intermediate commits were not individually gated.** The three commits are
  ordered so each is self-consistent, and the final tree is verified; each
  commit was not checked out and built in isolation.
- **`.claude/settings.json` is not committed.** It is a local tool permission
  allowlist containing an absolute path to one developer's home directory.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/url_rules.py` | `is_spider_trap`, `same_site`, `site_host`, `.eps/.ai/.psd/.wmv` |
| `src/modules/seo/page_classifier/discovery.py` | Trap refusal in `SiteGraph.add`; `traps_skipped` |
| `src/modules/seo/page_classifier/discovery_parsers.py` | `site_host` in the link host test |
| `scripts/run_crawl.py` | Prints `loop URLs skipped` |
| `scripts/export_ui_fixtures.py` | Builds `DiscoveryReport` instead of a literal dict |
| `rankuno-ui/src/components/ErrorBoundary.tsx` | New |
| `rankuno-ui/src/components/report/CrawlReport.tsx` | `count()`, trap row |
| `rankuno-ui/src/components/report/report.css` | Print cost |
| `rankuno-ui/src/store/useCrawlStore.ts` | `liveJobs`, `newestLiveJob`, per-job pollers |
| `rankuno-ui/src/components/layout/HeaderBar.tsx` | New; extracted from the shell |
| `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` | New |
| `rankuno-ui/src/components/jobs/CrawlNotifier.tsx` | New; completion toasts |
| `rankuno-ui/src/components/jobs/jobs.css` | New |
| `rankuno-ui/src/components/telemetry/UrlTicker.tsx` | New; lifted from the modal |
| `rankuno-ui/src/lib/duration.ts` | New; clock, ETA, fetched-percent |
| `rankuno-ui/src/lib/time.ts` | New; crawl timestamps for the selector |
| `rankuno-ui/src/lib/url.ts` | New; shared `hostOf` |
| `rankuno-ui/src/store/useUiStore.ts` | New; rail view, no router |
| `rankuno-ui/src/components/layout/NavigationRail.tsx` | Crawl-jobs tab, glowing badge |
| `rankuno-ui/src/components/layout/DashboardShell.tsx` | View switch; modal removed |
| `rankuno-ui/src/adapters/*` | `crawledAt` carried through to the selector |
| `rankuno-ui/src/styles/design-system.css` | Badge, pill, two-line select row |
| `.gitignore` | `.claude/` |
| `rankuno-ui/src/components/telemetry/LiveCrawlProgressModal.tsx` | Deleted |
| `tests/modules/seo/test_url_rules.py` | `TestSpiderTrap`, `TestSameSite` |
| `tests/modules/seo/test_discovery.py` | `TestSpiderTrapRefusal` |
| `tests/modules/seo/test_discovery_parsers.py` | `TestWwwEquivalence` |

## 8. Follow-ups

- Decide whether `KNOWLEDGE_DOCUMENT` is worth the taxonomy change.
- Re-crawl highradius.com now the trap filter is in; the previous 800-page run
  spent most of its budget on loop artefacts, so the comparison is worth having.
- Report the relative-href defect to the client: it is a real SEO finding.
