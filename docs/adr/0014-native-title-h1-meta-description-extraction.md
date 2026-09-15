# ADR 0014: Native title/H1/meta-description extraction, and the pixel-width outcome

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`FullPageIntelligenceProfile` (ADR 0002) carried a resolved canonical URL and an
indexability verdict, but nothing about a page's own title, meta description or H1.
As a direct consequence, `audit_export.py` declared all seventeen `PAGE_TITLES` /
`META_DESCRIPTION` / `H1` catalogue issues `NOT_MEASURED` — not because the rules were
hard to write, but because nothing upstream of the adapter ever read the three
elements those rules need.

This cycle adds native extraction at crawl time, using the standard library's
`html.parser` (no new dependency), and threads the result through the existing
discovery → evidence → profile → audit-export pipeline the same way `canonical_url`
already travels it.

## Decision

**Extract natively, at fetch time, inside `SiteGraph.record_fetch`.**

A new pure module, `src/modules/seo/page_classifier/content_signals.py`, exposes
`ContentSignals(StrictModel)` and `extract_content_signals(html: str) -> ContentSignals`.
It is hooked into `discovery.SiteGraph.record_fetch` at the same guard that already
extracts the canonical tag (`if result.is_html and result.body:`), which is the single
method both `discover_site` (sync) and `adiscover_site` (async) call — so sync/async
parity is structural rather than a second call site that could drift. No change to
`async_discovery.py` was needed or made.

**Eight fields, not seven.** The design brief for this cycle specified eight attribute
names on `ContentSignals` (`page_title`, `page_title_count`, `page_title_outside_head`,
`meta_description`, `meta_description_count`, `meta_description_outside_head`,
`h1_text`, `h1_count`) but later referred to "the 7 new fields" flowing through
`DiscoveredNode` → `PageEvidence` → `FullPageIntelligenceProfile`. That is a miscount in
the brief, not a hidden ninth field to drop: `H1` has no `OUTSIDE_HEAD` catalogue issue
(only `PAGE_TITLES` and `META_DESCRIPTION` do), so the eight fields are exactly what the
seventeen catalogue ids need. All eight are threaded through, with `""` / `0` / `False`
defaults at every layer so a profile persisted before this shipped still deserialises
under `extra="forbid"`.

**Extraction rules, stated once here because they are the load-bearing interpretation
for a tokenizer that builds no DOM:**

- **First-occurrence-wins for text**, matching `document.title` semantics; **every**
  occurrence — including a duplicate and including malformed nesting — increments the
  independent *count*. `PAGE_TITLES_MULTIPLE` reads the count, never whether two
  occurrences' text happens to match.
- **`OUTSIDE_HEAD`** is a one-way flip, `_closed_head`, set the moment a start tag
  arrives whose lowercase name is not in
  `{head, title, meta, link, base, style, script, noscript, html}`. This is a heuristic
  for malformed and no-`<head>` documents, not a read of DOM ancestry — `html.parser`
  builds no tree to read one from.
- **`<noscript>` content is excluded entirely** via a depth counter (it nests), so a
  tracking-pixel fallback `<title>` or `<meta name="description">` inside one is never
  counted, captured, or allowed to flip `_closed_head`.
- **HTML comments require no special handling.** `html.parser` never emits
  `handle_starttag` for markup inside `<!-- -->`, including an unterminated comment
  running to end of document; a test pins this rather than assuming it.
- **Runaway/unterminated tags are truncated, not dropped.** An accumulator stops
  appending once a field reaches its cap (500 / 500 / 1000 characters for
  title / meta description / H1), and any element still open at end-of-document is
  finalised from whatever was collected rather than discarded — the bytes were fetched,
  and a browser would render the truncated text. `extract_content_signals` never raises.

**Fourteen of seventeen ids join `audit_export._RULES` directly**
(`*_MISSING`, `*_MULTIPLE`, `*_OUTSIDE_HEAD`, `PAGE_TITLES_SAME_AS_H1`,
`H1_OVER_70_CHARACTERS`, and the four `*_PIXELS` ids as originally scoped). The three
`*_DUPLICATE` ids are cross-profile and dispatched separately, following the existing
`_over_50k` pattern for `SITEMAPS_XML_SITEMAP_OVER_50K_URLS`
(`_CROSS_PROFILE_RULES`, a superset of the sitemap dispatch that already existed).

**The three `*_MISSING` rules are gated on `profile.indexability not in {UNKNOWN,
NOT_A_PAGE}`** (`_UNFETCHED`, a new frozenset sibling to the existing `_NON_INDEXABLE`).
Without the gate, a URL the crawl never fetched — or a redirect/error/non-HTML response
— would read `page_title == ""` and register as `PAGE_TITLES_MISSING`, which is a false
positive: the crawl said nothing about that page's markup, and "we did not look" must
not read as "the page has no title." No other new rule needed this gate: `MULTIPLE`,
`OUTSIDE_HEAD`, `SAME_AS_H1` and `H1_OVER_70_CHARACTERS` are all falsy on an unfetched
page's `""` / `0` / `False` defaults, which already reads as "no evidence of the defect"
rather than as an ambiguous finding.

