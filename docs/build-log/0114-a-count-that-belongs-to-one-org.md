# Cycle 0114: A count that belongs to one org

- **Date**: 2026-09-28
- **Scope**: `GET /crawl-activity` (org-scoped in-flight crawl counts) and a header indicator that polls it.
- **Commit**: `f3b82fb` (backend), `2b4cae3` (UI), merges `53b6eb4` + `d5d5d0a`, fix `d459031`. Pushed to origin/main. This entry is uncommitted at time of writing.
- **Quality gate**: targeted only. The full `verify.ps1` and the whole-repo `pytest` were **not** run this cycle (see section 1).

## 1. Gate results

Backend worktree (agent-reported, not re-run by the author of this entry): 14/14 new tests, 98% coverage of `src/api/crawl_activity.py`; `tests/api` 454 passed, 1 skipped in 460 s; `ruff`, `ruff format`, `mypy --strict` clean.

Merged main, run independently by the orchestrating session:

| Check | Result |
| :--- | :--- |
| `test_crawl_activity` + `test_server` + `test_worker_routes` + `test_adr0016_job_scoping` | 280 passed |
| `ruff check` | clean |
| `mypy --strict` on `crawl_activity.py` + `server.py` | clean |
| `scripts/export_ui_contract.py --check` | "UI contract is up to date" |
| `tsc --noEmit` | clean (after `d459031`) |
| full `vitest` | 42 files, 494 tests passed (before the one-line fix); 6 layout files / 60 tests re-run after it |
| `npm run build` | succeeded, 22 s |

Re-run by this entry's author on the final tree:

```
tests/api/test_crawl_activity.py  --no-cov
..............                                                           [100%]
14 passed in 3.28s
```

Not run: the full `verify.ps1` (ruff format, ruff check, mypy over the tree, pytest with the 85% coverage floor). Nothing in this entry certifies the repo-wide gate.

## 2. What landed

- **`src/api/crawl_activity.py`** (new; 3 lines plus imports wired in `server.py`). `GET {API_PREFIX}/crawl-activity` returns `CrawlActivityView {rankuno_active, rankuno_cap, sf_active}` for the caller's org only, authenticated with `require_principal` like `/jobs`.
  - `rankuno_active`: the org's `queued`/`running` jobs from `state.store.list_jobs()`. Local Screaming Frog records (`SF_TOOL_NAME`) are excluded, because they are not what the cap governs.
  - `rankuno_cap`: `state.max_concurrent_jobs`, the value `try_reserve` enforces. Never hardcoded in the UI.
  - `sf_active`: the org's `queued`/`dispatched` worker-dispatch jobs via `list_jobs_for_org`. Returns 0, logged and cached, when the dispatch store is unconfigured or unreachable. `/workers/jobs` returns 503 in that case; this route does not, because a header badge must not fail a page.
  - A 5 s per-org TTL cache with a per-org lock and an injectable clock sits in front of both reads. `DiskJobStore.list_jobs()` globs and parses every record per call, and `PostgresWorkerDispatchStore` opens a connection per call with no pool.
  - `DISPATCHED` jobs older than `worker_dispatch_timeout_s` (3 h) are filtered out read-only instead of calling `expire_stale_dispatched`, which is an `UPDATE` and would cost a second Postgres connection on a polled GET. The real sweep still runs from `/workers/jobs` and the worker poll.
- **UI**: `CrawlActivityIndicator` and `useCrawlActivity` in `rankuno-ui/src/components/layout/`, rendered in `HeaderBar` on every view beside the session-local `BackgroundPill`.
  - Polls every 10 s while visible and 60 s while hidden, fetches immediately on becoming visible, never overlaps requests, backs off exponentially on error up to 5 min while keeping the last value, and stops on 401 (the session-expired handler owns sign-out).
  - Polls only when authenticated and only when the adapter has the optional `getCrawlActivity`.
  - States: idle, running, at capacity ("FULL", warn colour), unavailable (renders nothing). Below 1180 px it shows icon and numbers only.
- **Contract**: `CrawlActivityView` added to `MODELS` in `scripts/export_ui_contract.py`; `schema.ts` regenerated; the interface is also hand-written in `adapterInterface.ts` (and implemented in `httpAdapter.ts` and `mockAdapter.ts`).

## 3. Design decisions

- **Visibility is same-org only** (user decision). A cross-org or global count was rejected: `GET /health` already exposes a process-global integer and that is precisely the leak this route avoids.
- **Two numbers, not one.** The user asked how many crawls the engine can take given RAM and floated a combined figure of 5. Screaming Frog worker dispatches are not governed by the server cap (`worker_routes` never calls `try_reserve`; each desktop worker daemon runs one job at a time), so `5` combined would describe nothing enforceable. The indicator shows `rankuno_active/rankuno_cap` and `sf_active` separately.
- **The cap was not changed.** Default 5 (`Settings.max_concurrent_crawls`, `ge=1, le=10`) stays pending the inputs in section 6.
- **Per-crawl RAM is an estimate.** About 1-3 GB for a 20k-page crawl. It is unmeasured: no RSS measurement exists anywhere in the repo. Do not quote it as a figure.
- **Failed dispatch lookup is cached as 0.** Retrying a dead database on every poll is the load pattern that keeps it dead.
- **`/health` was not reused.** It is unauthenticated, process-global, and excludes worker dispatches. It is still unused by the UI.

