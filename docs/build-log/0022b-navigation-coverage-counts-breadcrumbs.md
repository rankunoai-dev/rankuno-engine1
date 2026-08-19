# Cycle 0022: Navigation coverage counts breadcrumbs, not just the menu

- **Date**: 2026-08-12
- **Scope**: Teach `nav_coverage` about breadcrumb placement, so the KPI cards
  stop contradicting the tree beside them; relabel the node count that called
  itself a URL count.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1238 passed, 1 warning in 94.73s` / `Total coverage: 95.17%`

---

## 1. Gate results

```
159 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 42 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.17%
1238 passed, 1 warning in 94.73s (0:01:34)
PASSED: Tests
ALL GATES PASSED.
```

Frontend, from `rankuno-ui/`:

```
tsc --noEmit    TSC_EXIT=0
vite build      VITE_EXIT=0   ✓ built in 21.96s
```

---

## 2. The bug, as the operator saw it

One screen, two numbers about the same thing, 34× apart. The OTHERS **card**
read `24,371 — no navigation path reaches these`. The OTHERS **lane** in the
tree beside it held 1,544 nodes. Both were computed correctly. The card was
answering a different question than its own subtitle claimed.

Measured on the stored kinsta.com crawl (27,656 pages):

| `trail_source` | pages | tree places it | `nav_coverage` called it |
| :--- | ---: | :--- | :--- |
| `menu` | 3,285 | under its menu section | in navigation ✓ |
| `breadcrumb` | 22,869 | under Home / Resources / Docs | **unmatched** ✗ |
| `none` | 1,502 | OTHERS | unmatched ✓ |

`3,285` was the In-navigation card exactly; `22,869 + 1,502 = 24,371` was the
OTHERS card exactly. The arithmetic was never wrong. The **meaning** was: 94% of
the pages in that bucket had a published navigational position, and the card
said nothing reached them.

### Root cause

`assign_navigation` runs *before* `_better_trail` decides between the menu path
and the page's own breadcrumb. It therefore cannot know which source won — it
only sees the menu. When breadcrumb placement was added, the metric was never
taught the second source existed.

The divergence had already been *noticed* and worked around locally: the printed
report stopped reading `nav_coverage` and counted from the tree instead, and its
comment records the same failure on gep.com — 5,834 in OTHERS against 1,210 in
the tree. That workaround fixed one surface and left the metric wrong for every
other reader. Worth naming as a pattern: a local workaround for a shared metric
hides the defect from the next person rather than removing it.

---

## 3. What landed

### `NavCoverageReport.breadcrumb_matches`, and `unmatched` means it now

`unmatched` now means *nothing on the site places this URL*. The menu split
(`exact_matches` / `inherited_matches`) is unchanged, and `breadcrumb_matches`
is new. Two properties name the two questions so neither has to be reassembled
by a caller:

* `coverage` — any published position. Widened from the old menu-only meaning.
* `menu_coverage` — the previous meaning, kept. The **gap between the two is
  itself the finding**: kinsta.com is 94.6% placed and 11.9% menu-placed, which
  says its header menu reaches almost none of the site.

### `recount_placements(report, pages)`

Restates a menu-derived report against the final `trail_source`. Three decisions
inside it:

* **Counts `trail_source`, not a non-empty `breadcrumb_path`.** A page in OTHERS
  carries the trail `(OTHERS, <page type>)` — non-empty, and placing nothing.
  Counting paths would report every unplaced page as placed, which is the
  inverse of the bug being fixed. There is a test pinning this.
* **Carries the menu split through rather than re-deriving it.** Re-deriving
  would put a second definition of "exact match" in the codebase to disagree
  with `_nav_entries`' prefix matching.
* **Clamps that carried split.** `_better_trail` can demote a menu-placed page
  when its breadcrumb is deeper, so the stored `exact + inherited` can exceed
  the pages still menu-placed; unclamped, `unmatched` goes negative and trips
  its own `ge=0` constraint. Found by writing the test, not by the gate.

Called from all three placement paths — `place_pages`, its no-homepage branch,
and `reparse_placement`. The no-homepage branch matters most: it is the
sitemap-only crawl, where *every* placement that exists came from a breadcrumb,
so a menu-only count reports a fully-breadcrumbed site as 100% unplaced.

### The KPI card

"In navigation" → **"Placed in navigation"**, with both sources on the card:

```
26,154        94% of pages · 3,285 via header menu · 22,869 via published breadcrumbs
```

OTHERS keeps its number but loses the false subtitle: *"neither the menu nor a
breadcrumb places these"*.

### Verified against the real crawl, not a fixture

`reparse_placement` over the stored kinsta result:

```
                           BEFORE      AFTER
