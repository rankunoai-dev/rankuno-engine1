# Cycle 0053: A banner that outlived its cause

- **Date**: 2026-09-01
- **Scope**: `useCrawlStore.refreshJobs` — retract the connection error when the
  connection comes back.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI `140 passed` across 13 files; ruff clean. See §5.

## 1. The report

A screenshot: **"Cannot reach the engine at http://127.0.0.1:8001/api/v1. Is the
API server running?"** — above a live job list showing a highradius crawl that
finished 44 minutes earlier and four gep.com runs beneath it.

The engine was running. `GET /api/v1/health` answered `200`, and the server's own
log showed it serving `GET /api/v1/jobs 200` to that browser while the banner
was on screen.

## 2. The banner was a memory, not a measurement

`refreshJobs` is the poller. On failure it set `error`; on success it set
**only** `jobs`:

```text
try   { set({ jobs: await adapter.listJobs() }) }
catch { set({ error: describe(cause) }) }
```

So the first failed poll pinned the message permanently. Every later poll
succeeded, refreshed the list underneath it, and left the claim standing. The
only way to clear it was a page reload.

This project restarts the API constantly — twice in the last session alone,
each time to pick up code that Python will not reload — so a failed poll is a
routine event, not an exceptional one. The banner was near-permanent by design
and nobody had noticed because the data underneath kept working.

**The failure mode is the interesting part.** A false "it is broken" is worse
than no banner: it teaches the reader to distrust the screen, and the next time
the engine really is down they will assume it is stale.

## 3. Why not simply clear the error on every success

Because not every error is a claim a poll can disprove. "This data source cannot
start crawls" is true whether or not the job list loads; clearing it would erase
a message the operator had not read yet.

The poller now remembers the message it raised and takes down **only that one**.
Anything else — an upload that failed, an adapter that cannot reconcile — is
left alone, including an error raised *after* the failed poll, which a later
success does not speak to either.

`lastPollError` is module state rather than store state deliberately: it exists
so the poller can recognise its own banner, and a store field would invite a
component to render it as a second error.

## 4. Design decisions

**Five tests, and four of them are about restraint** — what the poller must not
clear. The clearing case is one line; the not-clearing cases are where a fix
like this goes wrong.

**This is the store's first test file.** `useCrawlStore` had none, which is part
of why a poller that never retracted its own error survived this long: every
existing UI test mounts a component and stubs the store.

## 5. Bugs found and fixed

**`npx prettier --write` reformatted the whole file.** The repo has no prettier
config, so it applied its own defaults — 4-space indent against the project's 2
— and turned a 25-line change into `412 +/351 -`. Caught on `git diff --numstat`
before committing; reverted with `git checkout` and the edit reapplied by hand.

Worth recording as a rule: **this project has no JavaScript formatter**, and
running one reformats whatever it touches. The UI is formatted by hand and by
review.

## 6. Explicitly not done

- **The health check at startup is still one-shot.** `App.tsx` picks the HTTP
  adapter or fixtures once, at load. If the engine is down at that moment the
  app runs on fixtures for the whole session and starting the engine does not
  change that. This cycle fixes the banner, not the adapter choice — those are
  different mechanisms and the second is a larger change.
- **Nothing tells the reader which build is answering.** Recorded in 0048 §4b
  after the same class of confusion, and still true: a stale server and a live
  one look identical.
- **The Python gate still cannot run green** because of `split_sheets.py`, an
  untracked one-off at the repo root belonging to another working tree. Python
  tests and lint were run directly instead.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/store/useCrawlStore.ts` | the poller retracts its own error |
| `rankuno-ui/src/store/useCrawlStore.test.ts` | new — 5 tests |

## 8. Follow-ups

1. Re-check the adapter choice periodically, so starting the engine mid-session
   promotes the app off fixtures without a reload.
2. Show which build is serving, per 0048.
