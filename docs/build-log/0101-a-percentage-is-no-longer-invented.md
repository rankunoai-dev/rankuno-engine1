# Cycle 0101: A percentage is no longer invented

- **Date**: 2026-09-23
- **Scope**: `WorkerJobsPanel.tsx` renders the live progress telemetry
  build-log 0100 shipped on the backend — a real progress bar for a
  `dispatched` Screaming Frog job once its worker has reported
  `pages_crawled`/`progress_pct`/`current_phase`, replacing (for that case
  only) the static "no progress detail is available" placeholder. UI-only;
  no `src/` file is touched.
- **Commit**: `00abf65`, single parent `43ca79f` (a linear commit on `main`,
  not a two-parent merge commit — landing it was a fast-forward, not a merge
  requiring reconciliation, unlike build-log 0100's own `c7ff68b`). Verified:
  `git log --pretty=format:'%H %P' -1 00abf65` shows one parent hash.
- **Quality gate**: Targeted UI suite, independently re-run —
  `WorkerJobsPanel.test.tsx`: 12 passed, 0 failed. `tsc --noEmit`: clean, no
  output. `npm run build`: clean, exit 0, one pre-existing chunk-size warning
  on `synthetic-20000`/`synthetic-500` (fixture data, unrelated to this
  cycle). No Python file changed; Python gate not re-run for this cycle.

---

## 1. Gate results

Independently re-run this session, in `rankuno-ui/`, against `node_modules`
already present in this worktree (not the fresh-worktree case the implementer
worked from — see §5):

```
npx vitest run src/components/screaming-frog/WorkerJobsPanel.test.tsx

 Test Files  1 passed (1)
      Tests  12 passed (12)
   Start at  12:46:51
   Duration  13.74s (transform 287ms, setup 758ms, collect 5.78s, tests 3.66s, environment 2.42s, prepare 341ms)
```

`npx tsc --noEmit`: no output, exit 0.

`npm run build`:

```
> rankuno-ui@0.1.0 build
> tsc -b && vite build

vite v5.4.21 building for production...
transforming...
✓ 3067 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                          1.35 kB │ gzip:   0.73 kB
dist/assets/index-C2w_TqCA.css           47.23 kB │ gzip:   9.95 kB
dist/assets/synthetic-500-CqKmg5V8.js   386.76 kB │ gzip:  15.43 kB
dist/assets/index-CRZoV_sW.js         1,229.04 kB │ gzip: 385.99 kB
dist/assets/synthetic-20000-CWU9lvCu.js  16,018.27 kB │ gzip: 472.00 kB

(!) Some chunks are larger than 2000 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 14.85s
```

The `synthetic-20000`/`synthetic-500` chunks are pre-existing test-fixture
bundles, not anything this cycle added — confirmed by name and by the file
list in `git show 00abf65 --stat` (three files touched, none named
`synthetic*`).

`.\.venv\Scripts\python.exe scripts\drift_check.py`, run after this entry's
own doc edits (this file, the index row, `README.md`, `docs/ARCHITECTURE.md`):
see §6 — clean once this file exists on disk (the check reads via
`git ls-files` for its file *count*, but its broken-link check reads the
working tree, so it failed while this entry's own filename was referenced but
not yet written, and passes once it is).

## 2. What landed

- **`rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.tsx`** — a new
  `DispatchProgress` function component: antd `<Progress percent={...}
  size="small" status={exporting ? "normal" : "active"} showInfo={false} />`
  plus a `<span className="sfj-detail">` caption underneath with the real
  numbers (`"Crawling: 3,718 pages (40%)."` while `current_phase ===
  "crawling"`, `"Exporting the crawl bundle — 9,204 pages found."` while
  `current_phase === "exporting"`). Rendered in the status cell in place of
  `describeStatus(job)` only when `job.status === "dispatched" &&
  job.progress_pct != null` — read directly in the diff, confirmed matching
  the claim exactly:

  ```tsx
  {job.status === "dispatched" && job.progress_pct != null ? (
    <DispatchProgress
      percent={job.progress_pct}
      pages={job.pages_crawled}
      phase={job.current_phase}
    />
  ) : (
    <span className="sfj-detail">{describeStatus(job)}</span>
  )}
  ```

  Every other status, and a `dispatched` job with `progress_pct` still
  `null`, is unchanged — `describeStatus(job)` and its original strings are
  untouched by this diff (confirmed: the function's only edit is its own
  docstring, not its `switch` body).
- **The panel's module docstring** — the paragraph that read "There is no
  progress column and there will not be one. The supervisor knows whether the
  Screaming Frog process is alive, and nothing else... a percentage would be
  invented" is replaced, not deleted, with a paragraph naming the same
  reasoning, stating build-log 0100 made it obsolete (the numbers are now
  read from Screaming Frog's own `SpiderProgress` line, not invented), and
  stating explicitly that the original fallback text and its "no progress
  detail is available" case still apply and are still shown whenever a
  `dispatched` job has not yet reported. Read directly in the diff — this is
  the harder-to-fake claim in the implementer's report (replace-with-context
  vs. silent delete) and it holds.
- **`rankuno-ui/src/adapters/adapterInterface.ts`** — `WorkerJobView` gains
  three optional fields, `pages_crawled?: number | null`, `progress_pct?:
  number | null`, `current_phase?: "crawling" | "exporting" | null`, with a
  docstring addition naming exactly why they are hand-written (§4) and
  restating the non-monotonic behaviour.
- **`rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.test.tsx`** —
  5 new cases: no progress report yet (fallback text kept, no
  `role="progressbar"` in the DOM), a live crawling bar with real numbers, an
  exporting-phase caption, a decreasing percentage rendered as-is ("500 pages
  (13%)" — verified this is `12.5` rounded, not clamped up or held at a
  prior high-water mark), and a `dispatched`-only gate (a stray progress
  report on a non-`dispatched` record draws no bar). 12/12 pass, independently
  re-run (§1).

## 3. Design decisions

- **Gate strictly on `progress_pct != null`, not on `status === "dispatched"`
  alone.** A `dispatched` job with no report yet (older worker daemon, job
  just started, worker offline) still needs the original honest "not
  available" text rather than a bar drawn from absent data. Confirmed this is
  exactly what the code does (§2) — `progress_pct` is the single field
  checked, `pages_crawled`/`current_phase` are read but never gate anything.
- **No clamping, no monotonic-increase enforcement.** Matches build-log
  0100's own finding that Screaming Frog's completion denominator grows
  mid-crawl as new URLs are discovered, so a later report can legitimately
  show a lower percentage than an earlier one. Confirmed in the component
  (`percent={percent}` passed straight through with no `Math.max` or
  previous-value tracking) and in a dedicated test (§2, "renders a decreasing
  percentage as-is").
- **Replace the old docstring's reasoning rather than delete it.** The old
  paragraph was a considered design stance, not a stray comment — silently
  removing it would erase the record of why the panel looked the way it did
  for one cycle. The replacement names the specific technical claim ("a
  percentage would be invented"), states what changed (the backend now
  supplies a real one), and states what did *not* change (the fallback case
  is still real and still shown). This is the CLAUDE.md build-log
  discipline — "never edit an old entry, correct it and cite it" — applied
  to a code comment instead of a doc.

## 4. Bugs found and fixed

None in this cycle's own new code. One pre-existing gap this cycle's own
commit message surfaces and this entry verifies rather than takes on faith:
`scripts/export_ui_contract.py`'s `MODELS` tuple (read directly, §below) has
no worker-dispatch model in it at all —

```python
MODELS: tuple[type[BaseModel], ...] = (
    SignalScore, FullPageIntelligenceProfile, CmsRecord, DiscoverySource,
    DiscoveredNode, DiscoveryReport, SiteProfile, WeightProfileReport,
    NavSource, NavNode, NavigationTree, NavCoverageReport, JobTelemetry,
    CrawlSummary, GscEnrichmentReport, PageClassificationInput,
    PageClassificationOutput,
)
```

not just missing the three fields this cycle added. Confirmed more directly
than the implementer's report states it: `export_ui_contract.py`'s two
generated outputs are `SCHEMA_PATH = rankuno-ui/src/types/schema.ts` and
`COLORS_PATH = rankuno-ui/src/constants/colors.ts` — `adapterInterface.ts`,
where `WorkerJobView` and `WorkerJobEnvelope` live, is not a generator output
at all, for any model. This cycle's three fields are additions to an
already-entirely-hand-written file, not a new instance of manual drift on an
otherwise-generated one. The claimed `GscAccountsView` precedent
is real and checked directly: `rankuno-ui/src/components/gsc/
GscAccountsView.tsx` defines its own local `interface GscAccount {
account_name: string; client_id: string | null; has_secret_override:
boolean; }` rather than importing a generated one, for the same reason
(no GSC-account-profile model is in `MODELS` either). This is a real,
broader pre-existing gap — the UI's worker-dispatch and GSC-account
contracts have no generation coverage at all — not fixed here, and not
previously named this precisely in any build-log; flagged as a follow-up
(§6).

## 5. Corrections

- **The "fresh worktree, needed `npm install`" claim could not be
  reproduced or falsified in this review.** This docs-scribe pass ran from
  the same worktree the implementer used, where `node_modules` was already
  present (checked directly: `ls node_modules` succeeds). The claim that
  `package-lock.json` was touched by an install and then explicitly reverted
  is consistent with what is observable now — `git status --porcelain --
  rankuno-ui/package-lock.json` is empty, and `git show 00abf65 --stat --
  rankuno-ui/package-lock.json` shows the file is not part of the merged
  diff — but this entry did not independently witness the install or the
  revert happen, only their absence of a trace, which is what a clean revert
  looks like either way. Recorded as verified-by-absence, not
  verified-directly.
- No other correction to a previously published number. Build-log 0100's own
  "no frontend consumes this" line (§6 there) is not wrong for the cycle it
  described — it was accurate at the time build-log 0100 was written, and
  this entry does not retroactively edit it; the doc drift it caused (stale
  copies of that line living on in `README.md` and `docs/ARCHITECTURE.md`
  after this cycle shipped) is closed in §7, not by editing 0100.

## 6. Explicitly not done

- **`export_ui_contract.py`'s `MODELS` tuple is not extended to cover
  `src/api/worker_schemas.py` or a GSC-account-profile model.** Both the
  worker-dispatch contract and the GSC-account contract remain entirely
  hand-maintained TypeScript, with no generated fallback to catch drift if a
  backend field is renamed or removed. This is a real, standing gap broader
  than the three fields this cycle added — flagged in §4, not fixed here;
  out of scope for an additive UI cycle.
- **No cloud dashboard or worker-management screen.** Unchanged from
  build-log 0098/0100 — this cycle only touches the existing
  `WorkerJobsPanel.tsx`, not a new surface.
- **No change to `describeStatus()`'s non-`dispatched` branches**, or to any
  other status's rendering. Confirmed by reading the full diff (§2) —
  the `switch` body for `queued`/`succeeded`/`partial`/`failed` is untouched.
- **`progress_pct` is still not guaranteed monotonic on the wire** (that was
  build-log 0100's own decision, restated here) and this cycle does not add
  any client-side smoothing, easing, or animation beyond what antd's
  `Progress` does on its own for a changed `percent` prop.
- **Python quality gate not re-run.** No `src/` file changed in this commit
  (confirmed: `git show 00abf65 --stat` lists exactly the three
  `rankuno-ui/` files in the summary at the top of this entry); re-running
  `verify.ps1` would only reproduce build-log 0100's own numbers with zero
  new information, so it was not repeated here.

## 7. Files changed

Per `git show --stat 00abf65` (3 files, 174 insertions(+), 11 deletions(-)):

```
rankuno-ui/src/adapters/adapterInterface.ts                     | 19 +++-
rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.test.tsx | 87 +++++++++++++
rankuno-ui/src/components/screaming-frog/WorkerJobsPanel.tsx      | 79 +++++++++--
```

Plus, from this docs-scribe pass: this entry, its `docs/build-log/README.md`
index row, and edits to `README.md` and `docs/ARCHITECTURE.md` closing the
stale "no frontend consumes this" / "there is no progress column and there
will not be one" language that build-log 0100 recorded as an explicit gap —
found in three places and updated in all three: the `README.md` capability
table row for build-log 0100's own feature, the `docs/ARCHITECTURE.md`
"Planned, not yet implemented" table (row removed, with a numbered removal
note added following the same pattern cycles 0039/0087/0098 already
established), and the ADR 0015 index-table description in
`docs/ARCHITECTURE.md` §5 ("still no frontend consumer" -> names this
cycle). No stale copy of that language was left standing.

## 8. Follow-ups

- **Generation coverage for `worker_schemas.py` and any GSC-account-profile
  model** (§4/§6) — a dedicated cycle should decide whether
  `export_ui_contract.py` is worth extending to cover both, or whether a
  hand-written contract with a docstring pointer (the current pattern, now
  used twice) is the accepted long-term shape.
- Whether a cloud dashboard or worker-management screen is ever built remains
  open and untouched by this cycle (build-log 0098 §6, unchanged).
