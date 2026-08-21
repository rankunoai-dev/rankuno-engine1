# Cycle 0041: The opportunity scorer, and what the data would not support

- **Date**: 2026-08-21
- **Scope**: `src/modules/seo/performance/opportunity_scorer.py` — ranked
  recommendations from a crawl crossed with Search Console.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1481 passed, 1 warning in 111.51s`, total coverage 95.94%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.94%
1481 passed, 1 warning in 111.51s (0:01:51)
PASSED: Tests
 Test Files  9 passed (9)
      Tests  76 passed (76)
PASSED: UI Component Tests
ALL GATES PASSED.
```

`src/modules/seo/performance/` remains at **100%** (560 statements, 132
branches, 0 missed) across 83 tests.

## 2. Two of the four findings could not be built as specified

The specification named four findings and the fields behind two of them do not
hold what their names say. Both were found by measuring before writing, and
neither would have raised anything.

**`depth_from_l0` is not depth from L0.** The specification asked for "deep
pages (Depth 4+) pulling heavy organic traffic". Measured across 482,190 stored
pages, **90.4% sit at exactly `URL path segments + 2`** and **no page anywhere
is at depth 0 or 1** — the homepage of gep.com reads as depth 2.

The cause is one line, `cascading_pipeline.py:322`:

```python
depth_from_l0=depth_of(evidence.normalized_path),
```

`depth_of` counts `/`-separated segments, and `normalized_path` holds a whole
URL rather than a path, so `https:` and the host are counted as two segments.
The offset is constant; the deeper problem is that even corrected it would be
**path depth, not click depth** — which its own docstring explicitly disclaims:

> depth_from_l0: Graph distance from the homepage. Distinct from
> `hierarchy_level`: a blog post linked on the homepage is depth 1 but still an
> `L3_LEAF_PAGE`. **This is the click-depth fallacy the engine exists to avoid.**

A "Depth 4+" rule against that field selects every URL with two or more path
segments, which is most of a site. **Navigation trail depth is used instead**,
which is real browsing depth and is the same measure the section rollup uses.
`BURIED_TRAIL_DEPTH = 3` catches 26.9% of corpus pages, so depth alone is a
filter; earning clicks from down there is what makes it a finding.

**`discovery_sources` is absent on 98.1% of stored pages** — 473,005 of 482,190.
"Monetizable Sitemap Orphans" cannot require a sitemap origin when there is
nothing to read it from on 57 of 58 crawls. The finding is built on zero inbound
internal links and named `ORPHAN_WITH_TRAFFIC` rather than implying a sitemap
check it does not perform.

**A third specified signal was checked and discarded.** `trail_source != "menu"`
— "the menu does not reach this page" — is true of **88.6%** of corpus pages and
100% on several crawls. It is not a discriminator and is not used.

## 3. The guard that matters most

The share of pages with zero inbound internal links is a property of the
**crawl**, not the site. Across 58 stored crawls, sorted:

```
0% 0% 0% 0% 0% 0% 0% 1% 2% 2% 2% 2% 4% 4% 4% 6% 8% 8% 10% 10% 10% 10% 16% 17%
17% 17% 17% 18% 18% 19% 19% 24% 34% 34% 35% 38% | 54% 64% 72% 80% ×15 97% 99%
100% 100%
```

The high group is crawls that stopped at their page ceiling: pages were listed
by a sitemap and never fetched, so no link pointing at them was ever counted.
Two crawls have **no page with any inbound link at all**. Running the orphan
finding over the 100,687-page crawl would produce 99,361 "monetizable orphans",
every one of them an artefact.

`MAX_ORPHAN_SHARE = 0.5` sits in the empirical gap between 38% and 54%. Above
it, the two link-dependent kinds are **skipped with a named reason**
(`SignalGap.INBOUND_LINKS_UNRELIABLE`) rather than answered. Verified live: the
guard fired on 5 of 29 crawls in the scale run, including gep.com's 4,427-page
crawl.

`BURIED_WITH_TRAFFIC` deliberately survives that gate, because trail depth and
clicks do not depend on the link counts.

## 4. Design decisions

**Crawl traps are read from the export, not from a refusal list.** There is no
stored refusal list — discovery counts refusals (`loop_urls_skipped`,
`malformed_skipped`) but keeps no URLs. Rather than add storage, the finding
tests the *unresolved Search Console rows* against `is_spider_trap` and
`is_malformed_url`. This is better evidence than a stored list would have been:
a trap the crawler declined costs nothing, while one Google has indexed is
already spending crawl budget.

**`score` ranks within one kind and is documented as meaningless across
kinds.** Clicks already earned by an orphan and impressions sitting at position
12 are not the same quantity. Combining them would be an invented exchange rate
presented as arithmetic.

**Thresholds are a floor, not a judgement.** A Search Console export carries no
date range, so the same site over 28 days and over 16 months produces very
different absolute numbers. This is stated in the module docstring rather than
hidden behind a default.

**The cap is reported.** `found` counts before truncation and `truncated` counts
what was dropped. A list that stops at 50 and says nothing reads as "there were
50".

