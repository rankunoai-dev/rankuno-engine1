# Cycle 0149: A reloaded page forgot the running crawl

- **Date**: 2026-10-09
- **Scope**: BUG FIX, UI only. After closing the tab during a running crawl and coming back, the Crawl jobs list and the header pill showed RUNNING with "—" in Progress and no bar, ETA, elapsed time or URL stream.
- **Commit**: (uncommitted at time of writing)
- **Quality gate**: implementer's run (output file `verify.txt`, exit 0); not re-run by the scribe. See section 7.

## 1. Why this cycle exists

The user reported, with a screenshot, that the gep.com row showed only RUNNING and "—" after a reload, while the page says "Crawls run in the background. Leaving this tab does not stop them."

The server was checked first and cleared. `GET /jobs` returns `JobView` (cycle 0147, commit 5e0febc, checked as a regression suspect), which keeps `telemetry`. Both job stores persist telemetry through `TelemetryRecorder` every few seconds. The data was on the wire; the client dropped it.

## 2. Root cause

Three client-side gaps, all confirmed in code:

1. `rankuno-ui/src/adapters/httpAdapter.ts` `toSummary` (~266-297) never copied `record.telemetry`, and `CrawlJobSummary` had no field for it.
2. `useCrawlStore.init()` only called `listJobs` and `selectJob`. `liveJobs` was filled only by `startCrawl`, relaunch and `watchJob`, so a reloaded page had no `liveJobs` entry and nothing polled the already-running job.
3. `CrawlJobsView.buildRows` and `HeaderBar` read progress only from `liveJobs`.

## 3. What landed

All under `rankuno-ui/src/`.

- `adapters/adapterInterface.ts`: optional `telemetry?: JobTelemetry` on `CrawlJobSummary`.
- `adapters/httpAdapter.ts`: `toSummary` passes `record.telemetry` through unchanged.
- `store/useCrawlStore.ts`: new `reattachRunningJobs()`, called from `init()` and `refreshJobs()`. For each queued or running job not already in `liveJobs` it seeds `liveJobs` from the server's telemetry and starts the existing `watchJob` poller.
  - `startedAt = Date.parse(crawledAt)` (started_at, else created_at), so elapsed time continues from the real start; `Date.now()` only if unparseable.
  - ETA, rate, completed, discovered and `recent_items` are the server's values. Nothing is computed client-side.
  - Terminal jobs are never attached.
  - One poller per job: a module-level `watching` set guards `watchJob` itself. This was needed because `startCrawl` calls `refreshJobs` before `watchJob`; without the guard every new crawl would be polled twice. The guard is released just before the final `refreshJobs` when a watched job finishes.
- `components/jobs/CrawlJobsView.tsx`: the stale comment "returns metadata, not progress" was replaced. Comment only for this fix. The file also contains an unrelated delete-button change (`DeleteOutlined` import and action-cell edits) made by someone else; it is not part of this fix.

## 4. Tests

| Test | Asserts |
| :--- | :--- |
| `httpAdapter.test.ts` "carries the server's telemetry through to the summary" | `toSummary` keeps `telemetry` |
| `useCrawlStore.test.ts` "seeds liveJobs from the server's telemetry and polls the job once" | telemetry in `liveJobs`; `startedAt` equals the record's start; `getProgress` called once; a second `refreshJobs` and a second `init` add no second poller; completion moves the job to succeeded with `endedAt` |
| `useCrawlStore.test.ts` "never attaches to a job that already finished" | terminal job gets no `liveJobs` entry (passes on old code by design; it guards over-attaching) |

Fail-before proof: `git stash push` of only the three source files, then the two test files against the old code gave "Tests 2 failed | 37 passed (39)". The adapter test failed with `Received: undefined` at `httpAdapter.test.ts:323`; the store test failed with `expected undefined to deeply equal { completed: 120, … }` at `useCrawlStore.test.ts:137`. After `git stash pop`: "Test Files 2 passed (2), Tests 39 passed (39)". Three older stashes from earlier sessions were left alone.

No HeaderBar or CrawlJobsView test was added; they read `liveJobs` unchanged.

## 5. Bugs found and fixed, corrections

- The bug above: telemetry dropped in the adapter, never re-attached on load.
- Double-poll trap avoided: `refreshJobs` now reattaches, and `startCrawl` calls it before `watchJob`; the `watching` guard prevents two pollers per new crawl.
- No test was wrong; the failing tests were correct and the code wrong. No specification bug found.
- Correction: the `CrawlJobsView` comment claiming the list "returns metadata, not progress" was false. The list has returned telemetry throughout. Replaced here.

### Restart behaviour

A crawl that died with the server is not shown as RUNNING. Startup recovery (`server.py` ~1629-1641 calls `recover_orphans` in a background thread; `state_store.py` ~956, `postgres_store.py` ~863) marks every queued or running job FAILED "interrupted by a server restart", adding that partial results can be viewed when a checkpoint exists. Recovery runs in the background (`ApiState.recovery_done`), so in the first moments a stale RUNNING row can be listed. The attached poller would see FAILED on its next poll and end cleanly; this race is not tested. Whether the user's gep.com crawl survived a server restart cannot be confirmed: no logs or `.jobs/` were inspected and the servers were down.

## 6. Explicitly not done

1. No stale-snapshot indicator for a genuinely stalled live job; its telemetry would show frozen from the first poll.
2. No HeaderBar or CrawlJobsView component test.
3. The recovery race window is untested.
4. No Python or API change.

Handoff for a separate decision: `PostgresJobStore.recover_orphans` fails every queued or running row in the table. If a second API instance shared the database, one instance's restart would fail the other's live crawls. This relates to the multi-worker gap in CLAUDE.md section 8 and needs owner/instance tagging.

## 7. Gate output

Implementer's report, not re-run by the scribe. Output file `verify.txt`, exit 0:

- `tsc` clean; `npm run contract` up to date (the hand-written adapter type is not in the generated contract); `npm run build` built in 46.92s.
- Full vitest: "Test Files 53 passed (53), Tests 698 passed (698)".
- `verify.ps1`: "ALL GATES PASSED"; format, lint and type check passed; "TOTAL 17495 980 3788 279 93%"; "Required test coverage of 85.0% reached. Total coverage: 93.49%"; "4388 passed, 2 skipped, 2 warnings in 1258.57s (0:20:58)".
- `drift_check.py` (implementer): PASSED across 246 md files. Scribe's run is in the hand-back report.
