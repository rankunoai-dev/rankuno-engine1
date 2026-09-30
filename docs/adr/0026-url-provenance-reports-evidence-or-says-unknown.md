# ADR 0026: A URL's provenance is reported from evidence, or reported as unknown

- **Status**: Accepted (item 1 decided by the user: "same URLs, honest labels")
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

### Item 1 — Screaming Frog gap reason (implemented: same URLs, honest labels)

`merge_reconciled_urls` now passes each page's `DiscoverySource` to `reconcile(...,
engine_sources=)`. The existing rules keep their precedence (malformed markup, repeated-suffix
trap, the four file types, query variant). Only a URL none of them explains is judged on
provenance, where it used to fall through to `SITEMAP_ORPHAN` unconditionally:

| Flags on the engine-only URL | Reason |
| :--- | :--- |
| `dom_link` (with or without others) | `LINKED_NOT_IN_EXPORT` — this crawl reached it by an internal link; the export does not contain it |
| `sitemap`, no `dom_link` | `SITEMAP_ONLY_NO_LINK` — listed in a sitemap; this crawl followed no internal link to it |
| `cms_api` only | `CMS_API_ONLY` — found only through the CMS API |
| all False, or not supplied | `PROVENANCE_UNKNOWN` — never guessed |

Spellings that `normalise()` folds into one gap pool their flags: a link to either spelling counts
as a link to the page.

**What the reconciler still cannot know.** Screaming Frog's configuration: whether it read
sitemaps, its depth or URL limits, its include/exclude rules. So no reason and no gloss claims a
cause on the Screaming Frog side. `LINKED_NOT_IN_EXPORT` says the export lacks the URL, not why.

**Membership of `orphans` is unchanged, by decision.** List mode defines an orphan as "a URL this
engine found that Screaming Frog's own link-following crawl did not" (`url_list_sources.py`
module docstring, "Why 'Orphans Only' is conditional"). Its purpose is to give Screaming Frog, in
list mode, the URLs its crawl did not reach, and linked-but-missed pages are in scope. So
`ReconciliationReport.orphans` is now `reason in ORPHAN_REASONS`. That set holds the four
provenance reasons plus legacy `SITEMAP_ORPHAN`, which is exactly the set the old fallback
covered. `tests/modules/seo/test_screaming_frog_provenance.py` pins membership as identical with
and without provenance on a mixed fixture, and the membership test passes unchanged on the
pre-provenance reconciler.

**Legacy rows.** `SITEMAP_ORPHAN` stays a readable member and is no longer produced. Saved
reconciliations (`.jobs/*.reconciliation.json`, and Postgres job payloads) are not rewritten. They
load unchanged because `UrlGap.reason` is a string, and they keep serving "Orphans Only" unchanged
because that reads the saved `orphans` list. A legacy row was never evidence of a missing link;
it was the fallback for every such URL. So it is now displayed as "cross-checked before discovery
sources were tracked — how it was found is unknown", in the .xlsx/.csv gloss, its workbook tab
("Orphans – pre-provenance"), the reconcile panel, and the tree overlay.

**Measured split.** Across the 20 saved reconciliations in the local `.jobs/` store (21,910
orphan-list entries), binned by the source crawl's own flags. This is what a re-run would now
report:

| Real flags | Entries | Share |
| :--- | ---: | ---: |
| `dom_link` set | 10,437 | 47.6% |
| all False (predates the field / merged) | 4,693 | 21.4% |
| `sitemap`, no `dom_link` (a true sitemap orphan) | 3,852 | 17.6% |
| `cms_api` only | 2,928 | 13.4% |

Only 17.6% of the saved "orphans" were what the old label said. Narrowing membership to them was
considered and rejected: it would have silently removed about 82% of what "Orphans Only" sends,
including the 47.6% that Screaming Frog's crawl missed even though a link reaches them.

## Consequences

- Discovery Method values change for unlinked pages: those without a sitemap flag now read
  `ORPHANED`. Stored results are not rewritten; the column changes on the next crawl.
- `fetch_outcomes` may contain `robots_disallowed`; `transport_error` shrinks by the same count.
  The UI types `fetch_outcomes` as `Record<string, number>`, so no contract change.
- New checkpoints are slightly larger. Old checkpoints load, and admit what they do not know.
- A re-run cross-check reports the four provenance reasons. Workbook tabs are now
  "Orphans – sitemap, no link / CMS API only / linked / source unknown / pre-provenance" instead of
  one "Orphans" tab. The panel's tile reads "Orphans", no longer "Sitemap orphans".
- The orphan count and list are unchanged for the same inputs.

## Not done

- Docstrings in the list-mode files owned by another session (`url_list.py`,
  `url_list_sources.py`, `url_list_routes.py`) still say `EngineGapReason.SITEMAP_ORPHAN` and
  "pages no internal link reaches". Their behaviour is correct; the wording needs a follow-up.
- Phase 2 (referrer URL, full sitemap path, link depth, CMS record on the profile, refusal ledger)
  and Phase 3 (export columns, UI) were out of scope.
