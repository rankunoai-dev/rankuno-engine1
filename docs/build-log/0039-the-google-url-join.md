# Cycle 0039: The Google-URL join, and what it found in our own crawls

- **Date**: 2026-08-21
- **Scope**: `src/modules/seo/performance/` — resolve Search Console and GA4
  addresses onto crawled pages, and report how much of an export landed.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1430 passed, 1 warning in 101.28s`, total coverage 95.67%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.67%
1430 passed, 1 warning in 101.28s (0:01:41)
PASSED: Tests
 Test Files  9 passed (9)
      Tests  76 passed (76)
PASSED: UI Component Tests
ALL GATES PASSED.
```

New module coverage, measured separately: **100%** of
`src/modules/seo/performance/` (204 statements, 48 branches, 0 missed).

## 2. What landed

`schemas.py` and `url_identity.py`, plus 32 tests. Nothing is wired to an
endpoint, a connector, or the UI — this is the join and only the join.

**Why a whole module for a dictionary lookup.** Search Console reports the URL
*it* chose. GA4 reports a path with no host at all. The crawler holds the
address a link pointed at. A naive string join drops every page where those
three disagree, and it does it **silently**: the section total is simply lower
than it should be, and nothing on screen says a row was thrown away. Everything
here exists to turn that silence into a number an analyst can read.

`UrlResolutionIndex` builds an alias map from every address a page is known by,
in descending order of evidence — the crawled URL, then the redirect
destination, then the declared canonical. A stronger tier is never overwritten
by a weaker one, and `MatchTier` records which one decided each match, because
a join made on canonical tags is not a join made on crawled addresses and a
reader who cannot tell them apart cannot audit it.

`ResolutionOutcome` carries the match rate, a per-tier breakdown, and a
per-reason breakdown of the misses. The reasons are the actionable half:
`not_crawled` is our defect, `off_site` is a property-configuration question,
`ambiguous` is a site with competing canonicals, and `unparseable` is a bad
export. One number says the join is bad; these four say who has to fix it.

## 3. Design decisions

**Ambiguity is refused, not guessed.** Canonical tags are many-to-one by
design, so the same alias routinely names several crawled pages. Picking one
would move a real URL's clicks into the wrong section *and look exactly like a
correct answer*. Any alias claimed by two pages at the tier that would decide it
resolves to `AMBIGUOUS`.

**A clash at a strong tier stops the search rather than falling through.**
Answering a harder question with weaker evidence is backwards, and the fallthrough
would have been invisible in the output.

**The path maps carry no host, and that is the safety property, not a
shortcut.** GA4 supplies no host, so a path map is unavoidable. A crawl spanning
two hosts therefore has two owners for `/pricing/`, and the same clash rule
refuses it — no host special case was needed.

**The host check happens after the lookup, not before.** A page naming another
property as its canonical is exactly the case where Google reports the other
host, and that address is already in the index. Checking the host first would
have rejected it.

**`BARE_PATH` is a real tier, not a silent fallback.** GA4 property filters
routinely strip parameters the crawl kept, so `/search/` arrives for a page held
as `/search/?q=…`. It is accepted only when exactly one crawled page owns the
path, and it is reported under its own tier so it can be discounted rather than
blended into the honest matches.

**An empty export is not reliable.** `is_reliable` is False at `total == 0`.
Vacuous truth is the wrong answer to "can I trust these totals" — there are no
totals, and True would present an empty dashboard as a healthy one.

**Rates are derived, never stored.** A section's CTR is not the mean of its
pages' CTRs. `ctr` is a property over clicks and impressions, which are the two
things that survive addition. `position` is stored but documented as
un-summable: the correct rollup is impression-weighted.

**A missing metric is not a zero.** `PagePerformance.gsc` and `.ga4` are
optional. "No clicks" and "not in the export" roll up identically if both are
written as `0`, and only the second one is a defect in us.

## 4. Bugs found and fixed

**The engine ships duplicate pages, and this is the first thing that could see
it.** The plan assumed the crawl holds one profile per address. Measured across
70 stored crawls and 483,450 pages, it does not: **3,491 profiles are
re-emissions of a page already present**, identified by recomputing
`normalize_url` over each result.

Two shapes produce them, both confirmed on a **fresh** 12,807-page highradius
crawl written 2026-08-20 — 20 duplicates — so this is live, not historical:

```
https://www.highradius.com/en-gb/whats-new/?ref=navbar
https://www.highradius.com/en-gb/whats-new/

https://www.highradius.com/en-gb/value-creation//konica-minolta-…/
https://www.highradius.com/en-gb/value-creation/konica-minolta-…/
```

Both pairs carry an **identical `normalized_path`** in the stored result. The
engine's own dedup key already says they are one page, and the result contains
two rows anyway. `SiteGraph.add` keys on `normalize_url` (discovery.py:455), so
the duplication is downstream of the graph, not in it. **Root cause not yet
located; not fixed in this cycle.**

