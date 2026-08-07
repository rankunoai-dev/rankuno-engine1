# Cycle 0007: First live run

- **Date**: 2026-08-07
- **Scope**: Run the engine against a real website for the first time, and record what six cycles of mocks could not tell us.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 640 tests, 94.56% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   35 source files, mypy --strict
=== Tests ===       PASSED   640 passed in 13.54s, 94.56% coverage
ALL GATES PASSED.
```

---

## 2. It ran

Target: `https://www.highradius.com`, robots-compliant, low concurrency.
Two runs: 40 pages / depth 1, then 250 pages / depth 2.

```
SITE PROFILE
  platform           WORDPRESS
  client-rendered    False
  locales            de, en-gb, fr
  weight vector      default (detected: wordpress)
```

**Detection was correct on all counts.** WordPress via `/wp-json/wp/v2/types`;
server-rendered; and the locale set `de, en-gb, fr` matches
`docs/HIGHRADIUS_CRAWL_AUDIT_RECORD.md` §2 exactly — that document records 346
URLs across German, UK-English and French sub-directories. The prober derived
that from the site's own sitemap entries, with no configuration.

26 sitemaps parsed. 250 URLs discovered. 101 pages fetched. Report rendered:
113 KB of self-contained HTML, 264 nodes, no script breakout.

---

## 3. The bug the live run found

**`pages_fetched: 0`** on the very first run. 40 URLs discovered, **zero pages
retrieved**.

Cause: sitemap discovery (Path A) ran first and filled all 40 node slots, so
`graph.at_capacity()` was already true when the DOM crawl began — and both crawl
loops used capacity as a *stop* condition. They broke out before fetching
anything.

The consequence is severe and silent: no HTML captured, so no link graph, no
in-degree, no orphan detection, and Signals 1 (ARIA), 4 (Schema.org) and 5
(link centrality) starve. The crawl reports a healthy-looking URL count while
producing almost no evidence.

**Capacity must stop *discovering* new nodes, not stop *fetching* known ones.**
`graph.add()` already refuses new nodes when full, so the frontier drains
naturally — the loop guard was both wrong and redundant. Fixed in the sync and
async paths, with regression tests in both.

Effect on the same live crawl:

| Metric | Before | After |
| :--- | ---: | ---: |
| pages fetched | 0 | 15 |
| from DOM links | 1 | 38 |
| orphans (of 40) | 40 | 2 |
| elapsed | 40.4s | 10.9s |

Six cycles and 638 passing tests did not catch this, because every fixture site
is smaller than any sane node ceiling — the condition simply never arose. This
is the entire argument for running against something real.

---

## 4. Findings that need a decision

Neither is a bug in the code. Both are the specification meeting reality.

### 4.1 Path A starves Path B on any large site

`DOM-only: 0` on both runs — the DOM crawl contributed **no** URLs that sitemaps
had missed, which is the headline capability of 3-path discovery.

The mechanism: HighRadius publishes ~3,145 sitemap URLs. Path A runs first and
consumes the entire node budget (`from_sitemap: 250` = the full ceiling,
`truncated: True`). By the time Path B runs, `graph.add()` refuses every new URL
it finds, so a page absent from the sitemap can never be recorded.

This defeats the module's stated purpose **precisely on the sites where it
matters most**. `HIGHRADIUS_CRAWL_AUDIT_RECORD.md` §4 lists the pages this was
built to find — `/code-of-ethics/`, `/anti-corruption-and-bribery-policy/`,
`/human-rights-policy/` — and the current budget allocation guarantees they are
excluded whenever the sitemap is larger than the budget.

Options, none yet chosen:

1. **Reserve budget for DOM-only discoveries** — cap Path A at, say, 80% of
   `max_pages`, leaving headroom that only Path B can fill. Simple, and directly
   targets the capability being lost.
2. **Run Path B first.** Inverts the starvation rather than removing it.
3. **Separate budgets per path.** Most explicit, most parameters.

I recommend (1), but it changes what a crawl returns and belongs in an ADR.

### 4.2 The 2% escalation assumption is wrong by ~50x

`low confidence: 246 / 250` — **98% of pages** fell below the 0.85 escalation
threshold.

