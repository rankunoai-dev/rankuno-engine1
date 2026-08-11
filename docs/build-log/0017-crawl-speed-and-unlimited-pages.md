# Cycle 0017: Crawl speed presets and an optional page ceiling

- **Date**: 2026-08-11
- **Scope**: Per-host request rate and connection pool as crawl parameters;
  `max_pages` becomes optional.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 987 tests, 95.74% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   987 passed in 42.90s
                             Required test coverage of 85.0% reached. Total coverage: 95.74%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0.

---

## 2. The bug this cycle found: "Polite" was not polite

A token bucket built by `per_minute` takes its capacity from the rate, so a
60 rpm bucket holds 60 tokens. That is correct for an API quota — spending a
minute's allowance early is fine as long as the minute balances — and **wrong
for pacing a crawler**: the first 60 requests leave as fast as the network
allows, and a crawl shorter than 60 pages never throttles at all.

Measured against gep.com before the fix:

```
polite   (1 rps,  c=5)    partial  fetched=57  in 27.7s  peak=10.21/s
standard (10 rps, c=20)   partial  fetched=58  in 18.4s  peak=27.89/s
turbo    (25 rps, c=50)   partial  fetched=56  in 15.4s  peak=28.65/s
```

A control labelled "Polite (1 req/sec)" was sending 10 requests per second, and
the difference between the three presets was concurrency alone — the rate limit
never engaged in any of them. Shipping that would have meant an operator
selecting Polite on a client's site and hitting it ten times harder than the
label promised.

Fixed by giving the per-host buckets an explicit burst of roughly one second's
worth of tokens. `per_minute` keeps its old default, because the API-quota
callers are right to want it; only the crawler passes a burst. After:

```
polite   (1 rps,  c=5)    partial  fetched=61  in 75.7s  peak= 1.83/s
standard (10 rps, c=20)   partial  fetched=57  in 18.5s  peak=15.94/s
turbo    (25 rps, c=50)   partial  fetched=58  in 16.6s  peak=25.35/s
```

Polite takes 2.7× longer than before because the rate now binds. Turbo lands on
25.35/s against a target of 25.

`peak` is a smoothed sample and overshoots the sustained rate briefly — Standard
reads 15.9 against a target of 10 — because a burst of one second's tokens can
be spent inside a sampling window. The sustained rate is what the bucket
enforces; the peak is not it.

---

## 3. `Crawl-delay` wins in both directions

A declared `Crawl-delay` and a configured rate are combined with `min`, and
which direction matters more depends on the case:

* A site declaring `Crawl-delay: 10` is **not** sped up by selecting Turbo. The
  site owner stated a rate; a faster setting here would be this tool deciding it
  knows better about someone else's server.
* A site declaring `Crawl-delay: 0.1` permits 10 rps, and that must **not**
  override a deliberately chosen Polite setting — otherwise "1 req/sec" would
  crawl ten times faster on any such host.

The second direction was a live defect in the code as it stood: the async
registry preferred a declared delay unconditionally. Reconciling has to happen
in the caller, which is the only place that knows both numbers, so
`AsyncRateLimiterRegistry.get_or_create` gained an explicit
`requests_per_minute` parameter rather than inferring one.

---

## 4. `max_pages=None` is bounded, not unbounded

The request was for "no page ceiling — crawls 100% of reachable URLs".
`None` now resolves to `ABSOLUTE_MAX_PAGES = 500_000`, which is the top of the
range ADR 0001 builds for.

There is no genuinely unbounded mode and offering one would misdescribe the
implementation. `SiteGraph` holds every node **and every page body** in memory;
ADR 0001 explicitly defers the Bloom-filter and disk-spill path needed past
500k. On a large catalogue an unbounded crawl would exhaust memory hours in and
lose the entire run — a worse outcome than a stated ceiling, because the crawl
also reports when it hit one.

For any real site this is "everything reachable". The operator-facing approval
summary says `every reachable page (max 500,000)` rather than "unlimited", and
the modal's help text says the same.

---

## 5. Also landed

* **Connection pool sized to concurrency.** Below the worker count, requests
  queue on sockets rather than on the rate limiter, so the configured rate is
  silently never reached. Capped at `MAX_CONNECTIONS = 100`: sockets are finite
  and a caller asking for thousands has made a mistake, not a choice.
* **`rate_limit_rps` capped at 25.0** on the input model.
* **The approval summary names the rate**, because that is the part of the
  decision that lands on somebody else's server.
* **UI**: a Polite / Standard / Turbo selector replacing the raw concurrency
  field, each preset stating what it means for the target; a warning banner on
  Turbo; and an optional page ceiling whose placeholder reads
  "Every reachable page".

---

## 6. Explicitly not done

* **"1,000 pages in ~40 seconds" is unverified.** Every test crawl here was
  budget-bound rather than rate-bound — gep.com's sitemap fills the node budget,
  so the DOM crawl fetched ~60 pages regardless of speed. Turbo demonstrably
  raises throughput; the specific claim has not been measured.
* **No live crawl above 400 URLs**, so the 500,000 ceiling is a documented
  bound rather than a tested one.
* **Turbo is untested against a rate-limiting origin.** A server responding
  `429` under Turbo would be counted as a refusal by `fetch_failures`; no
  backoff-on-429 exists.
* **Presets are client-side.** The engine takes `rate_limit_rps` and
  `concurrency` directly, so an API caller can choose any combination within the
  caps; the three named presets exist only in the modal.
