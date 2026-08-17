# Cycle 0023: Placement fidelity — self-referential breadcrumbs, mega-menu nesting, duplicate URLs

- **Date**: 2026-08-17
- **Scope**: Stop the tree inventing placement the site never published — drop
  breadcrumbs that name only the page itself, stop sibling mega-menu headings
  nesting under each other, and report duplicate URLs as a finding instead of
  rendering them as separate sections. Also lands the locale-folding reversal
  begun in the previous session.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1202 passed`, `Total coverage: 95.43%`

## 1. Gate results

```
=== Format ===
153 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 42 source files
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.43%
1202 passed, 1 warning in 104.55s (0:01:44)
PASSED: Tests

ALL GATES PASSED.
```

UI, separately: `tsc --noEmit` clean. There is no test runner in `rankuno-ui/`;
`audit.ts` was verified by executing `buildFindings` against a real crawl result
(see §4), not by unit test. That is a gap, recorded in §6.

## 2. What landed

### `breadcrumb_parser.py` — `section_labels(site_root, page_url)`

A trail that reduces to **one step naming the page itself** now returns `()`.

The shape that forced this is rankuno.com's, and it is not exotic — it is what
Yoast emits when no ancestor is configured:

```
Home                                                     -> https://rankuno.com/
What Should Digital Agencies Do to Be SEO-ready in 2019?  -> None
```

Strip the root crumb and one crumb remains, which is the page. Kept, it made
each such page its own top-level section containing only itself: 38 of 83 pages
on that crawl, including all 12 blog posts. It also inflated the "in navigation"
KPI by the same 38, because a self-referential crumb was being counted as
navigation reach when nothing in the menu points at those pages at all.

The crumb is dropped only when it can be *shown* to be the page — unlinked (the
conventional "you are here" markup) or carrying this page's URL. That guard is
the whole reason the parameter exists; see §3.

### `nav_tree_parser.py` — depth by rank, not by clamping

`_build_tree` previously derived each entry's depth as
`min(min(raw_depth, MAX_NAV_DEPTH - 1), len(stack))`. The second clamp closed a
level gap for the **first** entry after the jump and for no other.

rankuno.com's Our Expertise mega-menu arrives from the collector as
`0, 2, 3, 3, 2, 2, 3` — the tab, a column heading, its items, the next heading.
The collector's depths were correct throughout; the assembly corrupted them.
`Marketing Strategy & Transformation` (raw 2) hit a stack of height 1 and
dropped to depth 1. Every later raw-2 heading met a deeper stack, stayed at 2,
and became its *child*. The entire dropdown collapsed into one chain:

```
before                                after
Our Expertise                         Our Expertise
  Marketing Strategy & Transf.          Marketing Strategy & Transf.
    Multi-Channel Digital Roadmap         Multi-Channel Digital Roadmap
    …                                     …
    Content Marketing                   Content Marketing
    Digital Channels                    Digital Channels
    SEO                                   SEO
    Paid Search                           Paid Search
    Perspective                         Perspective
```

Entries are now ranked against the raw depths of the levels still open, so two
entries arriving at the same incoming depth leave at the same outgoing depth
however wide the jump that preceded them. The raw depth is what gets recorded
per open slot, not the clamped one — past `MAX_NAV_DEPTH` several raw levels
share one slot, and ranking on the clamped value would make a deeper entry look
like a sibling of its own parent.

### `audit.ts` — duplicate URLs as a finding

Groups pages by normalised leaf segment, then confirms on ancestry. Filler
tokens (`and`, `the`, `of`, …) are dropped inside a segment, and one ancestor
chain being a subsequence of the other counts as a match. Both live shapes:

```
…/marketing-strategy-transformation/multi-channel-digital-roadmap/
…/marketing-strategy-and-transformation/multi-channel-digital-roadmap/

