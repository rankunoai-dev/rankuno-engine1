# ADR 0026: A URL's provenance is reported from evidence, or reported as unknown

- **Status**: Accepted for items 2–4; **Proposed, awaiting a human decision** for item 1
- **Date**: 2026-09-30
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Every URL this engine captures carries `DiscoverySource` flags (`sitemap`, `dom_link`,
`cms_api`, OR-merged) on `FullPageIntelligenceProfile.discovery_sources`. On the live async crawl
path they are populated correctly. The product question they exist to answer is "why does this
engine find URLs Screaming Frog misses", and that answer is worthless if any layer replaces the
evidence with a guess.

Three read-only investigations found four places that gave a wrong reason:

1. `screaming_frog_reconciler._engine_reason` labels every engine-only URL that is not a file,
   trap, malformed address or query variant `SITEMAP_ORPHAN`. It never sees the flags:
   `reconcile()` receives URL strings only.
2. `NavigationContextClassifier` rule 4 ("sitemap only") tested enum membership and the
   truthiness of a model instance, so it held for every unlinked page and `ORPHANED` was
   unreachable. This fed the "Discovery Method" column of urls.xlsx / urls.pdf.
3. `RobotsDisallowedError` and `UnsafeUrlError` are siblings under `GuardrailViolationError`.
   Every discovery fetch handler tested only `UnsafeUrlError`, so a robots refusal was filed as
   `transport_error` ("no answer at all") about a URL that was never requested.
4. A checkpoint stored URLs only, so a page recovered from one carried all-False flags — the exact
   shape of a Screaming-Frog-merged page (build-log 0069).

## Decision

**The rule.** Provenance is reported from the flags the crawl recorded. Where those flags are
absent, the engine says it does not know. It never substitutes a plausible default.

### Item 2 — Discovery Method (implemented)

`SITEMAP_ONLY` requires `discovery_sources.sitemap`. An unlinked page with no sitemap flag is
`ORPHANED`, including a **CMS-only** page: the enum's meaning is "no links or sitemap entry",
which is true of it. The CMS API is how this engine found the page, not a route a visitor or a
link-following crawler can take, so no better existing member fits.

### Item 3 — robots refusals (implemented)

A new, additive `fetch_outcomes` bucket `robots_disallowed`, with an `OUTCOME_MEANINGS` gloss.
One classifier, `discovery._refusal_outcome_for`, is used by all **six** fetch handlers (the four
named in the brief plus the two CMS-pagination loops, which had the same defect). The exception
hierarchy is unchanged: `http_fetcher` already catches the two classes separately, and making
one a subclass of the other would silently change every `except UnsafeUrlError` in the tree.
`fetch_failures` still counts a robots refusal, as before. `record_fetch` is still not called:
there is no response to record, and fabricating a `FetchResult` would be the kind of invented
evidence this ADR forbids. A per-URL refusal ledger is Phase 2.

### Item 4 — checkpoint recovery (implemented, option a)

The checkpoint payload gains `sources`, a list index-aligned with `urls`, each entry the letters
of the flags set (`"s"`, `"d"`, `"c"`, e.g. `"sd"`, or `""`). Letters rather than objects keep a
file rewritten every ten seconds to a few extra bytes per URL. Both lists are built from one pass
over the graph (`SiteGraph.all_url_sources`), so a URL cannot be paired with a neighbour's flags.

On read, if `sources` is missing (every checkpoint written before this change), mis-sized, or
contains an unknown letter, the whole list is distrusted: flags stay all-False, the output's
`stopped_reason` says "how each URL was found is unknown", and each page's placeholder signal note
says the same. Partial trust is refused because one misaligned entry makes every later pairing
suspect. Option (b) alone was rejected because it would discard evidence that costs almost
nothing to keep.

The placeholder still carries a `SITEMAP_INDEX`-sourced `SignalScore` at confidence 0.0.
`signals_evaluated` requires at least one entry and no `SignalSource` member means "none"; no
consumer reads that signal as discovery evidence. Left as is.

### Item 1 — Screaming Frog gap reason (NOT implemented; decision required)

Proposed derivation, keeping the existing members and their precedence (malformed, trap, file
types, query variant) ahead of it:

| Flags on the engine-only URL | Proposed reason |
| :--- | :--- |
| `sitemap` and not `dom_link` | `SITEMAP_ORPHAN` — listed in a sitemap, no internal link found |
| `cms_api` only | new: found only via the CMS API |
| `dom_link` | new: reached by an internal link Screaming Frog's crawl did not include |
| all False, or URL absent from the result | new: `UNKNOWN` — never guessed |

Reason text would describe only what **this engine** observed. The reconciler cannot know
Screaming Frog's configuration (whether it read sitemaps, its depth or URL limits, its
include/exclude rules), so no reason may claim a cause on the Screaming Frog side. New members
would be additive; saved `ReconciliationSummary` JSON with `SITEMAP_ORPHAN` loads unchanged,
because `UrlGap.reason` and `engine_reasons` are plain strings.

**Why it is not implemented.** `ReconciliationReport.orphans` is *defined* as
`reason == SITEMAP_ORPHAN`. That list is saved beside each reconciliation and is exactly what
Screaming Frog list mode's "Orphans Only" source sends (`url_list_sources.orphan_urls` reads the
saved `orphans` list). Correcting the label therefore changes which URLs are sent. Measured across
the 20 saved reconciliations in the local `.jobs/` store (21,910 orphan-list entries), binned by the
source crawl's own flags:

| Real flags | Entries | Share |
| :--- | ---: | ---: |
| `dom_link` set | 10,437 | 47.6% |
| all False (predates the field / merged) | 4,693 | 21.4% |
| `sitemap`, no `dom_link` (a true sitemap orphan) | 3,852 | 17.6% |
| `cms_api` only | 2,928 | 13.4% |

Only 17.6% of today's "orphans" are what the label says. Changing membership is a product
decision with a visible effect on list-mode dispatches, so it waits for a human.

## Consequences

- Discovery Method values change for unlinked pages: those without a sitemap flag now read
  `ORPHANED`. Stored results are not rewritten; the column changes on the next crawl.
- `fetch_outcomes` may contain `robots_disallowed`; `transport_error` shrinks by the same count.
  The UI types `fetch_outcomes` as `Record<string, number>`, so no contract change.
- New checkpoints are slightly larger. Old checkpoints load, and admit what they do not know.
- Item 1 remains wrong until decided: every non-file engine-only URL is still `SITEMAP_ORPHAN`.

## Not done

- Item 1 (above). Phase 2 (referrer URL, full sitemap path, link depth, CMS record on the profile,
  refusal ledger) and Phase 3 (export columns, UI) were out of scope.
