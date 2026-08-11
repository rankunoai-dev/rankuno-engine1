# Cycle 0016: Live crawl telemetry

- **Date**: 2026-08-11
- **Scope**: A real progress signal from the engine — throughput, ETA, and the
  URLs being fetched — surfaced while a crawl runs.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 966 tests, 95.71% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   966 passed in 17.07s
                             Required test coverage of 85.0% reached. Total coverage: 95.71%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0.

---

## 2. This reverses cycle 0012's decision, deliberately

Cycle 0012 asked whether to fake a progress fraction or report honest binary
status, and the operator chose binary. The alternative offered then was "add a
real progress callback seam", which is what this cycle builds. Nothing about the
earlier reasoning was wrong; the cheaper option was taken first and the real one
is now warranted.

ADR 0003 still holds. The sink is observability: it cannot influence the crawl,
its exceptions are swallowed, and one `BaseTool.run()` is still one governed job.
No per-page decision point was introduced.

---

## 3. Three findings that changed the plan

### 3.1 Writing telemetry per URL would have made crawls slower

`DiskJobStore` writes the whole record through a temp file, `os.replace` and an
`fsync`. The plan called for updating telemetry on every extracted URL; on a
20,000-page crawl that is 20,000 fsyncs, and the telemetry would plausibly cost
more wall-clock than the crawling.

`TelemetryRecorder` accumulates in memory and flushes at most every 500 ms —
except the first call, which flushes immediately so a crawl does not appear
stalled for the first half second.

### 3.2 The specified ETA formula divides by the wrong number

The plan gave `eta = (max_pages - pages_fetched) / rate`. `max_pages` is the
*ceiling*, not the expected total: a 300-page site crawled with a 20,000-page
ceiling would report 19,700 pages remaining and a bar stuck at 1.5% that never
completes.

The denominator is URLs actually discovered, capped by the ceiling.

### 3.3 The exporter had no mapping for `datetime`

`JobTelemetry.updated_at` broke `export_ui_contract.py` with
`No TypeScript mapping for <class 'datetime.datetime'>` — the guard refusing to
emit `any`. Mapped to `string`, not `Date`: Pydantic serialises to an ISO 8601
string and `JSON.parse` yields a string, so typing it as `Date` would let a
consumer call `.getTime()` on something that has no such method.

---

## 4. Bug found by the live run: the bar froze, then jumped

First live measurement against gep.com:

```
[ 12.1s] running    1/400   rate=0.94/s
[ 34.5s] running    1/400   rate=0.94/s     ← 28 seconds, no movement
[ 40.0s] partial   81/400
```

I had notified **per level** rather than per page, with a comment asserting that
notifying inside the gather would "fire from many coroutines for a number that
has not changed". That was simply wrong — the number changes with every page.
The crawler is level-synchronous, so one level of 80 pages fetched concurrently
produced exactly one update.

Fixed by reporting as each fetch lands. Same crawl afterwards:

```
[ 12.1s]   6/400  rate=5.33/s  eta= 74s
[ 16.2s]  21/400  rate=4.14/s  eta= 92s
[ 22.2s]  49/400  rate=7.43/s  eta= 47s
[ 30.3s]  77/400  rate=5.11/s  eta= 63s
[ 36.7s]  81/400  partial
```

Per-page notification is affordable precisely because the sink throttles its own
writes — the two decisions depend on each other.

The unit tests could not have caught this: the fixture sites are small enough
that one level is one page, so per-level and per-page reporting are
indistinguishable. It took a real site with a wide level. There is now a test
asserting a reading per page on a 20-hop chain, and one asserting counts never
decrease.

---

## 5. What landed

* **`core/state_store.py`** — `JobTelemetry`, domain-agnostic like the rest of
  the module: "items", not "URLs". `MAX_RECENT_ITEMS = 20` bounds the URL
  stream, because returning every URL on every poll would push megabytes per
  second at a browser that renders the last handful.
* **`ProgressSink`** threaded through `discovery.py`, `async_discovery.py` and
  `tool.py`. Constructor-injected on the tool rather than added to
  `PageClassificationInput`: it is a callable the caller owns, not a crawl
  parameter, and has no place in a serialised, audited request payload.
* **`api/TelemetryRecorder`** — EMA rate smoothing (0.3 on the newest sample), a
  3-second warmup before any ETA is offered, and the flush throttle. Smoothing
  and throttling live in the API layer because they are presentation concerns
  for a polling client; the engine should not know anyone is watching.
* **`LiveCrawlProgressModal`** — progress bar, elapsed clock, rate, ETA and the
  live URL ticker. The ticker auto-scrolls only when already at the bottom, and
  only the newest line pulses; `prefers-reduced-motion` disables it.

Measured poll payload on the live run: **735 B idle, 2.4 kB at full stream.**

---

## 6. Known limitation: the bar completes below 100%

The gep.com run finished `partial` at **81/400**. That is correct and it is not
a stall.

`completed` counts pages *fetched*; `discovered` counts every URL in the graph,
most of which arrived from the sitemap and are never fetched. So on a
sitemap-heavy site the ratio tops out well short of 1.0 and the job then
completes.

There is no honest fix available: the number of pages the DOM crawl will
ultimately fetch is not knowable in advance — the frontier grows as pages are
parsed, and the crawl ends when the node budget fills. Rather than invent a
denominator, the modal states what the ratio means, and the client snaps the bar
to 100% on a terminal status.

---

## 7. Explicitly not done

* **No live 20k run.** The largest measured crawl remains 400 URLs at 81 fetched.
  The throttle's justification is arithmetic, not measurement.
* **`MockAdapter` reports no telemetry.** `JobProgress.telemetry` is optional and
  the fixture adapter omits it; the modal degrades to elapsed time only.
* **No frontend tests**, so the modal is covered by `tsc` and manual use alone.
* **Telemetry is not persisted per sample.** Only the latest snapshot is kept, so
  there is no throughput history to chart after the fact.
* **No cancellation.** The modal cannot be dismissed while running because there
  is no `DELETE /jobs/{id}` to dismiss *to*.
