# ADR 0035: A crawl releases each page body once it has been read

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: AI Lead, Lead AI Systems Engineer (user chose "A: extract at fetch, phased";
  security review of the P4 design PASS WITH CONDITIONS C1–C10; follow-up review PASS WITH
  CONDITIONS R1–R2; the user set the fetch URL ceiling to 8,192 and approved 5,000 links per page)
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
| Canonical URL | 2,048 (`contracts.audit.MAX_URL_LENGTH`) | Dropped: a truncated URL was never named by the site |
| Any fetched or redirect-hop URL | 8,192 (`core.url_safety.MAX_FETCH_URL_LENGTH`) | Fetch refused as `UnsafeUrlError`: not retried, recorded `guardrail_refused` |
| Any extracted link | 8,192 (the same constant) | Dropped inside `extract_page_links` before it is collected (R1) |
| Title / meta / H1 | 500 / 500 / 1000 (already capped) | Truncated |
| Links per page | 5,000 (`MAX_LINKS_PER_PAGE`) | Ignored in document order, counted on `SiteGraph.links_capped`, logged |

Notes on the bounds:

- The first recognised schema type is unchanged by de-duplication and the cap of 8. The length
  rule lives in `_recognised`, which both Signal 4 paths use, so the homepage (body) and every
  other page (stored) agree.
- The worst case a page can keep at every cap at once is ≤ 256 KiB, computed at four bytes a
  character with the 8,192 fetch ceiling (`test_release_bodies.py`, test 12). That bound is a
  **sanity check on the caps, not the safety mechanism**: what a page keeps is measured and
  charged (`retained_page_bytes`), so the budget is right even where the arithmetic is not.
- 5,000 links per page is a judgement, not a measurement of the stored corpus. **An HTML sitemap
  page with more than 5,000 links loses its tail**: the links past the 5,000th are not followed
  from that page (they may still arrive through XML sitemaps or other pages). The overflow is
  counted on `SiteGraph.links_capped` and logged (`page_links_capped`).
- The overflow count is not in `DiscoveryReport`. Adding it there changes the persisted result
  contract (handoff to `api-data-engineer`).

### Link length and link bytes (R1, R2)

The follow-up review measured a 104 KB body with a long same-site `<base href>` and 200
`href="?n"` anchors producing 20,013,290 bytes of link strings, about 193 times the body, because
every relative link resolves to the full base. Two changes close that:

- **R1, length.** `extract_page_links` drops any resolved link longer than
  `MAX_FETCH_URL_LENGTH` before it is added to the result, so the long string is never collected
  or held. It is the same constant the fetcher enforces, defined once in `core.url_safety`.
- **R2, bytes.** While a level is in flight, its pages' link tuples are counted.
  - When a page lands, `charge_links` charges `getsizeof` of the tuple and every string in it,
    both readings when the page redirected.
  - The level loop credits exactly that (`credit_links`) once it has recorded the page. That loop
    has no `await`, and the charge sits in the same no-`await` stretch as the body charge and
    credit (an AST test covers both).
  - `credit_links` clamps against outstanding *link* bytes, logs an over-credit at ERROR, and never
    selects a victim.
  - A level abandoned before it is recorded (build-log 0137 §4.2), and the pages after an
    extraction error in the same level, never credit. Their link charge stays until the crawl
    ends: the safe over-count.
  - Link accounting applies with release on and off. It is not tied to the flag.

### The 8,192-character fetch ceiling is a behaviour change

Before extract-at-fetch, nothing bounded URL length on the crawl path. Now:

- **Over 8,192 characters:** a link is not collected, so it never becomes a node. A URL of that
  length that still reaches the fetcher (a sitemap entry, a seed, a redirect) is refused as
  `guardrail_refused`.
- **2,049 to 8,192 characters:** a URL behaves exactly as on main. It is discovered, fetched and
  classified, and because every node is in the audit spine, `to_audit_dataset` raises
  `AuditExportError` ("profiles do not satisfy the audit contract"), so the workbook build for
  that crawl fails. That failure predates this ADR and is unchanged (confirmed against `1eff2d0`;
  pinned in `test_long_urls.py`). The audit contract is not changed here.

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

**It rolls back body release only.** With it off, every body is retained and the body
accounting is ADR 0031's. It does not undo the rest of this ADR:
- the fetched set and fetch-time extraction (P0–P3)
- the caps and the 8,192 ceiling
- the 5,000-link limit
- link charging

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
  node, or a URL found by a link and never fetched, costs memory uncharged. Its URL string is
  capped at 8,192 characters when it came from a link (R1); a sitemap or CMS entry is not
  length-checked until it is fetched.
- the job-import path (ADR 0034)

## Measured

Method: 2,001 pages of ~1 MB HTML (half carrying one 2-byte character), served in-process to
`PageClassificationTool` through a fake fetcher. Each run is a fresh process, measuring the Windows
peak working set via `GetProcessMemoryInfo` minus the pre-run peak. Median of 3.

| Configuration | MiB / page | Peak after (MiB) |
| :--- | ---: | ---: |
| Before (1eff2d0) | 1.4504 | 2961.4 |
| Release off (rollback) | 1.4525 | 2966.5 |
| Release on, before R1/R2 (5258968) | 0.0245 | 109.3 |
| **Release on (default), with R1/R2** | **0.0247** | **109.5** |

**Extrapolated, not measured:** at 36,000 such pages, release on would peak at about 60 + 36,000 ×
0.0247 ≈ 0.9 GiB; release off would need about 51 GiB, and ADR 0031's budget would stop it long
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
  - adding `links_capped` to `DiscoveryReport`
