# Cycle 0120: an action beside the download

- **Date**: 2026-09-29
- **Scope**: The reconciliation panel's engine-only gap gained a "Run in Screaming
  Frog" action beside its Download, and the Screaming Frog launcher gained the
  list-mode surface that action opens — closing [build-log 0119 §6.1](0119-a-list-that-travels-as-a-hash.md),
  which shipped the whole `--crawl-list` backend with nothing consuming it.
- **Commits**: `52532ba` (19 files, all under `rankuno-ui/`), `2dceae1` (deletes
  `lib/urlParser.ts` and its test)
- **Quality gate**: UI only; no file under `src/` changed, so the Python gate was
  not run. `tsc --noEmit` clean, **43 files / 546 tests passed**, contract up to
  date, `vite build` clean — all four re-executed by the scribe, output in §1.

This is the UI half of ADR 0023. The backend half is
[build-log 0119](0119-a-list-that-travels-as-a-hash.md) and
[ADR 0023](../adr/0023-a-url-list-travels-as-a-digest.md); neither is restated here.

---

## 1. Gate results

Re-executed at `2dceae1` by the scribe, not copied from the implementing agent's
report.

### 1.1 Type check

```
$ npx tsc --noEmit
TSC_EXIT=0
```

No output, exit 0.

### 1.2 Tests

```
$ npx vitest run

 Test Files  43 passed (43)
      Tests  546 passed (546)
   Start at  17:05:56
   Duration  77.51s (transform 3.12s, setup 10.89s, collect 102.46s, tests 126.89s, environment 35.84s, prepare 5.68s)
```

### 1.3 Generated contract

```
$ npm run contract

> rankuno-ui@0.1.0 contract
> python ../scripts/export_ui_contract.py --check

UI contract is up to date.
CONTRACT_EXIT=0
```

`--check` passing is not evidence that the new shapes are covered. It is not:
every `UrlList*` type in §2.1 is **hand-written** on `adapterInterface.ts`,
because `export_ui_contract.py` reads the page-classifier schemas and emits
`schema.ts`/`colors.ts`, and these models live in `src/api/worker_schemas.py`,
which it never reads. This is the same seam recorded in
[build-log 0101](0101-a-percentage-is-no-longer-invented.md) for the three
progress fields. Nothing verifies these seven interfaces against the Python
models; a rename on the wire would be caught by a failing request at runtime, not
by this command.

### 1.4 Production build

```
$ npx vite build
✓ 3072 modules transformed.
dist/index.html                           1.35 kB │ gzip:   0.73 kB
dist/assets/index-Qtgp2FTq.css           50.24 kB │ gzip:  10.46 kB
dist/assets/synthetic-500-CqKmg5V8.js   386.76 kB │ gzip:  15.43 kB
dist/assets/index-BTLVjl6F.js         1,252.99 kB │ gzip: 392.76 kB
dist/assets/synthetic-20000-CWU9lvCu.js 16,018.27 kB │ gzip: 472.00 kB

(!) Some chunks are larger than 2000 kB after minification.
✓ built in 45.55s
```

The chunk-size warning is pre-existing and is the synthetic fixture data, first
recorded in [build-log 0101](0101-a-percentage-is-no-longer-invented.md).

### 1.5 The 567 figure, and why it is not the one above

The implementing agent reported **44 files / 567 tests** at `52532ba`. That run
was not reproduced — `52532ba` is not HEAD — but it reconciles exactly:
`urlParser.test.ts` held 21 test declarations, counted statically from the
deleted file, and 567 − 21 = 546 across 44 − 1 = 43 files. The deletion removed
test count, not coverage of anything live.

34 new test declarations were added by `52532ba`, counted statically from the
diff.

### 1.6 Python gate

Not run, and not skipped by oversight: `git show --name-only` on `52532ba` and
`2dceae1` together lists 21 paths, all under `rankuno-ui/`. No `src/` file, no
test under `tests/`, no migration. Running `pytest` would also have collided with
a concurrent session's `.coverage`, the same hazard recorded in
[build-log 0119 §1](0119-a-list-that-travels-as-a-hash.md).

### 1.7 Drift audit (Step 8)

Run after this entry was committed, so the count includes it:

```
$ .\.venv\Scripts\python.exe scripts\drift_check.py
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 204 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

The same command run immediately before the commit reported **203** files and
also passed. The difference is this entry: `drift_check.py` counts tracked
markdown, so an uncommitted entry is invisible to it — the same artefact noted
in [build-log 0100](0100-mcompleted-twice-with-two-meanings.md).

---

## 2. What landed

### 2.1 The wire shapes, hand-written (`adapters/adapterInterface.ts`, +166/−1)

Seven additions mirroring `src/api/worker_schemas.py`: `UrlListSource` (a closed
`"orphans" | "all"` union), `UrlListSourceOption`, `UrlListSourcesView`,
`UrlListCounts`, `UrlListView`, `UrlListRequest`, plus optional fields on
`DispatchPreviewRequest` (`url_list?`), `DispatchPreview` (`url_list?`),
`DispatchConfirmRequest` (`url_list_sha256?`) and `WorkerJobView`
(`url_list_url_count?`, `url_list_shortfall?`, `url_list_shortfall_note?`).

Every new field on an existing interface is **optional**, which is what lets the
UI render against an engine predating ADR 0023 rather than throwing on a missing
key.

`WorkerDispatchAdapter` was widened with `listUrlListSources` and — separately —
with `Partial<Pick<CrawlDataAdapter, "listJobs">>`. The `Partial` is load-bearing:
`listJobs` is *required* on `CrawlDataAdapter`, and a plain `Pick` would have
forced every existing test double in `adapters/` to implement a method the
launcher needs only in list mode.

### 2.2 `UrlListSourcePicker.tsx` (new, 340 lines)

Two questions in order — which finished crawl, then which of its URLs — because
the second cannot be answered without the first. The component never derives
availability: it renders `UrlListSourceOption.available` and, when false,
`unavailable_reason` verbatim beside a disabled radio. The counts it shows are
labelled "before filtering" on purpose; the truthful post-filter number is the
one the preview returns and the only one the confirmation dialog shows.

It filters the crawl list to `succeeded` and `partial` locally. That is a
different thing from deciding availability and is worth naming as such: a queued
crawl has nothing finished to take, so offering it would produce a picker whose
entries mostly answer "this has not finished yet". Whether a *source* within a
finished crawl is usable is still never re-derived.

Two effect-loop hazards were avoided explicitly, both documented in the source:
the fetch callbacks key on the adapter **object**, never on a `.bind(api)` of one
of its methods (`bind` returns a new function every render), and `onChange` is a
`useCallback` in the parent and is called only from event handlers, never from an
effect.

### 2.3 `ScreamingFrogView.tsx` (+249/−22, now 782 lines)

A `CrawlMode` radio group — "Spider from a seed URL" vs "A list of URLs from a
finished Rankuno crawl" — with the list option disabled, and given a reason, when
the adapter cannot answer `listUrlListSources`/`listJobs`.

Choosing a source fills the seed URL from the source crawl's own `base_url`
rather than leaving it typed. A list dispatch still needs a seed: it names the
site in the job record and its registrable domain is the rule the list was
filtered against. It is not spidered, and the field's label and hint both change
to say so.

`reuse()` (the "run this again" action on a finished job) forces `spider` mode.
The envelope carries a digest, not a list, so re-running a list job means picking
its source again; dropping silently back to a site crawl on the same seed would
be a different crawl wearing the old one's settings.

Preview failures are now typed (`PreviewFailure`) and a 409/422/404/403/400 is
rendered as a **warning** with the server's own sentence as the description,
rather than as an error with a paraphrase. The 422 heading is "Nothing was
prepared, and no shortened crawl will run" — the one wrong conclusion available
to an operator here is "it will run, just with fewer URLs", which is exactly what
the engine refuses to do.

`newCorrelationId` moved out to `correlationId.ts` (18 lines) because two screens
now mint one.

### 2.4 `DispatchConfirmModal.tsx` (+127/−10)

A `UrlListSummary` section rendering the source label, the post-filter count, the
`off_domain_dropped` figure *with the domain that produced it*, and the server's
`sample` as text nodes. `preview.url_list.sha256` is echoed back untouched —
never recomputed from `sample`, which holds only the first few URLs.

`typedUrl` became optional. In list mode nobody typed a URL, so the "the address
above is the server's normalized form of what you typed" note is suppressed
rather than shown against text the operator never entered.

`describeFailure` gained a `hadList` argument, for one reason: a `404` on the
confirm route means "unknown worker" for an ordinary crawl and "the approved URL
list is gone" for a list one. The stored list has a retention window and the
confirm re-checks the digest, so an approval can outlive the bytes it names.
Telling that operator their PC was unregistered would send them to the wrong
machine.

### 2.5 `WorkerJobsPanel.tsx` (+77/−1)

A `ListModeOutcome` cell with three distinct sentences, not one number:

| `url_list_shortfall` | Rendered as |
| :--- | :--- |
| `> 0` | `url_list_shortfall_note` verbatim, in the error style |
| `0` | "Every URL supplied was crawled." |
| `null` / absent, job settled | "How many were crawled was never reported, so whether any were missed cannot be said." |
| `null` / absent, job not settled | nothing — "not yet known" is the ordinary state |

A new `SETTLED` set (`succeeded`, `partial`, `failed`) was added rather than
taking the complement of the existing `ACTIVE` set. A status this build does not
recognise belongs to neither, and treating it as settled would print "never
reported" against a job that may still be running.

### 2.6 `ReconcilePanel.tsx` (+84/−2) and `useUiStore.ts` (+29)

`RunInScreamingFrog` sits inside a new `.jb-gap-acts` span next to the existing
`GapDownload`, under the "We found, Screaming Frog did not" heading. It is
**absent, not disabled**, when the adapter lacks either `listUrlListSources` or
`previewDispatch`.

It calls `onLeaving()` (close the modal, `reset()`) and then
`useUiStore.startListCrawl(jobId)`, which sets `view: "screaming-frog"` and
`listCrawlSourceJobId`. The launcher consumes that once and calls
`clearListCrawl()`. `listCrawlSourceJobId` is deliberately **not** persisted —
the storage subscription writes `view` and nothing else — so a reload two days
later cannot re-arm list mode on a crawl nobody remembers choosing.

---

## 3. Design decisions

### 3.1 Navigate to the launcher; do not dispatch in the modal

The obvious alternative was a dispatch form inside the reconciliation dialog, so
the operator never leaves the gap report. Rejected: preview → confirm is the only
evidence of approval that exists (ADR 0013/0015 gate a), and a second dispatch
path is a second copy of that gate to get wrong. The launcher already owns it.
The cost is a screen change mid-task, which is real and was accepted.

### 3.2 Only the crawl id crosses; the subset does not

"Run in Screaming Frog" carries `jobId` and nothing else. The specific gap URLs
on screen are not carried across, and neither is a pre-selected source. Which
URLs is the decision being approved, so the list is rebuilt server-side and
re-approved at the launcher against a fresh preview. Carrying the displayed set
would mean approving a list assembled in a browser from a table that may be
stale.

### 3.3 The mode radio is on the launcher, not a separate screen

A separate "list crawl" screen would have duplicated the worker picker, the
template dropdown, the liveness warning and the preview button. One extra
fieldset on `ScreamingFrogView` was the smaller change — at the cost of §6.4.

### 3.4 `null` shortfall is a third state, not zero

Stated in §2.5 and repeated here because it is the one place a reasonable
simplification would be a lie. `0` is the positive claim that nothing was
missed; `null` is "no page count arrived". Collapsing them is how a free-tier
licence cap goes unnoticed.

---

## 4. Bugs found and fixed

### 4.1 A commit that swept in 47 files belonging to other sessions

The largest finding of this cycle, and the one most likely to recur: **several
agent sessions share this one working tree.**

The implementing agent staged with explicit paths and never used `git add -A`.
That was not sufficient. Another session had already staged its own work into the
index, and `git commit` commits **the whole index**, not the paths most recently
added. The result was `3a501d8`, "feat(ui): run a crawl's URLs through Screaming
Frog in list mode", carrying 47 files: 14 UI files and **33 belonging to the
concurrent ADR 0023 backend session** — `src/api/url_list_routes.py`,
`alembic/versions/0007_worker_dispatch_url_lists.py`, that session's own
`docs/adr/0023-*.md` and `docs/build-log/0119-*.md`, and 11 of its test files.

Undone with `git reset --soft HEAD~1` followed by a mixed reset. No working-tree
file was touched and nothing was lost.

Independently verified by the scribe from git itself:

```
$ git show --name-only --format='' 52532ba | wc -l
19
$ git show --name-only --format='' 52532ba | grep -cv '^rankuno-ui/'
0
$ git branch -a --contains 3a501d8
(no output — unreachable from any branch, local or remote)
```

The reflog shows this happened **twice**, which the implementing agent's report
did not mention and which makes the point stronger rather than weaker:

```
$ git reflog --date=iso
2dceae1 HEAD@{2026-09-29 17:03:10}: commit: chore(ui): delete urlParser ...
52532ba HEAD@{2026-09-29 15:49:05}: commit: feat(ui): run a crawl's URLs ...
68b4cce HEAD@{2026-09-29 15:48:43}: reset: moving to HEAD
68b4cce HEAD@{2026-09-29 15:48:43}: reset: moving to HEAD~1
43fa222 HEAD@{2026-09-29 15:39:56}: commit: docs: cycle 0119 build-log ...
68b4cce HEAD@{2026-09-29 15:39:36}: reset: moving to HEAD
68b4cce HEAD@{2026-09-29 15:39:31}: reset: moving to 68b4cce
3a501d8 HEAD@{2026-09-29 15:37:56}: commit: feat(ui): run a crawl's URLs ...
68b4cce HEAD@{2026-09-29 15:30:33}: commit: docs: cycle 0118 build-log ...
```

`43fa222` is the mirror image: four minutes later, under a `docs:` message, a
commit swept 33 files — the whole ADR 0023 backend plus its docs. Both commits
are unreachable from `main` and from `origin/main`; both sessions' files survive
in the working tree, unstaged.

The rule that actually holds, and that the next agent in this tree should use:

```
git add <explicit paths>
git diff --cached --name-only     # <- the check. Not optional.
git commit
```

`git add` with explicit paths is necessary and **not** sufficient. Only
`git diff --cached --name-only`, read immediately before committing, tells you
what is about to be in the commit.

### 4.2 `git status` and `ls` returned stale data for several minutes

After a network interruption on the workstation, `git status` and directory
listings returned stale results for several minutes, hiding test files that
already existed on disk. Two tests were written that duplicated existing ones and
were deleted again before the commit.

This leaves no trace in git and the scribe could not verify it independently — it
is recorded as the implementing agent reported it. What *is* verifiable and
consistent with it: the abandoned `3a501d8` contains only one of this cycle's six
test files (`DispatchConfirmModal.test.tsx`); the other five
(`ReconcilePanel.test.tsx`, `ScreamingFrogView.test.tsx`,
`UrlListSourcePicker.test.tsx`, `WorkerJobsPanel.test.tsx`,
`useUiStore.test.ts`) appear only in `52532ba`, twelve minutes later.

### 4.3 No application bug was found by the tests this cycle

Recorded because its absence is information. The 34 new tests all passed against
code written in the same session. Nothing here was caught the way
[build-log 0111](0111-a-test-that-had-never-run.md) caught three component bugs
by running a test file that had never executed. The confidence this cycle's suite
justifies is correspondingly lower, and §6.5 is the reason that matters.

---

## 5. Corrections

### 5.1 `urlParser.ts` was kept for a reason that turned out to be wrong

[Build-log 0112 §6.1](0112-a-wizard-wired-to-the-wrong-crawler.md) retained
`rankuno-ui/src/lib/urlParser.ts` (205 lines) and `urlParser.test.ts` (175 lines)
when the 4-stage crawl wizard was deleted, on the stated reasoning that a
Screaming Frog dispatch form would want the same domain, rate and concurrency
checks.

That form now exists — it is §2.2 and §2.3 of this entry — and it uses **none**
of it. The reasoning was wrong in both halves:

- There is no file to parse. The URLs come from a finished crawl the server
  already holds, reached through `GET /jobs/{id}/url-list/sources` and the
  preview. Nothing is uploaded.
- Re-filtering domains in the browser would be actively harmful. The server
  filters off-domain URLs and reports `counts.off_domain_dropped`; a second
  browser-side filter would produce a second count, and a count in an approval
  that disagrees with the count dispatched is the specific failure ADR 0023's
  digest exists to make impossible.

Deleted in `2dceae1`. A repository-wide search for `urlParser` under
`rankuno-ui/src` now returns nothing.

### 5.2 `ARCHITECTURE.md`'s dead-module row is stale as written

The row in the "Planned, not yet implemented" table reads "A UI that consumes
`rankuno-ui/src/lib/validation.ts` or `lib/urlParser.ts` … Both modules are
retained with zero importers". Half of that is now false — `urlParser.ts` does
not exist. The row is rewritten in this cycle (§7) to name `validation.ts` alone
and to record why the retention argument was falsified rather than merely
overtaken.

### 5.3 The `README.md` row for ADR 0023 says "no UI consumes it"

The `README.md` row for the `--crawl-list` backend ends "⚠️ Backend implemented
& tested; **no UI consumes it, so it is API-only**". True when written at
`cc7dac1`; false since `52532ba`. Amended in §7. Noted here because a
"⚠️ API-only" marker is exactly the kind of claim that survives past its truth.

### 5.4 Not a correction, but the number is different: 780 vs 782

The implementing agent reported `ScreamingFrogView.tsx` at 780 lines. `wc -l`
gives **782**. Recorded so the figure in §6.4 is the measured one.

---

## 6. Explicitly not done

### 6.1 `MockAdapter` does not implement `listUrlListSources`

Deliberate, and for a narrower reason than the other absent mock methods.
Whether "Orphans Only" is available depends on a saved Screaming Frog cross-check
that fixture mode has no way to hold. Any answer invented there would be the
**client** deciding availability, which is the one thing the endpoint exists to
prevent. The consequence is visible and intended: in fixture mode the list-mode
radio renders disabled with "This mode cannot read the engine's own crawls", and
`RunInScreamingFrog` does not render at all.

The gap report that launches a list crawl is unreachable in fixture mode anyway —
`reconcileScreamingFrog` is also absent, so no cross-check can be produced.

### 6.2 The gap URLs on screen are never dispatched

Stated as a decision in §3.2 and repeated here so it is not read as an oversight.
The list the worker receives is built server-side from the crawl, not from the
table the operator was looking at.

### 6.3 `validation.ts` is also dead, and was not deleted

`rankuno-ui/src/lib/validation.ts` has **zero importers** except
`validation.test.ts` — a search for imports of it across `rankuno-ui/src` returns
that one line and nothing else. It was kept in cycle 0112 on the same
now-falsified reasoning as `urlParser.ts` (§5.1). `validateProxyUrl`,
`validateRate`, `validateConcurrency`, `validateCustomHeaders`,
`validateGA4PropertyId`, `estimateCrawlSeconds`, `formatCrawlTimeEstimate` and
`normalizeDomain` are all unconsumed.

It was **not** deleted this cycle, only recorded, because `normalizeDomain` /
`parseDomain` were repaired in cycle 0112 for a real defect and a decision to
discard that work should be taken deliberately rather than as a tidy-up rider on
a UI feature.

### 6.4 `ScreamingFrogView.tsx` is 782 lines, past the 400-line target

`CLAUDE.md` §9 targets under 400 lines. This file is 782. Not split this cycle
because the natural seam — pulling the whole dispatch form out of the view —
would have moved code the reviewer had to read anyway into a second file
mid-review. Recorded as debt, not as an acceptable steady state.

### 6.5 No browser verification. Nobody has looked at the rendered result

The strongest statement in this section. Everything in §1 is jsdom, `tsc` and a
production bundle. jsdom reports zero element heights, which is why
`UrlListSourcePicker` passes `virtual={false}` to antd's `Select` — an explicit
acknowledgement in the source that the test environment lays nothing out. Nobody
has opened this screen in a browser, clicked "Run in Screaming Frog", seen the
launcher arrive in list mode, or read a real confirmation dialog.

Specifically unverified: the 113 new lines of `screaming-frog.css` and 13 of
`jobs.css`; whether the radio labels wrap legibly; whether the sample list
overflows the modal; and whether the whole path works end to end against a real
worker at all. Not one list-mode dispatch has been run.

### 6.6 Migration 0007's SQL has still never run against a real PostgreSQL

Unchanged from [build-log 0119](0119-a-list-that-travels-as-a-hash.md) and from
migrations 0002–0005 before it. `psycopg` is not installed in the local venv and
no server is reachable from this workstation. `worker_dispatch_url_lists` is
covered only by an in-memory fake cursor. This cycle's UI sits on top of that
table and did nothing to change it.

### 6.7 Nothing verifies the hand-written types against the Python models

See §1.3. Seven interfaces and six optional fields were transcribed by hand from
`src/api/worker_schemas.py`. A field rename on the wire produces a silently
`undefined` value in the browser, not a build failure.

### 6.8 No ADR was written

ADR 0023 already rules on how a URL list travels and who decides which URLs.
Nothing here changes or narrows it, and the four decisions in §3 are UI shape,
not binding architectural constraints.

---

## 7. Files changed

### Code (`52532ba`, `2dceae1` — no `src/` file touched)

| File | +/− | What |
| :--- | :--- | :--- |
| `rankuno-ui/src/adapters/adapterInterface.ts` | +166 / −1 | 7 hand-written wire types, 6 optional fields, `listUrlListSources` |
| `rankuno-ui/src/adapters/httpAdapter.ts` | +17 | `GET /jobs/{id}/url-list/sources` |
| `rankuno-ui/src/adapters/mockAdapter.ts` | +8 | Docstring for a deliberate absence (§6.1) |
| `rankuno-ui/src/components/screaming-frog/UrlListSourcePicker.tsx` | +340 | New. Crawl picker + served source options |
| `rankuno-ui/src/components/screaming-frog/UrlListSourcePicker.test.tsx` | +286 | New, 11 tests |
| `rankuno-ui/src/components/screaming-frog/ScreamingFrogView.tsx` | +249 / −22 | Mode radio, typed preview failures, seed from source |
| `rankuno-ui/src/components/screaming-frog/ScreamingFrogView.test.tsx` | +255 / −2 | 18 tests |
| `rankuno-ui/src/components/screaming-frog/DispatchConfirmModal.tsx` | +127 / −10 | `UrlListSummary`, digest echo, list-aware 404 |
| `rankuno-ui/src/components/screaming-frog/DispatchConfirmModal.test.tsx` | +144 / −2 | 15 tests |
| `rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.tsx` | +77 / −1 | `ListModeOutcome`, `SETTLED` |
| `rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.test.tsx` | +114 | 23 tests |
| `rankuno-ui/src/components/screaming-frog/correlationId.ts` | +18 | Extracted from `ScreamingFrogView.tsx` |
| `rankuno-ui/src/components/screaming-frog/screaming-frog.css` | +113 | Unverified in a browser (§6.5) |
| `rankuno-ui/src/components/jobs/ReconcilePanel.tsx` | +84 / −2 | `RunInScreamingFrog`, `onLeaving`, list-mode note |
| `rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx` | +58 | 20 tests |
| `rankuno-ui/src/components/jobs/jobs.css` | +13 | `.jb-gap-acts`, `.jb-gap-note` |
| `rankuno-ui/src/store/useUiStore.ts` | +29 | `listCrawlSourceJobId`, `startListCrawl`, `clearListCrawl` |
| `rankuno-ui/src/store/useUiStore.test.ts` | +26 | 19 tests |
| `rankuno-ui/src/test/factories.ts` | +93 | `crawlJob`, `urlListSources`, `urlListView` |
| `rankuno-ui/src/lib/urlParser.ts` | −205 | **Deleted** (§5.1) |
| `rankuno-ui/src/lib/urlParser.test.ts` | −175 | **Deleted** (§5.1) |

Test counts above are `it(`/`test(` declarations in the file at HEAD, not
declarations added by this cycle; `DispatchConfirmModal.test.tsx`,
`WorkerJobsPanel.test.tsx` and `useUiStore.test.ts` all existed before it.

### Documentation (this cycle)

| File | What |
| :--- | :--- |
| `docs/build-log/0120-an-action-beside-the-download.md` | This entry |
| `docs/build-log/README.md` | Index row for 0120 |
| `README.md` | ADR 0023 row amended: no longer "no UI consumes it" |
| `docs/ARCHITECTURE.md` | Dead-module row rewritten — `urlParser.ts` deleted, `validation.ts` still unconsumed |

`README.md`, `docs/ARCHITECTURE.md` and `docs/build-log/README.md` each also
carry a **concurrent session's** uncommitted edits for ADR 0023 and build-log
0119. Only the lines named above were touched in them, and only
`docs/build-log/0120-an-action-beside-the-download.md` was committed by this
cycle — committing the three shared files would have committed another session's
work, which is precisely the failure in §4.1, and would additionally have left a
committed index row pointing at an untracked `0119-*.md`.

---

## 8. Follow-ups

1. **Open this screen in a browser** (§6.5). Until someone does, the feature is
   verified only against jsdom, which reports no layout at all. A single real
   list-mode dispatch against a real worker would also settle whether the whole
   path works, which nothing so far has.
2. **Decide about `validation.ts`** (§6.3) — delete it, or give it the importer
   cycle 0112 expected. It has been dead through three cycles now.
3. **Split `ScreamingFrogView.tsx`** (§6.4), 782 lines against a 400-line target.
4. **Either generate the worker-schema types or pin them with a test** (§6.7).
   The same hand-transcription seam has now been recorded three times — build-log
   0101, build-log 0119's envelope fields, and this cycle.
