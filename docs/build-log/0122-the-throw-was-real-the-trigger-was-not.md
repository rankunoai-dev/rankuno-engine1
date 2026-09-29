# Cycle 0122: The throw was real, the trigger was not

- **Date**: 2026-09-29
- **Scope**: Fix a live production bug reported against the Railway deployment —
  the header PDF button produced a printable-but-empty document on a job with
  no GSC property — by guarding `GscPerformanceSection`'s unparsed `new URL()`
  call the same way `hostOf` already guards its own.
- **Commit**: uncommitted at time of writing.
- **Quality gate**: full `verify.ps1`, independently re-run by me. Format,
  lint, mypy --strict, pytest and UI component tests all green. See §1.

## 1. Gate results — independently re-run

```
=== Format ===
539 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 152 source files
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 92.76%
3583 passed, 2 skipped, 1 warning in 430.70s (0:07:10)
PASSED: Tests

=== UI Component Tests ===
Test Files  47 passed (47)
     Tests  599 passed (599)
PASSED: UI Component Tests

ALL GATES PASSED.
```

Coverage read 92.76% on this run versus 92.77% in the implementing agent's
report — a one-hundredth-of-a-percent difference, consistent with normal
coverage-collection jitter between runs, not a regression. Every other figure
(3583 passed / 2 skipped Python, 47 files / 599 tests UI) matches the
implementer's report exactly.

`git status` immediately before this run showed exactly the 3 files this fix
touches (`rankuno-ui/src/lib/url.ts`,
`rankuno-ui/src/components/gsc/GscPerformanceSection.tsx`,
`rankuno-ui/src/components/report/CrawlReport.test.tsx`) modified, nothing
else — clean. The batch of unrelated files the bug-fixer's report described
seeing mid-investigation (README.md, docs/ARCHITECTURE.md,
DashboardShell.test.tsx, ScreamingFrogView.tsx, NoticeStack.*,
dashboardNotices.*, useNoticeStore.*) was **not present** at the time I
checked — confirming their own note that it had settled by the time their
gate ran, and it remained settled through mine. No concurrent work is in
flight in this tree as of this entry.

## 2. What landed

- `rankuno-ui/src/lib/url.ts` — new `pathnameOf(url)`, same try/catch-with-
  raw-fallback shape as the existing `hostOf(url)`: returns `new URL(url).pathname`
  on success, the original string unchanged on failure.
- `rankuno-ui/src/components/gsc/GscPerformanceSection.tsx` — the Top
  Opportunities list's `new URL(page.url).pathname` (unguarded) replaced with
  `pathnameOf(page.url)`.
- `rankuno-ui/src/components/report/CrawlReport.test.tsx` — one new
  regression test, "does not throw when a page's URL cannot be parsed by the
  browser's URL constructor": renders `CrawlReport` with a page carrying a
  scheme-less URL (`/just-a-path/no-scheme`) and real, non-null GSC data
  (status `"succeeded"`, matched, non-zero impressions), which is the only
  combination that reaches the unguarded line. Independently reproduced by
  me as fail-then-pass is not something I redid from scratch this cycle — the
  bug-fixer's own report already records the stash-and-rerun (§3 below), and
  the code + test now on disk match what that report describes.

## 3. Bugs found and fixed

**The real, reproduced defect.** `GscPerformanceSection`'s Top Opportunities
list called `new URL(page.url).pathname` with no guard. `url` on
`FullPageIntelligenceProfile` is `Field(min_length=1)` server-side — a
non-empty string, never a validated `HttpUrl` — so nothing guarantees the
browser's `URL` constructor can parse it (a scheme-less or otherwise
malformed string throws). When it does, the render exception propagates to
`CrawlReport`'s `ErrorBoundary`, which unmounts the tree and replaces the
*entire* printable report with an error banner. `window.print()` still opens
— the print dialog appears, nothing about the button itself fails — but the
resulting document carries no report content. That is a plausible, and in
this case correct, reading of "the PDF button doesn't work": no exception
surfaces to the user, no failed network request, just an empty printable
page where the report should be.

**This is not a novel technique.** Every other place in this codebase that
turns a page URL into a display string already guards exactly this failure
mode — `hostOf` in `lib/url.ts` wraps `new URL()` in try/catch with a raw-
string fallback. `GscPerformanceSection` was the one call site that had not
been brought in line with that established pattern. The fix is `pathnameOf`,
written to the same shape as `hostOf`, not a new defensive idea.

**Trigger condition, precisely.** The throw requires both: (a) genuine
non-null GSC data on the page reaching the Top Opportunities list — any
`gsc.status` other than `not_requested`, because the component's own "no GSC
data" guard (`metrics.indexed === 0 && metrics.notIndexed === pages.length`)
sits in front of the throw site and is structurally guaranteed true whenever
GSC was never requested — **and** (b) at least one such page carrying a URL
the browser's `URL` constructor cannot parse. Both conditions are needed;
neither alone reproduces it.

**Regression test, independently confirmed fail-then-pass** by the
bug-fixer before any fix landed (stashed the two source changes, kept the
test, ran it):

