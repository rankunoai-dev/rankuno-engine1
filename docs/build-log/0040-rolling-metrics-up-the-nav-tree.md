# Cycle 0040: Rolling Google metrics up the navigation tree

- **Date**: 2026-08-21
- **Scope**: `src/modules/seo/performance/aggregator.py` — section rollups over
  the trail tree, plus the placement-aware dedup rule cycle 0039 got wrong.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1458 passed, 1 warning in 105.62s`, total coverage 95.79%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.79%
1458 passed, 1 warning in 105.62s (0:01:45)
PASSED: Tests
 Test Files  9 passed (9)
      Tests  76 passed (76)
PASSED: UI Component Tests
ALL GATES PASSED.
```

`src/modules/seo/performance/` remains at **100%** (366 statements, 74 branches,
0 missed) across 60 tests.

## 2. What landed

`aggregate(index, gsc_rows, ga4_rows) -> PerformanceRollup`, plus
`SectionPerformance`, `UnattributedTotals` and `PerformanceRollup` in `schemas`.
Still no I/O: nothing fetches a Google row, and nothing persists a rollup.

The shape was chosen by measuring the 70 stored crawls first, and the
measurements overturned three things the plan assumed.

**Section identity is the whole trail, not the label.** Up to 68 labels per
crawl appear under more than one parent. An `Overview` under Products and
another under Company would merge into one row that is wrong with nothing on
screen to indicate it.

**A section is routinely a page too.** 1,220 distinct trails are a strict prefix
of a deeper trail. One total cannot answer "is this section big, or is its
landing page big", so `direct_pages` and `direct_clicks` sit beside the subtree
totals.

**Trails run 0–6 deep and nothing recurses.** A page contributes to every prefix
of its own trail. There is no tree walk, so no cycle in the navigation data can
hang it.

**Rates are recomputed from counters, never averaged.** CTR comes from summed
clicks over summed impressions; position is the impression-weighted mean, held
during accumulation as `Σ position × impressions`. A page seen 10 times must not
pull a section average as hard as one seen 990 times.

**`position` is `float | None`, never `0.0` for "no data".** Position zero reads
as better than rank 1, so an unmeasured section would sort to the top of a
best-performing list purely for having nothing in it.

**Unresolved rows are held, not dropped.** `unattributed` carries the metrics
that reached no page, and `attributed_share` is the headline: how much of what
Google reported this rollup actually explains. Without it the sum of the
sections is quietly smaller than the total in the Search Console UI, and
comparing those two is the first thing an analyst does.

## 3. Design decisions

**The aggregator consumes `index.pages`, not its own page list.** The dedup rule
now exists in exactly one place. Two copies would eventually disagree about the
page count on the same screen, which is the failure this codebase has already
had once with `nav_coverage` and the tree.

**Several Google rows summing onto one page is the normal case, not an edge
case.** Canonical tags are many-to-one by design, so the resolver maps several
addresses onto one crawled page. The rows are added, including their position
weights. Assigning instead would discard clicks and leave a total that still
looks plausible.

**A row of zeroes counts as measured.** "Reported with no clicks" says the page
is indexed and losing; "never reported" says nothing at all. `pages_with_data`
counts the first, which is why the accumulator tracks *whether a row arrived*
rather than inspecting whether its numbers are non-zero.

**Empty trails fold into `(OTHERS,)`.** Four stored crawls express "nothing
placed this" as an empty trail and 53 express it as `(OTHERS, <page type>)`.
**No crawl uses both**, so folding is unambiguous and cannot create two buckets
for one idea. Left empty, those pages would appear in the site total and in no
section — present in one number and missing from every other.

## 4. Bugs found and fixed

**Cycle 0039's dedup was arbitrary, and the copies disagree.** Last cycle kept
whichever duplicate profile arrived first. Measured this cycle: **516 of the
2,544 duplicate groups place their members differently** — one copy under
`("Home",)`, the other in `("OTHERS", "UNKNOWN")`:

```
https://highradius.com/en-gb/value-creation/konica-minolta-finance-transformation/
      ('Home',)
      ('OTHERS', 'UNKNOWN')
```

So a fifth of the duplicates were handing their section to dict ordering, and
every total built on top would have been wrong with nothing to indicate it. That
was invisible in cycle 0039 because nothing yet read `breadcrumb_path`.

