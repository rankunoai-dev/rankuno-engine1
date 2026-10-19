# Cycle 0161: A green gate with the crawl unplugged

- **Date**: 2026-10-19
- **Scope**: The fix for the GA4 wiring defect recorded in cycle 0162 §4.3. The live crawl runner now passes the organisation's GA4 access store to `PageClassificationTool`. Closes ADR 0038's first Known gap. Two wording-only docstring and Settings fixes follow the 0162 review.
- **Commit**: uncommitted at time of writing. The code is commit `7ead8cd` (`fix(ga4): pass the org GA4 store to the live crawl (ADR 0038)`), on branch `ga4-account-and-crawl`, on top of `6d9d6f3`. The build-log, README, ARCHITECTURE and ADR 0038 edits in this cycle are not committed; the lead commits them.
- **Quality gate**: reported by the builder on the fix tree, not re-run by the scribe (the brief forbids the Python gate and npm for this step). Verbatim output in §1.

## 1. Gate results

Reported by the builder on the fix tree (`7ead8cd`). Pasted from the builder's report, not re-run by the scribe:

| Stage | Result | Run by |
| :--- | :--- | :--- |
| Targeted: GA4, GSC and server tests | 365 passed, 1 warning | builder |
| `ruff format` | 712 files | builder |
| `ruff check` | passed | builder |
| `mypy --strict` (src) | 189 source files | builder |
| `pytest` with coverage | coverage 93.75%, 4692 collected, exit 0 | builder |
| `scripts/drift_check.py` | PASSED, 261 files | builder |
| `scripts/export_ui_contract.py --check` | up to date | builder |
| UI `tsc --noEmit` | exit 0 | builder |
| Full UI vitest | 61 files, 823 tests passed | builder |

Notes on these figures:

- The `pytest` summary line is suppressed by `addopts = -q`. The builder reported exit 0 as the pass signal and did not print a pass count. The collected count is 4692. Cycle 0162 recorded 4689 passed and 2 skipped (4691 collected), so the one added test accounts for the difference.
- `ruff format` covered 712 files here against 710 in 0162. One new Python file (`tests/api/test_crawl_ga4_wiring.py`) accounts for one of the two. The second was not identified by the builder and was not investigated by the scribe.
- The UI figures match 0162 exactly, as the fix changed no UI file.

Targeted run by the lead, after the fix, on the same tree:

```
tests/api/test_crawl_ga4_wiring.py
tests/modules/seo/page_classifier/test_ga4_enrichment.py
exit 0
```

The regression test was also run by the lead on `6d9d6f3` and failed with `status 'unmapped'`. The builder reports that the same test passed after the fix. The scribe did not re-run either run.

