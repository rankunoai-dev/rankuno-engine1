# Cycle 0008: DOM discovery budget reserve

- **Date**: 2026-08-07
- **Scope**: Implement build-log 0007 Finding 1 — stop a large sitemap starving out the pages only the DOM crawl can find.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 646 tests, 94.55% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   35 source files, mypy --strict
=== Tests ===       PASSED   646 passed in 13.42s, 94.55% coverage
ALL GATES PASSED.
```

---

## 2. The problem, restated

Discovery runs Path A (sitemaps) → Path C (CMS) → Path B (DOM). HighRadius
publishes ~3,145 sitemap URLs, so on any budget below that Path A filled every
slot before the DOM crawl started. `SiteGraph.add()` then correctly refused each
new URL Path B found, and `dom_only` was **structurally guaranteed to be zero**.

That defeats the module's headline capability on exactly the sites where it
matters most: the bigger the sitemap, the more certain Path B contributes
nothing.

---

## 3. What landed

**`DEFAULT_DOM_RESERVE_FRACTION = 0.2`.** Sitemap and CMS discovery now stop at
`pre_crawl_budget = max_pages - reserve`; only the DOM crawl may use the full
`max_pages`. The hard ceiling is unchanged — the reserve **redistributes** the
budget, it never enlarges it, and there is a test asserting exactly that.

`DiscoveryReport` gains `dom_reserve` and `dom_reserve_used`. When they are
equal the reserve is exhausted, which means the setting is too small for that
site and sitemap-omitted pages are *still* being dropped. `run_crawl.py` prints
that condition with the remedy, because a silent cap would be the same class of
invisible failure as the bug in cycle 0007.

Threaded through `discover_site`, `adiscover_site`,
`PageClassificationInput.dom_reserve_fraction` (bounded `[0.0, 0.9]`) and a
`--dom-reserve` CLI flag.

Recorded as [ADR 0007](../adr/0007-dom-discovery-budget-reserve.md).

---

## 4. Live validation

Three runs against `highradius.com`, same target, same depth:

| Reserve | `dom_only` | pages fetched | Audit-record pages found |
| :--- | ---: | ---: | :--- |
| none (pre-fix) | 0 | 101 | 0 of 5 |
| 0.2 (new default) | 50 | 147 | 1 of 5 |
| 0.6 | 180 | 230 | **4 of 5** |

The "audit-record pages" are the five listed in
`HIGHRADIUS_CRAWL_AUDIT_RECORD.md` §4 as absent from every sitemap. At a 0.6
reserve the crawl found `/code-of-ethics/`, `/human-rights-policy/`,
`/glossary/` and `/finsider/`.

This is the first time the engine has demonstrated the capability the audit
record was written to describe.

---

## 5. Findings from the validation

### 5.1 The 0.2 default is probably too low

At 0.2 the reserve was exhausted (50/50) and only one of the five target pages
came through. At 0.6 it was *still* exhausted (180/180) — so even then pages are
being dropped.

I have **not** changed the default on this evidence. One site is not a sample,
and HighRadius is unusually sitemap-heavy (3,145 URLs for a site whose primary
navigation is perhaps 40 pages). Setting a default from a single observation is
the same mistake as the uncalibrated weight profiles in ADR 0006.

What the evidence does support: **the exhaustion indicator is the useful
control**, not the default. An operator who sees `180/180 used` knows to raise
it; an operator who sees `12/50` knows the setting is fine.

### 5.2 `UNKNOWN` pages appeared for the first time

`unclassified: 0 → 2`. Not a regression. Before the fix every discovered URL
came from a sitemap, which always yields a Signal 3 opinion. DOM-only pages have
no sitemap entry, so a page with no recognised Schema.org type and no nav
presence genuinely has less evidence.

This is the honest consequence of discovering harder pages, and it is exactly
the population Layer 3 exists for.

### 5.3 Throughput fell to 2.0 pages/sec

From 3.2. Expected: the crawl now *fetches* far more (230 vs 101 pages) because
DOM-discovered URLs have to be retrieved, whereas sitemap URLs were counted
without being fetched. More real work per page, not slower work.

---

## 6. Corrections

Nothing published in cycles 0001–0007 turned out wrong during this cycle.

Build-log 0007 §4.1 proposed three options and recommended reserving budget.
That recommendation is now implemented and validated; ADR 0007 supersedes the
open question.

---

## 7. Explicitly not done

| Item | Status |
| :--- | :--- |
| Right value for the default reserve | **Unmeasured.** 0.2 is a judgement call; the corpus should fit it (§5.1) |
| Adaptive reserve | Not implemented. A second pass could grow the reserve when it exhausts |
| Escalation-rate recalibration | Finding 2 from cycle 0007, untouched. Cost model still untrustworthy |
| Throughput target restatement | Still needed; 20k-in-30s implies ~666 req/s at one host |
| Golden corpus | Still not started, still the top blocker |
| `LlmPageClassifier` / Layer 2 | Protocols only |
| Sitemap/CMS pagination | Carried from cycle 0004 |

**The reserve does not make `dom_only` unbounded.** A site whose sitemap omits
more than the reserved fraction will still drop pages. That is a deliberate
trade — the alternative is an unbounded crawl — but it means the indicator, not
the default, is what an operator must actually watch.

---

## 8. Files changed

**Modified — source**: `discovery.py` (reserve, report fields),
`async_discovery.py` (parameter passthrough), `tool.py` (input field),
`scripts/run_crawl.py` (`--dom-reserve`, exhaustion warning)

**New — docs**: `docs/adr/0007-dom-discovery-budget-reserve.md`

**Modified — tests**: `test_discovery.py` (+7, including a before/after pair
pinning the starvation)

---

## 9. Follow-ups

1. **Golden corpus** — now blocking two separate calibration questions: the
   reserve fraction (§5.1) and the escalation rate (cycle 0007 §4.2).
2. Escalation-rate recalibration, cycle 0007 Finding 2.
3. Restate the throughput target against polite single-host crawling.
4. Consider an adaptive reserve that grows on exhaustion.
5. Sitemap/CMS pagination.
