# Cycle 0137: A page fetched a level too late

- **Date**: 2026-10-06
- **Scope**: Bug fix. Resuming a crawl that had died re-downloaded the whole site. The async DOM
  crawl recorded a page as fetched only when its whole BFS level ended, while checkpoints were
  written after every page, so every mid-level checkpoint listed the current level as unfetched.
  Pages are now recorded as fetched the moment a successful HTML fetch lands.
- **Commit**: `c54f2a8` (fix) on top of `origin/main` `d8da2ea`. Branch `resume-fetched-set`.
  This entry is uncommitted at time of writing.
- **Quality gate**: builder's run GREEN (3,938 passed, 2 skipped, 93.21%; mypy 166 files). The
  lead's independent full gate was in progress when this entry was written; see §1.

**Numbering note**: the highest entry in this worktree, on `origin/main` and in the main checkout's
`docs/build-log/` is `0136`. No other worktree under `.claude/worktrees/` held a `0137` when this
was written. `0137` was used. The `local-launcher` session may write an entry concurrently and
should take `0138`.

## 0. Background

On 2026-10-05 a production crawl of groundsguys.com labelled "(resumed +7,238)" died at 2,011 pages
when the server restarted (build-log 0136 §0). Resuming it produced a job labelled
"(resumed +7,972)". That label excluded nothing the dead job had fetched: the new job set out to
fetch the whole site again.

The `investigator` agent found this while analysing a separate failure (a 502 on a poll, §6).

The chain, as confirmed by the lead:

| Piece | Behaviour |
| :--- | :--- |
| `_acrawl` (`async_discovery.py`) | Called `graph.store_html(url, html)` for each page only after `_gather_bounded` returned for the whole level (old line about 874) |
| `note()` in `_acrawl` | Offered a checkpoint after every page (about line 849) |
| `SiteGraph.unfetched_urls()` (`discovery.py:873`) | "Unfetched" means "no stored HTML" |
| Resume | Seeds every outstanding URL at depth 0, so a resumed crawl is one BFS level |
| `resume_job` (`server.py`) | Computes `already = discovered − unfetched` and the "+N" label from the checkpoint. Correct, but fed a wrong checkpoint |
| Serial path (`discovery.py:1397`) | Already stored HTML at fetch time. The two crawl paths disagreed |

So any checkpoint written inside a level recorded every page of that level as unfetched, fetched or
not. For a resumed crawl the whole run is that one level, so its checkpoint said nothing had been
fetched until the run finished. A crawl that died, which is the only kind anyone resumes, could
never be resumed without re-downloading everything it had already downloaded.

---

## 1. Gate results

LEAD GATE (run by the lead on commit c54f2a8 in this worktree, main venv, `import src` resolved to the worktree):

```
ruff format --check .          -> 607 files already formatted
ruff check .                   -> All checks passed!
mypy src                       -> Success: no issues found in 166 source files
export_ui_contract.py --check  -> UI contract is up to date.
pytest --cov=src               -> Required test coverage of 85.0% reached. Total coverage: 93.21%
                                  3938 passed, 2 skipped, 1 warning in 1621.20s (0:27:01)
```

The builder's full gate, on `c54f2a8` in this worktree, as reported by the builder. Not re-run by
the scribe:

```
ruff format --check .            607 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 166 source files
pytest --cov=src                 3938 passed, 2 skipped, 1 warning in 776.98s
                                 Total coverage: 93.21%
drift_check                      PASSED (232 markdown files)
export_ui_contract.py --check    UI contract is up to date
```

Fail-before, run by the lead: with `origin/main`'s `async_discovery.py` restored and the new tests
present, all 5 new tests failed. The builder's assertion text:

```
assert 'resumed +4' in 'https://e.com/ (resumed +7)'
fetched pages checkpointed as unfetched: frozenset({'/'})
fetched pages checkpointed as unfetched: frozenset({'/', '/a/'})
assert '/ok/' not in frozenset({'/broken/', '/data/', '/ok/'})
```

