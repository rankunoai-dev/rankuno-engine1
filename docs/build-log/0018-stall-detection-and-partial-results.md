# Cycle 0018: Bounded requests, stall detection, and partial results

- **Date**: 2026-08-11
- **Scope**: Stop a crawl hanging on an unresponsive target, and keep what it
  found when it stops.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 992 tests, 95.75% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   992 passed in 45.53s
                             Required test coverage of 85.0% reached. Total coverage: 95.75%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0.

---

## 2. Why stricter socket timeouts alone would not have fixed this

The request was for `httpx.Timeout(10.0, connect=5.0)` so hung connections abort
after ten seconds. Per-phase timeouts are worth having and are now set — but on
their own they do **not** bound how long a request can take.

httpx's read timeout measures the gap **between bytes**, not the duration of the
request. A server sending one byte every few seconds resets it indefinitely: the
request never times out, and the worker never comes back. That is precisely what
a tarpit does, and it is the failure mode described. The previous configuration
was already a 30-second scalar, and it did not prevent the hang for this reason.

So the fix is three layers, not one:

1. **Per-phase timeouts** — `connect=5.0`, `pool=10.0`. A host that has not
   accepted a connection in five seconds will not serve a useful page.
2. **`REQUEST_DEADLINE_S = 20.0`** — a total wall-clock bound per fetch, applied
   with `asyncio.wait_for` because httpx has no equivalent setting. This is the
   layer that actually defeats a dribbling server.
3. **`STALL_TIMEOUT_S = 30.0`** — the crawl-level detector below.

---

## 3. The stall detector fires on *no progress*, not on slowness

`_gather_bounded` now takes an optional `stall_timeout_s` and abandons a batch
only when **nothing at all** completes inside the window.

The distinction matters more than it looks. A per-batch timeout would kill a
large crawl of a slow-but-healthy site — exactly the crawls this engine is built
for, at polite request rates. Firing only when every in-flight request is stuck
means the detector catches a dead target and never a slow one. There is a test
for each direction: a batch sleeping forever raises, and a batch of ten slow
tasks completes untouched.

Cancelled rather than awaited when it fires: the entire premise is that these
requests are not coming back.

---

## 4. A stopped crawl keeps what it found

`DiscoveryReport.stopped_reason` is new and deliberately distinct from
`truncated`:

* **`truncated`** — the page ceiling was reached. A planned stop at a known
  boundary.
* **`stopped_reason`** — the crawl was abandoned. The pages found are real, but
  it covered less of the site than asked and **how much less is unknown**.

Both the serial and concurrent DOM crawls are now wrapped so any failure keeps
the graph built so far. Losing a 500-URL crawl because page 501 broke the event
loop throws away real work and tells the operator nothing.

The blocked-crawl guard from cycle 0013 still applies underneath: if a crawl
retrieved *nothing at all*, it still fails rather than presenting a seeded root
node as a one-page site. Partial results mean partial, not empty.

Verified by test: a target that serves its sitemap and then tarpits every page
fetch returns a report with its sitemap URLs intact rather than nothing.

The UI carries a distinct banner naming the reason and stating that the missing
fraction is unknown — a partial crawl that looks complete is the failure this
codebase keeps designing against.

---

## 5. Explicitly not done

* **No live reproduction.** The tarpit case is covered by a mock transport that
  raises `ReadTimeout`; no real hanging server was crawled, so the deadline and
  stall values are reasoned rather than tuned against one.
* **No 429 backoff.** A rate-limiting origin still counts refusals rather than
  slowing down, which under Turbo is the likelier real-world cause of a stall.
* **The serial path has no stall detector.** It is sequential, so a single hung
  request blocks it; only the async path, which is the default, is protected.
* **`REQUEST_DEADLINE_S` is not configurable.** A legitimately slow endpoint
  taking over 20 seconds will be recorded as a failure.
