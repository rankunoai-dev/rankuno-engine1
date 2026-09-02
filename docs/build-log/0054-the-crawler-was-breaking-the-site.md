# Cycle 0054: The crawler was breaking the site it was measuring

- **Date**: 2026-09-02
- **Scope**: `_LoadGovernor` in `async_discovery` — narrow the in-flight cap
  while an origin is returning 5xx.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1702 passed`, ruff and `mypy --strict` clean.

## 1. The report

A rankuno.com crawl finished at **28 / 81** and reported `SUCCEEDED`.

Cycle 0050's outcome ledger answered the "why" immediately, which is the first
time it has earned itself:

```text
"pages_fetched": 33,
"fetch_failures": 54,
"fetch_outcomes": { "ok": 39, "server_error": 54 }
```

**Every failure was a 5xx.** Not 404s, not timeouts. Before 0050 this said
`fetch_failures: 54` and nothing else, and the obvious reading — a slow or
blocked site — would have been wrong.

The ledger also reconciles exactly: 39 `ok` = 6 sitemaps + 33 pages, and
39 + 54 = 93 attempts.

## 2. It was not the crawl settings

The same site, the same settings — `rate_limit_rps: 10`, `concurrency: 20` —
fetched **80 of 83** on 2026-08-21. So nothing about the configuration explained
it, and the question became what the origin does under load.

Measured directly, ten URLs at a time:

```text
concurrency  2 -> 10x 200        in 7.0s
concurrency  5 -> 10x 200        in 3.4s
concurrency 10 -> 5x 500, 5x 200 in 2.1s
```

**rankuno.com starts returning 500 between five and ten concurrent requests**,
and answers in 2.4–3.0 seconds when it answers at all. The crawl ran at twenty:
double the breaking point, sustained for the whole run.

The crawler was very probably the reason the site was failing.

## 3. The module said this could not happen

`async_discovery`'s own docstring:

> Politeness is *not* enforced here. `HttpFetcher` already applies a per-host
> token bucket honouring `Crawl-delay`, so raising `concurrency` cannot make the
> crawler rude to a single host — **it makes it wait**.

That is false, and the measurement is what disproves it. **A token bucket bounds
requests per second; it does not bound requests in flight.** On an origin taking
2.5 seconds to answer, twenty in flight means twenty of its workers are occupied
at once regardless of the arrival rate. Nothing in the engine bounded pressure —
only rate — and the docstring asserted the opposite for as long as the file has
existed.

Corrected in place, with the numbers, rather than quietly deleted.

## 4. What landed

`_LoadGovernor` replaces the fixed `asyncio.Semaphore` on the two paths that
fetch pages in bulk. Additive increase, multiplicative decrease — the shape TCP
uses, for the same reason: **back off fast when the other end is in trouble,
return slowly so a recovering origin is not knocked straight over again.**

* A server error halves the cap, to a floor of 1. A cap of zero is a hung crawl,
  not a polite one.
* `BACKOFF_RECOVERY_STREAK` clean completions widen it by **one**.
* A clean crawl never narrows, so a healthy site pays nothing.

**Failure is read from the graph's outcome ledger, not from task return values.**
A task returning `None` cannot distinguish "500" from "200 but not HTML", and
throttling on the second would punish every site that serves a PDF. This is the
second time 0050's ledger has turned out to be the thing that made a fix
possible.

The attribution of one error to one completing task is approximate under
concurrency. A control loop does not need better, and the docstring says so
rather than implying precision it does not have.

## 5. Explicitly not done

- **The job still reports `SUCCEEDED`.** `partial` is decided solely by
  `discovery.truncated` — hitting the page ceiling — so a crawl that retrieved a
  third of a site because the origin was failing looks like a complete one. It
  should not. The change is in `server.py`, which a parallel session has open,
  so it is deferred rather than merged into a contested file.
- **The low-water mark is not reported.** `_LoadGovernor.low_water` knows the
  narrowest the cap became; nothing carries it into `DiscoveryReport`, so a
  throttled crawl cannot yet say it was throttled.
- **No 429 handling.** `Retry-After` is the polite signal for this and is
  ignored; only 5xx drives the governor.
- **Not re-measured against rankuno.com.** The governor is unit-tested and the
  breaking point is measured, but the two have not been put together — doing so
  means crawling the site again while it is already unhealthy.
- **Pagination**, still waiting on `url_rules.py` (0050 §7).

## 6. Files changed

| File | Change |
| :--- | :--- |
| `async_discovery.py` | `_LoadGovernor`, wired into both bulk-fetch paths; the docstring corrected |
| `tests/modules/seo/test_async_discovery.py` | 5 new tests |

## 7. Follow-ups

1. Report a throttled crawl as `partial`, and carry `low_water` into the report.
2. Honour `Retry-After` on 429.
3. Consider lowering `DEFAULT_CONCURRENCY`; 10 is above rankuno.com's breaking
   point, and it is the default.
