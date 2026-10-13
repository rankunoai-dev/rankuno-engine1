# Cycle 0157: A guide for the bot that answers users

- **Date**: 2026-10-13
- **Scope**: Documentation only. A new user guide, `docs/guides/rankuno-user-guide-for-assistant.md`, written to be loaded as context by an LLM support bot that helps non-technical users. No code, setting or test changed.
- **Commit**: on branch `assistant-user-guide` (from `origin/main` `1afe7cb`); hash in the commit that adds this entry. Not pushed.
- **Quality gate**: `verify.ps1` not run, because no Python, TypeScript or test file changed. `drift_check.py`: `PASSED: no drift detected across 259 markdown files.` (§1).

## 1. Gate results

Nothing executable changed, so the full gate was not run. The last full gate on this base is cycle 0156's: `10 failed, 4524 passed, 2 skipped`, 93.74%, all 10 failures pre-existing golden-snapshot tests. This cycle neither fixes nor affects them.

Drift check, run after the guide, the README line, this entry and its index row were written (new files marked with `git add -N` first):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 259 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 2. What landed

| File | Change |
| :--- | :--- |
| `docs/guides/rankuno-user-guide-for-assistant.md` (new, 1,230 lines, 16 `##` sections, 89 `###` subsections) | The guide. |
| `README.md` | One line under "Master Specifications & Directives" pointing at the guide. |
| `docs/build-log/README.md` | Index row for this entry. |

### Why this cycle exists

The user asked for "a very detailed doc" that, given to a bot as context, lets the bot guide a new, non-technical user through the tool. The brief required every UI string to be quoted from source, every limit and default given, and anything unconfirmed marked "[unverified]".

### How it was built

Read along one chain only: `NavigationRail.tsx` to each view component, to its `rankuno-ui/src/lib` helper, to the `src/api` route it calls, to `schemas.py` and `config.py` for enums and limits. Every label, status, tooltip, error and limit in the guide was read from that chain at `1afe7cb`. The guide covers sections 0 to 15 as the brief listed them: bot role and clarifying questions, product overview, sign-in, a screen-by-screen tour, crawl lifecycle and statuses, GSC, Screaming Frog, reading results, the local site and import, limits, glossary (all 14 `PrimaryPageType` members), workflows, troubleshooting by symptom, escalation, a NEVER list, and 35 FAQ entries.

No client site names, operator names, credentials or job data appear in the guide. Examples use `example.com`.

## 3. Design decisions

- **One file, organised for retrieval.** Each screen, status and message is under its own heading or table row, so a bot retrieving a chunk gets a self-contained answer.
- **Exact strings in quotes; technical names in code style.** A user can search their screen for a quoted label; an admin can search the repo for a code-style name.
- **"How to answer" notes** sit where users are most likely to be confused: the Launch-only rail, the per-org crawl count against a server-wide cap, "Default (.env.local)" not being the account the user added, the 500-page default ceiling, the crawl form's stale sentence.
- **Known gaps stated as gaps.** The guide says there is no automatic resume, a resume is not merged, the memory budget is not an out-of-memory guarantee, accuracy is unverified, and Layers 2 and 3 are not implemented, consistent with CLAUDE.md §8.
- **Local site and import marked as technical tasks**, so the bot explains them rather than walking a non-technical user through terminal commands.
- **No ADR.** A user guide records no architectural decision.

## 4. Bugs found and fixed

None fixed: this cycle changed no code. Found while reading, and recorded in the guide so the bot answers correctly, are these defects in shipped text or behaviour:

1. **Crawls started from the dashboard cannot be deleted from it.** `LiveCrawlModal.tsx` sends `deletion_password: null` (from `DEFAULT_CRAWL_REQUEST`, `adapterInterface.ts:1109`) and has no field for it. `server.py` `delete_job` (~3725-3732) answers `403 "deletion requires a password set at job creation"` for such a job, yet `CrawlJobsView.tsx` shows the bin icon on every finished row whenever the adapter supports deletion. Build-log 0146 §6 already lists the missing form field as not done; what was not said there is that the button is still offered on rows it can never delete. `JobView.has_delete_password` exists and is unused by the UI.
2. **Stale sentence on the crawl form.** `LiveCrawlModal.tsx` ends with "The engine reports no incremental page count, so the header shows an indeterminate indicator rather than a percentage while the crawl runs." The header pill (`HeaderBar.tsx`, `BackgroundPill`) and `CrawlJobsView.tsx` show a percentage and "<fetched> / <found>".
3. **Stale sentence in the Cross-check panel.** `ReconcilePanel.tsx` says the file "is read in your browser and posted to the local engine on this machine". On the cloud site it goes to the cloud server.
4. **One description for every PARTIAL.** `httpAdapter.ts` `describeStatus` returns "Crawl stopped at its page ceiling — results are incomplete." for every `partial` job, including memory-budget and stalled stops. The Crawl jobs status detail (`statusDetail` in `CrawlJobsView.tsx`) distinguishes them correctly. Where `describeStatus`'s message is displayed was not traced.
5. **A URL-prefix property for the apex is accepted for a `www.` crawl.** `gsc_property_validator.py` `_is_subdomain` treats `https://example.com/` as covering `https://www.example.com/` ("Subdomain match"), but a Search Console URL-prefix property reports only its own host, so this passes validation and returns few or zero matches. The guide lists it among the "0 matched" causes.
6. **Quota and other GSC errors read as "0 matched".** `gsc_client.py` `fetch_analytics` (~301-330) returns an empty response for `GscQuotaExceededError`, `GscApiDeprecatedError` and any other exception, so enrichment ends `succeeded` with 0 matched rather than `failed`. Cycle 0153 fixed this for 403 and 404 only.
7. **Stale code comments, not user-visible.** `HeaderBar.tsx` says "the engine takes three at once"; `FacetRouter.__init__` says its default is 3. The running default is `Settings.max_concurrent_crawls = 5`, which is what the server passes in.

## 5. Corrections

- **The brief's status list.** The brief asked for "cancelled" as a crawl outcome alongside "stalled/aborted". There is no cancelled status: "Kill" marks the job `FAILED` with "cancelled by operator — the crawl thread may still be running until it finishes or the server restarts" (`server.py` `cancel_job`). The guide describes it that way.
- **The brief's import limits.** The brief gave "32 MB compressed / 128 MB unpacked". The settings are `32 * 1024 * 1024` and `128 * 1024 * 1024` bytes, so MiB. The Search Console export limit (32,000,000 bytes) and the cross-check limit (80,000,000 bytes) in the UI are decimal MB. The guide uses each unit as the code does.
- **The activity indicator label.** The brief wrote "Rankuno n/5 | Screaming Frog n active". The visible text uses a "|" separator; the accessible label uses "·". The guide quotes the visible form.
- No earlier build-log entry was found to be false.

## 6. Explicitly not done

- **None of the §4 defects were fixed.** This was a documentation brief with "do not change code". Each is a candidate for its own cycle (§8).
- **No live verification.** No crawl, GSC request, Screaming Frog dispatch, import or deletion was run. Every statement comes from reading source at `1afe7cb`. Items the guide marks "[unverified]": the 8 GB container figure, whether a cloud restart signs users out, the cause of a 502, the 10,000-row GSC request not being paged in a live run, and whether a killed crawl later reappears as PARTIAL (§8, RISK).
- **No ARCHITECTURE.md change.** No module, route or UI surface was added.
- **No tutor lesson started here.** Step 8c is the lead's to run; this agent's brief ends at the commit.
- **Not pushed**, per the brief.

## 7. Files changed

| File | Lines |
| :--- | :--- |
| `docs/guides/rankuno-user-guide-for-assistant.md` | new, 1,230 |
| `docs/build-log/0157-a-guide-for-the-bot-that-answers-users.md` | new |
| `docs/build-log/README.md` | +1 index row |
| `README.md` | +1 line |

## 8. Follow-ups

HANDOFFS, in `docs/standards/AGENT_HANDOFF_PROTOCOL.md` form, abbreviated:

1. **UI / NON-BLOCKING, target `ui-engineer`**: hide or disable the delete button when `has_delete_password` is false, or add a deletion-password field to "Start a live crawl". Evidence: §4.1. Confidence HIGH (read, not reproduced).
2. **UI / OPTIONAL, target `ui-engineer`**: remove the stale sentences in `LiveCrawlModal.tsx` and `ReconcilePanel.tsx`; make `describeStatus` distinguish PARTIAL reasons. Evidence: §4.2-4.4.
3. **BUG / RISK, target `investigator`**: after "Kill", the crawl thread still finishes and calls `store.finish(...)`. `DiskJobStore.finish` and `_transition` (`state_store.py` ~637-669) do not check that the job is already terminal, so a killed job may be rewritten from `FAILED` to `PARTIAL` with `error = "cancelled by operator"`, contradicting "its result is thrown away". Not reproduced; the Postgres store was not read. Confidence MEDIUM.
4. **BUG / NON-BLOCKING, target `bug-fixer`**: GSC quota and other errors degrade to `succeeded` with 0 matched (§4.6); URL-prefix apex property accepted for a `www.` crawl (§4.5).
5. **DOCS / OPTIONAL**: when the UI changes, the guide goes stale. Its header tells the bot to trust the user's screen over the document; a future cycle touching a quoted string should update the guide in the same change.
