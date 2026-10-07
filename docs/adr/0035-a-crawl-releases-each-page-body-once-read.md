# ADR 0035: A crawl releases each page body once it has been read

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: AI Lead, Lead AI Systems Engineer (user chose "A: extract at fetch, phased";
  security review of the P4 design PASS WITH CONDITIONS C1–C10)
- **Amends**: [ADR 0031](0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md)

---

## Context

A crawl held the HTML of every page it fetched in `SiteGraph._html` until the job ended. On sites
with ~1 MB pages that was about 2 MiB per page in RAM. ADR 0031 bounded the sum across crawls with
a budget that stops the largest over-share crawl cleanly. It explicitly left retaining the HTML at
all to a later decision. On those sites a lone crawl stopped at about 1,400 pages.

An investigation found that no step after the crawl needs HTML from more than one page:

- **Links** were already read at fetch time on the serial path. The async path read them after the
  whole BFS level had landed.
- **Content signals, canonical and robots directives** were already read at fetch time
  (`record_fetch`).
- **The breadcrumb trail** was read after the crawl, in `to_page_evidence`, from each page's own body.
- **JSON-LD Signal 4** was read after the crawl from each page's own body.
- **The header menu** is read from the homepage only, after the crawl (`html_for(base_url)`).
- **"Fetched"** was defined as "has a stored body". Checkpoints and resume read that definition.

## Decision

Read everything at fetch time, keep only the homepage's body, and charge the memory budget for
what a page really keeps. This was delivered in phases, each its own commit, each proven
byte-identical by a golden test (a ~500-page site, serial and async under three completion
orders, compared with a committed snapshot):

- **P0.** The golden test and a `homepage_sink` contract test.
- **P1.** `SiteGraph._fetched`, a set of its own. It is written in `store_html` only after an HTML
  success and dropped on loop eviction. `unfetched_urls` reads it.
- **P2.** The async fetch task extracts links. Links are still recorded after the level, in input
  order. For a redirected page that an earlier sibling evicts, both answers are kept, so link
  resolution stays exactly as the serial path does it.
- **P3.** Breadcrumb section labels and recognised schema.org types are read in `store_html` into
  side tables. `PageEvidence.jsonld_types` is a new optional field. Signal 4 reads the body when
  present, otherwise the stored types.
- **P4.** Bodies are released, with the budget changes and caps below.

### What is released, and when

- **When.** `SiteGraph.store_html` fills the side tables and marks the page fetched. It then keeps
  the body only if `normalize_url(url) == normalize_url(base_url)`; otherwise it does not store
  it, and returns `released = True`.
- **Where the body last lives.** The async fetch task's own frame. Links are extracted there, then
  the task returns, and nothing else holds the body.
- **The homepage.** It is kept under the key it was requested at, so a redirected homepage still
  serves `html_for(base_url)`, the menu parse and `homepage_sink`.
- **The serial path** releases the same way. It has no budget account.

### Bounds on what a page keeps (C1, C2)

Everything a page keeps after its body is gone has a bound:

| Value | Bound | Over the bound |
| :--- | :--- | :--- |
| Breadcrumb label | 256 characters, 12 steps | Truncated (display text) |
| Schema types | 8 distinct, document order, ≤ 256 characters each | Not recognised, on both the body and the stored path |
| Canonical URL | 2048 (`contracts.audit.MAX_URL_LENGTH`) | Dropped: a truncated URL was never named by the site |
| Any fetched or redirect-hop URL | 2048 (`MAX_FETCH_URL_LENGTH`, pinned equal) | Fetch refused as `UnsafeUrlError`: not retried, recorded `guardrail_refused` |
| Title / meta / H1 | 500 / 500 / 1000 (already capped) | Truncated |
| Links per page | 5,000 (`MAX_LINKS_PER_PAGE`) | Ignored in document order, counted on `SiteGraph.links_capped`, logged |

Notes on the bounds:

- The first recognised schema type is unchanged by de-duplication and the cap of 8. The length
  rule lives in `_recognised`, which both Signal 4 paths use, so the homepage (body) and every
  other page (stored) agree.
- The worst case a page can keep at every cap at once is ≤ 128 KiB (asserted in
  `test_release_bodies.py`).
- 5,000 links per page is a judgement, not a measurement of the stored corpus.
- The overflow count is not in `DiscoveryReport`. Adding it there changes the persisted result
  contract.

### The memory budget (C3–C5, C8–C10)

**Charge.**
- When a page lands, `charge(body_bytes, overhead_bytes=LEAN_PAGE_BYTES + retained)`.
  - `LEAN_PAGE_BYTES = 32 KiB` covers a page's structural cost: node, loop-watcher share, and the
    evidence and profile built for it later. It was measured at ~17 KiB end to end on 2,000 small
    pages; the investigation measured 20–36 KiB.
  - `retained` is `SiteGraph.retained_page_bytes`, the measured `getsizeof` of everything the page
    derived from its own body. It is charged on top because the worst case (above) exceeds the
    flat constant. A page cannot make the constant a lie.