/expertise/digital-channels/paid-search/
/expertise/digital-channels/search/paid-search/
```

Query strings are ignored, which collapsed 14 `/job-application/?role=…` URLs
onto one page.

### `url_rules.py` — `strip_locale` now defaults to `False`

Carried over from the previous session and undocumented until now. `/de/pricing/`
is a URL Google indexes and ranks separately; an audit tool that merges it away
cannot report on it, and hreflang is an entire audit category that depends on
the variants existing. `normalize_url` also folds `www.` and the scheme.

## 3. Design decisions

**Prove self-reference; do not assume it.** The last item of a `BreadcrumbList`
is by definition the current page, so *any* lone survivor is almost always the
page — which argued for dropping every one-step trail unconditionally. Rejected.
A truncated trail such as `Home > Resources` on `/resources/foo/` also reduces
to one step, and that step is a **real parent** and the only placement the page
has. Discarding it would trade one placement bug for another. Hence the
`page_url` parameter and the URL comparison. Both directions are tested.

The parameter is optional because a caller may legitimately not have the page
URL; without it, a *linked* lone crumb is kept, since it cannot be shown to be
self-referential. Only `discovery.to_page_evidence` calls this in anger, and it
passes the URL.

**Duplicate URLs are a finding, not a tree repair.** Both URLs were crawled and
both must appear in the tree — the tree's job is to say where each page sits.
What is wrong is that they exist. Merging them in the tree would hide the
defect and, worse, would have to pick one of two *contradictory breadcrumbs*:
on rankuno.com the `-and-` variant omits the `Our Expertise` crumb its twin
publishes. That disagreement is the finding.

**Leaf segment alone is not enough to call two URLs the same page.**
`/products/socks/reviews` and `/products/hats/reviews` share a leaf and are two
pages. The ancestry check is what separates them: neither chain is a subsequence
of the other, while `[expertise, digital-channels]` is a subsequence of
`[expertise, digital-channels, search]`.

## 4. Bugs found and fixed

**The nav bug was in assembly, not extraction.** The first hypothesis — that
`_HEADING_TAGS` was picking up wrappers and swallowing siblings — was wrong.
Dumping `_NavCollector.entries` for the live homepage showed depths
`0, 2, 3, 3, 2, 2, 3`, exactly right. The defect was one line further on. Worth
recording because the collector is the complicated part and the obvious place to
look, and an afternoon spent there would have found nothing.

**`+ 16 more` on a finding with nothing more to show.** The duplicate finding's
`examples` are *groups*, one per line, but `count` was set to the URL total.
`AuditView` renders `count - examples.length` as "+ N more", so a card showing
all four groups claimed sixteen further examples. `count` is now the group count.
Found by running `buildFindings` against the real crawl rather than by reading
it.

**`1 orphaned pages`.** Pre-existing across every finding title. A `plural()`
helper now covers all five.

**A 14-URL example line.** The job-application group printed whole was a wall of
text. Capped at three URLs per group with a `(+N more URLs)` tail.

**Scratch measurement script could not call `execute` directly.** `tool.execute`
raised `CrawlBlockedError` where `scripts/run_crawl.py` succeeded seconds
earlier against the same host. The governed `tool.run()` entry point works. Not
investigated further — the measurement was the goal — but the asymmetry is real
and is logged as a follow-up.

## 5. Corrections

**Cycle 0022 and earlier described `strip_locale=True` as correct.** It is not,
for this tool. Measured on highradius.com, folding put `/de/software/order-to-cash/`
and its English twin on one key, so the surviving node's language depended on
crawl order — a German `Startseite` root inside an English tree. The damage was
limited there only because highradius translates its slugs; a site using
identical slugs per locale, which is common, would lose every variant silently.
The cost of the reversal is also real: multilingual sites now report more pages,
and those pages consume the page budget.

**An earlier session claimed the report's `Perspective` placement was a
mega-menu promo link the engine had read correctly.** Half right. The link is
genuinely inside the Our Expertise dropdown, but the two-step ancestry
`Our Expertise > Marketing Strategy & Transformation > Perspective` was
fabricated by the depth bug above. The correct trail is one step.

## 6. Explicitly not done

- **`Perspective` is still not a top-level tab.** It appears twice in
  rankuno.com's header — as a nav tab and as a mega-menu column — and URL
  de-duplication keeps the *first* occurrence, which is the dropdown copy. The
  real tab is dropped. Fixing this means preferring the shallowest occurrence
  over the first, and that carries a live regression risk: a mobile menu
  rendering flat would then beat the desktop nesting on every site. Deferred as
  its own measured change.
- **No unit tests for `audit.ts`.** `rankuno-ui/` has no test runner at all.
  `buildFindings` was verified by executing it against a stored crawl result via
  `tsx`, which is a real check but not a regression guard. Every finding in that
  module is currently protected by `tsc` alone.
- **Duplicate detection does not compare content.** It reasons about URLs only.
  Two genuinely different pages at `/search/?q=a` and `/search/?q=b` will be
  grouped. That is arguably still a finding — indexed faceted URLs — but it is
  not the claim the title makes.
- **The `-and-` duplicates are not canonicalised by the crawler.** They are
  reported, not merged. `normalize_url` does not drop filler tokens, and giving
  it that power would change the dedup key for every site at once.
- **Nothing re-measured on highradius or gep.** Both fixes are site-shape
  fixes and both sites have mega-menus; the numbers in this entry are
  rankuno.com only.

## 7. Files changed

```
src/modules/seo/page_classifier/breadcrumb_parser.py
src/modules/seo/page_classifier/discovery.py
src/modules/seo/page_classifier/nav_tree_parser.py
src/modules/seo/page_classifier/url_rules.py
tests/modules/seo/test_breadcrumb_parser.py
tests/modules/seo/test_nav_tree_parser.py
tests/modules/seo/test_url_rules.py
rankuno-ui/src/lib/audit.ts
rankuno-ui/src/lib/navTree.ts
docs/build-log/0023-placement-fidelity.md
```

## 8. Follow-ups

1. Shallowest-wins URL de-duplication in the nav parser, measured against a site
   with a flat mobile menu before it lands.
2. A test runner for `rankuno-ui/`, and `audit.ts` covered by it.
3. Re-run both fixes against highradius.com and gep.com and record the deltas.
4. `tool.execute` refusing a crawl that `tool.run` completes — reproduce and
   explain.
5. Suffix-frequency spider-trap detection. `is_spider_trap()` catches repeated
   segments *within* a path and so flagged 3,214 second-generation loop URLs on
   highradius while missing all 2,652 first-generation ones, which share a
   repeated path *suffix* across different prefixes. Unstarted; needs a
   threshold chosen against the stored crawls.
