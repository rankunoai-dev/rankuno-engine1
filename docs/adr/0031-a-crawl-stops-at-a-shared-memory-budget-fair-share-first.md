# ADR 0031: A crawl stops at a shared memory budget, fair share first

- **Status**: Accepted
- **Date**: 2026-10-05
- **Deciders**: AI Lead, Lead AI Systems Engineer (user approved the plan and the victim policy)

---

## Context

Every crawl keeps the HTML of every page it fetches (`SiteGraph._html`) until its job ends,
because classification reads it after discovery. The server runs up to five crawls at once
(`MAX_CONCURRENT_CRAWLS=5`), and nothing limited how much HTML they held in total. On Railway,
crawls of sites whose pages are about 1.07–1.1 MB on the wire came back `FAILED` with "interrupted
by a server restart". The most likely cause is the container being OOM-killed mid-crawl. A SIGKILL
gives the process no chance to save anything, so every running job is lost, not only the large one.

### What the HTML costs

Measured in-process with a fake fetcher serving generated bodies through the real
`PageClassificationTool.execute()` (probe, async discovery, classification), then
`json.dumps(output.model_dump())`. No network was used. 300 pages per run, concurrency 10:

| Body | Bytes per char | Retained per page | Retained, 300 pages | RSS growth at end of discovery | Peak in classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1.1M chars, ASCII | 1.0 | 1.10 MiB | 330 MiB | +337 MiB | +340 MiB |
| 1.1M chars, one U+2019 | 2.0 | 2.20 MiB | 660 MiB | +668 MiB | +670 MiB |
| 1.1M chars, one emoji | 4.0 | 4.40 MiB | 1320 MiB | +1327 MiB | +1329 MiB |
| 2.0M chars, ASCII | 1.0 | 2.00 MiB | 600 MiB | +608 MiB | +610 MiB |

Three findings shaped the design:

1. **Retained HTML is almost all of the memory.** RSS growth divided by retained bytes was
   1.005–1.03, and classification added at most 3 MiB. Counting retained bytes is therefore a
   faithful proxy, with no need to read RSS.
2. **One character can double a page.** Python stores a string at the width of its widest
   character (PEP 393). A single curly apostrophe makes a whole page 2 bytes per character, which
   is why a page of about 1.1 MB on the wire costs about 2.2 MiB in memory. `sys.getsizeof`
   reports the real width in O(1).
3. **The peak comes before serialisation, not during it.** The result JSON was 0.46 MiB for 300
   pages. By the time `finish()` serialises it, `execute()` has returned and the graph has been
   freed. The highest point for a job is the end of discovery, and it holds through classification.

These figures are from Windows. glibc's allocator on Railway may fragment differently. That was
not measured, and the default below leaves room for it. A real-site crawl was considered and
deliberately not run, because the synthetic results were linear and needed no confirmation.

## Decision

**A process-wide budget on retained crawl HTML.** When the budget is reached, the crawl chosen as
the victim stops at a safe point, classifies what it has, and ends `PARTIAL` with
`stopped_reason = "memory budget reached"`.

* **Configuration.** `Settings.crawl_memory_budget_mib` (env `CRAWL_MEMORY_BUDGET_MIB`), with
  range 256–65536 and default 3072. It is not a request field: `PageClassificationInput` forbids
  unknown fields, so a request that names one is refused with 422. There is no admin route.
* **Counting** (`src/core/memory_budget.py`). `_ahtml` charges `sys.getsizeof(body)` the moment a
  page lands. It does not wait for `store_html`, because a BFS level keeps every body in its
  results list before any is stored. Each crawl's projected bytes are its charged bytes plus its
  concurrency ceiling times its mean page size, which covers bodies still in flight. RSS is never
  read.
* **Victim policy: fair share first, then largest.** Each live crawl is guaranteed
  `budget // MAX_CONCURRENT_CRAWLS`. When the projected total reaches the budget, the candidates
  are crawls that have fetched at least one page and are over their share. The largest is stopped,
  with the latest-started stopped on a tie. One victim is chosen per charge, and later charges pick
  more if the budget is still reached. Consequences of the rule:
  - A crawl at or under its share is never stopped by another tenant's load.
  - A crawl running alone may use the whole budget.
  - A crawl that has fetched nothing is never chosen. If it were, it would retrieve nothing and
    fail as blocked, which is the outcome this decision exists to prevent.
