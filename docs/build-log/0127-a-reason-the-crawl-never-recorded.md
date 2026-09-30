# Cycle 0127: A reason the crawl never recorded

- **Date**: 2026-09-30
- **Scope**: URL provenance, Phase 1 only: stop the four places that stated a wrong reason for how
  a URL was found (Screaming Frog gap reason, navigation "Discovery Method", robots refusals in the
  fetch ledger, checkpoint-recovered pages)
- **Commit**: `a80648a` (items 2-4) and `89e90ce` (item 1), integrated on branch
  `provenance-integration` and pushed to `origin/main` as `5c0d149` (fast-forward from `954c9fd`)
- **ADR**: [0026](../adr/0026-url-provenance-reports-evidence-or-says-unknown.md)
- **Quality gate**: GREEN on the combined tree of cycles 0127, 0128 and 0129. `pytest --cov=src`
  exit code 0, "Required test coverage of 85.0% reached. Total coverage: 92.90%". No pass count
  printed; see §1.

## 0. Background

The user asked for a feature that explains how each URL was found (sitemap, CMS API, DOM link),
mainly so the engine can explain why it captures URLs Screaming Frog misses. They asked for
feasibility, a plan and every breaking point before any code.

Three parallel read-only investigations found that the per-URL flags already exist
(`DiscoverySource`: `sitemap`, `dom_link`, `cms_api`, OR-merged on
`FullPageIntelligenceProfile.discovery_sources`) and are set correctly on the live async crawl
path. The problem was the reverse of the one asked about: the engine gave wrong reasons in four
places and exposed the right ones almost nowhere.

The plan was split into four phases. The user approved **Phase 1, "stop the wrong answers"**
only. Phases 2 to 4 are listed in §6. The two crawl bugs found along the way were fixed as
separate cycles: [0128](0128-a-link-resolved-against-the-address-that-was-asked-for.md) (link
resolution) and [0129](0129-two-pages-that-differed-only-by-case.md) (path case).

## 1. Gate results

All three branches (`provenance`, `fix-redirect-links`, `fix-path-case`) were merged into
`provenance-integration` with no conflicts. The gate below was run once, on the combined tree, by
the lead. The same block appears in 0128 §1 and 0129 §1.

```
ruff format --check .                    -> 550 files already formatted
ruff check .                             -> All checks passed!
mypy src                                 -> Success: no issues found in 152 source files
scripts/export_ui_contract.py --check    -> UI contract is up to date.
scripts/drift_check.py                   -> PASSED: no drift detected across 215 markdown files.
pytest --cov=src                         -> exit code 0
                                            Required test coverage of 85.0% reached. Total coverage: 92.90%
```

The pytest pass-count summary line did not print. This is the same output-buffering artifact
recorded in build-log 0098 §1 and 0100 §1. No test count is claimed for this cycle.

UI:

```
tsc --noEmit                             -> exit 0
vitest                                   -> Test Files  47 passed (47)
                                            Tests  605 passed (605)
npm run build                            -> ✓ built in 8.07s
```

Every fix's regression tests were run by the lead against the pre-fix code (fail) and against the
fix (pass). The scribe did not re-run the gate. The `drift_check.py` figure above predates these
three entries; the scribe's own run is in §9.

## 2. What landed

### 2.1 Screaming Frog gap reason (item 1, `89e90ce`)

`screaming_frog_reconciler._engine_reason` decided why a URL was engine-only from the URL string
alone. After the malformed-markup, repeated-suffix trap, four file-type and query-variant rules, it
fell through to `SITEMAP_ORPHAN` unconditionally. It could not do better: `reconcile()` received
bare URL strings from `screaming_frog_merge.py`, so the flags never reached it.

Now `merge_reconciled_urls` passes each page's `DiscoverySource` through
`reconcile(..., engine_sources=)`. The earlier rules keep their order. Only a URL none of them
explains is judged on provenance:

| Flags on the engine-only URL | Reason |
| :--- | :--- |
| `dom_link` (with or without others) | `LINKED_NOT_IN_EXPORT` |
| `sitemap`, no `dom_link` | `SITEMAP_ONLY_NO_LINK` |
| `cms_api` only | `CMS_API_ONLY` |
| all False, or not supplied | `PROVENANCE_UNKNOWN` |

`dom_link` wins because it is the strongest statement the crawl can make. Spellings that
`normalise()` folds into one gap pool their flags. The reason text describes only what this engine
observed. It never claims anything about Screaming Frog's configuration (sitemap reading, depth,
URL limits, include/exclude rules), because the reconciler cannot know it.

`ReconciliationReport.orphans` is now `gap.reason in ORPHAN_REASONS`, where `ORPHAN_REASONS` is
the four new reasons plus legacy `SITEMAP_ORPHAN`. See §3.1 for why membership did not change.

The UI and exports followed:

- `ReconcilePanel.tsx` and `lib/treeOverlay.ts` label each reason. The "Sitemap orphans" tile is
  now "Orphans". A note claiming Screaming Frog "cannot reach these by following links" was
  removed as untrue.
- The reconciliation workbook's single "Orphans" tab became five: "Orphans – sitemap, no link",
  "Orphans – CMS API only", "Orphans – linked", "Orphans – source unknown" and
  "Orphans – pre-provenance" (`SHEET_TITLES` in `server.py`).
- Legacy `SITEMAP_ORPHAN` rows load unchanged (`UrlGap.reason` is a string) and are glossed as
  "Cross-checked before discovery sources were tracked. How this crawl found it is unknown; re-run
  the cross-check to find out." Stored `.jobs/*.reconciliation.json` files and Postgres job
  payloads are not rewritten.

### 2.2 Navigation "Discovery Method" (item 2, `a80648a`)

`NavigationContextClassifier` rule 4 ("sitemap only") combined a tautological enum-membership check
with `and page.discovery_sources`. `discovery_sources` is a Pydantic model instance, which is always
truthy. The rule therefore held for every unlinked page, and `ORPHANED` was unreachable. The rule
now tests `discovery_sources.sitemap`. An unlinked page with no sitemap flag, including a CMS-only
page, is `ORPHANED`.

This value feeds the "Discovery Method" column of `urls.xlsx` / `urls.pdf` and the GSC integrated
report table. Stored results are not recomputed. The column changes on the next crawl.

### 2.3 Robots refusals in the fetch ledger (item 3, `a80648a`)

`RobotsDisallowedError` and `UnsafeUrlError` are siblings under `GuardrailViolationError`, not
parent and child. Every discovery fetch handler caught only `UnsafeUrlError` as a refusal, so a
robots refusal fell through to `transport_error` ("no answer at all") for a URL that was never
requested.

