# Cycle 0011: Multi-page CMS retrieval

- **Date**: 2026-08-07
- **Scope**: Read every page of a CMS collection instead of only the first, and stop crawling markdown files.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 777 tests, 95.15% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   36 source files, mypy --strict
=== Tests ===       PASSED   777 passed in 12.66s, 95.15% coverage
ALL GATES PASSED.
```

35 new tests. All 109 pre-existing discovery tests still pass unchanged.

---

## 2. Why

Build-log 0010 §4 established the causal chain across three live sites:

| Site | CMS coverage | Confidence ≥ 0.85 |
| :--- | ---: | ---: |
| VitaQuest | 95% | 100% |
| Allbirds | 29% | 31% |
| HighRadius | 27% | ~2% |

Confidence tracks CMS coverage almost 1:1, and Allbirds' 29% was traced to a
specific defect: Shopify serves 30 products per page by default, and the engine
read page one and stopped. Every unread record is a page that reaches Layer 3
and costs money.

---

## 3. What landed

### `FetchResult.headers`

Pagination state lives **only** in headers. Shopify signals the next cursor via
`Link`; WordPress reports `X-WP-TotalPages`. The response body of a truncated
collection looks identical to a complete one, so without headers a caller has no
way to know it stopped early — which is exactly how the Allbirds crawl read 35
of a far larger catalogue and reported success.

### Pagination primitives — `discovery_parsers.py`

* `parse_link_header` — RFC 8288, tolerant of unquoted `rel` and malformed input.
* `with_page_param` — **replaces** an existing `page` rather than appending, so a
  retry cannot produce `?page=1&page=2` and let the server pick.
* `wordpress_total_pages` — reads the declared count.

### `_paginate` / `_apaginate`

Three termination signals, in descending reliability:

1. **`Link: rel="next"`** — authoritative when present.
2. **`X-WP-TotalPages`** — lets pagination stop *exactly*. Requesting a page past
   the end returns `rest_post_invalid_page_number`, so probing works but wastes a
   request and logs an error on the client's server. A test asserts we never ask.
3. **Empty or repeated page** — the universal fallback.

The repeat check is the one that matters most in practice. A server that ignores
`page` and serves the same response forever would otherwise run to the ceiling,
making 40 pointless requests against a client's site and collecting duplicates.
The test asserts exactly two requests in that case: one real page, one repeat
detected, stop.

`MAX_CMS_PAGES = 40` bounds the worst case at 4,000 WordPress records or 10,000
Shopify ones — past the point where the node budget binds instead.

### `.md` filtered from crawlable links

`allbirds.com/agents.md` was observed entering the graph as a page and being
classified `UNKNOWN` at 0.0 confidence (build-log 0010 §7).

**`.txt` was deliberately not added.** `llms.txt` and `llms-full.txt` are the AI
crawler manifests Phase 7's answer-readiness audit reads, so filtering `.txt`
would blind a later phase to files it specifically needs. There is a test
asserting `llms.txt` remains crawlable, so a future tidy-up cannot quietly
remove it.

---

## 4. Corrections

**The requested file was wrong, and I did not flag it before starting.** The
brief said to add `.md` to `url_rules.py`; the non-page extension list actually
lives in `discovery_parsers.py`. I put it where the filter is. Worth recording
because it is the kind of small divergence that is invisible in a diff.

**I wasted time measuring badly.** After implementing, I re-crawled Allbirds live
to read the new CMS record count — three times, at roughly two minutes each. The
per-host token bucket throttles the extra pagination requests to ~1/second, so
each run spent ~80 seconds on CMS fetching alone. That is the crawler being
correct, but re-crawling a third-party site to read one number the tests already
prove was the wrong call: slow, repeatedly hitting someone else's server, and
uninformative.

Nothing published in cycles 0001–0010 turned out wrong during this cycle.

---

## 5. Explicitly not done

| Item | Status |
| :--- | :--- |
| **Live confirmation of the coverage improvement** | **Not obtained.** See below |
| Reviewing the draft worksheets | 141 rows, still 0 reviewed |
| Escalation-rate recalibration | Blocked on the corpus |
| `HEADLESS_SPA`, `MULTI_REGION`, `LARGE_CATALOGUE` labels | Still zero |
| Recall gap | 3 of 13 HighRadius labels never discovered; uninvestigated |

### The measurement was not taken

Sandbox network access disappeared partway through this cycle. A direct probe of
`allbirds.com/products.json` — and then a control request to `highradius.com`,
which had responded in ~2 seconds earlier the same session — both timed out.

So the improvement is **proven against mocks, not observed in production**:

* Pagination reads every page under cursor, `X-WP-TotalPages` and `?page=N`
  schemes, and terminates correctly on empty pages, repeated pages, mid-collection
  errors and the ceiling. All asserted.
* The predicted effect — Allbirds moving from 35 records toward its full
  catalogue, and confidence rising with it — **has not been measured.**

The causal chain in §2 is a hypothesis supported by three observations. This
cycle removes the mechanism believed to cause it. Whether confidence actually
rises is the next live run's job, and until then the claim should be stated as
expected rather than demonstrated.

---

## 6. Files changed

**Modified — source**: `http_fetcher.py` (`headers` on `FetchResult`),
`discovery_parsers.py` (pagination primitives, `.md` filter),
`discovery.py` (`MAX_CMS_PAGES`, `_paginate`),
`async_discovery.py` (`_apaginate`)

**New — tests**: `test_cms_pagination.py` (35)

---

## 7. Follow-ups

1. **Re-crawl Allbirds when network returns** and record the real CMS record
   count and confidence distribution against §2's table. This is the only
   outstanding item from this cycle.
2. Review the draft worksheets.
3. Then re-run `evaluate_corpus.py` and see whether escalation moves as predicted.
4. Remaining archetypes.
