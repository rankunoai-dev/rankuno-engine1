# Cycle 0136: A crawl that stops before the container does

- **Date**: 2026-10-05
- **Scope**: Crawl memory budget, step 1 (safety net). A process-wide budget on retained DOM-crawl
  HTML (`src/core/memory_budget.py`, `CRAWL_MEMORY_BUDGET_MIB`, default 3072 MiB). When it is
  reached, the largest crawl over its fair share stops at a safe point, classifies what it has and
  ends `PARTIAL` with "memory budget reached", instead of the container being OOM-killed and every
  running job coming back `FAILED`
  ([ADR 0031](../adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md)). Step 2,
  which stops retaining the HTML, is a separate later cycle.
- **Commit**: `6c16e03` (feature) on top of `origin/main` `92ec406`. Branch `crawl-memory-budget`.
  This entry is uncommitted at time of writing.
- **Quality gate**: builder's run GREEN (3,933 passed, 2 skipped, 93.19%; mypy 166 files; vitest
  39 passed). The lead's independent full-gate run was in progress when this entry was written;
  see §1.

**Numbering note**: the highest entry on disk is `0135` in this worktree, on `origin/main` (fetched
2026-10-05) and in the main checkout's `docs/build-log/`. `0136` was free in all three.

## 0. Background

On 2026-10-05, between about 07:29 and 08:32 UTC, three production native crawls ended `FAILED`
with "interrupted by a server restart — partial results were saved and can be viewed":

| Crawl | State when it died |
| :--- | :--- |
| groundsguys.com, resumed (+7,238 URLs to fetch) | stopped at 2,811 / 7,972 |
| mrrooter.com, resumed (+34,296 URLs to fetch) | interrupted |
| mrrooter.com, plain crawl | interrupted |

The browser console showed a 502 on `/api/v1/crawl-activity` and a 409 on
`/api/v1/jobs/<id>/result`.

The `investigator` agent found:

- No push to `origin/main` since 2026-10-02 15:29 +0530, so this was not a push-triggered
  redeploy.
- The Railway CLI was not available, so there are no Railway logs or metrics. An OOM kill is a
  strong inference (MEDIUM-HIGH confidence). It is **not confirmed**.
- The message is written by `recover_orphans` (`src/core/postgres_store.py:811-857`), which marks
  every `QUEUED`/`RUNNING` job `FAILED` at startup, with the checkpoint wording when one exists. The
  message records that the process restarted. It does not record why.
- `SiteGraph._html` keeps every fetched page's HTML until the job ends.
- The lead measured both homepages: mrrooter.com 1,095,122 bytes, groundsguys.com 1,069,682 bytes.
- The 409 is `/result` refusing a job that has no result (`FAILED`). The partial data is behind
  `/checkpoint`. It is console noise, but the UI's `selectJob` should not request `/result` for a
  `FAILED` job (handed off, §8).
- Resume exists (`POST /jobs/{id}/resume`, [build-log 0032](0032-resume-excludes-what-was-already-fetched.md)),
  but it starts a new job that refills memory the same way. Two of the three dead crawls were
  resumes.

User decisions, in order:

| Question | Decision |
| :--- | :--- |
| Scope | "Safety net now, then the real fix" |
| `MAX_CONCURRENT_CRAWLS` | Keep at 5 |
| Container memory | 8 GB, the user's statement of the Railway plan. Not confirmed from Railway metrics |
| Victim policy | Fair share first, then largest (approved) |
| Real-site measurement crawl | Skipped; synthetic measurement only |
| UI | `CrawlJobsView` `statusDetail` change allowed |

The pre-implementation security audit returned **PASS WITH CONDITIONS**, C1–C9:

| # | Condition | Where it is met |
| :--- | :--- | :--- |
| C1 | Budget is Settings-only | `Settings.crawl_memory_budget_mib`; a request naming a budget field is refused 422 (`extra="forbid"`) |
| C2 | Fair-share victim policy, so one org cannot stop another's under-share crawl | `MemoryBudget` victim selection |
| C3 | Charge at fetch completion, not at `store_html` | `_ahtml` charges `sys.getsizeof(body)` |
| C4 | Distinct reason; never the cancel or `mark_failed` path | `MEMORY_BUDGET_REASON`, through the existing `PARTIAL` mapping |
| C5 | Registry lifetime tied to the worker thread, closed in `finally` | `_run_job` |
| C6 | No stop before the first page | accounts with 0 pages are never victims |
| C7 | Numberless tenant-visible message | fixed string; numbers logged server-side only |
| C8 | No per-page RSS read | counting only |
| C9 | Default derived from measurement | §3 |

