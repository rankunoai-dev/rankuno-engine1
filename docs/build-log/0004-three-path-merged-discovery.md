# Cycle 0004: 3-path merged discovery

- **Date**: 2026-08-07
- **Scope**: Close the last structural gap — produce `PageEvidence` by merging sitemap, DOM link graph and CMS API discovery.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 554 tests, 94.99% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED   All checks passed
=== Type check ===  PASSED   30 source files, mypy --strict
=== Tests ===       PASSED   554 passed in 11.09s, 94.99% coverage
ALL GATES PASSED.
```

| Module | Coverage |
| :--- | ---: |
| `discovery_parsers.py` | 94% |
| `discovery.py` | 87% |

Total 95.95% → 94.99% on 2,176 statements (from 1,841). `discovery.py` at 87% is
now the floor; uncovered lines are ceiling-refusal branches and fetch-failure
paths that need a failing transport to reach.

---

## 2. What this closes

Before this cycle the chain had a hole at the front:

```
[ nothing ] ──?──> PageEvidence ──> signal_parsers ──> cascading_pipeline ──> profile
```

Every parser consumed `PageEvidence`; every test constructed it by hand. Nothing
produced it. That is now closed, and `TestEndToEnd` in the new suite runs
discovery straight into `classify_page()` with no intermediate wiring — the
first time the full path has executed.

---

## 3. What landed

### `discovery_parsers.py` — pure payload parsing (94% coverage)

Mirrors the split in `signal_parsers.py`: parsing here, I/O in `discovery.py`.

**Sitemap XML** — index and urlset, namespace-agnostic because real sitemaps
vary the declared namespace. De-duplicates, bounds at 50,000 entries per the
protocol.

**DOM links** — every `<a href>`, not just navigation. This is where Path B
differs from Signal 1: Signal 1 reads nav structure to infer *hierarchy*, Path B
reads all anchors to find *existence*. Resolves relative URLs, drops external
hosts, strips fragments, and skips non-page assets (images, CSS, archives) —
following those wastes crawl budget and pollutes the graph with nodes that can
never be classified.

**CMS records** — WordPress `/wp-json/wp/v2/pages` and Shopify
`/products.json`. The WordPress parser resolves parent IDs to parent URLs and
marks which records have children, which is precisely what Signal 2 needs and
why it carries the heaviest weight: the database states hierarchy that a flat
slug cannot express.

### `discovery.py` — the merge (87% coverage)

`SiteGraph` accumulates nodes keyed by normalised URL, merging *which paths*
surfaced each one. Sources are kept as independent flags rather than a single
winner, because agreement is information: a URL found by all three is certainly
real, while one found only by a DOM link may be a generated artefact.

`DiscoveryReport` breaks down the contribution of each path, and specifically
reports `sitemap_only` and `dom_only` — the two gap classes the HighRadius audit
identified. The test suite asserts both directions:

- `/code-of-ethics/` is reachable by link and **in no sitemap** — the
  documented HighRadius finding.
- `/orphaned-campaign/` is in the sitemap and **linked from nowhere** — the
  reverse gap, and a real SEO finding rather than a crawl artefact.

The DOM crawl is **breadth-first**, deliberately. When the node ceiling is hit,
what has been captured is the shallow, structurally important part of the site
rather than one arbitrarily deep branch.

`to_page_evidence()` is the join between discovery and classification, carrying
through `sitemap_source` (Signal 3), `cms_record` (Signal 2), link counts
(Signal 5) and retained HTML (Signals 1 and 4).

---

## 4. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| Reject any sitemap containing `<!DOCTYPE` | Add `defusedxml` | No legitimate sitemap carries a DTD. Closes billion-laughs *and* XXE with no dependency, and cannot reject valid input |
| `SiteGraph` is a plain class | A `StrictModel` | Assembled incrementally; `validate_assignment` on every edge insertion costs more than it is worth at 20,000 nodes. Everything it *emits* is a strict model |
| Path C skipped for `UNKNOWN` platform | Always probe | Probing endpoints that are not there wastes requests and, on a sensitive host, looks like scanning |
| Breadth-first DOM crawl | Depth-first | Determines *what survives truncation*, not just traversal order |
| Faceted URLs are never fetched | Fetch then classify | They are classified from the URL alone; fetching them is the combinatorial trap the Amazon-scale rules exist to avoid |
| Truncation is reported | Silently applied | A truncated crawl that looks complete is worse than one that says it stopped |

---

## 5. Bugs found and fixed

### The DOM crawl silently skipped every URL the sitemap already knew

The serious one. `SiteGraph.record_links()` returned only URLs that were **new
to the graph**, and `_crawl_dom` used that return value as its frontier.

Since Path A (sitemaps) runs *before* Path B (DOM crawl), every sitemap URL was
already in the graph by the time the crawler reached it. `record_links` filtered
those out, so they never entered the frontier and **were never fetched**.

The failure mode is what makes this worth recording: discovery would report
hundreds of URLs found, the report would look healthy, and almost no HTML would
be captured — leaving Signals 1 and 4 with nothing to read on the majority of a
site. It is invisible unless you check the response bodies, which is exactly what
`test_retains_html_for_dom_based_signals` does.

Root cause was a conflated concept: "new to the graph" and "not yet crawled" are
different things. A URL known from the sitemap still has to be *fetched*.
`record_links` now returns every target it recorded, and crawl-visited
bookkeeping belongs to the caller's frontier where it always should have.
Regression test added with the reasoning inline.

### A test bug worth noting for the pattern

CMS discovery appeared broken (`from_cms == 0`) because my mock route table was
keyed `"/wp-json/wp/v2/pages?per_page=100"` while `MockTransport` routes on
`request.url.path`, which excludes the query string. The code was correct; the
fixture was wrong. Noted because the symptom — a whole discovery path silently
contributing nothing — looked identical to a real defect.

---

## 6. Corrections

Nothing published in cycles 0001–0003 turned out wrong during this cycle.

One clarification to cycle 0003 §7: it listed "`discovery.py` — not started,
**`PageEvidence` still has no producer**". That is now resolved, and this entry
supersedes it.

---

## 7. Explicitly not done

| Item | Status | Consequence |
| :--- | :--- | :--- |
| `tool.py` | Not started | Discovery and classification both work, but neither is reachable through the governed `BaseTool` pipeline. **Nothing is HITL-gated or audit-logged as a job yet** |
| Async discovery | Not implemented | `discover_site` is synchronous and fetches pages one at a time. The 20k-in-30s target needs the async path; the fetcher already has `afetch()`, discovery does not use it |
| Sitemap pagination | Not handled | WordPress `/wp-json` returns 100 records per page; only the first page is read. **A site with more than 100 pages will have an incomplete Path C** |
| Gzipped sitemaps | Not handled | `.xml.gz` sitemaps are common and are currently skipped |
| `lastmod` / `priority` | Ignored | Parsed sitemaps discard everything but `<loc>` |
| Canonical URL extraction | Not implemented | `PageEvidence.canonical_url` still defaults to the URL; SKU variant clustering needs the real `<link rel="canonical">` |
| Live-site validation | Still none | Every test uses `MockTransport`. **Discovery has never run against a real site** |
| Tree visualizer, Layer 2 classifier, golden corpus | Unchanged | Carried from earlier cycles |

**Path C page-size limit is the most likely near-term surprise.** A WordPress
site with 500 pages will report 100 from the CMS and look like it worked.

---

## 8. Files changed

**New — source**: `src/modules/seo/page_classifier/discovery.py`,
`src/modules/seo/page_classifier/discovery_parsers.py`

**New — tests**: `tests/modules/seo/test_discovery.py` (32),
`tests/modules/seo/test_discovery_parsers.py` (47)

**Modified**: `README.md`, `docs/ARCHITECTURE.md`

---

## 9. Follow-ups

1. **`tool.py`** — bring discovery + classification under `BaseTool` so a crawl
   is governed, audit-logged and HITL-classified as one job (ADR 0003). This is
   now the only thing between here and an invocable end-to-end engine.
2. **Sitemap and CMS pagination** — see §7; the WordPress 100-record limit
   silently under-reports.
3. **Async discovery**, using the fetcher's existing `afetch()`.
4. First live run against a Rankuno-owned site.
5. Golden corpus, archetype-structured.
