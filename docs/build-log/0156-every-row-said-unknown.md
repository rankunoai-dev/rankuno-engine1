# Cycle 0156: Every row said "Unknown"

- **Date**: 2026-10-13
- **Scope**: Bug fix with an additive stored-result/contract change (ADR 0002). A crawl now records each fetched page's final HTTP status, the first redirect status, and a fetch outcome, and the xlsx and PDF URL exports print them. Before this cycle the "HTTP Status" column said "Unknown" on every row.
- **Commit**: none. Nothing is committed; the working tree is dirty (§7).
- **Quality gate**: **RED.** `verify.ps1` exited non-zero: 10 failed, 4524 passed. All 10 failures are golden-snapshot tests and fail identically on clean HEAD (§1, §4). Do not read this entry as a green cycle.

## 1. Gate results

Figures below were reported by the implementer; the scribe did not re-run the full gate (it takes about 11 minutes). The only command the scribe ran is `drift_check.py`, at the end of this section.

| Stage | Result |
| :--- | :--- |
| ruff format | passed |
| ruff check | passed |
| mypy --strict | `Success: no issues found in 182 source files` |
| coverage | `Required test coverage of 85.0% reached. Total coverage: 93.74%` |
| pytest | `10 failed, 4524 passed, 2 skipped, 2 warnings in 645.95s (0:10:45)` |
| UI tests inside the gate | `PASSED: UI Component Tests`, 57 files / 783 tests |
| `npm run contract` (after the gate) | `UI contract is up to date.` |
| `npx tsc --noEmit` | clean |
| `npx vitest run` | 57 files / 783 passed |
| `npm run build` | built in 14.5s (pre-existing chunk-size warning) |

The 10 failures:

| File | Failures | Message |
| :--- | :--- | :--- |
| `tests/modules/seo/test_golden_extract_at_fetch.py` | 8 | `$.tool.pages[N].final_confidence_score: 0.8 != 0.8000000000000002`, and from page 29 onward `0.48` vs `0.5333` |
| `tests/modules/seo/test_fetch_time_extraction.py::TestClassificationWithoutBodies::test_matches_the_snapshot` | 2 | same |

The implementer stashed its changes and confirmed the same tests fail on clean HEAD, so this cycle did not cause them. The likely cause is a prior commit and is unproven (§4, §5).

Not re-run after the last two files were added (the contract test in `tests/test_ui_contract.py` and `rankuno-ui/src/test/factories.test.ts`): the full gate and the drift check run by the implementer. Both files pass when run alone. The `ScreamingFrogView` UI flake did not appear in this run.

Scribe's drift check, run after the README and ARCHITECTURE edits:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 254 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 2. What landed

### Why this cycle exists

The user downloaded the URL-list PDF and sent a screenshot: every row's HTTP Status read "Unknown". Two agents re-verified the cause in code independently. The status code was dropped at four points in a chain, and no one of them was a bug on its own:

| # | Where | What happened |
| :--- | :--- | :--- |
| 1 | `src/integrations/http_fetcher.py`, `FetchResult` | Carried `status_code` (the final response only) and `redirect_chain` (URLs only). |
| 2 | `http_fetcher.py`, `_fetch_chain` / `_afetch_chain` redirect loops (~630-635 / ~659-664) | Each hop's `response.status_code` was read to decide whether to follow and then discarded. |
| 3 | `discovery.py`, `SiteGraph.record_fetch` (~834; called by the sync path ~1807 and `async_discovery.py` ~488) | Read `result.status_code` once (~891), fed it to `indexability_of()`, and kept nothing. |
| 4 | `DiscoveredNode` had no field; `reports.py` `_extract_status_code` was a hard-coded `return None` | Every renderer printed "Unknown". |

The first hop's status (the 301 or 302) existed nowhere in the stack, so showing it needed a new field on `FetchResult`. The implementer stopped and asked; the user chose to carry it (option A).

### User decisions

- Show the **final** status, plus the **first redirect** code in a second column.
- Labels: "Not fetched", "No response", "Not recorded (older crawl)".
- Add a small per-node fetch-outcome marker.

### Per module