After the fix, the lead ran the resume, async discovery, memory budget and discovery suites: exit
0, 194 passed.

The scribe re-ran the new tests and the whole `TestResume` class in this worktree, main venv,
`import src` resolving to the worktree's `src/`:

```
python -m pytest tests/modules/seo/test_async_discovery_resume_checkpoint.py \
    "tests/api/test_server.py::TestResume" --no-cov -p no:warnings
15 passed in 24.46s
```

---

## 2. What landed

**`src/modules/seo/page_classifier/async_discovery.py`** (+11 / −5, now 941 lines).

- `_ahtml` calls `graph.store_html(url, result.body)` when a successful HTML fetch lands, right
  after the ADR 0031 memory charge. The docstring says why.
- The level loop in `_acrawl` no longer stores. It still reads the returned body to extract links.

There is still one definition of "fetched": stored HTML. `SiteGraph.unfetched_urls()` is
unchanged. The async path now agrees with the serial path, which stored at fetch time already.

Peak memory is unchanged. The graph holds the same string object the results list holds, so storing
it a level earlier adds no copy, and ADR 0031's charge was already taken at this point.

Thread safety: a crawl runs as one event loop on one worker thread. `store_html` and the
checkpoint's read of the graph are both synchronous on that loop, with no `await` between them, so
a checkpoint never sees a half-stored page.

**Tests**

| File | Tests |
| :--- | :--- |
| `tests/modules/seo/test_async_discovery_resume_checkpoint.py` (new, 149 lines) | 4: a checkpoint inside level 0 of a resumed crawl; one inside a level below the root; a fetch not yet made stays unfetched (the other half of the equality); errors and non-HTML responses stay unfetched |
| `tests/api/test_server.py` (+62) | `TestResume::test_a_crawl_that_died_mid_level_resumes_only_what_it_never_fetched`: end to end through `adiscover_site`, a real `CrawlCheckpointer` and `POST /jobs/{id}/resume`. 6 seeds, the checkpointer stops writing after the third page as if the process died, and the resume must say "resumed +4", exclude the root and the first two seeds, and seed the other four |

The end-to-end test uses a checkpoint written by a real crawl. The existing resume tests used
hand-written checkpoints, which is why they could not catch a crawl that writes the wrong one (§5.1).

---

## 3. Design decisions

**Store at fetch, not a second "fetched" set.** A separate set of fetched URLs maintained alongside
`_html` would have fixed the checkpoint too, but would give two definitions of "fetched" that could
drift apart. Moving the store to the point the serial path already uses keeps one.

**Errors and non-HTML 200s are not stored, so they stay unfetched and are retried on resume.** A
5xx or timeout is often transient and worth retrying. A non-HTML 200 is re-requested too; that is
the cost of the single definition. Media URLs are filtered before they enter the graph (build-log
0020), so this is rare.

---

## 4. Bugs found and fixed

### 4.1 A mid-level checkpoint recorded the whole level as unfetched

Described in §0. The fix is §2. Measured on production: groundsguys.com's resume of a job that died
at 2,011 pages offered "+7,972", larger than the dead job's own "+7,238".

### 4.2 Behaviour change: pages from an abandoned level are now kept

Side effect of the fix, recorded because it changes output. When a level is abandoned by
`CrawlStalledError` or an exception from `_gather_bounded`, the pages that completed in that level
were previously dropped, because the level loop that stored them never ran. They are now already
in the graph when the level is abandoned, so they are kept and classified. A stalled crawl's
`PARTIAL` result can therefore hold more pages than the same crawl would have produced before this
cycle. Their outbound links were not extracted, because link extraction still happens in the level
loop.

---

## 5. Corrections

### 5.1 Build-log 0032: resume excluded already-fetched pages only when the source crawl ended cleanly

