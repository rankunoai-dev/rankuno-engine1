# Cycle 0115: A menu that sent the wrong id

- **Date**: 2026-09-28
- **Scope**: Masterfile building and downloading moved from the native crawl table to finished Screaming Frog worker-dispatch rows; the old menu, which sent an id the backend refuses, is deleted. UI only.
- **Commit**: `44e50fc` (`feat(ui): build masterfiles from finished Screaming Frog dispatch rows`), fast-forward merged from branch `masterfile-ui`, on origin/main. This entry is uncommitted at time of writing.
- **Quality gate**: UI only, no Python file changed, so the Python gate was **not run**. `tsc --noEmit -p .` exit 0; full vitest 43 files / 506 tests passed in the worktree (see §1 for the 530 figure on merged main).

## 1. Gate results

Reported by the implementing agent and independently re-run by the lead in the worktree, then again on merged main. This scribe did not re-execute any of it; the figures below are the lead's and the agent's, not pasted from a run here.

| Check | Where | Result |
| :--- | :--- | :--- |
| `tsc --noEmit -p .` | worktree (agent, lead) | exit 0 |
| full vitest | worktree (agent, lead) | 43 files / 506 tests passed |
| `npm run build` | worktree (agent) | built in 27 s |
| `npm run build` | merged main (lead) | built in 24 s |
| `npm run contract` | worktree (agent only) | "UI contract is up to date" |
| `tsc --noEmit -p .` | merged main, shared working tree (lead) | exit 0 |
| full vitest | merged main, shared working tree (lead) | 43 files / 530 tests passed |

The 530 is not 506 plus this commit's tests. The shared working tree holds another session's uncommitted test edits (24 extra tests); they are not part of `44e50fc`. The number that describes this commit is 506.

The Python gate (`verify.ps1`) was not run. `git show --stat 44e50fc` lists 8 files, all under `rankuno-ui/`. No mutation check was run on the new assertions (the agent said so), so a test that passes for the wrong reason would not have been caught here.

`git push` reported "Everything up-to-date": `44e50fc` had already reached origin/main through another push from the shared main branch. main equalled origin/main at that point.

## 2. What landed

`git show --stat 44e50fc`: 8 files, 598 insertions, 165 deletions.

- **`rankuno-ui/src/components/screaming-frog/useMasterfileBuild.ts`** (new, with `.test.tsx`). The build, poll, download flow extracted from `CrawlJobsView`. `POST /jobs/{id}/masterfile/{slug}` returns a deliverable id (202); `getDeliverable` is polled once a second, up to 60 tries; `has_result` ends with a download, a `failed` status ends with the server's error text. In-flight state is tracked per job and per service, with a synchronous ref guard so two clicks in one tick cannot start two builds; timers are cleared on unmount. The service list comes from `adapter.listAvailableMasterfiles` (`GET /masterfiles/available`), not a hard-coded 21. The download goes through the bearer-authenticated `downloadDeliverable` and `saveBlob`, never an `<a href>` (build-log 0103).
- **`WorkerJobsPanel.tsx`**. A "Masterfiles" popover button (aria-label `Masterfiles for <seed url>`) on rows where `hasBundle(job)` is true, the adapter supports building, and the service list is non-empty. Inside is a wrapping grid with one button per service and a per-button spinner. Only the button whose build is running is disabled. The id sent is the **worker** job id.
- **`CrawlJobsView.tsx`**. The masterfile menu, `onBuildMasterfile`, and its props and state removed. The URL-list xlsx download and delete (cycle 0102) are untouched.
- **`adapterInterface.ts`**. The four masterfile methods added to the `WorkerDispatchAdapter` `Pick` type. The methods themselves already existed on the adapter.
- **`screaming-frog.css`**. 21 lines for the popover grid.

Backend untouched. Routes used, all in `src/api/deliverables_routes.py`: `GET /masterfiles/available`, `POST /jobs/{job_id}/masterfile/{service_slug}` (202), `GET /deliverables/{id}`, `GET /deliverables/{id}/download`.

## 3. Design decisions

1. **Remove the old menu, do not keep it with an explanatory message.** The user chose removal. The menu could never work on a native row, so a message would be a permanently disabled control.
2. **Build now, not after the concurrent backend work.** Another session is changing what the masterfile workbooks contain. That work changes contents, not routes or slugs, so the UI does not depend on it. The user chose to build now.
3. **A shared hook, not a copy in the panel.** The polling and download logic is the part that is easy to get subtly wrong (double-click, unmount, error mapping); it now has one implementation with its own test file.
4. **Services from the server, not a constant.** The 21 services are the keys of `_SERVICES` in `src/modules/seo/deliverables/masterfile_registry.py`, exposed as `AVAILABLE_SERVICES`. The UI renders whatever `GET /masterfiles/available` returns, so adding or removing a service needs no UI change.
5. **Error messages are per call site.** 409, 410 and 429 messages apply only to the build POST. The same status codes from a poll mean something different (a poll has no bundle to be missing), so they fall through to the `ApiError` message.
6. **Filename `<slug>-<first 8 chars of job id>-<date>.xlsx`**, where the date is the job's `finished_at`, falling back to `created_at`. The deliverable record has no filename field to use instead.