- `src/integrations/http_fetcher.py`: `FetchResult.redirect_statuses: tuple[int, ...] = ()`, parallel to `redirect_chain`, filled next to `chain.append` in both loops and passed through `_build_result`. `redirect_chain` keeps its type because `audit_export.py` (lines 195-196) and `cascading_pipeline.py` (line 318) read it. No SSRF or robots code was touched.
- `src/modules/seo/page_classifier/discovery.py`: `DiscoveredNode.http_status`, `first_redirect_status` and `fetch_outcome`, all defaulting to `None`. New `OUTCOME_NOT_FETCHED`, `_interned_status`, `page_outcome_for`, `_set_fetch_facts` and `_exception_outcome`. `record_fetch` writes the three fields. New `SiteGraph.record_attempt_failure`. `record_fetch_exception` gained `mark_node=False`; it is set `True` only at the two page-fetch sites, `_safe_fetch_html` in `discovery.py` and `_ahtml` in `async_discovery.py`. `to_page_evidence` stamps `fetch_outcome = node.fetch_outcome or OUTCOME_NOT_FETCHED`.
- `async_discovery.py`: the one-line `mark_node=True` change.
- `signal_parsers.py`: the three fields on `PageEvidence`.
- `schemas.py`: the same three on `FullPageIntelligenceProfile`, all optional, default `None`, with `ge`/`le` bounds on the codes, so stored results from before this cycle still validate.
- `cascading_pipeline.py`: three pass-through lines.
- New `src/modules/seo/page_classifier/fetch_status.py` (89 lines): the three labels, the legend text, `http_status_label()` and `first_redirect_label()`, shared by the xlsx and the PDF so the two cannot drift.
- `reports.py`: a First Redirect column on "All URLs", "By HTTP Status" and the PDF. The PDF now has 12 columns, widths `[150,66,66,62,48,42,56,40,52,34,88,70]` = 774pt, inside about 806pt usable on landscape A4. A legend footnote sits under the PDF table. The xlsx HTTP Status header carries a cell comment with the legend. No Notes sheet was added because `tests/api/test_server.py` pins the sheet names. "By HTTP Status" sorts numeric codes first, then Not fetched, No response, Not recorded. `_extract_status_code` returns `page.http_status`. "By Indexability" now puts real 4xx/5xx pages in Blocked rather than all in Unknown.
- UI: `rankuno-ui/src/types/schema.ts` regenerated (`npm run contract`); `src/test/factories.ts` updated; new `src/test/factories.test.ts`. No table in the UI renders this crawl's HTTP status, so only types and the factory changed.

### Tests added or changed

| File | Change |
| :--- | :--- |
| `tests/modules/seo/test_http_status_capture.py` (new, 327 lines) | 20 tests: capture per case in §3, sync/async parity, loop-evicted nodes never reaching the evidence, `indexability_of()` recomputed from the same inputs. |
| `tests/integrations/test_http_fetcher.py` | `TestRedirectStatuses`: 301 to 200, 302, multi-hop, none, async. |
| `tests/test_ui_contract.py` | Contract test for the three new fields. |
| `tests/modules/seo/page_classifier/test_reports.py`, `tests/api/test_server.py` | Old "Unknown" assertions replaced. |
| `tests/modules/seo/test_golden_extract_at_fetch.py` | The pinned projection now excludes the three new fields, as it already does for `jsonld_types`. The committed snapshot was **not** regenerated. |

With the new fields excluded, the golden output equals the committed snapshot byte for byte, checked outside pytest: zero differences other than `final_confidence_score`, the field build-log 0150's weight change affects.

## 3. Design decisions

Every case, as implemented:

| Situation | HTTP Status shown | First Redirect | Outcome |
| :--- | :--- | :--- | :--- |
| 200 | 200 | blank | ok |
| 404 | 404 | blank | not_found |
| 503 | 503 | blank | server_error |
| 301 then 200 | 200 | 301 | ok (record-only: the node is not moved, `final_url` unchanged) |
| 302 | the final code | 302 | per final code |
| 204, 304 | literal code | blank | per code |
| 200, non-HTML body | 200 | blank | not_html |
| timeout, transport error, SSRF-guard refusal | "No response" | blank | per exception |
| robots disallowed | "Not fetched" | blank | robots_disallowed |
| sitemap-only, CMS-only, faceted, depth-capped, resume-excluded | "Not fetched" | blank | not_fetched (stamped by `to_page_evidence`) |
| loop-evicted | gone with the node; a test proves it never reaches the evidence | | |
| refused by the 8,192-character URL ceiling | the node is never created | | |
| older stored result, imported or bundle job, checkpoint placeholder profile (`server._placeholder_profile`) | "Not recorded (older crawl)" | | |

