# ADR 0025: Cooperative cancellation stops new fetches on the Python crawler only

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`POST /jobs/{id}/cancel` existed before this decision and did exactly one thing: release the
job's concurrency slot and mark it `FAILED`. Its own docstring said outright that it did not stop
the crawl — the work runs on a worker thread via `asyncio.to_thread`, and a Python thread cannot
be killed from outside, nor does cancelling the awaiting task reach into it. Two stripe.com jobs
once held two of a workstation's three slots for sixteen hours, wedged in network I/O, before this
was understood as a capacity problem rather than a stop button (referenced in build-log
0024). RAE — the system this engine replaces — has the same class of defect from the opposite
direction: its cancel endpoint SIGKILLs the worker process before it writes its Redis flag, which
leaves orphaned child processes running for hours. Tracked as DEF-02 against the reference
comparison in `rae_defects_and_fixes.xlsx`.

This engine runs two structurally different kinds of job under one "crawl" label, and they do not
admit the same fix.

### The Python autonomous crawler has await points

`PageClassificationTool`'s async path (`adiscover_site` / `_acrawl` / `_gather_bounded`,
`src/modules/seo/page_classifier/async_discovery.py`) is a breadth-first traversal that awaits a
bounded number of concurrent fetches per level. Every fetch that has not yet been dispatched is a
coroutine sitting behind an `await`, which means a flag checked immediately before that await can
stop it from ever starting, without touching anything already in flight.

### The Screaming Frog worker does not

`ScreamingFrogTool.execute()` (`src/modules/seo/screaming_frog_control/tool.py`, roughly lines
255-310) launches `ScreamingFrogSEOSpiderCli.exe` under `launch_supervised` (ADR 0013) and polls
`process.is_running()` in a loop, breaking either when the process exits on its own or when
`self._max_runtime_s` is exceeded. Read directly: **the code after that loop cannot distinguish
"the process finished normally" from "the process was terminated by an external call"** — both
exit paths look identical to everything that runs afterward, including the licence check that
decides whether the run is treated as successful. Wiring a cancel-triggered `process.terminate()`
into this loop today, without first giving it a way to record *why* the loop exited, would risk
silently reporting a prematurely killed crawl as a successfully completed one and uploading
truncated data labelled as real — a worse failure mode than the one being fixed, and the same
"declared success, no result to show for it" shape that build-log 0113 recorded for the ledger's
own liveness-vs-orphan confusion.

## Decision

**Cooperative cancellation ships for the Python autonomous crawler only.** Specifically:

1. `ApiState` gains a per-job `threading.Event` (`_cancel_flags`), created on `try_reserve`,
   moved across `rekey`, and dropped on `release` — the same lifecycle as the concurrency-slot
   bookkeeping it sits beside, not a persisted field on `JobRecord` (a `threading.Event` cannot
   survive a restart or a `StrictModel`'s atomic disk write).
2. `cancel_job` sets the `Event` **before** calling `state.release()`. Order is load-bearing:
   `release()` removes the registry entry `cancel_event()` looks up, so reversed, the flag would
   already be gone and cancellation would silently do nothing.
3. `async_discovery.py` checks the `Event` in exactly two places: inside `_gather_bounded`'s
   per-task wrapper, before a queued fetch claims a concurrency slot; and at the top of `_acrawl`'s
   outer BFS-level loop, before a new level begins. Neither reaches into a fetch already
   dispatched — that fetch runs to completion or hits the existing `REQUEST_DEADLINE_S` (200s),
   which is the disclosed worst case, not an oversight.
4. Only Path B (the DOM/BFS crawl) is gated. Path A (sitemap discovery) and Path C (CMS-specific
   discovery) run to their own natural completion regardless of the flag — both are already
   bounded, single-pass operations with no comparable per-fetch await structure to interrupt
   cheaply.
5. **Screaming Frog cancellation is explicitly deferred**, not attempted as a partial fix. Nothing
   in this change wires a cancel signal into `ScreamingFrogTool.execute()`'s poll loop.

### What must be true before the Screaming Frog follow-up is picked up

`ScreamingFrogTool.execute()`'s poll loop must first be able to record, and callers must be able
to read, *why* the loop exited — normal completion, `self._max_runtime_s`, or an external
cancellation request — as three distinguishable outcomes, before an external `terminate()` call is
wired to the cancel endpoint. Until then, nothing in this codebase triggers that ambiguity, so it
is a precondition for future work, not an open bug today.

## Alternatives considered

**Abort the in-flight fetch too, via `asyncio.wait_for` around each `afetch` call.** Rejected for
this cycle: it changes the failure semantics of every fetch (a slow-but-honest 200s response would
now race an operator-controlled cutoff instead of the deadline), and the existing
`REQUEST_DEADLINE_S` bound was judged an acceptable, disclosed worst case against that added
complexity. Left as a narrower possible follow-up, not ruled out.

**Ship a half-measure for Screaming Frog — terminate the process, accept the status ambiguity as a
known gap.** Rejected: build-log 0113 already recorded what an unrecorded ambiguity like this one
costs once observed on real, hours-long crawls (a killed run reported `SUCCEEDED` with a 22-byte
download). Repeating that shape deliberately, with the mechanism already identified in review,
would not be a smaller version of the fix — it would be the same defect reintroduced through a
different button.

**Re-check the cancel flag mid-fetch inside `_gather_bounded`'s governor wait.** Rejected as not
worth its complexity: it would close a narrower race (a task already waiting on the concurrency
governor when cancellation lands) for a window bounded by one governor cycle, against a button
whose own worst-case bound is already `REQUEST_DEADLINE_S`.

## Consequences

**Accepted.** Cancelling a Python crawl job is not instant. The worst case is: cancellation lands
the instant a batch of up to `concurrency` (default 10) fetches has just started, and the thread
keeps making progress on only those until each resolves or `REQUEST_DEADLINE_S` fires. This is
disclosed in `cancel_job`'s docstring and in the endpoint's OpenAPI-visible text, not left implicit
the way the old docstring's blanket "it does not stop the crawl" was.

**Accepted.** A Screaming Frog dispatch has no user-facing stop button today beyond what the
process supervisor already offers operationally (ADR 0013). The Cancel action in the UI only ever
targeted native crawl rows; this does not remove a capability that existed.

**Follow-up required.** `DiskJobStore`/`PostgresJobStore`'s `_transition`/`finish()` have no
terminal-state guard: a cancelled job now frequently exits within seconds rather than hours, so its
own `store.finish(..., partial=True, error="cancelled by operator")` call — made by the crawl
thread on its way out — now routinely races and overwrites the `FAILED` status `cancel_job`'s
`mark_failed()` call wrote moments earlier. This is a pre-existing gap in `state_store.py`,
exposed rather than introduced by this decision, recorded in build-log 0126 and not fixed here.

**Gained.** The failure this whole mechanism exists for — a slot held for hours by a crawl nobody
can meaningfully stop — is closed for the crawler that produced the original stripe.com incident,
without touching the process-supervision half (ADR 0013) that already governs the other job kind
correctly.
