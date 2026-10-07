# Cycle 0141: A fetched flag that outlives the body

- **Date**: 2026-10-07
- **Scope**: Refactor, step 1 of the stream-and-release plan. `SiteGraph` gains a separate
  `_fetched: set[str]` so that "this URL was fetched" no longer depends on its HTML being held in
  `_html`. Behaviour is unchanged: `_html` is still populated and nothing is released yet. This step
  only removes the coupling that would have made releasing HTML break resume.
- **Commit**: none. Uncommitted at time of writing.
- **ADR**: none. No ruling changes in this step. ADR 0031 and CLAUDE.md section 8 still describe the
  memory budget as before; amending them is deferred (section 6).
- **Quality gate**: GREEN on the lead's clean rerun (section 1). The refactorer's first run was not.

## 0. Background

An investigation (read-only, preceded this cycle) established that `SiteGraph._html`
(`src/modules/seo/page_classifier/discovery.py`) is the sole per-page HTML retention in a crawl, at
roughly 1 to 2.2 MiB per page, and that it is freed only by loop-trap eviction. That is the cost
behind the memory budget of ADR 0031.

The user's hypothesis was to extract breadcrumb and JSON-LD at fetch time, release the HTML, and
keep the homepage. The investigation found it mostly right, with one miss that this cycle fixes.

`SiteGraph.unfetched_urls()` defined "fetched" as `node.normalized in self._html`. Checkpoints and
resume depend on that answer (`src/api/server.py` around lines 297 and 3681-3724; build-log 0137).
Had HTML been released first, every page would have looked unfetched and a resume would have
re-crawled the whole site. The old docstring called this a feature ("no separate flag is needed and
none is kept"). It was only true while the body was never dropped.

## 1. Gate results

The refactorer's first `verify.ps1 -Fix` run exited non-zero: 1 failed / 641 passed in the UI stage.
The failure was `ScreamingFrogView.test.tsx` "sends a list dispatch...", a 5000 ms timeout. It passed
when run alone, and the lead's clean rerun passed. No code change was made between the two runs. It
is a timing flake under full-suite load, not something this change touches (no UI file is in the
diff).

Lead's clean rerun, `powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1`: exit 0. Quoted
from `C:\Users\RankUno\AppData\Local\Temp\verify_full.txt`:

```
641 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 175 source files
PASSED: Type check
TOTAL                                                                      17201    970   3704    285    93%
Required test coverage of 85.0% reached. Total coverage: 93.40%
4242 passed, 2 skipped, 1 warning in 1218.06s (0:20:18)
PASSED: Tests
 Test Files  52 passed (52)
      Tests  682 passed (682)
PASSED: UI Component Tests
ALL GATES PASSED.
```

The refactorer separately reported ruff format 359 files clean, ruff check clean, mypy --strict 168
files clean and drift_check PASSED (237 md files). Those counts differ from the lead's run (641 and
175) because the file sets differ (the refactorer evidently ran a narrower path set); they are the
refactorer's, not re-run by the scribe. The drift_check result for this entry is in section 7.

## 2. What landed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/discovery.py` | `self._fetched: set[str]` holds `node.normalized`. Filled only in `store_html`. `unfetched_urls()` reads it. Loop-trap eviction does `self._fetched.discard(stale)` beside `self._html.pop(stale, None)`. `unfetched_urls` docstring rewritten. |
| `tests/modules/seo/test_discovery.py` | New class `TestUnfetchedMatchesStoredBodyDefinition`. |
| `tests/modules/seo/test_async_discovery.py` | Sync and async crawls of the same site return identical `unfetched_urls()`. |

Diff size: 3 files, 74 insertions, 6 deletions.

Why `_fetched` is filled in `store_html` and not in `record_fetch`: `record_fetch` also runs for 404s
and non-HTML responses, and the old definition counted those as unfetched (they never had a body
stored). Writing the flag in the same method as the body keeps the two definitions identical today.

Unchanged: `_html` is still populated; `store_html`, `html_for`, `to_page_evidence` and the
checkpoint shape keep their signatures and output. The set is not persisted, so nothing on disk
changes.

New tests, all asserting equivalence with the old `normalized in _html` definition:

- a 404 page is unfetched;
- a non-HTML 200 is unfetched;
- a sitemap-only URL is unfetched;
- a depth-capped URL is unfetched;
- a loop-trap-evicted URL is unfetched (the discard line).

## 3. Decisions taken

- A separate set rather than a flag on `DiscoveredNode`: the node is shared by the nav-tree and
  evidence code, and adding mutable fetch state there widens the boundary for no gain. The cost is
  one string reference per fetched page, shared with the dict key already held in `_nodes`.
- Not persisted. The checkpoint stores URLs only (CLAUDE.md section 8); the set is rebuilt by the
  crawl itself and `unfetched_urls()` is computed live.

## 4. Bugs found and fixed

None in code. One latent coupling in the design, not a bug today: `unfetched_urls()` was correct only
because HTML was never released. This cycle removes the coupling before the release lands, so no
wrong behaviour ever shipped. The old docstring's claim that a separate flag would be a second source
of truth was true as a warning, but became false as a reason not to have one once the body is to be
dropped. The new docstring says where the two are written and discarded.

## 5. Corrections

These correct claims in the brief that started this work, none previously published in a build-log
entry.

1. The user's hypothesis (extract at fetch, release HTML, keep the homepage) missed that
   `unfetched_urls()` and therefore checkpoints/resume (build-log 0137) read presence in `_html`.
   Releasing first would have made resume re-crawl everything.
2. The "2.2 MiB per page" figure is conditional. It applies only when a page contains at least one
   character outside Latin-1, which makes CPython store the string in 2 bytes per character (PEP 393).
   Pure Latin-1 pages are about 1 MiB per megabyte of HTML. The CLAUDE.md section 8 text ("~2 MiB per
   page on sites with ~1 MB HTML") is the wide-character case, not the floor. It is left unamended
   here (section 6).
3. `MemoryAccount` (`src/core/memory_budget.py`) has no `release()`. Any plan that frees HTML must
   first add one, or the account will keep counting freed pages and stop crawls early.
4. Popping the `_html` dict entry would not free the body in the async crawl: the per-level results
   list still holds each response body until the level ends. Release needs link extraction moved
   into `_ahtml` so the list holds parsed links, not bodies.

## 6. Explicitly not done

Each of these needs HITL review before it is built.

- Releasing HTML. `_html` is still populated, so no memory is saved by this cycle.
- Precomputing breadcrumb and JSON-LD at fetch. Which `PageEvidence` field carries them is a pending
  decision.
- `MemoryAccount.release()` and the mean-skew fix in the account.
- Amending ADR 0031 and CLAUDE.md section 8 memory-budget text, including the conditional 2.2 MiB
  figure.
- Moving link extraction into `_ahtml` so the level results list stops pinning bodies.
- Event-loop CPU cost of parsing 1 MB pages at fetch time, which precomputation would add. Not
  measured.
- Loop-trap eviction does not credit the account for the bytes it frees. An existing small leak,
  unchanged.
- Faceted and resume-excluded nodes have no dedicated new test. They never reach `store_html`, so
  they take the same never-stored path as the 404 and sitemap-only cases that are tested.
- `discovery.py` is about 1,650 lines against the 400-line target. A refactor was handed off, not
  done.

## 7. Documentation

`README.md` and `docs/ARCHITECTURE.md` needed no change: no module, tool, route or UI surface was
added. The index row was added to `docs/build-log/README.md`. drift_check is run as the last step of
this cycle; its output is in the scribe's report, not duplicated here.