Rules behind the table:

- **Retries happen only on exceptions, and only the exhausted failure is recorded.** A failure clears an earlier status; the last write wins.
- **Only GET results reach `record_fetch`**, so HEAD probes cannot overwrite a page's status.
- **Screaming Frog data is untouched.** It carries its own Status Code column.
- **`indexability_of()` is untouched**, and a test recomputes it from the same inputs.
- **Sync/async parity** is tested for 200, 301, 404, 503, `ConnectError`, robots refusal, SSRF guard and sitemap-only on both paths. The serial path's legacy single `transport_error` counter bucket is unchanged.
- **After a resume** (`POST /jobs/{id}/resume`, build-log 0032) the new job is unmerged, so status exists only for re-fetched URLs and the rest read "Not fetched". The checkpoint shape is unchanged.

Why a separate `redirect_statuses` tuple and not a change to `redirect_chain`: two existing consumers read `redirect_chain` as URLs. A parallel tuple adds the data without a signature change for either.

### Memory

Measured by the implementer with `tracemalloc`, 20,000 nodes, Python 3.11. No ADR 0035 measurement harness exists in the repo; the implementer wrote its own and deleted it, so the figures cannot be re-run from the tree.

| Version | Cost per node |
| :--- | :--- |
| Naive fields on the model | about +2.0 KB: node `__dict__` 464 to 832 bytes (24 fields no longer fit the 32-slot dict table) and `model_fields_set` 728 to 2,264 bytes (a set nothing on a node reads) |
| As shipped (`_set_fetch_facts` writes the instance dict directly, statuses interned) | **+368 B/node**; retained bytes per node after `record_fetch` went from 1,902 to 2,270 |

`DiscoveredNode` is a pydantic model, not `__slots__`, so the dict growth cannot be avoided. 368 B is about 1.4% of the measured 25 KiB/page (0.0247 MiB, ADR 0035) and about 1.1% of the 32 KiB flat per-page charge, so the flat charge in ADR 0031/0035 needs no adjustment and `retained_page_bytes` needs no change. At 500,000 nodes the addition is 368 B x 500,000 = 184,000,000 B, about 184 MB (computed, 184.0 MB decimal). That is the same figure ADR 0001's per-node note carries; this is the first cycle to measure it rather than assume it. **Not measured**: the `PageEvidence` and profile objects (a `PageEvidence` tuple measured 3,184 B/node before and after, which says nothing about the new fields on the profile).

## 4. Bugs found and fixed

1. **The status code was dropped at four points** (§2). Fixed by carrying it through all four. This is a loss-in-transit bug with no single faulty line, which is why two earlier cycles could describe it correctly and still not fix it.
2. **A naive implementation cost about +2.0 KB/node**, ten times the final figure, because 24 fields overflowed the instance dict's key-sharing table and pydantic's `model_fields_set` grew with them. Found by measuring, fixed in `_set_fetch_facts` (§3).
3. **Design rule to avoid a stale status:** a failure clears an earlier status and the last write wins, so a page that returned 200 and then failed on a later attempt does not keep printing 200. This is a rule built in, not a bug that shipped; the scribe did not confirm which test pins it.
4. **Spec flaw, not code: the first redirect code did not exist in the stack.** The brief assumed the 301 was recoverable from `FetchResult`; it was not (§2). Caught because the implementer stopped to ask before inventing it.
5. **Pre-existing, not caused here, not fixed: 10 golden-snapshot failures.** See §5 and §6.

## 5. Corrections