* **Where the stop is honoured.** The stop is checked in `_gather_bounded`, both before and after
  a fetch claims a concurrency slot, and at each BFS level boundary in `_acrawl`, always after the
  operator-cancel check, so "cancelled by operator" wins any race. If the stop lands during the
  last level, the reason is still set, but only when it actually cost fetches. `truncated` is never
  touched, because it means the page ceiling.
* **Registry lifetime.** `_run_job` opens the crawl's account and closes it in its own `finally`,
  on the worker thread, when the crawl really ends. That is not when `cancel_job` releases the
  slot: a cancelled crawl still holds its HTML until it drains, so it stays counted and stays in
  the victim pool. The budget never touches slots, job status, or cancel flags.
* **Tenant visibility.** The reason is a fixed string with no numbers. Byte counts, the share, and
  the job ids of the trigger and the victim are logged server-side only
  (`crawl_memory_budget_victim`). HTML is never logged.

### How the default was derived

For an 8 GiB container (the operator's figure for the Railway plan):

* Reserve 0.5 GiB for the server baseline and the other crawls' non-HTML graphs.
* Reserve 1.5 GiB for memory the budget does not count (see below).
* Divide by 1.10 for RSS overhead (measured 1.03, rounded up) and by 1.25 for allocator margin.

(8 − 0.5 − 1.5) / (1.10 × 1.25) = **4.36 GiB** ceiling. The default is **3 GiB**, below that
ceiling. At the budget, RSS is about 3.1 GiB, which leaves about 4.3 GiB for everything uncounted.

What this means for the affected sites, at about 2.2 MiB per page: 3072 / 5 = 614 MiB per crawl
is guaranteed, about 280 pages each when five crawls run at once. A crawl running alone reaches
about 1,400 pages. The user accepted that ceiling as an interim measure until the HTML itself
stops being retained (below).

## Alternatives considered

* **A hard per-crawl cap of `budget / MAX_CONCURRENT_CRAWLS`.** Simpler, and it gives the same
  tenant guarantee. Rejected because it stops a crawl running alone at about 280 pages of an
  affected site even when the server is otherwise idle.
* **Reading RSS (psutil, or `/proc`).** Rejected. It costs a syscall per page or needs a poller,
  it cannot say *which* crawl to stop, and it would add a dependency to justify. Counting matched
  RSS to within 3%.
* **Refusing admission (429) once memory is high.** Not needed. The fair-share floor already
  guarantees an admitted crawl room for at least its share, and admission cannot stop a crawl that
  grows after it was admitted, which is the actual failure.
* **Lowering `MAX_CONCURRENT_CRAWLS`.** Rejected by the user. It caps throughput for everyone in
  order to bound the worst crawl, and it still bounds nothing for a single large crawl.
* **Stopping retaining, compressing, spilling, or extracting the HTML.** This is the real fix, and
  it is deliberately a separate later step with its own ADR. This decision is the safety net that
  keeps jobs from dying until then.

## Consequences

* A crawl that would have been OOM-killed, taking every concurrent job with it, now ends `PARTIAL`
  with its fetched pages classified. The UI shows the reason through the existing "Crawl stopped
  early — …" notice. The job list labels it "memory budget reached" rather than "stalled/aborted".
* **This is not a process-wide OOM guarantee.** Only DOM-crawl HTML on the async path is counted.
  The following are outside the budget:
  - sitemap and CMS bodies (Paths A and C)
  - the serial discovery fallback
  - `/result` reads (`read_result` loads a whole blob)
  - workbook deliverables
  - Screaming Frog jobs
  - per-node graph structures

  The 1.5 GiB reserve is a sizing assumption, not an enforced bound.
* Pages evicted from `_html` by the loop watcher are not credited back. This over-counts slightly,
  which errs on the safe side.
* `finish()` and `_transition()` still have no terminal-state guard. A job cancelled (and so marked
  `FAILED`) whose thread later finishes can still be overwritten to `PARTIAL`, including with this
  reason. That is a known defect, not addressed here.
* The budget is in-process, like the rate limiter and the cost ledger. Several worker processes
  would each have their own budget.
