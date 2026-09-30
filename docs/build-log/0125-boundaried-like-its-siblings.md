# Cycle 0125: Boundaried like its siblings

- **Date**: 2026-09-29
- **Scope**: Fix a production crash on the Crawl Jobs list view (mobile,
  `rankuno-engine1-production.up.railway.app`) — an on-page error "Cannot read
  properties of undefined (reading 'baseUrl')" alongside a console 404 on
  `GET /jobs/{id}/reconciliation` for job `202c2acc...` — by wrapping
  `CrawlJobsView` in `DashboardShell.tsx`'s existing `<ErrorBoundary>` pattern,
  the one view it was missing from.
- **Commit**: uncommitted at time of writing.
- **Quality gate**: `npm run typecheck` clean; `npm run test -- --run` — Test
  Files 47 passed (47) / Tests 605 passed (605); `npm run build` clean, 3076
  modules transformed. Python gate not run — no `src/` file changed. Not
  independently re-run by this scribe pass; pasted verbatim from the
  implementing agent's report per this entry's §1.

## 1. Gate results (pasted, not independently re-run)

```
npm run typecheck    → tsc --noEmit, clean, no output
npm run test -- --run → Test Files 47 passed (47) / Tests 605 passed (605)
npm run build         → tsc -b && vite build succeeded, 3076 modules transformed
```

Python gate not run this cycle — no `src/core`, `src/integrations`,
`src/modules`, or `src/api` file changed. Only the two files in §7 were
touched.

## 2. What landed

`rankuno-ui/src/components/layout/DashboardShell.tsx` wraps `LaunchView`,
`ScreamingFrogView`, `AuditView`, `GscAccountsView` and the printable
`CrawlReport` in `<ErrorBoundary>`. `CrawlJobsView` — the component behind the
"jobs" nav item, which itself renders `ReconcilePanel` and `PerformancePanel`
as dialogs — was the one view rendered unboundaried:
`{view === "jobs" && <CrawlJobsView />}`. No root-level boundary exists in
`App.tsx`/`main.tsx` either, so a render-time throw anywhere in that subtree —
the jobs table itself, or either dialog it opens — had nothing between it and
React unmounting the entire dashboard: header, nav rail, everything.

The fix adds the same wrapper already used for every sibling view:

```tsx
{view === "jobs" && (
  <ErrorBoundary label="Crawl jobs">
    <CrawlJobsView />
  </ErrorBoundary>
)}
```