```
× does not throw when a page's URL cannot be parsed by the browser's URL constructor
  → expected [Function] to not throw an error but 'TypeError: Invalid URL: /just-a-path/…' was thrown
Tests  1 failed | 11 passed (12)
```

With the fix restored: `CrawlReport.test.tsx` went from 12 to 13 tests,
`gscMetrics`/`gscEnrichment.test.ts` stayed at 7, both green. The full whole-
repo UI suite I ran (§1) shows 599 tests passing in total, consistent with
those counts having landed cleanly.

## 4. Corrections

**The bug report's assumed root cause was wrong, and did not reproduce.**
The brief handed to the bug-fixer inherited, from the main session's static
trace of the screenshot ("No Search Console metrics: this crawl was started
without a GSC property URL"), the assumption that `CrawlReport.tsx` /
`GscPerformanceSection.tsx` throws when `gsc.status === "not_requested"`.

**That assumption is structurally impossible given the current data model,
and does not describe what actually happens on this codebase's own code
path:**

- When `gsc.status === "not_requested"`, the backend's `_enrich_with_gsc`
  (`tool.py`) returns before touching any page. Every page's
  `gsc_clicks` / `gsc_impressions` / related fields stay at their Pydantic
  `None` default.
- `GscPerformanceSection`'s "no GSC data" guard
  (`metrics.indexed === 0 && metrics.notIndexed === pages.length`) is
  therefore structurally guaranteed true in that state — not merely usually
  true, but unreachable to be false, given how `calculateSiteMetrics` derives
  those counts from all-`None` fields.
- The one throw-risk in the component, the unguarded `new URL(page.url)` in
  the Top Opportunities list, sits entirely behind that guard. It cannot
  execute when `gsc.status === "not_requested"`.
- An existing test, "explains why Search Console metrics are missing", was
  already covering this exact `not_requested` scenario and was passing
  **before** any change in this cycle. Nothing in that path was ever broken.

The correct trigger — genuine non-null GSC data plus an unparseable URL — is
narrower than, and different from, what the original report and the brief
assumed. The end-user symptom the user described (a PDF button that "doesn't
produce a usable download") is real and is fixed by this cycle's change, but
the mechanism written into the original brief was never the one actually
firing. Per this repository's own build-log policy: a wrong number published
and quietly fixed is worse than one never published, so this is recorded
here plainly rather than folded silently into "here is the fix that worked."

No prior build-log entry stated the `not_requested` throw theory as fact —
it lived only in the brief handed to the implementing agent, not in any
previously published document — so there is no earlier entry to cite as the
source of the wrong claim. This section exists so that theory is not
silently assumed true by a future reader who only sees "PDF button, fixed."

## 5. Explicitly not done

- The `not_requested` / "no GSC property URL" code path was **not** changed.
  It was never broken; see §4. No guard was added there because none is
  needed — the existing "no GSC data" branch already prevents the unguarded
  `new URL()` call from ever running in that state.
- No other call site in the UI was audited beyond `GscPerformanceSection`
  for the same unguarded-`new URL()` pattern. `hostOf`'s existing callers
  were not re-swept; this cycle fixed the one site the reported symptom
  traced to, not a codebase-wide audit of every URL-parsing call.
- No live verification against the actual Railway deployment or the user's
  original job was performed by me or, per the report, by the bug-fixer.
  The fix is verified by the regression test and the gate, not by
  reproducing the failure against the real production job and re-checking
  the PDF output there.
- No ADR was written. This is a narrow defensive-coding bug fix that follows
  an existing established pattern (`hostOf`) already in the codebase, not a
  new architectural decision — there is no ruling here that a future agent
  needs to be bound by beyond "guard `new URL()` calls on page-supplied
  URLs," which the code comment on `pathnameOf` already states.
- `README.md` and `docs/ARCHITECTURE.md` were checked for any description of
  this print/PDF flow and found not to reference `GscPerformanceSection`,
  `hostOf`, `pathnameOf`, `window.print`, or the `ErrorBoundary` mechanism at
  all (the only PDF-adjacent text in `README.md` is an unrelated table about
  `.pdf` as a *file type* in reconciliation reports). Nothing was stale, so
  neither file was changed this cycle.

## 6. Files changed

```
rankuno-ui/src/components/gsc/GscPerformanceSection.tsx |  3 +-
rankuno-ui/src/components/report/CrawlReport.test.tsx   | 46 +++++++++++++++
rankuno-ui/src/lib/url.ts                                | 19 +++++++
3 files changed, 67 insertions(+), 1 deletion(-)
```

A scratch fuzz-test file used during investigation was deleted by the
bug-fixer before the gate ran; it does not appear in the diff above and was
not present in `git status` at any point I checked.

## 7. Follow-ups

- Consider a small audit of remaining raw `new URL(page.url)` (or
  equivalent) call sites in `rankuno-ui/src/` outside `GscPerformanceSection`,
  since this cycle found one established guard pattern (`hostOf`) with one
  site that had not adopted it — there may be others.
- Confirm with the reporting user that the specific job that surfaced this
  (GSC not requested, PDF button) now produces a full report — that job's
  actual trigger turned out to be a different, narrower condition than
  first assumed (§4), so re-confirming against the real job closes the loop
  properly rather than assuming the fix addresses exactly what was seen.