## 4. Bugs found and fixed

1. **A semantic merge conflict that neither side could see.** The UI branch's test set `lastMode` on `useUiStore`; commit `d3a35e8` on the other line of work had removed that field. Each side compiled and passed alone. The merged tree failed `tsc` (and therefore `npm run build`) while `vitest` still passed 494/494, because vitest does not typecheck. Fixed in `d459031` by dropping the field from the test. Lesson: run `tsc --noEmit` on the merged tree, not on each branch.
2. **The worktree isolation tool refused to create worktrees** ("core.worktree redirect") four times this session, apparently a `c:\` versus `C:\` drive-letter casing mismatch in the primary working directory path. Worked around by creating the two worktrees manually with `git worktree add` and pointing the agents at them. Three locked leftovers from the failed attempts remain under `.claude/worktrees/` (`agent-a3268c80...`, `agent-a4281fa0...`, `agent-a765d79f...`, all at `e83486a`); a fourth named in the session (`agent-abb22...`) did not appear in `git worktree list` when this entry was written. None were removed.
3. **Residual risk, not fixed** (backend agent's Step 5 audit): `PostgresWorkerDispatchStore` sets no `connect_timeout`. An unreachable Postgres host can block one threadpool thread per org per TTL window. The cache bounds this to one blocked thread per org per 5 s at worst; it does not eliminate it.

## 5. Corrections

- **CLAUDE.md section 8 and ADR 0008 say a 3-crawl cap. The code default is 5** (`DEFAULT_MAX_CONCURRENT_JOBS = 5` in `src/api/server.py`, `Settings.max_concurrent_crawls`). README and ARCHITECTURE already say 5. `src/core/facet_router.py:84` separately falls back to 3 silently. CLAUDE.md and ADR 0008 were not edited here (CLAUDE.md is a binding contract and ADRs are history); treat 5 as correct and 3 as stale.
- **"The poll reads directly from RAM, zero DB overhead"** (claim in the plan for this feature) was false. The org count needs a store read (disk) and a Postgres query, which is why the TTL cache exists. `len(self._active)` is process-global across orgs, so it cannot be the org number either.
- `GET /health` remains unauthenticated and process-global. It leaks other orgs' load as an integer and excludes worker dispatches.

## 6. Explicitly not done

- No limit is enforced on Screaming Frog dispatches. The indicator displays `sf_active`; nothing caps it.
- The cap was not re-tuned. Still owed by the user: Railway RAM plan, typical and maximum pages per crawl, number of Screaming Frog desktops.
- No cross-org or global count.
- The indicator is not clickable, has no link to the jobs view, and is invisible when the endpoint fails.
- Local Screaming Frog jobs (server-run) are counted in neither number.
- Polling only; no SSE or WebSocket.
- No ADR was written for "0 when the dispatch store is unavailable" or for the local-Screaming-Frog exclusion. The rules live in the `crawl_activity.py` module docstring. Consider a short ADR.
- `connect_timeout` on `PostgresWorkerDispatchStore` (section 4, item 3).
- Cleanup of the locked leftover worktrees.
- The full `verify.ps1`.

## 7. Files changed

Feature files: `src/api/crawl_activity.py` (new), `src/api/server.py`, `scripts/export_ui_contract.py`, `tests/api/test_crawl_activity.py` (new, 14 tests), `rankuno-ui/src/types/schema.ts`, `rankuno-ui/src/adapters/{adapterInterface,httpAdapter,mockAdapter}.ts`, `rankuno-ui/src/components/layout/{CrawlActivityIndicator,useCrawlActivity}.tsx/.ts` and their tests, `HeaderBar.tsx`, `rankuno-ui/src/styles/design-system.css`, `README.md`, `docs/ARCHITECTURE.md`, `docs/build-log/README.md`.

The push to origin also published `d3a35e8` ("keep the engine's tabs out of the launch chooser"), another session's already-committed work that was ahead of origin at the time. It is not part of this feature.

## 8. Follow-ups

- Decide the cap after the user supplies the RAM plan and page counts; measure RSS on a real 20k-page crawl first.
- Add `connect_timeout` to the Postgres dispatch store.
- Reconcile the 3-versus-5 statements in CLAUDE.md and ADR 0008 (a maintainer edit, not an agent one).
- Run the full `verify.ps1` on the merged tree.