## 4. Bugs found and fixed

**The masterfile menu on native crawl rows sent the native crawl id to a route that refuses it.** The menu called `POST /jobs/{id}/masterfile/{slug}` with a native crawl job's id. In `src/api/deliverables_routes.py`, when `state.store.get(job_id)` finds a record, the route org-scopes it and then calls `_reject_engine_job(job_id)` (around line 716; the lead confirmed this in the code). The route accepts only a Screaming Frog worker job with an uploaded bundle. Its other outcomes: 409 no bundle, 410 bundle expired, 403 or 404 for another organization's job, 429 when busy.

So the menu was broken from the moment the backend began rejecting engine ids, and the UI was never updated to match. It was never caught because the old UI tests mocked the adapter: they asserted that the component called `buildMasterfile` with a job id and polled, and had no way to know the real route refuses that kind of id. A contract between two layers was verified on each side against a fake of the other.

Fix: the flow now starts from a worker-dispatch row and sends `WorkerJobView.id`. The panel test asserts that id, not a native one. That assertion is against a mocked adapter too, so it holds the UI to the contract but does not prove the backend accepts it end to end (see §6).

No other bug was found in code. No failing test turned out to be wrong.

## 5. Corrections

- **README.md** at the masterfile route block said "The id may be an engine crawl job or an ADR 0015 worker job; a native crawl is refused 409". An engine crawl job and a native crawl are the same thing, so the sentence contradicted itself. It now says the id must be a worker job with an uploaded bundle. The route's own behaviour (engine record found, then refused) was already correct in the code and in the README's status-row list of `409` causes.
- **README.md and docs/ARCHITECTURE.md** said no UI consumed the masterfile routes ("No UI calls it", "Any UI for masterfiles ... nothing consumes either"). That is now false. The ARCHITECTURE row was removed with a note, following the convention already used for removed rows there; the README status row now describes the popover.
- Build-log 0105 and 0107 described the masterfile route and services. Nothing in them said the UI menu existed or worked, so they need no correction on this point. Their corrections about services rendering empty workbooks stand, and this cycle does not change them.

## 6. Explicitly not done

1. **Not verified end to end against a real dispatched bundle.** No live build or download was performed in a browser. Every test in this cycle mocks the adapter. A worker job with a real uploaded bundle, a click, a poll and a saved `.xlsx` has not been observed.
2. **If `listAvailableMasterfiles` fails, the control is silently hidden.** The same behaviour as the old menu. There is no error and no retry, so a failed service-list call and "this adapter cannot build" look identical to the user.
3. **The masterfile workbook contents are unchanged by this cycle.** Per build-log 0107 §5 many services render empty or partial workbooks against a real Screaming Frog export. A user can now click all the way to a download and receive one of those. The concurrent backend "RAE parity" work may change the contents; it is not documented here, and this entry should not be read as saying it landed.
4. **No "generate all 21" bulk action.** One workbook per click.
5. **No mutation check** on the new assertions.
6. **Python gate not run**, because no Python changed.
7. **Naming.** "Phase 2 Masterfile Download UI" and the "21-button grid" are the user's plan wording. No document in `docs/` defines either. "RAE" is the older Rankuno reference app, as used in build-logs 0104 and 0105. The grid has one button per service the server lists; 21 is the current registry size, not a UI constant.
8. The CrawlJobsView URL-list xlsx (cycle 0102) is unrelated and was not touched.

## 7. Files changed

From `git show --stat 44e50fc`:

```
 rankuno-ui/src/adapters/adapterInterface.ts        |   4 +
 .../src/components/jobs/CrawlJobsView.test.tsx     |  61 ++-----
 rankuno-ui/src/components/jobs/CrawlJobsView.tsx   | 121 +------------
 .../screaming-frog/WorkerJobsPanel.test.tsx        | 193 +++++++++++++++++++-
 .../components/screaming-frog/WorkerJobsPanel.tsx  |  64 ++++++-
 .../components/screaming-frog/screaming-frog.css   |  21 +++
 .../screaming-frog/useMasterfileBuild.test.tsx     |  98 ++++++++++
 .../screaming-frog/useMasterfileBuild.ts           | 201 +++++++++++++++++++++
 8 files changed, 598 insertions(+), 165 deletions(-)
```

`CrawlJobsView.test.tsx`: its three masterfile tests were replaced by one asserting there is no Masterfiles item and no service-list call.

Docs in this entry's change: `README.md`, `docs/ARCHITECTURE.md`, `docs/build-log/README.md`, this file.

Worktree: created manually (`git worktree add -b masterfile-ui`) because the Agent isolation option refuses on this machine (the `c:\` versus `C:\` casing check), the same workaround as build-log 0114.

## 8. Follow-ups

- Build one masterfile from a real dispatched bundle in a browser and open the workbook. Until then §6.1 stands.
- Decide whether a failed service-list call should show a message (§6.2).
- When the backend workbook-content work lands, document it in its own entry and revisit the ARCHITECTURE row about unpopulated masterfiles.
- The masterfile "Planned, not yet implemented" row in `docs/ARCHITECTURE.md` about empty workbooks is unchanged and still true as of this commit.
