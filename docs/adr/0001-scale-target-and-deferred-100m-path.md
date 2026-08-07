# ADR 0001: Build for 20k–500k URLs, defer the 100M path behind interfaces

- **Status**: Accepted
- **Date**: 2026-08-06
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Two specifications state incompatible scale targets:

- `docs/PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md` and the Phase 1 Master Blueprint
  target **20,000 pages in 15–30 seconds**.
- `docs/AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md` targets **10M–500M+ URLs**
  with a scalable Bloom filter, SQLite WAL spill, and a hard 512 MB RAM ceiling.

These are not the same system. A 20k crawl fits comfortably in memory with a Python
`set()` for deduplication and a dict for the graph. A 100M crawl requires a Bloom
filter, disk-backed frontier, streaming batch commits, and forced GC — machinery that
adds substantial complexity and slows the small case.

Building the 100M architecture on day one would delay Phase 1 significantly to serve
a scale no current client requires.

## Decision

Build for **20,000–500,000 URLs**. Do not implement Bloom filters, disk-backed
frontiers, or the streaming batch pipeline now.

However, every component that would need replacing at 100M scale MUST sit behind an
interface from the start:

- `UrlSeenSet` — deduplication. In-memory `set()` implementation now; Bloom filter
  implementation later.
- `CrawlFrontier` — the URL queue. In-memory deque now; SQLite/Redis-backed later.
- `GraphStore` — the site graph `G=(V,E)`. In-memory now; SQLite WAL later.

The **URL normalizer runs at Layer 0 from day one** regardless of scale. It is cheap,
it improves correctness at every scale, and retrofitting it later would invalidate
every stored URL hash.

## Alternatives considered

1. **Build the 100M architecture immediately.** Rejected: large complexity cost paid
   up front for a capability with no current client demand, and it slows the common case.
2. **Build only for 20k with no interfaces.** Rejected: the 100M path would require
   rewriting the crawl core rather than substituting implementations.
3. **Cap at 20k and declare larger sites out of scope.** Rejected: HighRadius alone is
   3,145 URLs, and mid-market e-commerce routinely exceeds 100k.

## Consequences

**Positive**

- Phase 1 ships materially sooner.
- The in-memory implementations are simple enough to be obviously correct, which
  matters while the classifier accuracy is still being tuned.
- The interface boundaries give natural seams for testing.

**Negative**

- Three interfaces exist with a single implementation each, which is mild
  over-abstraction until the second implementation arrives.
- A 100M crawl attempted before the second implementations land will exhaust memory.
  The crawl tool MUST enforce an explicit URL ceiling and fail with an actionable
  error rather than being OOM-killed.

**Follow-up**

- The URL ceiling constant must be configurable via `Settings`, not hard-coded.
