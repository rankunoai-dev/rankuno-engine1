# Cycle 0014: Grouping a crawl by the site's own header menu

- **Date**: 2026-08-11
- **Scope**: Add a navigation-based grouping axis alongside the URL-path tree.
  Configurable request headers for sites that reject unknown clients.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 943 tests, 95.57% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   943 passed in 45.63s
                             Required test coverage of 85.0% reached. Total coverage: 95.57%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0. 52 new tests.

---

## 2. Corrections to the cycle's own plan

**First, because these were the premises the work was requested on.**

### 2.1 "95–98% accuracy" is withdrawn

The plan compared the new architecture against the old with a table:
"OLD (URL path nesting) 40–60%" versus "NEW (Logical Header Nav Tree) 95–98%".
**None of those four numbers was measured**, and there is still no golden corpus
to measure accuracy against (CLAUDE.md §8).

More fundamentally, the comparison is category error. Navigation grouping does
not touch `primary_page_type`, `hierarchy_level`, `search_intent` or
`conversion_role` — every one of those is produced by the cascading pipeline from
page evidence and is byte-identical before and after this cycle. **This changes
how pages are grouped, not how they are classified.** It cannot raise
classification accuracy, and no number in this cycle should be read as saying it
did.

### 2.2 Measured navigation coverage on gep.com is 7.1%, not 95%

Against the full sitemap:

```
nav entries : 153        sitemap URLs : 4427
exact       : 141        (the URL is itself a menu entry)
inherited   : 172        (sits beneath one, e.g. /blogs/strategy/... -> /blogs/)
unmatched   : 4114
coverage    : 7.1%
```

The plan's edge case anticipated "~80%" in `OTHERS`. The real figure is **92.9%**.

The dominant cause is a real finding rather than a parser failure: gep.com's
header links `/blogs/` (plural), while several thousand legacy posts live under
`/blog/` (singular), which the current header links nowhere. Those pages are
unreachable by browsing. Surfacing that is what `OTHERS` is *for* — but it means
the navigation tree describes a small corner of this site, and the UI says so
rather than implying otherwise.

### 2.3 `L0`–`L3` was not redefined

The plan mapped `L0` to "top header tab", `L1` to "mega-menu heading" and so on.
`HierarchyLevel` already uses those names for something else — a page's **role**
(`L1_PRIMARY_NAV_HUB`), documented as "structural position … independent of page
purpose" — and it is consumed by the signal weights, the evaluation module, the
golden-corpus label format, the tree visualizer and the UI swimlanes.

Redefining it would have broken all five at once. Navigation position is carried
instead by `nav_parent_url` and `breadcrumb_path`, both of which have been on
`FullPageIntelligenceProfile` since Phase 1 was specified and were populated by
nothing until now.

---

## 3. What landed

### `nav_tree_parser.py`

Parses `<nav>`/`<header>`/`role="navigation"` into a tree, with nesting taken
from `<ul>`/`<ol>` depth. Capped at three levels.

* **Footer excluded.** gep.com publishes seven `<nav>` elements; most are not the
  header. Including them puts "Privacy Policy" beside "Solutions" as a top-level
  section.
* **Desktop/mobile duplicates collapsed.** Nearly every site ships both menus;
  counting each would double the tree.
* **JSON-LD fallback** to `SiteNavigationElement` for client-rendered headers
  that leave no anchors in the served HTML. Flat, because that markup has no
  nesting to recover — which is why it is a fallback.
* **`NavSource.strategy`** records `dom` / `jsonld` / `none`, so "no menu found"
  and "menu found but empty" stay distinguishable.

### `logical_hierarchy.py`

Maps each crawled URL to the deepest menu entry whose path contains it.

**Prefix inheritance is the whole feature.** Exact matching alone covers 141 of
4,427 gep.com URLs — 3.2%. A bucket holding 96.8% of a site has organised
nothing. Treating a menu entry as a prefix its descendants inherit is what makes
the grouping usable at all.

`OTHERS` members are sub-grouped by `PrimaryPageType` so the bucket stays
navigable at four thousand URLs.

### `http_fetcher.browser_headers`

Off by default, exposed per job. Some enterprise edges refuse any client they do
not recognise — returning `403` for `robots.txt` itself, so the site cannot state
what it permits.

Three things this deliberately is not, all departures from the plan as written:

* **Not automatic.** The plan specified a "WAF fallback" that retries after a
  `403`. Re-sending a refused request under a different identity the moment a
  server says no is working to defeat the refusal. An operator selects this
  up front instead.
* **No `Sec-CH-UA` client hints.** Those exist for a browser to describe itself
  accurately; forging them adds nothing except making the request harder to
  identify as automated.
* **robots.txt compliance unchanged.** The point of reaching `robots.txt` is to
  obey it.

`user_agent` was already a field and remains the operator's choice. A
non-default value is now logged, because which identity a crawl presented is part
of what it did.

### UI

A `Navigation` / `URL path` toggle, nav-grouped tree, nav-lane graph whose edges
follow `nav_parent_url`, and a coverage line stating what fraction of pages the
menu accounts for. Navigation mode falls back to the path tree when no menu was
parsed — a single `OTHERS` bucket holding the whole site is worse than the view
it replaced.

---

## 4. Bugs found and fixed

### 4.1 The logo link made coverage read 100% on every site

The first live measurement returned `OTHERS: 0` and `COVERAGE: 100.0%`. That was
the bug, not the achievement.

Almost every header links its logo to `/`, whose match key is `/` — a prefix of
**every URL on the site**. Sorted longest-first it matches last, so it silently
absorbed everything that should have gone to `OTHERS`. Any site with a logo link
would have reported perfect coverage regardless of its menu.

Fixed by excluding the site root as a match target. Post-fix on the same crawl:
`exact 120, OTHERS 480, coverage 20.0%`.

Had this shipped, the headline number would have been "100% navigation coverage"
— and it would have been meaningless on every site.

### 4.2 Decorative anchors became top-level sections

Live output: `top tabs: ['', '', 'Company', 'Solutions', 'Industries',
'Knowledge Bank', '›', '›', '›', ...]`.

Two causes. Icon-only links (logo, login, search) have no text, so their label was
empty. Chevron separators inside `<span>` were captured by the unlinked-heading
support added earlier in this cycle. Fixed: a label must contain a word
character, and an icon-only link is named from its URL's last path segment
(`/login` → `Login`).

### 4.3 The exporter refused the recursive navigation type

`NavNode.children: tuple[NavNode, ...]` is self-referential, which the contract
generator had never encountered. It failed with
`PageClassificationOutput.navigation references 'NavigationTree', which the
exporter does not emit` — the dangling-reference guard naming the missing model
rather than emitting a broken file. Registering the three models was the whole
fix; the recursion rendered correctly as `children: NavNode[]`.

### 4.4 Test bugs of my own

`FullPageIntelligenceProfile` requires `signals_evaluated`, `depth_from_l0`,
`search_intent`, `final_confidence_score` and `consensus_method`. My first
fixtures omitted them. Built in full rather than stubbed, because the model
validates its own level/type coherence and a duck-typed stand-in would pass tests
against a shape the pipeline cannot produce.

---

## 5. Known limitations

* **Mega-menu ancestry is unreliable on complex headers.** Observed on gep.com:
  `('Knowledge Bank', 'Join Us', 'Savings & Compliance Tracking')`. "Join Us" is
  not the parent of that item — gep's mega-menu interleaves several panels inside
  one list, and list nesting does not recover which panel an item belongs to. The
  top-level tab is usually right; the middle level often is not. **Do not present
  the middle level of a parsed menu as authoritative.**
* **`OTHERS` is sub-grouped by page type only.** The plan also called for URL
  path-prefix sub-grouping, which would organise the 4,114-URL `/blog/` tree.
  Not built.
* **Navigation is read from the homepage only.** Sites with section-specific
  headers will have those sections' menus ignored.
* **No live verification of `browser_headers`.** It is unit-tested; no blocked
  site was crawled with it.
* **No frontend tests.** `rankuno-ui` still has no test runner.

---

## 6. Live verification

```
status: partial
pages_fetched 123 | total_urls 600
nav strategy  : dom       nav containers: 2      nav links: 160
top tabs      : ['Login', 'Contact Us', 'Company', 'Solutions', 'Industries', 'Knowledge Bank']
exact 120 | inherited 0 | OTHERS 480 | COVERAGE 20.0%
```

`inherited: 0` on this slice is not a defect: the first 600 URLs of gep.com's
sitemap are dominated by the legacy `/blog/` tree, which no menu entry contains.
The full-sitemap measurement in §2.2 shows inheritance working — 172 pages placed
under `/blogs/` and other sections.
