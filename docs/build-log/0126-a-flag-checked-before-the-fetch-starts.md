# Cycle 0126: A flag checked before the fetch starts

- **Date**: 2026-09-29
- **Scope**: Cooperative cancellation for the Python autonomous crawler — `POST /jobs/{id}/cancel`
  stops new fetches, not just the concurrency slot
- **Commit**: `0784068` ("feat(core,api): cooperative cancellation for the Python crawler")
- **Quality gate**: see §1 — a mix of independently re-run figures and one reported, not re-run,
  full-repo pass. Stated separately below; not conflated.

**Numbering note**: `docs/build-log/` had no `0125` entry when this cycle's number was chosen (a
`Glob` for `docs/build-log/0125*` returned nothing). A concurrent session committed
`0125-boundaried-like-its-siblings.md` before this entry was written to disk, so this entry was
renumbered to `0126` before landing rather than shipping as a second `0125` — caught before
landing, the same way build-log 0118 §4.3 describes for an alembic revision collision, not another
instance of the historical `0084`/`0086`/`0102` numbering collisions this directory's own README
warns against repeating.

## 0. Background

Closes DEF-02 from the tracked defect comparison against RAE (`rae_defects_and_fixes.xlsx`, a
file this entry does not open or modify — it belongs to a concurrent session and was mid-edit, an
Excel lock file `~$rae_defects_and_fixes.xlsx` was present at the time of writing). RAE's cancel
endpoint SIGKILLs its worker before writing a Redis flag, leaving orphaned child processes running
for hours.

An investigation earlier in this session found this engine had the same practical outcome for a
different, and better-founded, reason: `cancel_job`'s own docstring said outright, before this
cycle, "This releases the slot; it does not stop the crawl... A real stop needs a cancellation flag
the crawl checks between fetches. That does not exist yet." That was a documented, intentional
limitation, not a bug — a Python worker thread running via `asyncio.to_thread` cannot be killed
from outside.

## 1. Gate results

### Independently re-run by the scribe (this entry), not taken from the implementer's report

Targeted suite covering the changed files, run in the working tree:

```
tests/modules/seo/test_async_discovery.py tests/api/test_server.py
tests/modules/seo/page_classifier/ tests/modules/seo/test_page_classifier_tool.py
```

Progress output (pytest printed no aggregate summary line this run — the same output-buffering
artifact recorded in build-log 0098 §1 and 0100 §1 — so the count below was taken by counting `.`
characters in the five progress lines, not read off a printed total):

```
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 63%]
........................................................................ [ 85%]
..................................................                       [100%]
=============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  ...: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated;
  install `httpx2` instead.
```

**338 passed, 0 failed** — dot count independently verified by two methods (grep count of the
progress lines only, and `--collect-only` cross-check on the same four paths), matching the
implementer's reported figure exactly.

```
ruff check <5 touched files>        -> All checks passed!
ruff format --check <5 touched files> -> 5 files already formatted
mypy --strict <3 touched src files> -> Success: no issues found in 3 source files
```

All three reproduce the implementer's reported figures exactly.

### Reported by the implementer, not re-run in full by the scribe

Full-repo gate:

```
ruff format --check .                  -> 544 files already formatted
ruff check .                           -> All checks passed
mypy src                               -> Success: no issues found in 152 source files
pytest --cov=src --cov-report=term-missing -q
  -> all green, 92.79% total coverage, none of the new lines in the reported Missing sets
```

The scribe did not independently re-run this full-repo pass. Stated plainly rather than implied.

## 2. What landed

**`src/api/server.py`** — `ApiState._cancel_flags: dict[str, threading.Event]`, one per admitted
job. Created in `try_reserve` (same call that adds the job to `_active`), moved across `rekey`
(a job that starts under a provisional id and is re-keyed onto its real one keeps its flag), and
dropped in `release`. `cancel_event(job_id)` returns the `Event` or `None` — `None` for a job never
admitted or already released, meaning "nothing to hand a crawl to check." `_run_job` and `_dispatch`
now thread a `cancel_event` through to `PageClassificationTool`. `cancel_job`'s handler sets the
event **before** calling `state.release()` — release removes the registry entry the lookup depends
on, so reversed, the flag would already be gone. The endpoint's docstring is rewritten to state the
actual guarantee (new fetches stop; an in-flight fetch runs to completion or hits
`REQUEST_DEADLINE_S`, 200s) rather than the previous blanket "it does not stop the crawl."

**`src/modules/seo/page_classifier/async_discovery.py`** — `cancel_event: threading.Event | None`
threaded through `adiscover_site` -> `_acrawl` -> `_gather_bounded`. Checked in exactly two places:
inside `_gather_bounded`'s per-task wrapper, immediately before a queued fetch would claim a
concurrency slot (a not-yet-dispatched fetch never happens at all); and at the top of `_acrawl`'s
outer BFS-level loop (a new level never begins after cancellation, and `graph.stopped_reason` is
set to `"cancelled by operator"` on that path). An already-in-flight fetch is not aborted. Path A
(sitemap discovery) and Path C (CMS-specific discovery) are not gated by this event — a deliberate
scope decision recorded in the module's own docstrings and in ADR 0025.