**"Evaluated and found none" is distinguishable from "did not evaluate".** A
kind absent from both `found` and `skipped` was looked for and not present. An
empty report with no explanation reads as "your site has no opportunities",
which is a much stronger claim than the data supports.

**A page is never both an orphan and buried.** The orphan is the stronger
defect and wins; two findings for one page is noise.

**The sibling finding cannot check whether the link already exists.** The crawl
stores inbound and outbound link *counts*, not edges. So the finding is the
underperformance — which stands on its own — and the well-linked sibling is
named as the place to look first, with the reason text saying "check whether
that page links here" rather than "add a link".

## 5. Refactor that came with it

`merge_page_metrics` and `PageMetricSet` were extracted from `aggregate`, and
`rollup_of` split out. The scorer and the rollup now share one implementation of
the per-page merge, including the impression weighting — the part most likely to
end up subtly wrong in one copy and not the other. `aggregate` is unchanged
behaviourally; its 28 tests passed untouched through the refactor.

`PagePerformance` finally has a producer. It was a declared contract with no
caller in cycles 0039 and 0040.

## 6. Bugs found and fixed

**`assert` used as a type guard in shipping code.** Two `assert gsc is not
None` statements existed only to satisfy `mypy --strict` after `_measured`
filtered out the `None`s. Asserts are stripped under `-O`, so those were
load-bearing statements that can vanish. `_measured` now returns the unpacked
`GscPageMetrics`, so the type carries the guarantee and no assertion is needed.

**Two test fixtures were wrong, neither in a way the code caused.**
`https://e.com/a/b/a/b/a/b/` is not a spider trap:
`TRAP_SEGMENT_MIN_LENGTH = 3` exists because `en`, `de`, `lp` legitimately
recur, so single-character segments are excluded by design. Fixture corrected to
realistic segments. Separately, a `**kwargs` helper was missing its annotation
and only `mypy` on the test tree caught it.

## 7. Verification beyond the unit tests

Run over the 29 stored crawls of ≥2,000 pages with synthetic Search Console rows
on a Pareto click distribution, plus 40 URLs Google "knows" that the crawl never
held and 12 synthetic crawl loops.

| Kind | Share of site, per crawl |
| :--- | :--- |
| `orphan_with_traffic` | 0.25% – 1.17% |
| `buried_with_traffic` | 1.54% – 2.36% |
| `indexed_crawl_trap` | 0.09% – 0.27% |
| `underperforming_sibling` | 3.64% – 6.01% |

Skips fired on **5 of 29 crawls**, both link-dependent kinds, all
`inbound_links_unreliable`.

**The sibling share is the loosest and is partly an artefact of the probe.** The
synthetic positions are uniform over 1–60, so ~25% of pages land in the 5–20
striking band; a real position distribution is heavily skewed and would select
far fewer. Whether 3–6% is the real rate is **not established** and cannot be
until a real export exists.

## 8. Corrections

Nothing previously published turned out wrong. Two things published earlier are
now **better supported**: cycle 0040 recorded that section rollups needed real
navigation depth, and this cycle establishes why `depth_from_l0` could not have
served — which was not known when 0040 was written.

## 9. Explicitly not done

- **`depth_from_l0` is not fixed.** It is wrong in two ways and is used by the
  cascade and the stored corpus. Correcting it changes the meaning of every
  stored crawl and needs its own cycle with a before/after. This module routes
  around it; nothing else does.
- **No ingestion, no persistence, no endpoint, no UI.** Still nothing that can
  obtain a Search Console row.
- **No CTR-curve uplift model.** No "this would gain N clicks" number is
  produced, because any such number needs a click-through curve that is an
  industry estimate rather than a measurement of this client.
- **The sibling finding does not verify link absence**, per §4.
- **No GA4-driven findings.** Everything here is Search Console; engagement and
  conversion signals are unused.
- **The thresholds are unvalidated.** `MAX_ORPHAN_SHARE` is measured;
  `BURIED_TRAIL_DEPTH`, `STRIKING_BAND`, `min_clicks` and `min_impressions` are
  reasoned defaults with no calibration behind them.
- **The real match rate remains unmeasured**, unchanged since 0039. Every
  finding here inherits that: a poor join produces confident recommendations
  about the wrong pages.

## 10. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/opportunity_scorer.py` | new — the four findings |
| `src/modules/seo/performance/aggregator.py` | `PageMetricSet`, `merge_page_metrics`, `rollup_of` extracted; unresolved rows kept whole |
| `tests/modules/seo/test_opportunity_scorer.py` | new — 23 tests |
| `docs/ARCHITECTURE.md` | scorer added to the tree |
| `docs/build-log/0041-what-the-data-would-not-support.md` | this entry |
| `docs/build-log/README.md` | index row |

## 11. Follow-ups

1. **One real Search Console export.** Third cycle asking. Everything built
   since 0039 rests on an unmeasured join.
2. Fix `depth_from_l0`, or rename it to what it holds and give the engine a real
   click-depth field. It currently contradicts its own docstring.
3. Locate the duplicate-profile emission (0039, 0040) and fix it upstream.
4. Store the refusal list, or decide deliberately not to — §4 works around its
   absence but a crawl-budget report would want both sides.
5. ADR 0010 for the GSC/GA4 architecture, owed since 0039.