A new additive `fetch_outcomes` bucket, `robots_disallowed`, with an `OUTCOME_MEANINGS` gloss ("The
site's robots.txt disallows this path, so it was never requested — a choice this crawler made, not
a network failure."). One classifier, `discovery._refusal_outcome_for`, is used by all six fetch
handlers: three in `discovery.py`, three in `async_discovery.py`. `fetch_failures` still counts a
robots refusal. `record_fetch` is still not called, because there is no response to record.

### 2.4 Checkpoint-recovered pages (item 4, `a80648a`)

A checkpoint stored URLs only. A page recovered from one carried all-False flags, which is exactly
the shape of a page merged in from a Screaming Frog export (build-log 0069), so the two were
indistinguishable.

The checkpoint payload gains `sources`, a list index-aligned with `urls`. Each entry is the letters
of the flags set: `"s"`, `"d"`, `"c"`, combinations such as `"sd"`, or `""`. Both lists come from
one pass over the graph (`SiteGraph.all_url_sources`), so a URL cannot be paired with a neighbour's
flags. On read, if `sources` is missing, the wrong length, or holds an unknown letter, the whole
list is distrusted: flags stay all-False, `stopped_reason` says how each URL was found is unknown,
and each placeholder page's signal note says the same. Old checkpoints load.

## 3. Design decisions

### 3.1 Same URLs, honest labels (user decision)

Correcting the reason could have changed what "Orphans Only" list mode sends to Screaming Frog
(`src/api/url_list_sources.py` reads the saved `orphans` list). Two options were put to the user:
narrow `orphans` to true sitemap orphans, or keep membership and relabel. The user chose **"same
URLs, honest labels"**.

The reason is list mode's own definition: an orphan is "a URL this engine found that Screaming
Frog's link-following crawl did not". Its purpose is to hand Screaming Frog, in list mode, the URLs
its crawl did not reach. A linked page Screaming Frog missed is in scope.

Membership is identical by construction. `ORPHAN_REASONS` is the four new reasons plus legacy
`SITEMAP_ORPHAN`, and the new fallback only ever returns one of those four, which is the same set
of URLs the old unconditional fallback covered. `tests/modules/seo/test_screaming_frog_provenance.py`
pins membership as identical with and without provenance on a mixed fixture.

Measured across the 20 saved reconciliations in the local `.jobs/` store (21,910 orphan-list
entries), binned by the source crawl's own flags:

| Real flags | Entries | Share |
| :--- | ---: | ---: |
| `dom_link` set | 10,437 | 47.6% |
| all False (predates the field, or merged) | 4,693 | 21.4% |
| `sitemap`, no `dom_link` (a true sitemap orphan) | 3,852 | 17.6% |
| `cms_api` only | 2,928 | 13.4% |

Only 17.6% of saved "sitemap orphans" matched the label. Narrowing membership to them would have
silently removed about 82% of what "Orphans Only" sends, including the 47.6% that Screaming Frog
missed even though a link reaches them.

### 3.2 CMS-only unlinked pages are `ORPHANED`

No existing `NavigationDiscoveryMethod` member says "found through the CMS API". `ORPHANED` means
"no links or sitemap entry", which is true of such a page. The CMS API is how this engine found it,
not a route a visitor or a link-following crawler can take. A new enum member was not added in
Phase 1.

### 3.3 Robots: a new outcome, not a new hierarchy

Making `RobotsDisallowedError` a subclass of `UnsafeUrlError` would have fixed the handlers in one
line. It would also have silently changed every `except UnsafeUrlError` in the tree, and
`http_fetcher` already catches the two separately on purpose. A shared classifier was chosen
instead. Fabricating a `FetchResult` to call `record_fetch` was rejected as invented evidence, the
thing ADR 0026 forbids.

### 3.4 Checkpoint sources: letters, all-or-nothing trust

Letters rather than objects keep a file rewritten every ten seconds to a few extra bytes per URL.
Partial trust of a damaged `sources` list was refused, because one misaligned entry makes every
later pairing suspect. Dropping the flags and only labelling recovered pages "unknown" (option b in
ADR 0026) was rejected because it discards evidence that costs almost nothing to keep.

## 4. Bugs found and fixed

| # | Bug | Where | Effect before the fix |
| :--- | :--- | :--- | :--- |
| 1 | Engine-only gap reason guessed from the URL string; unconditional `SITEMAP_ORPHAN` fallback; flags never passed to `reconcile()` | `screaming_frog_reconciler.py`, `screaming_frog_merge.py` | Reproduced: a CMS-only URL and a DOM-linked deep URL were both called sitemap orphans. On saved data, 82.4% of "sitemap orphans" were something else (§3.1) |
| 2 | Rule 4 always true (tautological enum check plus truthiness of a model instance) | `navigation_context.py` | `ORPHANED` unreachable; every unlinked page read `SITEMAP_ONLY` in urls.xlsx/urls.pdf and the GSC table |
| 3 | Robots refusals caught by no refusal handler | `discovery.py`, `async_discovery.py` | Counted as `transport_error` for URLs never requested |
| 4 | Checkpoints stored no flags | `server.py` | Recovered pages looked like Screaming-Frog-merged pages |
| 5 | A UI note said Screaming Frog "cannot reach these by following links" | `ReconcilePanel.tsx` | False for the 47.6% of saved orphans that had a DOM link |

**A bug in the brief.** The brief named four fetch handlers for item 3. The two CMS-pagination
loops in `discovery.py` had the same defect and were fixed too, making six.

## 5. Corrections

- **Every "sitemap orphan" label produced before `89e90ce`.** The reconciler never had evidence for
  it. Earlier entries that describe engine-only URLs as sitemap orphans or as "published with no
  internal link" describe the old fallback, not a measurement. That includes the README
  reconciliation table's row "Published with no internal link — a sitemap orphan", corrected in
  this cycle. Build-log 0076's "infosys orphans 8,123 to 630" counted the same fallback set; the
  count is still a count of engine-only URLs, but "orphan" in that entry does not mean "unlinked".
- **README's ADR 0023 row** said "Screaming Frog's `--crawl` follows links, so orphans and
  sitemap-only URLs are exactly what it cannot reach". Measured on saved data, 47.6% of orphans had
  a DOM link. Corrected in `README.md` this cycle.
- **Navigation "Discovery Method" values in stored crawls.** Every unlinked page in a stored result
  reads `SITEMAP_ONLY` whether or not a sitemap listed it. Those results are not rewritten.
- **`transport_error` counts in stored fetch ledgers** include robots refusals. Not rewritten.
- **README "The local API and the React UI"** said "there is no within-crawl checkpointing, so the
  work genuinely is lost". Crawl checkpoints have existed since build-log 0019, and CLAUDE.md §8
  already records the partial tree as renderable. Corrected in `README.md` this cycle, since the
  checkpoint payload changed here.

## 6. Explicitly not done

- **Phase 2**: referrer URL per page, the full sitemap path (index → child sitemap), link depth,
  the CMS record on the profile, and a per-URL refusal ledger. `robots_disallowed` is a count, not
  a list of URLs.
- **Phase 3**: provenance export columns in urls.xlsx/urls.pdf and a provenance UI. The "Discovery
  Method" column is the only per-URL provenance export, and it reports the navigation enum, not the
  three flags.
- **Phase 4**: extra discovery routes: `rel=canonical`, `hreflang`, `rel=next`, iframes.
- **No data migration.** Stored reconciliations, results and fetch ledgers keep their old values.
  A re-run cross-check produces the new reasons; a new crawl produces the new Discovery Method and
  `robots_disallowed`.
- **No new `NavigationDiscoveryMethod` member for CMS-only pages** (§3.2).
- **Exception hierarchy unchanged** (§3.3).
- **The checkpoint placeholder profile still carries a `SITEMAP_INDEX`-sourced `SignalScore` at
  confidence 0.0.** `signals_evaluated` requires at least one entry and no `SignalSource` member
  means "none". No consumer reads it as discovery evidence. Left as is.
- **`SiteGraph.all_urls()` now has no callers** (replaced by `all_url_sources()`). Not deleted.
- **List-mode wording.** `url_list.py`, `url_list_sources.py` and `url_list_routes.py` are owned
  by another session. Their docstrings still describe orphans as `EngineGapReason.SITEMAP_ORPHAN`
  and "pages no internal link reaches". Behaviour is correct; the wording is stale. Handed off.
- **CLAUDE.md §8** still says checkpoints "hold URLs only". They now hold URLs and per-URL source
  letters; still no navigation footprint, no resume, never deleted. Not edited: CLAUDE.md is
  changed on the user's instruction, not a scribe's.
- **The cycle-0126 UI copy handoff** (Cancel/"Kill" tooltip) is untouched.

## 7. Coordination note: a parallel fix in the main checkout

At push time another session had **uncommitted** edits in the main checkout's
`src/modules/seo/page_classifier/discovery.py` that:

- independently fix the same robots misfiling, and also name the outcome `robots_disallowed`;
- add a "Discovered-to-Fetched gap" accounting to `DiscoveryReport` (`pages_not_retrieved`,
  `cms_only_unlinked`, `faceted_skipped`, and others), which overlaps in intent with this cycle's
  provenance work.

The user chose to push this work first. That session will meet a merge conflict in `discovery.py`
when it next integrates. Two readers should expect it:

- **That session**: `robots_disallowed`, `OUTCOME_ROBOTS_DISALLOWED` and `_refusal_outcome_for`
  already exist on `main` (`5c0d149`). Keep one classifier, not two. `cms_only_unlinked` should be
  checked against `CMS_API_ONLY` (reconciler) and the CMS-only `ORPHANED` rule (§3.2) so the three
  counts agree on what "CMS-only" means.
- **This side**: a later diff in `discovery.py` touching robots outcomes is that session's
  integration, not a regression of this cycle.

That session's `docs/build-log/0125-boundaried-like-its-siblings.md` is also uncommitted in the
main checkout. Cycle 0125 was treated as taken, so these entries start at 0127.

## 8. Files changed

```
a80648a
 docs/adr/0026-url-provenance-reports-evidence-or-says-unknown.md     | 119 +++
 src/api/server.py                                                  |  87 +++-
 src/modules/seo/page_classifier/async_discovery.py                 |  18 +-
 src/modules/seo/page_classifier/discovery.py                       |  51 ++-
 src/modules/seo/page_classifier/navigation_context.py              |  13 +-
 tests/api/test_server.py                                           |  53 +++
 tests/modules/seo/page_classifier/test_navigation_context.py       |  78 +++
 tests/modules/seo/test_async_discovery.py                          |  32 ++
 tests/modules/seo/test_discovery.py                                |  35 ++
 9 files changed, 443 insertions(+), 43 deletions(-)

89e90ce
 docs/adr/0026-url-provenance-reports-evidence-or-says-unknown.md     |  79 ++--
 rankuno-ui/src/adapters/adapterInterface.ts                        |   2 +-
 rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx             |  34 +-
 rankuno-ui/src/components/jobs/ReconcilePanel.tsx                  |  41 +-
 rankuno-ui/src/lib/treeOverlay.ts                                  |  16 +-
 src/api/server.py                                                  |  42 +-
 src/modules/seo/page_classifier/screaming_frog_merge.py            |   3 +
 src/modules/seo/page_classifier/screaming_frog_reconciler.py       | 108 +++-
 tests/api/test_server.py                                           |  68 ++-
 tests/modules/seo/test_screaming_frog_provenance.py                | 104 +++
 tests/modules/seo/test_screaming_frog_reconciler.py                |  10 +-
 11 files changed, 431 insertions(+), 76 deletions(-)
```

This entry also updates `README.md`, `docs/ARCHITECTURE.md` and the build-log index.

## 9. Documentation drift (Step 8)

- `README.md`: `url_rules.py` row notes path case (cycle 0129); new status row for evidence-based
  provenance; reconciliation direction table and workbook sheet list rewritten for the four orphan
  reasons; ADR 0023 row's "exactly what it cannot reach" sentence corrected; checkpoint sentence in
  "The local API and the React UI" corrected.
- `docs/ARCHITECTURE.md`: tree comments for `discovery.py` (`robots_disallowed`, `sources`),
  `discovery_parsers.py` (cycle 0128), `url_rules.py` (cycle 0129), `url_identity.py`
  (`CASE_FOLDED`); new tree entries for `navigation_context.py` and
  `screaming_frog_reconciler.py`, neither of which was listed; ADR table rows for 0026 and 0027.
  The missing 0022 and 0024 rows were left as they were.

`drift_check.py` after these edits:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 215 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

The count is 215, not 218, because the three new entries were untracked when it ran and the check
counts tracked files (the same effect noted in build-log 0100). Their relative links were checked
separately by path existence; none were broken.