exact_matches                  64         64
inherited_matches           3,221      3,221
breadcrumb_matches              0     22,869
unmatched (OTHERS)         24,371      1,502
placed                      3,285     26,154
coverage                    11.9%      94.6%
menu_coverage               11.9%      11.9%
parts sum to total -> True
```

OTHERS is now 1,502 against the tree's OTHERS lane of 1,544 — the 42 difference
being structural grouping nodes, which is the nodes-vs-pages distinction of §3
below and not a disagreement.

### `TeleportSearch` says "nodes"

It read `Teleport-search 29,248 URLs…` while the card beside it read 27,656.
Both were right: 1,592 of those nodes are **structural** — menu sections that are
not themselves pages, carrying `profile: null` and a path where a URL would go.
The count was never wrong; the noun was. Now "nodes", matching the header, which
already said nodes.

---

## 4. Bugs found and fixed

### A generated type that lies about stored data

`schema.ts` is generated from the Pydantic model, so `breadcrumb_matches` is
emitted **required**. Every result written before this cycle lacks it, and those
are still loadable from `.jobs/` — reading it as a guaranteed `number` puts
`undefined` behind `number` and prints `NaN` on the card.

This is the same lesson as cycle 0021 §4, hit again within a day: **generated
types describe what the engine emits today, not what is on disk.** Read through
a cast, like `trailSourceOf` already does.

`KpiMetricStrip` therefore has a fallback: when the field is absent it recounts
`trail_source` across the pages — the same input `recount_placements` uses — so
a stored crawl and a reparsed one show the same numbers. When `trail_source` is
absent too (older still), the stored menu-only numbers stand rather than a zero
being asserted: an absent measurement is not a measurement of zero.

### The gate caught the hand-edited contract

`test_ui_contract.py` failed on a stale `schema.ts` because the field was added
by hand. Regenerated with `scripts/export_ui_contract.py`. Working as designed.

---

## 5. Corrections

**A third defect was reported to the operator during diagnosis and does not
exist.** The claim was that localised unplaced pages escape the OTHERS lane
because `buildDashModel` only tests for the OTHERS label at depth 0, putting 802
of 1,502 into the L1–L3 lanes and leaving the lane at 712.

It is wrong. `buildDashModel` propagates `othersBranch` to every descendant and
re-tests each child's segment, so an OTHERS node under a locale root is caught.
The error was in the throwaway Python used to reproduce the numbers, which
tested `depth == 0 and label == OTHERS` and did not replicate the propagation.
The real OTHERS lane is **1,544**, not 712.

Recorded because it was acted on: an edit to `dashboardModel.ts` was written and
reverted before the gate. Two lessons, both cheap in hindsight:

* A reproduction script is not evidence about the code unless it reproduces the
  code. This one simplified the exact line that carried the behaviour.
* The number that should have raised the alarm was already on screen: 712 is
  smaller than the 1,502 genuinely-unplaced pages, and a lane cannot hold fewer
  nodes than the pages assigned to it.

Findings 1 and 2 were both verified against the stored crawl and stand.

---

## 6. Explicitly not done

- **Stored results are not migrated.** `.jobs/` holds ~40 crawls with the old
  menu-only numbers. The UI fallback recounts from `trail_source` so they *read*
  correctly, but the stored JSON is untouched. A crawl reparsed through
  `POST /jobs/{id}/reparse` gets the corrected figures written; nothing does
  that in bulk.
- **The lane chips still count nodes, not pages.** L0–L3 + OTH sums to 29,248,
  not 27,656, because structural nodes are nodes. The tooltip has always said
  "nodes". Left alone: the tree is a tree, and a chip that counted only pages
  would not match the rows it filters.
- **`menu_coverage` is not surfaced anywhere.** It exists on the model and is
  tested, but no card shows it. The menu-vs-breadcrumb split on the KPI card
  carries the same information for now.
- **No live crawl was run.** The change is verified by unit tests and by
  reparsing a stored 27,656-page result. A fresh crawl through
  `place_pages` — the path a live run actually takes — was not executed against
  a real site.
- **Nothing was looked at in a browser.** There is still no frontend test
  runner; `tsc` and `vite build` are the only automated frontend checks and
  neither renders a component. The KPI subtitle is now three clauses long and
  may wrap badly in a narrow card — unverified.
- **`breadcrumb_matches` is not broken down further.** A page placed by its own
  breadcrumb could be distinguished by trail depth or by whether the breadcrumb
  agreed with the URL path. Not attempted; there is no question waiting on it.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/logical_hierarchy.py` | `breadcrumb_matches`, `placed`/`menu_matches`/`menu_coverage`, `recount_placements` |
| `src/modules/seo/page_classifier/tool.py` | Recount in all three placement paths |
| `rankuno-ui/src/types/schema.ts` | Regenerated |
| `rankuno-ui/src/components/metrics/KpiMetricStrip.tsx` | Both sources on the card; legacy fallback |
| `rankuno-ui/src/components/tree/TeleportSearch.tsx` | "URLs" → "nodes" |
| `rankuno-ui/src/components/report/CrawlReport.tsx` | Stale workaround comment corrected |
| `tests/modules/seo/test_logical_hierarchy.py` | `TestRecountPlacements` (7 tests) |

## 8. Follow-ups

- Offer a bulk reparse, or reparse on read, so stored crawls carry the corrected
  coverage instead of relying on the UI fallback.
- Report the menu-coverage finding to the client: kinsta.com's header menu
  reaches 11.9% of its own site, and 22,869 pages depend entirely on breadcrumbs
  for their published position. That is an SEO finding, not a crawler artefact.
- Consider whether `unmatched` should be renamed `unplaced` in the contract; it
  now means something narrower than it did, and the old name is what invited the
  original misreading.