[Build-log 0032](0032-resume-excludes-what-was-already-fetched.md) §3 says `resume_job` derives
the exclusion from the checkpoint as "everything discovered, minus what was still outstanding", and
the entry is titled "Resume skips already-fetched URLs instead of re-crawling the site". The
derivation was right; the checkpoint it read was wrong whenever the source crawl died mid-level,
which on the async path is any death that does not fall exactly on a level boundary. For a resumed crawl, which is one
level, it was wrong every time. The exclusion then held only pages from completed earlier levels,
and for a resume of a resume it held nothing. 0032's tests used hand-written checkpoints and its
§6 already said the fix had not been observed live. 0032 is left as written.

### 5.2 The second groundsguys job reached 2,011 pages, not 2,811

The investigator's first report said the resumed groundsguys.com job reached 2,811 pages, and the
user-facing summary at the time repeated it. It was 2,011.
[Build-log 0136](0136-a-crawl-that-stops-before-the-container-does.md) §0 published the wrong
figure ("stopped at 2,811 / 7,972"). 0136 is left as written. Its "/ 7,972" denominator is
correct: the user's screenshot of the job that died ("resumed +7,238") reads "2,011 / 7,972" — the
denominator is the size of the discovered graph, not the resume label. That the later resume's label
is also +7,972 is the bug in §4.1: its checkpoint listed every discovered URL as unfetched.

---

## 6. Explicitly not done

- **A resume of a resume can still re-fetch the grandparent's pages.** The child job is given the
  parent's fetched URLs as `exclude_urls`. It never fetches them, so it never stores their HTML, so
  if it rediscovers them they appear in the child's `unfetched` list, and resuming the child
  re-downloads them. This is a policy question, because resume jobs are separate and never merged
  (0032 §6). Owner: `bug-fixer` or `api-data-engineer`. It may explain part of the gap between
  "+7,238" and "+7,972". Not quantified.
- **The UI marks a job `FAILED` after one failed poll.** A single 502 on a poll is treated as the
  job having failed. This is how the investigator came to the resume bug. Not fixed; owner
  `ui-engineer`.
- **`_asitemaps` takes an `on_checkpoint` parameter it does not use.** Cosmetic, left alone.
- **No automatic resume after a restart.** Checkpoints still hold URLs only, not HTML, so a resume
  re-classifies nothing from the dead job and the two jobs are not merged.
- **Crawl memory, step 2 (ADR 0031)** is not addressed. A resumed crawl of a large site still
  refills memory the same way and can hit the budget again. Fixing the checkpoint means it now
  re-fetches only what is outstanding, which shrinks a resume but does not bound it.
- **No live resume observed.** The fix has not been exercised against a real interrupted production
  crawl.
- **The progress denominator of a resumed crawl** still counts everything discovered (0032 §6).
  Unchanged.

---

## 7. Files changed

From `git show --stat c54f2a8`:

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/async_discovery.py` | +11 / −5 (store in `_ahtml`, removed from the level loop, docstring) |
| `tests/modules/seo/test_async_discovery_resume_checkpoint.py` | new, 149 lines, 4 tests |
| `tests/api/test_server.py` | +62, 1 test |

This cycle (docs, uncommitted): this entry, the `docs/build-log/README.md` index row, `README.md`
(resume paragraph) and `docs/ARCHITECTURE.md` (`async_discovery.py` tree note).

`async_discovery.py` (941 lines) remains over the 400-line target.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| `bug-fixer` / `api-data-engineer` | Resume of a resume re-fetches the grandparent's pages (§6). Decide whether the child's checkpoint should carry its `exclude_urls` forward as fetched |
| `ui-engineer` | One failed poll (502) marks a job `FAILED` in the UI |
| lead / operator | Resume a real interrupted crawl and confirm the "+N" label equals the number of pages it fetches |
| next cycle | Crawl memory step 2 (ADR 0031) |