### The pixel-width outcome: NOT_MEASURED, by design fallback

The brief's own contingency was exercised: **no pixel-width table was shipped.** The
four `*_PIXELS` ids (`PAGE_TITLES_OVER_561_PIXELS`, `PAGE_TITLES_BELOW_200_PIXELS`,
`META_DESCRIPTION_OVER_985_PIXELS`, `META_DESCRIPTION_BELOW_400_PIXELS`) remain
`NOT_MEASURED`, with `NOT_MEASURED_REASONS` rewritten (not removed) to name only those
four — `PAGE_TITLES` and `META_DESCRIPTION` are otherwise fully measured; `H1` (which
has no pixel ids) is fully measured and its entry was removed outright.

Why: a "true pixel width" requires a static, **verified** per-character glyph-width
table for a specific font and size. This agent session has no network access and no
authoritative font-metrics source to check a reconstructed table against. A table
recalled from training data, retyped from memory into source, is exactly the failure
mode this ADR exists to avoid — it would dress up an unverifiable guess as a measured
fact in a client-facing audit. The brief was explicit that character-count must never
be substituted for pixel width under any circumstance, and that a font-rendering
dependency (e.g. driving a real font engine) was also out of scope (no new dependency,
no non-deterministic cross-platform behaviour in a report that must reproduce
identically on any machine that runs the crawler). Given both substitutes were
foreclosed and no verified table was available, the fallback specified by the brief was
taken: honest `NOT_MEASURED` over a plausible-looking number nobody can stand behind.

**Result: 13 of the 17 ids ship as `MEASURED`** (10 direct rules + 3 cross-profile
duplicates), the 4 pixel ids stay `NOT_MEASURED`. Coverage moves from 16/110 to
29/110 `MEASURED` catalogue-wide.

## Alternatives considered

1. **Render with a real font via a system font library** (e.g. driving `tkinter.font`
   or a native text-shaping API) to measure exact pixel width. Rejected: not a static
   lookup table as scoped, introduces a runtime dependency on font availability that
   differs between the Windows workstation and a Linux CI/CD runner, and would make the
   same page measure differently on different machines — unacceptable in a report a
   client will read as ground truth.
2. **Substitute character count for pixel width**, labelled as an approximation.
   Rejected outright per the brief: a character count is not a pixel width, callers
   would silently trust a number that means something else, and the brief explicitly
   forbids this substitution.
3. **Recall an approximate Arial glyph-width table from training data and ship it.**
   Rejected: "approximate, from memory, unverified" is indistinguishable from wrong to
   a downstream reader, and this module exists specifically to replace guesses with
   measured facts. If a verified table (e.g. extracted from an actual font's metrics
   and checked in as a data file with its provenance recorded) becomes available in a
   future cycle, the four ids can move to `MEASURED` without touching any other rule —
   `pixel_width.py` was scoped as a pure `chars-in -> int-px-out` function precisely so
   it can be dropped in later.

## Consequences

**Positive**

- 13 of 17 previously-`NOT_MEASURED` issues become `MEASURED` with real crawl data;
  `H1` is now a fully-measured category.
- The extraction module is a pure function, exhaustively testable offline, with no new
  dependency and no I/O.
- Sync and async discovery share one implementation by construction (`SiteGraph.record_fetch`),
  which is itself a correction: the brief's design narrative assumed two call sites and
  asked for a mirrored edit in `async_discovery.py`; there is only one.

**Negative**

- The four `*_PIXELS` ids remain `NOT_MEASURED` until a verified glyph-width table is
  sourced — a follow-up item, not a defect in this cycle.
- `page_title` / `meta_description` / `h1_text` are truncated at 500/500/1000
  characters. A title beyond that length is vanishingly rare, but a report reading a
  truncated value should not be mistaken for the page's full markup.
- Duplicate detection (`*_DUPLICATE`) is not gated on indexability, matching the
  existing `_over_50k` precedent — a shared title between an indexable page and a 404
  error page with the same generic title would register. This mirrors existing
  crawler behaviour rather than introducing a new inconsistency, and is noted here so
  it is a recorded choice rather than a silent one.

**Follow-up**

- Sourcing and verifying a per-character glyph-width table (with its provenance
  recorded) is required before the four `*_PIXELS` ids can move to `MEASURED`.
- `docs-scribe` owns the build-log entry for this cycle (§8b) and any README/
  `docs/ARCHITECTURE.md` updates.