ADR 0005's cost model assumes ≤2% escalation, and its own arithmetic shows the
`<$0.05` target needs ≤0.5%. At the observed rate the same 20,000-page crawl
would make ~19,600 LLM calls rather than ~400 — roughly **$13–14 per crawl
instead of $0.05**, a ~275x miss.

Why so low: most pages were seen by the sitemap signal alone (weight 0.20,
confidence 0.75), which normalises to 0.75 — below the 0.85 threshold. Signals
1 and 4 need fetched HTML, and only 101 of 250 pages were fetched at depth 2.

Three things this does *not* mean:

* It is not a defect in the consensus maths. 0.75 is the honest confidence of a
  single sitemap signal.
* It is not necessarily the steady-state rate. Fetching more of the site would
  raise multi-signal agreement.
* It does not affect current spend: Layer 3 has no implementation, so escalation
  cost is £0 today. **But the cost model is now known to be untrustworthy**, and
  wiring up an LLM without recalibrating would be expensive.

This is exactly what the golden corpus is for, and it is now an urgent
prerequisite rather than a nice-to-have.

### 4.3 Throughput: 3.2–3.7 pages/sec

Against a "20,000 pages in 15–30 seconds" target, which implies **~666 requests
per second sustained against a single host**. That is not a polite crawl; it is
indistinguishable from a denial-of-service, and would get the source IP banned.

The observed rate is governed by `default_requests_per_minute = 60` in the
per-host token bucket — that is the crawler being *correct*, not slow. The
target appears to assume pages arriving from cache or many hosts in parallel,
not one server. It should be restated against a realistic constraint.

---

## 5. What landed

**`scripts/run_crawl.py`** — the operator CLI. Goes through the governed
`PageClassificationTool`, so a run inherits SSRF validation, robots compliance,
throttling and audit logging. Defaults are deliberately timid (50 pages, depth
1, concurrency 3) because it crawls somebody else's server. Prints a full
breakdown and writes the HTML report.

**Capacity fix** in `discovery.py` and `async_discovery.py`, plus a regression
test in each naming the live crawl that found it.

---

## 6. Corrections

**"Python outbound requests hang."** Stated in cycles 0001 and 0003. **Wrong.**
I concluded it from `urllib` and PowerShell, and never tested `httpx` — which
works fine and reached highradius.com on the first attempt. The live validation
I had been describing as blocked was available for at least four cycles. I
should have tested the library the project actually uses before generalising.

**Cycle 0006 §6 called throughput "unmeasured".** It is now measured: 3.2–3.7
pages/sec under polite defaults. See §4.3 for why that is the correct number
rather than a disappointing one.

---

## 7. Explicitly not done

| Item | Status |
| :--- | :--- |
| Path A / Path B budget split | **Diagnosed, not fixed.** Needs a decision — see §4.1 |
| Escalation-rate recalibration | **Diagnosed, not fixed.** Needs the corpus — see §4.2 |
| Throughput target restatement | Needs a decision on what the real target is |
| Golden corpus | Still not started, now the top priority |
| `LlmPageClassifier` / Layer 2 | Protocols only |
| Sitemap/CMS pagination | Carried from cycle 0004 |
| Report scalability at 20k nodes | Untested; 264 nodes renders fine |

One observation not yet investigated: `sitemap_doctype_rejected` fired once
during the live run. That is the XXE guard working, but it may have been a
legitimate sitemap served with a DTD, or an HTML error page. Worth confirming
before assuming the guard is over-strict.

---

## 8. Files changed

**New**: `scripts/run_crawl.py`

**Modified**: `src/modules/seo/page_classifier/discovery.py`,
`src/modules/seo/page_classifier/async_discovery.py` (capacity fix),
`tests/modules/seo/test_discovery.py`,
`tests/modules/seo/test_async_discovery.py` (regression tests)

---

## 9. Follow-ups

1. **Decide the budget split** (§4.1) and record it as an ADR.
2. **Golden corpus** — now blocking, because §4.2 makes the cost model
   untrustworthy and only labelled data can recalibrate it.
3. **Restate the throughput target** against polite single-host crawling.
4. Investigate the rejected sitemap.
5. Sitemap/CMS pagination.