Drift check, run by the scribe after this entry and the documentation edits in this cycle were written (§7):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 263 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
EXIT=0
```

The count is 263 with this entry present (intent-to-add, then unstaged). The builder's run reported 261. The difference is not explained by this cycle's documents, which add one file (this entry). It was not investigated.

## 2. What landed

- `src/api/server.py`, `_run_job`: the one `PageClassificationTool(...)` construction in `src/` now passes `ga4_access_store=state.ga4_access_store`. The argument sits beside `memory_account=account`. No other argument changed. The construction is the only one in the tree; the Screaming Frog, reparse and worker job-executor paths do not build the tool, and were checked by search, not by reading each path.
- `tests/api/test_crawl_ga4_wiring.py` (new, 161 lines, one test): drives the real crawl runner through `POST /jobs` with a mapped property. The HTTP transport is a `httpx.MockTransport` on the crawl fetcher. The Google client is a fake (`FakeGoogleClient`) and the store is in memory (`InMemoryGa4Store`). Nothing reaches the network. The test asserts that the job succeeds and that `result["ga4"]` has `status == "succeeded"`, `property_id` equal to the mapped property, `pages_matched >= 1` and an empty `reason`.
- `src/integrations/ga4_budget.py`: the module and class docstrings and the `try_spend` and `spent` docstrings now say crawl, not call. One crawl is one charge (§3.2). No behaviour change.
- `src/core/config.py`, `Settings.ga4_daily_calls_per_org`: the description now reads "Crawls per UTC day that one organisation may send to GA4, counted in-process (one crawl is one charge)". The field name `ga4_daily_calls_per_org` is unchanged, so no environment variable or contract changed.

## 3. Design decisions

1. **The fix is the one line, not a fallback in the tool.** `PageClassificationTool` defaults `ga4_access_store` to `None` and does not read `Settings`. The alternative was a fallback to `get_settings().ga4_access_store` inside the tool. That would have made a missing argument read as "use the server's store", which is what the caller should decide. The crawl runner already holds `state`, so it passes the store explicitly, the same way it passes `org_id`.
2. **The budget unit is the crawl.** `Ga4DailyBudget` counts one charge per crawl that reaches GA4, not per request or per page, because `run_ga4_enrichment` issues one host report per crawl (ADR 0038 decision 7). 0162 §3.6 gave this reason. The Settings description now matches it.
3. **No test was added for the budget or the breaker through the crawl runner.** The new test covers the store wiring only. Budget and breaker behaviour through the runner were not tested in this cycle.

## 4. Bugs found and fixed

### 4.1 The live crawl never received the GA4 store (found on review of 0162)

The crawl runner built `PageClassificationTool` without `ga4_access_store`. The tool held `None`. `run_ga4_enrichment` then reported `unmapped` with "not requested: GA4 is not configured on this server" for every crawl that named a property. Intake read the store from app state and passed, so a user could submit a GA4 crawl and receive a result that said the server had no GA4.

Effect on the code before this fix: no GA4 request was ever sent from a live crawl. The `Ga4ApiClient` path was reachable only from unit tests that called `run_ga4_enrichment` directly. See §4.3 for what changes now.

Root cause, in one line: an omitted constructor argument of `None` was indistinguishable from "GA4 is not configured", so the status text reported a server state that did not exist.

### 4.2 Process: the green gate could not see the defect, and the test that found it is the first end-to-end test

The 0162 gate was green (4689 passed, coverage 93.74%). Every GA4 test called `run_ga4_enrichment` or the store or the client directly. None drove the crawl runner. The defect was in the one line that joins them, so no test could fail on it.

Process lesson, recorded so that the next feature does not repeat it: **a feature's green gate must include at least one end-to-end test through the real entry point, not only unit tests of the handler.** For a crawl feature the entry point is `POST /jobs` into `_run_job`. A unit test of the handler proves the handler; it does not prove that the caller passes the handler what it needs. The regression test in this cycle is that test, and it failed on `6d9d6f3` with `status 'unmapped'` before the fix.

This is a process lesson, not a ruling. CLAUDE.md §2 is the lead's file and was not edited here.

### 4.3 The three documents still said "not wired" after the fix commit

`7ead8cd` changed `README.md` and `docs/ARCHITECTURE.md` by one or two lines each, and changed ADR 0038 by 26 lines. It did not remove the "not wired into the live crawl" wording from:

- the README GA4 row (`README.md`, the row beginning `core/ga4_access_store.py`), which still says "Implemented and tested in isolation, **not wired into the live crawl**";
- the ARCHITECTURE ADR 0038 index row (`docs/ARCHITECTURE.md`, the row beginning `| [0038]`), which still ends with "**Not wired into the live crawl**";
- ADR 0038's first Known gap ("The live crawl does not receive the GA4 store"), which still describes the defect as open.

These are corrected in this cycle (§7). Left in place, they would have described a fixed defect as open and would have been the first thing a reader found.

### 4.4 Stale wording in the GA4 budget (fixed in `7ead8cd`)

The docstrings in `src/integrations/ga4_budget.py` and `Settings.ga4_daily_calls_per_org` said "call" where the unit is one crawl. Corrected in `7ead8cd` (§2). This closes the follow-up in 0162 §4.5.

## 5. Corrections

Each correction is to 0162 (`docs/build-log/0162-ga4-separate-credential-per-org.md`). Nothing in 0162 is edited.

1. **0162 header, "Commit: uncommitted at time of writing".** Stale. The 0162 entry was committed in `7ead8cd`, together with the fix, as the commit message states ("Docs from docs-scribe for cycle 0162 committed with this fix"). The entry was correct when written and is stale now.
2. **0162 §4.3, "Status: open".** Closed by `7ead8cd` (§4.1 above).
3. **0162 §8, first follow-up, "Implementer (blocking)".** Done in `7ead8cd`. The second follow-up (wording of the Settings description and `ga4_budget.py`) is also done there. The third ("Lead: confirm the Step-7 gate after the wiring fix") is answered by §1 of this entry, with the builder's figures and the lead's targeted run.
4. **0162 §1 and the implementer's report, "4689 passed, coverage 93.74%".** Those figures were correct for `6d9d6f3`. They did not show the feature worked in a live crawl, and 0162 did not say so in §1. The 0162 index row says "Not wired", which is right. This entry records that the green gate for 0162 did not cover the live path (§4.2).
5. **The phrase "implemented and tested" for the GA4 feature.** Used in the README and in the lead's brief for 0162, and wrong for the live path until `7ead8cd`. The unit tests tested `run_ga4_enrichment`, not the crawl. Current README wording (§7) says "Implemented and tested in isolation".

## 6. Explicitly not done

1. **No live test against a real GA4 property.** The fix is proved only through the mocked transport and the fake Google client. Google's scope string, endpoint paths (`accountSummaries`, `runReport`), request body and response field names are still unverified (0162 §6.1, ADR 0038 Known gaps).
2. **The stale reason text in `REASON_OVER_BUDGET` is still in the code.** `src/modules/seo/page_classifier/ga4_enrichment.py`, line 73: `"skipped: this organisation has used its GA4 calls for today"`. The string is emitted when the daily budget refuses a crawl (line 205), so the word "calls" describes the unit the budget no longer uses. A search of `tests/`, `rankuno-ui/src/` and `scripts/` for the literal text and for the constant name found no pin, so changing it breaks no test. It was not changed here because this cycle is documentation plus a verified one-line fix, and a code change to a reason string needs its own gate run. Follow-up in §8.
3. **The governance step was not written out in full for this fix.** The brief said no new network path, no new credential read and no spend. That is true of the code this fix touches. It is not the whole picture: before `7ead8cd`, a live crawl that named a property never reached Google. After it, such a crawl reaches the GA4 Data and Admin APIs, spends one unit of the per-organisation daily budget (`ga4_daily_calls_per_org`, default 200, in process), and sends the stored refresh token to Google through the existing client. The `Ga4ApiClient` path and its credential read existed before this cycle. What is new is reachability from the live crawl. This was not reviewed against the Step 5 standard's eight questions in a separate document.
4. **No budget or breaker test through the runner.** The new test covers store wiring. The test fixture `fake_google` replaces `DAILY_BUDGET` with a fresh `Ga4DailyBudget`, so the test never reaches the process-wide budget. The breaker is not addressed by the fixture. Neither one's behaviour through `POST /jobs` is tested.
5. **The tool still silently accepts `ga4_access_store=None`.** `PageClassificationTool` defaults the argument to `None`, so an omitted argument reads as "GA4 not configured", as §4.1 showed. The wiring is fixed. The default is not. Making the argument required, or failing loudly when a property is requested and the store is `None`, is not done.
6. **Budget and breaker are in process.** Multi-worker deployment multiplies both by the worker count (CLAUDE.md §8, ADR 0038). Blocking for hosted multi-worker deployment, not for local.
7. **No Postgres run.** The store is covered by a recording fake and the offline migration render (0162 §6.3).
8. **No ADR.** The fix is a one-line wiring correction within ADR 0038's existing decision. It changes no ruling. The ADR's Known gap is closed in place (§7), not replaced by a new ADR.
9. **CLAUDE.md §8 has no GA4 entry.** The GA4 gaps (unverified Google contract, in-process budget and breaker, operator-run consent) are recorded in ADR 0038 and 0162 only. This cycle does not edit CLAUDE.md. The lead owns it.
10. **The tutor lesson (Step 8c) was not run.** The brief did not ask for it and the scribe cannot launch the tutor agent. It is for the lead to run on this entry.
11. **The `0159` index row is absent on this branch.** `origin/main` has the `0159` row (`docs/build-log/README.md`, line 187 on `origin/main`). The branch is cut from `bc35894` and does not contain it. The index row for `0161` is placed after `0160`, which is correct on this branch. The `0159` row arrives with the rebase on `origin/main`. This was not fixed here, because `0159` is another cycle's entry.

## 7. Files changed

This cycle (uncommitted):

- `docs/build-log/0161-a-green-gate-with-the-crawl-unplugged.md` (new, this entry).
- `docs/build-log/README.md`: index row for 0161, after the 0162 row.
- `README.md`: GA4 row. "Not wired into the live crawl" is replaced with "Wired into the live crawl (cycle 0161)". The unverified-against-Google sentence is kept.
- `docs/ARCHITECTURE.md`: ADR 0038 index row. The "Not wired" sentence is replaced with a statement that the store is passed to the live crawl (cycle 0161), and the unverified sentence is kept.
- `docs/adr/0038-ga4-access-is-a-separate-read-only-credential-per-org.md`: the first Known gap is moved to a "Closed" note with the cycle number. It is not deleted, so the defect remains visible under its own heading.

Fix, commit `7ead8cd` (9 files, 424 insertions, 21 deletions, from `git show --stat`): `README.md`, `docs/ARCHITECTURE.md`, `docs/adr/0038-…md`, `docs/build-log/0162-…md`, `docs/build-log/README.md`, `src/api/server.py`, `src/core/config.py`, `src/integrations/ga4_budget.py`, `tests/api/test_crawl_ga4_wiring.py`.

## 8. Follow-ups

- **Lead, before the next GA4 change**: decide whether `PageClassificationTool`'s `ga4_access_store` should be required, or should fail loudly when a property is requested and the store is `None` (§6.5).
- **Implementer, small**: replace `REASON_OVER_BUDGET` in `src/modules/seo/page_classifier/ga4_enrichment.py` with wording that names crawls, with its own gate run (§6.2).
- **Lead, Step 5**: write the eight-question audit for the live-crawl reachability of the GA4 path (§6.3).
- **Lead, Step 8c**: run the tutor on this entry.
- **Lead, Step 8**: consider a GA4 entry in CLAUDE.md §8 for the unverified Google contract and the in-process budget and breaker (§6.9).
- **Operator, before live use**: run one crawl against a real mapped property and check `result["ga4"]` by hand. The fix is proved only through a mock (§6.1).
- **Rebase**: this branch lacks the `0159` index row (§6.11).