- **Build-logs 0102, 0123 and 0124 reported "no per-page status reaches the profile" accurately, and did not fix it.** Superseded, not wrong. Those three entries were true on the day they were written and are left as they are. From this cycle on, `FullPageIntelligenceProfile.http_status`, `first_redirect_status` and `fetch_outcome` exist and are filled for new crawls. The README paragraph and the `reports.py` entry in ARCHITECTURE that repeated the old sentence were edited in this change (§7), because those are current-state documents.
- **The `audit_export.py` module docstring** ("status codes do not survive onto the profile") is now outdated. It was **not** edited here; it describes a module this cycle did not change, and the module still derives 4xx/5xx by parsing the prose in `indexability_reason` (`STATUS_RE`, §6).
- **Build-log 0150's gate claim is unverified for the golden tests.** Entry 0150 (commit `5176418`, "fix(signal-weights): increase schema confidence to settle orphan blog classification") cites "134 tests" and states that weight changes were "regression-tested to prevent silent reclassification". It never mentions the golden tests. The two golden snapshots that pin `final_confidence_score` (`tests/fixtures/golden/extract_at_fetch_500.json.gz` and the `test_fetch_time_extraction` snapshot, both committed at `e81e4a1`) now fail with `0.8 != 0.8000000000000002` and `0.48` vs `0.5333`. **This is a hypothesis, not a finding**: no revert test has been run, so it is not proven that 0150 caused it. What is proven is that the failures reproduce on clean HEAD with this cycle's changes stashed. Entry 0150 was not edited.
- **The "HTTP Status" column was described as "a genuine absence, not a code"** (README, from build-log 0123). That was true of the data then; it is no longer true of crawls run after this change. It stays true of older stored results, which read "Not recorded (older crawl)".

## 6. Explicitly not done

- **The golden snapshots were not regenerated.** Deciding whether the code or the snapshot is right is a user decision: regenerating would silently accept build-log 0150's weight change as intended. Until it is decided, `verify.ps1` stays red.
- **`audit_export.py` still parses prose.** It derives 4xx/5xx from `indexability_reason` via `STATUS_RE`. Switching it to read `http_status` would change audit counts, which falls under ADR 0011 and is a separate decision.
- **Not touched, and why**: `screaming_frog_reconciler.py`, `masterfile_response_codes.py`, `masterfile_enrichment.py` and `masterfile_base.py` use Screaming Frog's own Status Code data; `server.py` and `job_import_routes` only mention FastAPI status codes; `rankuno-ui` renders no table of this crawl's HTTP status.
- **PDF layout was checked by column-width arithmetic and by decoding the bytes, not by eye.** "Not recorded (older crawl)" is expected to wrap to about three lines in the 62pt cell. Nobody has looked at a rendered page.
- **Nothing was run against a live site or on Railway.**
- **Checkpoint-recovered partial results say "Not recorded (older crawl)"**, because `server._placeholder_profile` carries no status. The wording is slightly off for that case: the crawl is not older, it was interrupted.
- **After a resume, only re-fetched URLs carry a status** (§3).
- **Memory for `PageEvidence` and profile objects was not measured** (§3).
- **No ADR amendment was written.** The new fields are additive and optional on the Phase 1 contract ADR 0002 names (`FullPageIntelligenceProfile`), and old stored results validate unchanged. Whether that warrants an amendment to ADR 0002 is the user's call; it is flagged here and not decided.

## 7. Files changed

Source: `src/integrations/http_fetcher.py`, `src/modules/seo/page_classifier/{discovery,async_discovery,signal_parsers,schemas,cascading_pipeline,reports}.py`, new `src/modules/seo/page_classifier/fetch_status.py`.

Tests: `tests/integrations/test_http_fetcher.py`, `tests/modules/seo/page_classifier/test_reports.py`, `tests/modules/seo/test_golden_extract_at_fetch.py`, `tests/api/test_server.py`, `tests/test_ui_contract.py`, new `tests/modules/seo/test_http_status_capture.py`.

UI: `rankuno-ui/src/types/schema.ts`, `rankuno-ui/src/test/factories.ts`, new `rankuno-ui/src/test/factories.test.ts`.

Docs: this entry, `docs/build-log/README.md` (index row), `README.md` (module table and the URL-export paragraph), `docs/ARCHITECTURE.md` (`http_fetcher.py`, `reports.py`, and new `fetch_status.py`).

`git diff --stat` for tracked files: 14 files, 296 insertions, 67 deletions; plus 3 new untracked files. The untracked `.agents/` and `.codex/` directories are unrelated to this cycle.

## 8. Follow-ups

- **bug-fixer / test-engineer**: decide whether the golden snapshots or the 0150 weight change is right; run a revert of `5176418` to prove or refute the hypothesis in §5; regenerate the snapshots only if the user accepts the new weights. This turns the gate green.
- **feature-builder (optional)**: make `audit_export.py` read `http_status`, after an ADR 0011 decision on the audit-count change.
- **User**: decide whether ADR 0002 needs an amendment for the three additive fields.
- **User**: look at one rendered PDF page, and re-wording "Not recorded (older crawl)" for checkpoint-recovered results if it matters.
