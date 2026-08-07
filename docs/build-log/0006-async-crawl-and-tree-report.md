# Cycle 0006: Concurrent crawl path & interactive hierarchy report

- **Date**: 2026-08-07
- **Scope**: Make the throughput target reachable, and produce the operator-facing HTML report.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 638 tests, 94.50% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED   All checks passed
=== Type check ===  PASSED   34 source files, mypy --strict
=== Tests ===       PASSED   638 passed in 13.20s, 94.50% coverage
ALL GATES PASSED.
```

| Module | Coverage |
| :--- | ---: |
| `tree_visualizer.py` | 98% |
| `async_discovery.py` | 93% |
| `tool.py` | 89% |

Total 95.10% → 94.50% on 2,484 statements (from 2,273). The dip is the async
error branches, which need a failing transport mid-flight to reach.

---

## 2. What landed

### `async_discovery.py` — the concurrent crawl

The serial path fetches one page at a time. At even 100ms per request that is
**33 minutes for 20,000 pages**, against a 15–30 second target. Concurrency here
is not an optimisation; it is the difference between the specification being
met and being unreachable.

**Level-synchronous breadth-first**, not a free-running worker pool. Each depth
level is fetched concurrently, then the next begins. The idle time at each
barrier is real, and it buys two things worth more:

* **Truncation stays meaningful.** When the node ceiling is hit, what has been
  captured is every page down to depth *k* — a complete shallow crawl. A free
  pool captures an arbitrary slice, which is far less useful to an auditor.
* **Depth is correct by construction.** A page's depth is the level it was
  fetched at, with no reconciliation of racing discoveries of the same URL.

**Politeness is not implemented here, deliberately.** `HttpFetcher` already
applies a per-host token bucket honouring `Crawl-delay`, so raising
`concurrency` cannot make the crawler rude to a single host — it makes it wait.
The semaphore bounds local resources (sockets, memory), not remote impact. That
distinction is stated in the module docstring because someone will otherwise
read the semaphore as the politeness control and tune it wrongly.

**The tests assert behavioural equivalence with the serial path** — same URLs,
same per-path attribution, same graph nodes, same orphans. If concurrency
changes what is found, it is not an optimisation, it is a different crawler.
There is also a test that any concurrency from 1 to 50 produces identical
results, because correctness must not depend on how many requests are in flight.

### `tree_visualizer.py` — the operator-facing report

Per `docs/TREE_VISUALIZER_SPECIFICATION.md`. Single self-contained HTML file:
no CDN, no external stylesheet, no build step. It has to open from a filesystem,
survive being emailed, and work on a machine with no network.

Structure comes from the **URL path**, not `hierarchy_level` — the path is what
actually nests, while `hierarchy_level` classifies a page's *role* and
deliberately does not imply containment. An L1 hub can live at any path depth;
that is the entire point of decoupling the two axes. Intermediate segments with
no crawled page become unlabelled structural nodes so a child is never orphaned
by a missing parent.

Badge colours are pinned to the specification by test. `UNKNOWN` is red rather
than neutral: Phase 1's goal is zero of them, so they should be alarming rather
than blending in. The header highlights the unclassified count **only when
non-zero**, so a clean run does not cry wolf.

### `tool.py` — async wired in

`concurrency` and `use_async_crawl` added to the input. `execute()` runs the
concurrent path via `asyncio.run()`, which is exactly ADR 0003's design:
governance synchronous because it is per-job, the crawl async because it is
per-request.

The probe pass stays synchronous and runs *before* the event loop starts. It is
six requests; parallelising it saves nothing and running it outside the loop
avoids needing an async twin of `probe_site`.

---

## 3. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| Level-synchronous BFS | Free-running worker pool | Determines *what survives truncation*, and makes depth correct without reconciliation |
| Semaphore bounds local resources only | Use it for politeness | The per-host bucket already handles politeness; conflating them would let someone "tune" concurrency into rudeness |
| Failed task → `None`, siblings continue | `asyncio.gather` default | One unreachable page must not abandon the other 19,999 |
| Tree nests by URL path | Nest by `hierarchy_level` | Level is a role classification, not a containment relation |
| `createElement` + `textContent` in JS | `innerHTML` | Defence in depth: crawled strings cannot become markup even if server-side escaping missed something |
| Probe stays synchronous | Add `aprobe_site` | Six requests; an async twin is code with no benefit |

---

## 4. Bugs found and fixed

### XSS in the report — closed before it shipped, not after

Every string the visualizer renders comes from a **crawled third-party site**.
A page whose URL contains `</script><script>fetch('//evil')</script>` is the
obvious attack on any tool that renders crawl output.

`json.dumps` does **not** escape `<`, so a `</script>` sequence inside a URL
would terminate the script block early and inject markup. Two defences, both
unconditional: all interpolated text is HTML-escaped including quotes, and the
embedded JSON has `<`, `>` and `&` escaped to `\uXXXX`. Six tests cover the
specific attacks, including one asserting the payload is still **valid JSON**
after escaping — escaping that corrupts the data would be its own bug.

Also `rel="noopener noreferrer"` on the external links, since `target="_blank"`
without it is a tabnabbing vector. Tested.

### A fixture bug that masqueraded as a transport bug

14 async tests failed with `AssertionError` deep inside httpx's
`_send_single_request`. Cause: the mock route tables returned **shared
`httpx.Response` instances**. Once a response's stream is consumed it cannot be
re-read, and the async client additionally asserts the stream is an
`AsyncByteStream`.

The failure surfaced as an httpx internal assertion with no useful message,
which is worth recording — the instinct is to suspect the code under test. The
fix is that fixtures must build a **fresh response per request**. I applied it
to the tool tests too, where it was latent: those passed only because each route
happened to be requested once per client type.

---

## 5. Corrections

Nothing published in cycles 0001–0005 turned out wrong during this cycle.

Cycle 0005 §7 stated "**the 20k-in-30s target is not met and cannot be met on
this path**". The path now exists and is wired in. Whether the target is *met*
remains unmeasured — see §6 — so that claim is superseded only in part: the
architectural blocker is gone, the measurement has not been taken.

---

## 6. Explicitly not done

| Item | Status | Consequence |
| :--- | :--- | :--- |
| **Throughput measurement** | Never taken | The async path is *capable* of concurrency, but **no benchmark has been run**. "20k pages in 15–30s" remains an unverified claim, now for want of measurement rather than architecture |
| Live-site validation | Still none | Every test uses `MockTransport`. **Nothing has touched a real server across six cycles** |
| `LlmPageClassifier` implementation | Protocol only | Layer 3 never runs |
| Layer 2 classifier | Protocol only | Cascade falls 1 → 3 |
| State checkpointing | Not implemented | An interrupted crawl still loses all work |
| Golden corpus | Not started | Accuracy claim still unverifiable |
| Sitemap/CMS pagination | Not handled | Carried from cycle 0004: WordPress Path C reads only the first 100 records |
| Tree report JSON/CSV export | Not implemented | `CLAUDE_HANDOFF` §5.9 mentions it; only HTML is produced |
| Report pagination | Not implemented | A 20,000-node tree renders every node into one DOM. Fine at 3,000; **untested at 20,000 and likely sluggish** |

**Two of these are now the honest headline.** The engine is architecturally
complete for Phase 1 and has never been run against a real website or measured
for speed. Every performance and accuracy number in the specifications remains a
claim rather than a result.

---

## 7. Files changed

**New — source**: `src/modules/seo/page_classifier/async_discovery.py`,
`src/modules/seo/page_classifier/tree_visualizer.py`

**New — tests**: `tests/modules/seo/test_async_discovery.py` (22),
`tests/modules/seo/test_tree_visualizer.py` (33)

**Modified**: `discovery.py` (endpoint tables made public so the async path
shares one definition), `tool.py` (concurrency inputs, async dispatch),
`test_page_classifier_tool.py` (fixture fix), `README.md`,
`docs/ARCHITECTURE.md`

---

## 8. Follow-ups

1. **Run it against a real site.** Six cycles of mocks. This is overdue and will
   surface things no fixture can.
2. **Benchmark the async path** against the 15–30s target, and record the real
   number in place of the specification's claim.
3. Golden corpus, archetype-structured.
4. Report scalability at 20k nodes — virtualise or paginate if it drags.
5. Sitemap/CMS pagination.
