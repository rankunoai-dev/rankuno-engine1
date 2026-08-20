# Cycle 0035: An orphan count is not an orphan list

- **Date**: 2026-08-20
- **Scope**: Make the orphan finding a worklist an analyst can filter, read and
  export, and split it by the discovery path that found each page.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1372 passed` Python / `40 passed` UI / `Total coverage: 95.50%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.50%
1372 passed, 1 warning in 121.77s (0:02:01)
PASSED: Tests
 Test Files  6 passed (6)
      Tests  40 passed (40)
PASSED: UI Component Tests
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (10.68s).
Drift audit: `PASSED: no drift detected across 81 markdown files.`

---

## 2. What was there, and why it was not enough

Orphan detection has been correct since discovery was written. `is_orphan` is
`inbound_links == 0`, the count reaches `CrawlSummary.orphan_pages`, and
`buildFindings` phrases it as a finding.

What the analyst could actually see was a number and **five example URLs**
(`audit.ts`, `examples: orphans.slice(0, 5)`). On a crawl reporting 2,182
orphans that is 0.2% of the finding. Everything needed to do the work was in the
browser already; nothing rendered it.

---

## 3. Design decisions

### 3.1 The split is by discovery path, and the reason is that the advice differs

The single number was hiding two populations. Measured on the most recent stored
highradius crawl (`154dab01…result.json`):

| | Count |
| :--- | ---: |
| Pages with zero inbound links | 2,182 |
| …of which a sitemap lists | 1,142 |
| Remainder (CMS record or crawl-reached only) | ~1,040 |

A sitemap orphan is published to search engines and reachable by no visitor —
link it or de-list it. A page only the CMS database knows about was never
published anywhere a crawler can see, so "add internal links" is advice that
will not survive contact with the client's developer. Reporting 2,182 as
"orphans the site publishes" overstates the finding by nearly a thousand pages.

### 3.2 `DiscoverySource` moved from `discovery` to `schemas`

The flags existed on `DiscoveredNode` and stopped there — `to_page_evidence`
never carried them, so `FullPageIntelligenceProfile` could not either, and the
UI had no way to draw the distinction in §3.1.

`schemas.py` cannot import `discovery.py` (`discovery` imports `signal_parsers`,
which imports `schemas`), so the model moved to `schemas` and `discovery`
re-exports it. Every existing importer keeps working. The flags are still a
discovery concept; they are simply no longer private to that module.

Chain now: `SiteGraph.add` → `DiscoveredNode.sources` → `PageEvidence.
discovery_sources` → `FullPageIntelligenceProfile.discovery_sources`. No signal
reads the field. It is provenance travelling with the evidence, not evidence.

### 3.3 A drill-down inside Audit, not a fourth top-level view

Considered and rejected: a dedicated left-rail lane. Audit already answers "what
is wrong here?" and a page can be an orphan *and* sit in a mis-signposted silo —
the multi-membership that made the audit a separate view in the first place. A
lane whose only content is one of the audit's own findings splits that reading.

`Finding` gained an optional `pages` array. Findings that carry one render a
`See all N` control; findings that do not render exactly as before. The
distinction is real rather than cosmetic: an orphan set is a list handed to a
content team, while "41 duplicate title groups" is a report.

### 3.4 CSV is built in the browser

The reconciliation CSV is served from the API because it is computed there. The
orphan list is not — every row is already loaded in the client, and asking the
API to re-derive a set the client is currently rendering would create a second
definition of the same list that could drift from the first.

The export writes **what is on screen**, not the whole set. An analyst who
filters to sitemap orphans and then exports everything would send a client 1,000
rows they deliberately excluded, with nothing in the file saying so.

---

## 4. Bugs found and fixed

**A silent mislabelling of every crawl already on disk.** All 13 stored
highradius results predate `discovery_sources`. They deserialise with all three
flags `false` — indistinguishable from "found by no path at all" — so the first
working version of this view labelled every orphan in every stored crawl `Crawl
only` and drew a confident three-way split with 100% in the wrong bucket. It
looked like a finding about the site. It was a gap in the data.