Verified by direct read of the current file (not taken on the implementing
agent's word): the diff is real, `git diff --stat` shows
`DashboardShell.tsx | 14 ++++--` (14 insertions, 2 deletions — the
implementing agent's report said "+12/-2", the actual figure is 14/-2; see
§5) and `DashboardShell.test.tsx | 66 ++++...` (66 insertions), matching the
report's description of what changed, if not its exact insertion count.

A regression test was added to `DashboardShell.test.tsx`: a new `describe`
block mocks `CrawlJobsView` to `throw new Error("boom from the jobs table")`
and asserts `.rk-app` and the nav rail (`role="navigation"`) survive, with the
boundary's own message
(`"Crawl jobs could not be rendered — boom from the jobs table"`, matching
`ErrorBoundary.tsx`'s `{label} could not be rendered — {message}.` format at
line 42) rendered in place of the crashed view.

## 3. Root cause investigation

Three hypotheses were considered and ruled out before the real defect was
found. Recorded here so a future reader does not re-walk the same ground.

**(a) Reconciliation-fetch `.baseUrl` defect — ruled out.** Every literal
`.baseUrl` and bare `baseUrl` occurrence in `rankuno-ui/src` was re-walked,
broader than a plain grep to also catch destructuring. Each one is either
`this.baseUrl` on a bound `HttpAdapter` instance, inside a `.map()` callback
where the element cannot be undefined, or guarded by an `||` fallback chain.
`PerformancePanel.tsx` and `ReconcilePanel.tsx` were read in full and are
defensive throughout; `httpAdapter.ts`'s `getReconciliation`/`getPerformance`/
`request<T>`/`describeFailure` are all clean. No throw site exists on current
`main` in the reconciliation or performance fetch paths.

**(b) Deploy lag — ruled out.** Production's `index.html` references
`assets/index-Bm54yld-.js`, a hash that did not match any local build
produced by bisecting six commits (including current `HEAD` `f9f8232`) via
`git worktree` + `npm run build` — but Vite/Rollup content-hashing was
confirmed not run-to-run reproducible in this environment (two local builds
of identical source produced two different hashes), so hash comparison alone
is not evidence of staleness. Downloading production's actual JS bundle and
grepping it settles it instead: it contains the literal strings `urls.pdf`
and `downloadUrlListPdf`, which exist only as of `f9f8232` (today's PDF URL
export feature, build-log 0124). Production is running current `HEAD` or
later.

**(c) Migration 0008 not applied — ruled out.** The Dockerfile's `CMD` runs
`alembic upgrade head && exec uvicorn ...` on every container boot.
Production's `/api/v1/health` responds `200`, which is only reachable if that
migration step succeeded. Combined with (b), this confirms the
`reconciliation`/`performance` Postgres persistence fix from build-log 0121
(migration 0008, commit `f7e9e4e`) is live and functional in production right
now — see §5 for what this corrects.

**The 404 on `GET /jobs/{id}/reconciliation` for job `202c2acc...` is
legitimate, by design, not a live regression** — with one caveat. Given the
persistence fix and its migration are confirmed live, the 404 means either
that job never had a Screaming Frog cross-check run, or it is one of the jobs
whose reconciliation write silently no-op'd before `f7e9e4e` shipped, which
build-log 0121 §7/§10 states plainly is **not backfilled** and will 404
forever. This session could not authenticate to production's
`/api/v1/jobs` to read that job's exact creation timestamp — a genuine limit
on certainty, recorded as such rather than asserted as fact.

**The real, verifiable defect**: the containment gap described in §2. It
matches "an on-page error… the error banner appeared on the list page itself"
far better than a silently-swallowed 404 would, and — unlike the ruled-out
`.baseUrl` hypothesis — is independently verifiable by reading the file and
applies regardless of which specific line actually threw in the reported
session.

## 4. Bugs found and fixed

**Structural containment gap**: `DashboardShell` boundaried every view
*except* the jobs view, the one view whose subtree (the jobs table plus two
dialogs it opens) has the most render paths of any view in the shell. Any
render-time throw anywhere in that subtree — from any cause, including one
that could not be reproduced statically in this session — took down the
entire dashboard rather than being contained to the offending panel. Fixed by
applying the existing `<ErrorBoundary label="...">` pattern, unchanged in
shape from every other call site in the same file.

## 5. Corrections

**Build-log 0121 §7 stated: "The fix has not been confirmed against the real
user's actual failing job in production. It closes the traced root cause; no
live redeploy-and-retry has been observed by this session."** This cycle's
investigation (§3b/§3c) confirms the underlying claim now holds: production
is running commit `f9f8232` or later, its `/api/v1/health` returns `200`
(only possible if migration 0008 ran), and the reconciliation/performance
Postgres persistence fix build-log 0121 shipped is live and functional in
production. This does not confirm the *specific* job build-log 0121's
follow-up named (no production job list was reachable) — see §6.2 — but it
does close the general "has not been confirmed" uncertainty for the fix
itself.

**A numbering collision affects this entry's own source comments.** The code
comments landed in `DashboardShell.tsx` (line ~188) and
`DashboardShell.test.tsx` (the "boundaried like its siblings" `describe`
block) cite "(build-log 0122)" as the entry documenting this fix. That
number was claimed first, same day, by a concurrent session for an unrelated
production bug (the header PDF button printing an empty report on a
no-GSC-property job — see
[0122-the-throw-was-real-the-trigger-was-not.md](0122-the-throw-was-real-the-trigger-was-not.md)).
This cycle is **0125**, not 0122. The source comments are stale and, per
`docs/build-log/README.md`'s own numbering-collision register, are recorded
here rather than silently rewritten — correcting a source comment is outside
this scribe pass's scope (see §6.5) and the register's own precedent (the
0104/0107 citation mismatch) is to record the mismatch, not retroactively
edit code comments written by a prior cycle.

## 6. Explicitly not done

1. **The exact `.baseUrl` throw site was not located.** No live-browser tool
   was available to capture a real stack trace from the reported mobile
   session. The most likely explanation is that it was transient, or already
   superseded by one of the day's several other UI commits landing between
   the crash and now — but that is inference, not proof, and is stated as
   such rather than as a fact.
2. **Job `202c2acc...`'s exact creation time relative to `f7e9e4e`'s deploy
   was not confirmed** — no production credentials were available to this
   investigation. If the operator reproduces against a newly-run cross-check
   for that same job, it should now succeed; if it does, that confirms the
   404 was pre-fix orphaning rather than a live regression.
3. **A separate, pre-existing wiring defect was found and flagged, not
   fixed**: `HttpAdapter.toSummary()` (`httpAdapter.ts:244`) sets
   `baseUrl: record.label` — identical to the `label` field one line above
   (`httpAdapter.ts:243`). `CrawlJobSummary.baseUrl` never actually carries a
   crawl's base URL; it is a duplicate of `label`. This makes the
   `job.label || job.baseUrl || job.id` fallback chain in
   `CrawlJobsView.tsx:558` and the `${job.label || job.id} — ${job.baseUrl}`
   string in `UrlListSourcePicker.tsx:225` partly dead code — the `baseUrl`
   clause only fires when `label` is already falsy, and when it does,
   `baseUrl` is `undefined` too, since both are wired to the same source
   field. It does not crash anything (the `||` guards it), but it is a real
   naming/wiring defect. Left for `api-data-engineer` or `ui-engineer` to
   pick up in a separate cycle — no fix cycle has been dispatched for it as
   of this entry.
4. **Whole-repo Python `verify.ps1` was not run** — no Python file changed
   this cycle.
5. **The stale "(build-log 0122)" citations in `DashboardShell.tsx` and
   `DashboardShell.test.tsx` were not corrected** in the source files
   themselves — this scribe pass is documentation-only per its brief and did
   not touch those two files beyond reading them for verification. See §5 for
   the correction recorded here instead.
6. No ADR was written. This is a containment/consistency fix — applying an
   existing, already-established `<ErrorBoundary>` pattern to the one view
   that lacked it — not a new architectural decision a future agent needs to
   be bound by.
7. No change was needed in `README.md` or `docs/ARCHITECTURE.md`: neither
   file currently makes any claim about dashboard error-boundary coverage or
   per-view isolation (checked directly — no match for `ErrorBoundary`,
   "boundari-", "error handling", or "view isolation" in either file, save a
   list of grep hits in `README.md` unrelated to this topic), so there was no
   stale claim to correct and none was added speculatively.

## 7. Files changed

```
rankuno-ui/src/components/layout/DashboardShell.tsx      | 14 ++++++++++--
rankuno-ui/src/components/layout/DashboardShell.test.tsx | 66 ++++++++++++++++++++++
2 files changed, 78 insertions(+), 2 deletions(-)
```

`git status` at the time of this scribe pass showed exactly these two tracked
files modified (plus one unrelated untracked scratch file,
`~$rae_defects_and_fixes.xlsx`, not part of this cycle and not touched).

## 8. Follow-ups

- Correct the "(build-log 0122)" citations in `DashboardShell.tsx` and
  `DashboardShell.test.tsx` to "(build-log 0125)" in a future small cycle —
  not done here; see §6.5.
- Pick up the `baseUrl`/`label` duplicate-wiring defect described in §6.3.
- Confirm with the reporting user that a newly-run Screaming Frog cross-check
  against job `202c2acc...` now succeeds, closing the open question in §6.2.
- No live-browser reproduction of the original crash was ever obtained; if it
  recurs, capturing the actual stack trace would let a future cycle locate
  the specific throw site rather than relying on containment alone.