- With release off, the overhead is 0 and the accounting is exactly ADR 0031's.

**Credit.**
- `credit(body_bytes)` is called only when `store_html` returned `released`, with the exact count
  charged in the same frame.
- There is no `await` between the charge and the credit (comment plus an AST test).
- There is never a credit on the extraction-error path or any exception path, which is a safe
  over-count. The error's traceback is dropped because its frames held the body.

**Credit rules.**
- `MemoryBudget.credit` takes the lock and raises `ValueError` on a negative count.
- It clamps against outstanding *body* bytes (`landed_body_bytes − credited_body_bytes`), never
  against the total charged, so per-page overhead is never credited away.
- An over-credit is logged at ERROR with the job id and counts only. The test suite fails on that
  log.
- `pages` is never decremented, a credit never selects a victim, and the overrun log is re-armed
  only when the projected total falls below the budget. All counters change only under the lock.

**In-flight reserve.** The reserve uses the landed-body mean, not the charged mean. A released
body still predicts the size of the next one in flight.

### Rollback (C7)

`Settings.crawl_release_page_html` (env `CRAWL_RELEASE_PAGE_HTML`) defaults to `true`.

- `false` retains every body and charges exactly as ADR 0031.
- The tool reads it once per crawl through `get_settings()` and fixes it on the `SiteGraph` at
  construction.
- It is not a `PageClassificationInput` field. A request naming it is refused (422).

## Fair share with credits (C6)

The ADR 0031 invariant holds **structurally**: victim selection is per account and unchanged.
Candidates are still crawls with `pages > 0`, not already stopped, and over
`budget // MAX_CONCURRENT_CRAWLS`; the largest is chosen first, the newest on a tie. A credit only
lowers a projected total and never selects. So a crawl at or under its share is still never stopped
by another organisation's load.

What is **not** true is that every crawl's projected total is at or below what it was before. A
page now costs at least `LEAN_PAGE_BYTES` whatever its size, so:

- `projected ≤ today's + pages × LEAN_PAGE_BYTES + Σ retained`, where `retained` is a page's derived
  bytes (bounded above; typically under 1 KiB). On every site the body credit makes the P4 total
  far smaller in practice; the bound states the worst case against ADR 0031's accounting.
- **Small-page crawls reach their share earlier.** At the default 3072 MiB and 5 slots, the share
  is 614 MiB:
  - at ≥ 32 KiB per page a crawl reaches it at about **19k pages** (614 MiB / 32 KiB ≈ 19,660)
  - under ADR 0031 a site of 10 KB pages reached it at about 60k
  - sites of ~1 MB pages go the other way, from ~280 pages to about 19k
  - a lone crawl may use the whole budget, about 98k pages

### Not counted, so not an OOM guarantee

- sitemap and CMS bodies
- the serial fallback path (no account)
- `/result` reads, deliverables, and Screaming Frog jobs
- discovered-but-unfetched nodes: `LEAN_PAGE_BYTES` is charged per *fetched* page, so a sitemap-only
  node, or a URL found by a link and never fetched, costs memory uncharged. That includes its URL
  string, whose length is not capped.
- the job-import path (ADR 0034)
- links while their level is in flight: bounded by `MAX_LINKS_PER_PAGE`, held until the level is
  recorded, uncharged

## Measured

Method: 2,001 pages of ~1 MB HTML (half carrying one 2-byte character), served in-process to
`PageClassificationTool` through a fake fetcher. Each run is a fresh process, measuring the Windows
peak working set via `GetProcessMemoryInfo` minus the pre-run peak. Median of 3.

| Configuration | MiB / page | Peak after (MiB) |
| :--- | ---: | ---: |
| Before (1eff2d0) | 1.4504 | 2961.4 |
| Release off (rollback) | 1.4525 | 2966.5 |
| **Release on (default)** | **0.0245** | **109.3** |

**Extrapolated, not measured:** at 36,000 such pages, release on would peak at about 60 + 36,000 ×
0.0245 ≈ 0.9 GiB; release off would need about 51 GiB, and ADR 0031's budget would stop it long
before. The extrapolation assumes the per-page cost stays linear.

## Consequences

- A crawl's RAM is dominated by its graph, not by page bodies. The CLAUDE.md §8 statement that a
  crawl holds every page's HTML is no longer true by default.
- `PageEvidence.html` is `None` for every page except the homepage after a crawl. Layer 2/3 have
  no implementation; a text contract for them is future work.
- `html_for(url)` returning `None` no longer means "never fetched"; `unfetched_urls` says that.
- A finished crawl still persists no HTML except the homepage via `homepage_sink`, as before.
- Not done:
  - serial-path budget parity
  - a homepage sidecar for resumed crawls
  - de-duplicating LoopWatcher tails
  - charging links in flight
  - adding `links_capped` to `DiscoveryReport`