Caught by opening a real stored crawl rather than a fixture. Fixed by
`hasProvenance()`: when no page in the set carries any flag, the segmented
filter and the `Why` column are withdrawn and the view states why. The list and
the export still work — the URLs are the deliverable either way.

A reparse cannot recover this. `reparse_job` validates the *stored result*, so
the defaults it fills in are the same defaults. Only a re-crawl restores the
split, and the caveat text says so rather than implying otherwise.

**CSV columns could shift silently.** `toCsv` quotes any field containing a
comma, quote or newline. Without it a URL like `?a=1,2` opens in a spreadsheet
with every column after it displaced — the worst available failure mode, because
it still looks like data. A BOM is prepended for the same class of reason: Excel
on Windows reads a UTF-8 CSV as the system codepage without one.

---

## 5. Corrections

**Cycle 0034's build log records `29 passed` for the UI suite; the count is now
40.** Ten came from `OrphanTable.test.tsx` in this cycle and one from the stale
crawl guard. Nothing regressed — noted only because the two entries sit next to
each other and the jump is otherwise unexplained.

**A figure quoted in conversation before this cycle — "3,183 sitemap orphans on
highradius" — does not match any stored crawl.** The most recent result reports
2,182 zero-inbound pages, 1,142 of them in a sitemap. Orphan counts move with how much of the site a run
actually fetched — the stored highradius crawls range from 1 to 27,989 pages
retrieved — so any orphan number is only meaningful beside the crawl that
produced it. The view now shows the list rather than the number, which makes the figure
checkable instead of quotable.

---

## 6. Explicitly not done

- **No Search Console integration.** `src/integrations/` holds `base_client`,
  `http_fetcher` and `llm_client` and nothing else. The "orphans that earn
  impressions vs orphans that earn nothing" split — the reason this feature was
  asked for — **cannot be computed by this engine today**. The finding's action
  text tells the analyst to do the cross before deleting anything; it does not
  do the cross. Deferred deliberately: a GSC Performance CSV upload reconciled
  the way `screaming_frog_reconciler` handles a Frog export is the intended next
  step, and the live API is a separate decision with a Step 5 audit attached.
- **No backfill of stored crawls.** See §4. All thirteen stored
  highradius results will show the caveat rather than the split.
- **No orphan filter on the tree.** The visualiser is unchanged. An orphan has
  no navigational position by definition, so the tree is the wrong instrument.
- **`sitemap_source` is shown but not grouped.** On a large site it identifies
  the owning content team, and grouping orphans by it would order the worklist
  by who has to fix it. Not built; the column sorts and the CSV carries it.
- **No pagination of the underlying data.** The table pages at 25 rows, but the
  whole array is held in memory and filtered on every keystroke. Fine at 2,182
  rows; untested at 100,000.

---

## 7. Files changed

```
src/modules/seo/page_classifier/schemas.py          DiscoverySource moved here;
                                                    two fields on the profile
src/modules/seo/page_classifier/discovery.py        imports + re-exports it;
                                                    to_page_evidence carries it
src/modules/seo/page_classifier/signal_parsers.py   PageEvidence.discovery_sources
src/modules/seo/page_classifier/cascading_pipeline.py  passes both through
rankuno-ui/src/types/schema.ts                      regenerated (exporter)
rankuno-ui/src/lib/audit.ts                         orphanKind, orphanPages,
                                                    Finding.pages
rankuno-ui/src/lib/csv.ts                           new — RFC 4180 export
rankuno-ui/src/components/audit/OrphanTable.tsx     new — the worklist
rankuno-ui/src/components/audit/AuditView.tsx       drill-down toggle
rankuno-ui/src/components/audit/audit.css           drill-down + caveat styles
rankuno-ui/src/test/factories.ts                    new fields
tests/modules/seo/test_discovery.py                 +3 (flags reach the profile)
rankuno-ui/src/components/audit/OrphanTable.test.tsx  new — 11 tests
```

---

## 8. Follow-ups

1. **GSC Performance CSV upload.** The one that makes this feature what was
   actually asked for. Join on URL, split orphans into earning and dead.
2. **Group the worklist by `sitemap_source`**, so it can be handed out by owner.
3. **Re-crawl highradius** once, so at least one stored result carries the
   provenance flags and the split can be demonstrated rather than described.