---

## 1. Gate results

LEAD GATE (run by the lead on commit 6c16e03 in this worktree, main venv, `import src` resolved to the worktree):

```
ruff format --check .          -> 605 files already formatted
ruff check .                   -> All checks passed!
mypy src                       -> Success: no issues found in 166 source files
export_ui_contract.py --check  -> UI contract is up to date.
pytest --cov=src               -> Required test coverage of 85.0% reached. Total coverage: 93.19%
                                  3933 passed, 2 skipped, 1 warning in 498.49s (0:08:18)
rankuno-ui: npx tsc --noEmit   -> exit 0
rankuno-ui: npx vitest run src/components/jobs/CrawlJobsView.test.tsx src/lib/dashboardNotices.test.ts src/components/report
                               -> Test Files 3 passed (3), Tests 39 passed (39)
```

The builder's full gate, on `6c16e03` in this worktree, as reported by the builder. Not re-run by
the scribe:

```
ruff format --check .            605 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 166 source files
pytest --cov=src                 3933 passed, 2 skipped, 1 warning in 477.05s
                                 Total coverage: 93.19%
drift_check                      PASSED (230 markdown files)
export_ui_contract.py --check    UI contract is up to date
tsc                              exit 0
vitest                           Test Files  3 passed
                                 Tests  39 passed
```

Fail-before, run by the lead: with `origin/main`'s `async_discovery.py`, `tool.py` and `server.py`
restored and the new `src/core/memory_budget.py` present, 5 tests in
`tests/api/test_server_memory_budget.py` and 6 in
`tests/modules/seo/test_async_discovery_memory_budget.py` failed. Among them,
`test_a_small_budget_job_ends_partial_with_the_memory_reason_not_failed`, which the builder saw fail
as:

```
assert <JobStatus.SUCCEEDED: 'succeeded'> is <JobStatus.PARTIAL: 'partial'>
```

The two files hold 6 and 7 test functions. Which one in each passed on the old code was not
recorded; `test_a_budget_field_in_the_crawl_payload_is_refused` and `test_no_account_means_no_budget`
would be expected to, since neither depends on the new wiring. That is an inference, not a
measurement.