`dedupe_profiles` now keeps the **best-placed** copy, scored by
`placement_depth`, which mirrors `tool._menu_depth`: a trail headed by `OTHERS`
is two elements long and would beat a real one-crumb trail on length, so it
scores zero. Ties go to first-seen, so the result does not depend on ordering at
all. The test asserts both input orders, because "first seen" is exactly what
must not decide it.

**A test of mine asserted the opposite of its own docstring.**
`test_a_row_of_zeroes_is_data` documented that "seen with no clicks" differs
from "never seen", then asserted `pages_with_data == 0`. The docstring was
right. The accumulator was deciding `has_data` by inspecting whether the numbers
were non-zero, which collapses exactly the distinction that makes
`PagePerformance.gsc` optional rather than a row of zeroes. Fixed in the code;
`_Acc.has_data` deleted in favour of tracking whether a row arrived.

## 5. Corrections

**Nothing previously published turned out wrong this cycle**, but one number
from 0039 is now better understood. That entry reported 3,491 duplicate profiles
as a page-count inflation problem. It is also a *placement* problem: 20% of the
groups disagree about which section the page belongs to, which is the more
damaging half and was not visible when the entry was written.

**The 0039 warning about the self-join still stands and is unchanged.** The real
match rate against a Search Console export remains unmeasured. The synthetic
rows used to validate this cycle were derived from the crawls' own fields, so
they prove the arithmetic reconciles — they prove nothing about how much of a
real export resolves.

## 6. Explicitly not done

- **No ingestion, no persistence, no endpoint, no UI.** Nothing can obtain a GSC
  or GA4 row, and no rollup is stored or displayed. `PerformanceRollup` is a
  declared contract with a producer but no caller.
- **`opportunity_scorer.py` does not exist.** Ranking sections by opportunity is
  the next step and is not in this cycle.
- **No query-level data**, so no cannibalisation detection. Phase 2.
- **No currency handling.** `revenue` is summed within one property. The model
  does not carry a currency, and summing across properties would be wrong.
- **GA4 rows are resolved by path only.** The GA4 export carries no host, which
  is handled, but a property covering two hosts cannot be disambiguated and its
  paths will resolve as `AMBIGUOUS`. Not worked around, because guessing is what
  this design refuses everywhere else.
- **The duplicate-profile defect is still not fixed upstream.** The engine still
  emits the extra rows; this module and the resolver work around them.
- **`attributed_share` is a partition by construction**, so it can never expose
  an arithmetic bug in the split. It measures resolution quality, not
  correctness of the sums. The sum invariants are asserted in tests instead.

## 7. Verification beyond the unit tests

Run over every stored crawl of ≥5,000 pages — **27 crawls** — with synthetic
Search Console and GA4 rows for 3,000 sampled pages plus 200 rows for URLs the
crawl never held. Four invariants asserted per crawl, all held:

| Invariant | Result |
| :--- | :--- |
| top-level sections sum to the site row (clicks) | held on 27 |
| top-level sections sum to the site row (pages) | held on 27 |
| `site.clicks + unattributed.clicks == export total` | held on 27 |
| every reported position within the input range | held on 27 |

Largest run: 17,421 pages into 10 sections in 1.16s. A 12,787-page crawl
produced 928 sections in 0.81s.

**An unintended finding.** On the 17,421-page infosys crawl, **17,312 pages —
99.4% — land in `OTHERS`**, and the whole site resolves to 10 sections. The
rollup makes that impossible to miss where the tree view did not. Whether that
is a navigation-parse failure on that site or a genuine property of it is not
established here, and is worth its own look.

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/aggregator.py` | new — the rollup |
| `src/modules/seo/performance/schemas.py` | `SectionPerformance`, `UnattributedTotals`, `PerformanceRollup` |
| `src/modules/seo/performance/url_identity.py` | `dedupe_profiles` + `placement_depth` extracted; dedup now placement-aware; `pages` exposed |
| `tests/modules/seo/test_performance_aggregator.py` | new — 28 tests |
| `docs/ARCHITECTURE.md` | `aggregator.py` added to the tree |
| `docs/build-log/0040-rolling-metrics-up-the-nav-tree.md` | this entry |
| `docs/build-log/README.md` | index row |

## 9. Follow-ups

1. **One real Search Console export.** Unchanged from 0039 and still the only
   thing that can validate the join.
2. `opportunity_scorer.py`.
3. Locate the duplicate-profile emission and fix it upstream.
4. Investigate the infosys 99.4% `OTHERS` result.
5. ADR 0010 for the GSC/GA4 architecture, still owed.