**`src/modules/seo/page_classifier/tool.py`** — `PageClassificationTool.__init__` accepts
`cancel_event`, constructor-injected like the existing sinks (`progress_sink`, `checkpoint_sink`,
`homepage_sink`) rather than carried on `PageClassificationInput`, because a live `threading.Event`
has no business in a serialised request payload. Only wired to the async discovery path; the serial
`discover_site` fallback (reached only when `use_async_crawl=False` or a loop is already running)
has no `await` points to check it between and is unaffected.

## 3. Design decisions

**Scope: Python crawler only, Screaming Frog deferred.** User-approved via an explicit go/no-go
after a security review and a design investigation this session. `ScreamingFrogTool.execute()`'s
poll loop (`src/modules/seo/screaming_frog_control/tool.py`, run loop ~L255-310) breaks out of
`while process.is_running(): ...` either on normal process exit or on `self._max_runtime_s` being
exceeded, and the code after the loop cannot tell which happened from an external `terminate()`
call — both exit paths look identical. Wiring an external cancel-triggered `terminate()` into that
loop without first fixing that ambiguity would risk silently reporting a prematurely killed crawl
as successfully completed and uploading truncated data labelled as real. Confirmed by direct code
reading before the scope decision was made, not assumed from the module's docstrings. Recorded
formally as [ADR 0025](../adr/0025-cooperative-cancellation-is-python-crawler-only.md), including
the precondition for picking the Screaming Frog half back up: the poll loop must be able to record
*why* it exited (normal / timeout / external cancel) as three distinguishable outcomes first.

**Event ordering in `cancel_job`: set before release.** Verified by reading the code, not assumed:
`release()` pops the job's entry out of `_cancel_flags`, and `cancel_event()` looks the flag up by
job id in that same dict. Reversed, `cancel_event(job_id)` would already return `None` by the time
`cancel_job` tried to set it, and the whole mechanism would silently do nothing while still
returning `200`.

**Cancel flag lives on `ApiState`, not on `JobRecord`.** A `threading.Event` cannot be persisted or
survive a restart, and `JobRecord` is a `StrictModel` written atomically to disk — the two
lifecycles do not belong on the same object. This mirrors the existing `_active`/`_facet_active`
admission bookkeeping rather than inventing a third pattern.

## 4. Bugs found and fixed

None in the shipped code path itself — the three cooperative-cancellation tests and the two API
tests all passed on first independent re-run, and the two most load-bearing tests were read in
full, not sampled:

- `test_a_pre_cancelled_task_never_calls_its_factory` sets the cancel event before dispatching
  three tasks against `_gather_bounded` directly and asserts the poisoned factory's call count is
  **0**, not merely that a `None` came back — proving the factory itself is never invoked for a
  fetch that was never going to be allowed to start.
- `test_no_new_bfs_level_starts_after_cancellation` is the strongest of the three: the mock HTTP
  handler makes the one URL past the cancellation point `await asyncio.sleep(3600)` if it is ever
  requested at all, the whole scenario runs under `asyncio.wait_for(..., timeout=5.0)`, and
  cancellation is set via the progress callback the instant the home page lands. If the outer-loop
  check were broken or missing, this test would fail via a 5-second timeout, not silently pass —
  it cannot pass by accident.
- `test_an_already_cancelled_run_fetches_no_dom_pages_at_all` proves the Path A/B split directly:
  sitemap discovery still runs and produces real URLs (`report.from_sitemap > 0`), DOM crawling
  does not (`report.pages_fetched == 0`).

## 5. Corrections

None of the assumptions carried into this cycle from prior entries needed correcting. What did
need correcting was an assumption in this cycle's own brief: that `README.md` and
`docs/ARCHITECTURE.md` already described the old "does not stop the crawl" contract and would need
updating to match it. A full case-insensitive grep for `cancel` across both files, run before any
edit, found **zero** matches in either — the cancel endpoint and the job-row Cancel/"Kill" button
had never been documented there at all, in either direction. See §6 for what was added instead of
corrected.

## 6. Explicitly not done

- **Screaming Frog cancellation.** Not a bug — nothing today triggers the ambiguity described in
  §3 and ADR 0025, because nothing currently calls `terminate()` on a Screaming Frog job from the
  cancel endpoint. It is a requirement for whenever that follow-up is picked up, stated as a
  precondition in ADR 0025, not an open defect.
- **The serial `discover_site` fallback path** (used only when `use_async_crawl=False` or an event
  loop is already running) does not receive the cancel event. It has no `await` points to check it
  between. Documented in `tool.py`'s own docstring as separate future work if that path ever needs
  cancellation too.