On the new code, the lead ran the memory-budget and config tests: `82 passed, 1 warning in 6.46s`.
The scribe re-ran the same four files in this worktree with the main venv (`import src` resolves to
the worktree's `src/`):

```
python -m pytest tests/core/test_memory_budget.py tests/api/test_server_memory_budget.py \
    tests/modules/seo/test_async_discovery_memory_budget.py tests/core/test_config.py --no-cov
82 passed, 1 warning in 5.59s
```

---

## 2. What landed

**`src/core/memory_budget.py`** (new, 271 lines). `MemoryBudget` and `MemoryAccount`, guarded by
one `threading.Lock`. The fair share is `budget // max_concurrent_jobs`. A crawl's projected bytes
are its charged bytes plus its concurrency ceiling times its mean page size, which covers bodies
still in flight. When the projected total reaches the budget, the victim is the account with the
largest projection among those over their share, with the newest chosen on a tie. Accounts with 0
pages are never victims. Choosing a victim sets a flag and does nothing else: the module never
touches a job's status, slot or cancel flag. It sits in `core` because it is domain-agnostic; it
counts bytes it is handed and knows nothing about crawling.

**`src/modules/seo/page_classifier/async_discovery.py`** (+71 / −3, now 935 lines).
- `_ahtml` charges `sys.getsizeof(body)` the moment a page lands. Charging at `store_html` would
  miss a whole level, because a BFS level keeps every body in its results list before any is stored
  (condition C3). `getsizeof` is O(1) and reports the PEP 393 width.
- `_gather_bounded` checks the stop flag before **and after** `governor.acquire()`. The second check
  is the bug fix in §4.1.
- `_acrawl` checks the flag at each level boundary, after the `cancel_event` check, so "cancelled by
  operator" wins any race. If the stop lands during the last level, `stopped_reason` is set after
  the loop only when fetches were actually skipped. A crawl whose final page reached the budget lost
  nothing and is complete. `truncated` is never touched, because it means the page ceiling.

**`src/modules/seo/page_classifier/tool.py`** (+10). `memory_account` is constructor-injected,
like `cancel_event`: a live control object owned by the caller, never request data. Honoured by the
async path only.

**`src/api/server.py`** (+20 / −2). `ApiState.memory_budget` is built from
`Settings.crawl_memory_budget_mib` and split by `max_concurrent_jobs`. `_run_job` opens the account
before its `try` and closes it in `finally`, on the worker thread, when the crawl really ends. That
is not when `cancel_job` releases the slot: a cancelled crawl holds its HTML until it drains, so it
stays counted and stays in the victim pool. A stopped job ends `PARTIAL` with error "memory budget
reached" through the existing `stopped_reason` mapping added in build-log 0088. No new
`JobStatus`.

**`src/core/config.py`**, **`.env.example`**. `crawl_memory_budget_mib`, env
`CRAWL_MEMORY_BUDGET_MIB`, default 3072, range 256–65536.

**`rankuno-ui/src/components/jobs/CrawlJobsView.tsx`**. `statusDetail` shows "memory budget
reached" for that reason instead of folding it into "stalled/aborted". The site did not stall; the
server stopped the crawl to protect itself, which an operator acts on differently. The
"Crawl stopped early — …" notice already displayed any `stoppedReason` and needed no change; a test
in `dashboardNotices.test.ts` pins that.

Tests added: 18 in `tests/core/test_memory_budget.py`, 6 in `tests/api/test_server_memory_budget.py`,
7 in `tests/modules/seo/test_async_discovery_memory_budget.py`, 3 in `tests/core/test_config.py`
(one parametrised), and 2 UI tests.

---

## 3. Design decisions

The full reasoning is in ADR 0031. The points a later reader most needs:

**Counted, not measured.** Measured in-process with a fake fetcher through the real
`PageClassificationTool.execute()`, 300 pages per run, concurrency 10, no network (table copied
from ADR 0031):

| Body | Bytes per char | Retained per page | Retained, 300 pages | RSS growth at end of discovery | Peak in classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1.1M chars, ASCII | 1.0 | 1.10 MiB | 330 MiB | +337 MiB | +340 MiB |
| 1.1M chars, one U+2019 | 2.0 | 2.20 MiB | 660 MiB | +668 MiB | +670 MiB |
| 1.1M chars, one emoji | 4.0 | 4.40 MiB | 1320 MiB | +1327 MiB | +1329 MiB |
| 2.0M chars, ASCII | 1.0 | 2.00 MiB | 600 MiB | +608 MiB | +610 MiB |

RSS growth divided by retained bytes was 1.005–1.03. Classification added at most 3 MiB, because
`PageEvidence.html` shares the same string object. The result JSON is about 1.6 KB per page (0.46 MiB
for 300). Retained HTML is almost all of the memory, so counting it is a faithful proxy and RSS is
never read. These figures are from Windows; glibc on Railway was not measured.

One curly apostrophe doubles a page, because Python stores a string at the width of its widest
character. That is why a homepage of about 1.07–1.1 MB on the wire costs about 2.2 MiB in memory.

**The default.** For an 8 GiB container: reserve 0.5 GiB for the server baseline, 1.5 GiB for
memory the budget does not count, then divide by 1.10 for RSS overhead and 1.25 for allocator
margin: (8 − 0.5 − 1.5) / (1.10 × 1.25) = 4.36 GiB ceiling. The default is 3072 MiB, below it.

| Situation, at 2.2 MiB/page | Budget available | Pages before a stop |
| :--- | :--- | :--- |
| 5 crawls running, each at its fair share | 3072 / 5 = 614 MiB | about 280 each |
| 1 crawl running alone | 3072 MiB | about 1,400 |

The user accepted the 1,400-page ceiling as interim, until step 2.

**Fair share first, then largest**, over a hard per-crawl cap. A hard cap of `budget / 5` gives the
same tenant guarantee but stops a lone crawl at about 280 pages on an idle server. Rejected.

**Reading RSS (psutil or `/proc`)** was rejected: a syscall per page or a poller, no way to say
which crawl to stop, and a new dependency. **Admission refusal** was not needed: the fair-share
floor already guarantees an admitted crawl its share, and admission cannot stop a crawl that grows
later. **Lowering `MAX_CONCURRENT_CRAWLS`** was rejected by the user.

**The tenant sees a fixed string.** Byte counts, the share and the job ids of the trigger and the
victim are logged server-side only (`crawl_memory_budget_victim`). HTML is never logged.

---

## 4. Bugs found and fixed

### 4.1 A stop checked only before the governor never fires within a level

The first version checked the stop flag only where the cancel flag is checked: at the top of
`_gather_bounded`'s per-task wrapper, before `await governor.acquire()`. That check never fires
within a level. `_gather_bounded` creates a task for every URL in the level at once, so every task
runs the check immediately, before any fetch has landed and so before any victim can exist. All of
them pass, and then they queue on the governor. A stop chosen mid-level was not seen until the next
level boundary. A test showed the victim chosen at page 5, and all 21 pages fetched anyway.

A level can hold thousands of pages, which is exactly the memory this exists to protect. Fixed by
re-checking the flag after the slot is acquired, before `factory()` runs. Each skip is counted on
the account (`record_skip`), which is how `_acrawl` tells after the loop whether the stop cost any
fetches.

### 4.2 The same defect exists in operator cancel (found, not fixed)

The existing `cancel_event` check has the same shape and the same defect: a cancel during a level
does not stop fetches already queued on the governor. They run until the level ends. This is
handed to `bug-fixer` (§8) and is a correction to published claims (§5.1). It was left out of this
cycle to keep the change to one behaviour; the fix is the same one-line re-check.

---

## 5. Corrections

### 5.1 Operator cancel does not stop queued fetches within the current level

[Build-log 0126 §2](0126-a-flag-checked-before-the-fetch-starts.md) and
[ADR 0025](../adr/0025-cooperative-cancellation-is-python-crawler-only.md) decision 3 state that the
flag is checked "before a queued fetch claims a concurrency slot", so that "a not-yet-dispatched
fetch never happens at all". That is false within a level. The check runs when the task starts,
which for every task in a level is the moment the level begins, before it waits for a slot. A
cancel that lands mid-level stops nothing in that level that has not already been checked, which
is all of it. What does hold: no **new level** starts after a cancel.

The `_gather_bounded` docstring makes the same claim and sizes the gap wrongly. It says the check is
"deliberately not re-checked after a task is already waiting on the governor" because the race is
"a gap of at most one governor cycle". The gap is the rest of the level. The `cancel_job` docstring
(`src/api/server.py`, about line 3522) is the most explicit: it says cancellation stops new fetches
"for any fetch still queued behind the concurrency limit within the current level". The `_acrawl`
docstring repeats the guarantee. All of these are left unchanged in this cycle;
`bug-fixer` should correct them with the fix.

### 5.2 Per-crawl RAM was about 20x higher than estimated

[Build-log 0114 §3](0114-a-count-that-belongs-to-one-org.md) estimated "about 1-3 GB for a 20k-page
crawl" and marked it unmeasured. On sites whose pages are about 1 MB of HTML, the measured retained
cost is about 2.2 MiB per page, which is about 43 GiB at 20,000 pages. The 0114 estimate was about
20x low for these sites. The 0114 entry is left as written.

### 5.3 CLAUDE.md §8 held three stale statements

Recorded here; the lead edits CLAUDE.md.

| Statement on `origin/main` | Fact |
| :--- | :--- |
| "The 3-crawl concurrency cap is what bounds memory" | The cap is 5 (`Settings.max_concurrent_crawls`, default 5). It never bounded a single crawl |
| Checkpoints hold URLs only, "and no resume" | Manual resume exists since build-log 0032 (`POST /jobs/{id}/resume`), as a separate, unmerged job. There is no automatic resume |
| "`src/core/circuit_breaker.py` — does not exist" | It exists and `postgres_store.py` uses it. README.md and `docs/ARCHITECTURE.md` already corrected this (cycles 0098 and 0110); CLAUDE.md had not caught up |

### 5.4 README "nothing resumes from it"

`README.md` said of an interrupted crawl's checkpoint that "nothing resumes from it". Manual resume
from the checkpoint's unfetched URLs has existed since build-log 0032. The paragraph is corrected in
this cycle to say that nothing resumes it automatically.

---

## 6. Explicitly not done

- **Step 2.** The HTML is still retained until the job ends. Stopping retention, compressing,
  spilling to disk, or extracting what classification needs and dropping the body is the real fix.
  It needs its own ADR.
- **`MAX_CONCURRENT_CRAWLS` unchanged at 5** (user decision).
- **No RSS read and no psutil.** The budget counts bytes it is handed.
- **No per-request budget field and no admin route.** Settings only.
- **No real-site crawl.** The measurement is synthetic and from Windows. glibc fragmentation on
  Railway was not measured.
- **Not a process-wide OOM guarantee.** Uncounted: sitemap and CMS bodies (Paths A and C), the
  serial discovery fallback, `/result` reads (`read_result` loads a whole blob), workbook
  deliverables, Screaming Frog jobs, and per-node graph structures. The 1.5 GiB reserve is a sizing
  assumption, not an enforced bound. Memory is **not** bounded; the tracked async DOM-crawl HTML is.
- **Evicted pages are not credited back.** Pages the loop watcher evicts from `_html` stay charged.
  This over-counts, which errs on the safe side.
- **No terminal-state guard in `finish()` / `_transition()`** (audit LOW 8). A cancelled job marked
  `FAILED` whose thread later finishes can still be overwritten to `PARTIAL`, now possibly with this
  reason. Known since build-log 0126.
- **The budget is in-process**, like the rate limiter and cost ledger. Several worker processes
  would each have their own.
- **The Railway memory limit and the OOM cause are unconfirmed.** Both rest on the user's statement
  and the investigator's inference. Railway metrics were not available.
- **The UI 409 on `/result` for `FAILED` jobs is not fixed.**
- **No automatic resume after a restart.**
- **A resumed crawl of a large site will hit the budget again** until step 2. Resume starts a new
  job that refills memory the same way.
- **Operator cancel within a level** (§4.2) is not fixed.

---

## 7. Files changed

From `git show --stat 6c16e03`:

| File | Change |
| :--- | :--- |
| `src/core/memory_budget.py` | new, 271 lines |
| `src/modules/seo/page_classifier/async_discovery.py` | +71 / −3 (charge, two checks, level-boundary stop, post-loop reason) |
| `src/api/server.py` | +20 / −2 (`ApiState.memory_budget`, account open/close in `_run_job`) |
| `src/modules/seo/page_classifier/tool.py` | +10 (`memory_account` injection) |
| `src/core/config.py` | +14 (`crawl_memory_budget_mib`) |
| `.env.example` | +6 |
| `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` | +10 / −1 (`statusDetail` names the memory stop) |
| `rankuno-ui/src/components/jobs/CrawlJobsView.test.tsx` | +8 |
| `rankuno-ui/src/lib/dashboardNotices.test.ts` | +12 |
| `tests/core/test_memory_budget.py` | new, 209 lines |
| `tests/api/test_server_memory_budget.py` | new, 237 lines |
| `tests/modules/seo/test_async_discovery_memory_budget.py` | new, 176 lines |
| `tests/core/test_config.py` | +22 |
| `docs/adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md` | new |

This cycle (docs, uncommitted): this entry, the `docs/build-log/README.md` index row, `README.md`
(status row, concurrency paragraph, resume wording) and `docs/ARCHITECTURE.md` (core tree,
`server.py` note, planned table row, ADR 0031 row).

Files over the 400-line target, touched but not split: `async_discovery.py` (935),
`tool.py` (1,257), `server.py` (3,977). `discovery.py` (1,646) is in the same module and was not
touched.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| `bug-fixer` | Re-check `cancel_event` after `governor.acquire()` in `_gather_bounded`; correct the `_gather_bounded`, `_acrawl` and `cancel_job` docstrings (§5.1). ADR 0025 needs a correction note |
| `refactorer` | `async_discovery.py` (935), `tool.py` (1,257), `server.py` (3,977), `discovery.py` (1,646) are over 400 lines |
| `ui-engineer` | `selectJob` requests `/result` for a `FAILED` job and gets 409; it should read `/checkpoint` instead |
| lead | CLAUDE.md §8 text (§5.3) |
| lead / operator | Confirm the Railway memory limit and whether the 2026-10-05 restarts were OOM kills, from Railway metrics |
| next cycle | Step 2: stop retaining full HTML, with its own ADR |