Older crawls are far worse — 863 duplicate keys in a 33,439-page crawl, 849 and
714 in two 11k crawls from 2026-08-11 to 08-14. Those predate the `www.`/scheme
folding in `normalize_url`, which is why they collapse `http://`, `http://www.`
and `https://` variants of the same page into one key today.

**The fix in this module, and why it is not a guess.** The first draft refused
these as `AMBIGUOUS`, which was the wrong kind of honest — up to 7% of an export
dropped over a defect the analyst cannot see or fix. The index now deduplicates
profiles by `normalize_url` before building any tier, keeping the first, and
exposes the count as `duplicate_profiles`. This is not resolving a conflict; it
is honouring a dedup key the engine already computed. Keying on the recomputed
`normalize_url` rather than the stored `normalized_path` means it also holds for
crawls written before that field settled.

Re-measured after the change: **100% resolution across all 70 stored crawls**
(23,460 of 23,460), zero ambiguous, with 3,491 duplicates reported.

**A test asserted the wrong thing about tracking parameters.** The canonical-tier
test used `https://e.com/a/?ref=1` as the non-canonical variant. `ref` is on the
tracking list, so it normalises onto the canonical and matched at
`CRAWLED_URL`. The code was right; the fixture was not. Now uses `?page=2`.

**Dead defensive branch.** `_tier_index` guarded `elif seen != owner`. Once the
caller deduplicates by dedup key, one owner contributes at most one pair per
tier, so the equal case is unreachable. Removed rather than left as an
uncoverable branch.

## 5. Corrections

**The 99.28% first reported here was a self-join and is not a match rate.** The
probe built its "Google export" from the crawl's own `final_url`/`canonical_url`/
`url`, so it measures whether the index is internally consistent, not whether it
resolves what Google actually sends. The 100% figure above is the same
self-join after the duplicate fix. **The true match rate against a real Search
Console export is unmeasured**, and the ≥90% claim in the plan for this cycle
is therefore unverified. It cannot be verified without one real export.

**`docs/ARCHITECTURE.md` contradicted itself and CLAUDE.md §8.** Its
"Planned, not yet implemented" table listed crawl checkpointing (shipped in
cycle 0019 as `CrawlCheckpointer`) and `tree_visualizer.py` — which appeared in
the *implemented* tree six lines above it in the same file. Both rows removed,
with the removal recorded in the file itself. This is exactly the drift the
build log exists to prevent, and it survived four cycles.

## 6. Explicitly not done

- **No ingestion.** No CSV parser, no endpoint, no `google_search_console.py`,
  no `google_analytics.py`. Nothing in the repository can obtain a GSC or GA4
  row; this module only says which page a row is about once you have one.
- **No aggregation.** `aggregator.py` and `opportunity_scorer.py` do not exist.
  `PagePerformance` is a declared contract with nothing producing it yet — do
  not read its presence as a working feature.
- **No persistence.** Nothing writes `.jobs/<id>.performance.json`.
- **The duplicate-profile defect is reported, not fixed.** This module works
  around it. The crawl still emits the extra rows, and every page count in the
  dashboard is inflated by 0.72% on average — up to 2.6% on the worst stored
  crawl. Fixing it means changing where profiles are emitted, which is a
  separate cycle with its own before/after count.
- **No query-level data.** Page × query storage, and therefore cannibalisation
  detection, is Phase 2.
- **`RELIABLE_MATCH_RATE = 90.0` is an assumption, not a calibration.** It was
  chosen in the plan for this cycle and no measurement supports that particular
  number.
- **No ADR.** ADR 0010 for the GSC/GA4 architecture is still owed; this cycle
  landed one leaf of it and did not settle the connector or quota design.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/__init__.py` | new — package stance |
| `src/modules/seo/performance/schemas.py` | new — metrics + resolution contracts |
| `src/modules/seo/performance/url_identity.py` | new — the alias index |
| `tests/modules/seo/test_url_identity.py` | new — 32 tests, 100% of the package |
| `docs/ARCHITECTURE.md` | package added to the tree; two false rows removed |
| `docs/build-log/0039-the-google-url-join.md` | this entry |
| `docs/build-log/README.md` | index row |

## 8. Follow-ups

1. **Get one real Search Console export.** Every number in §1 is a self-join.
   The match rate against real Google data is the only thing that decides
   whether this design holds, and it is currently unknown.
2. **Locate the duplicate-profile emission** and fix it upstream, with a
   before/after page count per stored crawl.
3. `aggregator.py` — section rollups, with the impression-weighted position and
   the recomputed CTR this module's docstrings specify.
4. `QuotaLimiter` scoped per Google *property*, not per host or per crawl.
   In-process only, with the same multi-worker caveat as the existing rate
   limiter (CLAUDE.md §8).
5. ADR 0010 for the GSC/GA4 architecture.