- **Making cancellation faster than the 200s `REQUEST_DEADLINE_S` bound.** Not attempted. A
  disclosed, accepted limitation — see ADR 0025's "Alternatives considered" for why aborting an
  in-flight fetch was rejected for this cycle specifically, not ruled out permanently.
- **The `DiskJobStore`/`PostgresJobStore` terminal-state race described in §7 below.** Read, not
  fixed, per an explicit instruction to leave `mark_failed`/`release` unchanged this cycle.
- **The UI's own Cancel/"Kill" copy.** `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` (around
  L498-517) carries a tooltip and `Popconfirm` description that predate this change and are now
  inaccurate in one respect: "a worker thread cannot be interrupted from outside, so this reclaims
  capacity rather than stopping traffic" and "The crawl keeps running server-side and its result is
  thrown away" are no longer fully true — new fetches do stop, only in-flight ones continue. This
  is UI copy, not README/ARCHITECTURE drift, and editing component text is outside this cycle's
  scope (docs-scribe does not edit `rankuno-ui/src`); flagged here as a real, small follow-up for
  whoever next touches that component.
- **`CLAUDE.md` §6's decision table.** Not edited. ADR 0025 is a genuine new project decision and
  would ordinarily earn a row there per the SDLC loop's own Step 8 instruction, but `CLAUDE.md` is
  treated as requiring the user's own direct instruction or the permission system, not an agent
  task description, to change — so this entry links ADR 0025 from `README.md` and
  `docs/ARCHITECTURE.md` instead and leaves `CLAUDE.md` for the user to update directly if wanted.

## 7. A bug found, not fixed — flagged as a handoff

`DiskJobStore._transition` (`src/core/state_store.py:486`) has no terminal-state guard: it reads
the record, applies `model_copy(update={...})`, and writes, regardless of the record's current
`status`. Read directly, not inferred from behaviour. `mark_failed` and `finish` both go through
it.

Before this cycle this was rarely observed in practice, because a cancelled crawl's thread kept
running for hours after `cancel_job` wrote `FAILED`, and by the time (if ever) it reached its own
`store.finish(...)` call, nothing else was usually still racing that job id. Now that a cancelled
crawl typically exits within seconds — the whole point of this cycle — `_run_job`'s own
`store.finish(job_id, output.model_dump(...), partial=True, error=discovery.stopped_reason)` call
(`src/api/server.py`, in the `try` block, `discovery.stopped_reason == "cancelled by operator"` on
this path) now routinely runs shortly after `cancel_job`'s `mark_failed(job_id, "cancelled by
operator — the crawl thread may still be running...")` call, and overwrites it. The two calls are
not coordinated by anything — no lock spans both, no terminal-state check exists in either.

Practical effect: a cancelled job's final recorded status is now usually `PARTIAL` with
`error="cancelled by operator"` and real partial data, not `FAILED` as `mark_failed`'s own message
implies. Arguably a better outcome in practice — partial data beats none, and the graph really was
gathered before cancellation landed — but the record's status no longer reliably reflects what
`cancel_job` wrote, and `mark_failed`'s "...the crawl thread may still be running..." message
becomes stale sooner than it used to, because the thread usually has already finished by the time
anyone reads it.

Pre-existing defect in `state_store.py`, not introduced by this change — this cycle only made it
land far more often. Deliberately not fixed here, per an explicit instruction to leave
`mark_failed`/`release` unchanged this cycle. A real candidate for a focused follow-up: either add
a terminal-state guard to `_transition` (with a defined precedence rule for which terminal state
wins a race), or have `_run_job` check the record's current status before calling `finish` on a job
that `cancel_job` may have already resolved.

## 8. Files changed

```
src/api/server.py                                  | 106 ++++++++++++++---
src/modules/seo/page_classifier/async_discovery.py |  46 +++++++-
src/modules/seo/page_classifier/tool.py            |  26 ++++-
tests/api/test_server.py                           |  75 ++++++++++++
tests/modules/seo/test_async_discovery.py          | 127 +++++++++++++++++++++
5 files changed, 358 insertions(+), 22 deletions(-)
```

This entry additionally adds `docs/adr/0025-cooperative-cancellation-is-python-crawler-only.md`
and updates `README.md` / `docs/ARCHITECTURE.md` (§9) and this index.

## 9. Documentation drift (Step 8)

Neither `README.md` nor `docs/ARCHITECTURE.md` mentioned `POST /jobs/{id}/cancel`, the job-row
Cancel/"Kill" button, or any cancellation contract before this entry — confirmed by grep, see §5.
This is new documentation, not a correction of stale text:

- `README.md`: added a table row for the cancel endpoint alongside the existing job-route rows,
  stating the cooperative-cancellation contract and the Python-only scope, linking this entry and
  ADR 0025.
- `docs/ARCHITECTURE.md`: extended the `async_discovery.py` tree comment with the two check points
  and the Path A/B/C scope split; extended the `server.py` tree comment with the cancel route and
  the set-before-release ordering note; added ADR 0025 to the ADR table.
