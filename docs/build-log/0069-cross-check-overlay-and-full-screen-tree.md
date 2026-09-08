# Cycle 0069: Cross-check overlay, section totals and the OTHERS insight

- **Date**: 2026-09-07
- **Scope**: UI only. The directory tree marks every page Screaming Frog did
  not find, counts them per section, and opens across the whole screen with
  per-section totals and an OTHERS breakdown fed by Search Console.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `20 files, 202 tests passed`; `tsc --noEmit` exit 0. See §7.

## 1. The request

*"When I upload the Screaming Frog report, the URLs which are not under the
report must be marked differently in the tree view — a toggle. Show the number
of URLs at each classified category. Make a full-view directory tree covering
the whole screen where each L0 category shows how many URLs Screaming Frog
missed. The main insight point is OTHERS: if a category under OTHERS has good
GSC numbers, that is the main thing for the analyst — why did the engine
classify it under OTHERS? And many OTHERS URLs missed by Screaming Frog is
also a finding."*

The user's ruling on the one open design question: **count every reason, keep
the breakdown visible, make each reason a toggle.**

## 2. What was measured before anything was built

| Fact | Where | Consequence for the design |
| :--- | :--- | :--- |
| `engine_only[{url, reason}]` in the reconciliation sidecar is the list of URLs Rankuno found and Screaming Frog did not. Across all 10 stored sidecars, **100 % of those URLs match the source result's page URLs exactly.** | `.jobs/*.reconciliation.json` | Exact match first; loose match only for a residue; residue reported. |
| The sidecar is stored against the **source** job. The merged "(+N from Screaming Frog)" job has none, and its `JobRecord` carries no `source_job_id`. | `.jobs/d0a59fbc….json` | The toggle is disabled with a message naming this on the merged job. The backend fix needs `server.py`, which another session holds. |
| The 7 pages merged in from the export are exactly the profiles whose `discovery_sources` are all `false`. No page of a real crawl has that shape; 98 % of older stored pages lack the field entirely. | jobs `547ec81c` (0 all-false) vs `d0a59fbc` (7 all-false), `1e9dfba4` (8,139 missing) | "Added from SF" is read from the result itself, so it works on the merged job; a missing field is *unknown*, never *added*. |
| `breadcrumb_path = ["OTHERS", <PrimaryPageType>]`; no page has an empty trail. `navTree` roots each locale, so `/es-es/company` sits under `es-es > OTHERS > UNKNOWN`. | `navTree.ts:112-123` | OTHERS is identified by **lane**, not by the node named OTHERS. |
| On gep.com job `547ec81c`: 1,817 misses = `QUERY_VARIANT 1,332`, `SITEMAP_ORPHAN 403`, `REPEATED_SUFFIX_TRAP 82`. Knowledge Bank: 784 of 1,127 missed, 781 of them pagination. | sidecar summary | A raw count says "SF missed 70 % of Knowledge Bank". True and misleading. The reason travels with the count, and each reason can be switched off. |
| Search Console figures exist in two places: the profile's `gsc_*` fields (OAuth integration, 5,550 of 8,304 pages on that job) and my `.performance.json` sidecar (≤1,000 rows, section rollups keyed by raw trail, **no per-page map**). | `PerformanceSummary` | Only the profile fields feed the tree. The inspector's per-node card reads the same fields, so a section total and a page figure can never disagree on screen. The sidecar cannot feed a per-page rollup and its section keys ignore locale roots. |
| `DashboardShell.tsx`, `design-system.css`, `navTree.ts`, `AuditView.tsx`, `schemas.py`, `server.py` are all in the other session's working tree. | `git status` | Nothing here touches them. The full-screen view is a portal opened from inside the tree card. |

## 3. Architecture

An **overlay, not a model change**. `buildDashModel` is untouched.
`buildTreeOverlay(model, reconciliation, hiddenReasons)` returns typed arrays
indexed by `DashNode.i` — `mark`, `reason`, `missedCnt`, `addedCnt`, `clicks`,
`impressions`, `gscPages` — plus per-root and OTHERS summaries and an
integrity check. Subtree totals use the same reverse pass `cnt` uses.

The overlay carries a reference to the model it was built for, and every
consumer checks `overlay.model === model` before reading an index. That is
what makes the store safe across a job switch: the new model arrives before
its overlay, and the old overlay's indices belong to another tree.

`useTreeOverlay` runs in `VirtualizedTree` — the one component always mounted
while a tree is on screen — and publishes to `useDashboardStore`, where
`flatten` reads `missedCnt` for the "missed only" filter. That filter keeps a
section whose subtree holds a missed page, or the page could never be reached.

The full-screen view is `createPortal` to `document.body`, reusing `TreeList`
and the same expansion/focus state. Section cards focus a root; OTHERS rows
focus a page in the inspector.

## 4. What an analyst sees on gep.com job `547ec81c`

Real output of the shipped code against the stored result (run through the
same `buildDashModel` + `buildTreeOverlay` the UI calls):

```text
nodes=8644  model=1149ms  overlay=46ms
crossCheck true | gsc true | unmatched 0 | integrity {expected: 6487, actual: 6487}
reasons { SITEMAP_ORPHAN: 403, QUERY_VARIANT: 1332, REPEATED_SUFFIX_TRAP: 82 }
  Knowledge Bank   pages=1127 missed=784 {"QUERY_VARIANT":781,"SITEMAP_ORPHAN":3} clicks=14091 gscPages=164
  Company          pages=154  missed=15  {"QUERY_VARIANT":14,"SITEMAP_ORPHAN":1}  clicks=14508 gscPages=110
  Careers          pages=20   missed=0   clicks=24768 gscPages=20
OTHERS { pages: 1781, missed: 351, clicks: 6734, share: 0.027 }
  UNKNOWN        pages=1603 missed=349 clicks=3162 impressions=1934338 gscPages=705
  HOMEPAGE       pages=4    missed=0   clicks=2362 impressions=77433
  BLOG_ARTICLE   pages=150  missed=1   clicks=785  impressions=250862
```

Three findings the view surfaces without anyone asking:

1. **Four localised homepages sit under `OTHERS > HOMEPAGE`** (`/es-es/`
   1,473 clicks, `/it-it/`, `/jp-ja/`, `/zh-cn/`). The engine places a
   homepage nowhere when it is not the root homepage. That is a classification
   defect, and it is the first row of the OTHERS table.
2. **`OTHERS > UNKNOWN` carries 1.93 M impressions on 3,162 clicks** across
   705 pages with GSC rows — a 0.16 % CTR on pages nothing on the site links
   to from navigation. 349 of them Screaming Frog never saw.
3. **"Knowledge Bank 70 % missed" is 781 `?page=N` URLs.** With the
   `Query Variant` chip off it reads 3 missed, all sitemap orphans. Both
   numbers are true; the chip is what lets the analyst choose which question
   they are asking.

## 4b. OTHERS regrouped by URL folder, with FLAT_URLS

Requested on seeing the panel: *"I don't want the explicitly defined
category; club the URLs on the basis of folder structure, and an explicit
FLAT_URLS category under OTHERS for URLs with no folder."*

Measured first, on the same job's 1,781 OTHERS pages: **80 flat** (`/cookie-
policy`, `/privacy-statement`, `/grid`, the four locale homepages — 4,096
clicks between them), the rest in **59 folders up to five deep** —
`mind/blog/tag` 770, `prod/s3fs-public/files/newsroom/docs` 206, `podcasts`
155, `bulletins` 145, `partners` 59, `company` 55. `OTHERS > UNKNOWN 1,603`
hid all of that.

Done in the UI (`navTree.othersTrail`), not the engine. `logical_hierarchy.py`
still writes `nav_path = (OTHERS, page_type)`; the tree replaces that trail
with the URL's folders — locale prefix dropped because the locale is already
the root, last segment dropped because it is the page — or with `FLAT_URLS`
when nothing is left. Every one of the 155 stored jobs regroups without a
re-crawl, and the page type stays on each row's chip and in the inspector.
`FLAT_URLS` sorts last under OTHERS, as OTHERS sorts last among sections.

The OTHERS panel's bucket is now read by walking up from the page to the child
of OTHERS on screen, not from the engine's trail — the two no longer agree,
and the panel must describe the tree beside it.

Live, after the change: `mind` 772 pages, 342 SF-missed, **0 clicks** on
7,163 impressions (a tag-archive silo); `/strategy/` 59 unplaced pages with
440 clicks while the `Strategy` menu section holds 3.

**Correction to the record**: this section and its tests were written on
2026-09-07, lost twice to the parallel session's `git stash` / history
rewrite (`30f9284` → `e71e506`), and re-applied on 2026-09-08. The source
change (`navTree.ts`) survived in `e71e506`; the tests and this text did not.

## 5. Bugs found and fixed

- **Ancestors vanish under a leaf filter.** The first shape of "missed only"
  tested the node's own mark, which hid every section and left the missed
  pages unreachable. Fixed by filtering on the *subtree* count; the test
  "keeps the section above a missed page" pins it.
- **Effect ordering would have nulled the overlay.** Resetting `overlay` in
  `setModel` looked right and was wrong: child effects run before parent
  effects, so the tree's `setOverlay` would have fired *before* the shell's
  `setModel` cleared it. Replaced by the model-identity check, which needs no
  ordering at all. Pinned by "ignores an overlay built for a different model".
- **`Int32Array[parent] += …` fails `noUncheckedIndexedAccess`.** Written as
  explicit reads with non-null assertions, matching how `dashboardModel.ts`
  handles the same pass.
- **Late sidecar for the wrong job.** `loadReconciliation` guards on
  `activeJobId` before writing; the test releases job A's read after job B is
  selected and asserts the store holds `null`.
- **Two OTHERS figures that disagreed on screen.** The tree row named
  `OTHERS` showed 1,522 pages / 2,673 clicks; the panel showed 1,781 / 6,734.
  Both were right — the panel counts the OTHERS *lane*, and each locale root
  has an OTHERS of its own beneath it (`es-es` 36 pages / 2,325 clicks,
  `jp-ja` 53 / 705, `it-it` 93 / 675, `zh-cn` 75 / 356, `de` 2 / 0) — but
  nothing said so. `OthersSummary.byRoot` now carries the split and the panel
  renders it as focusable chips. Reported by the user from the screen.
- **Opening any section threw the tree to the bottom** (pre-existing, in
  `TreeList`'s reveal effect, reported by the user). The effect that scrolls a
  newly selected row into view was keyed on `[focus, flat]`, and every twisty
  click re-flattens `flat`. With `OTHERS` selected — the last root, off-screen
  — each click "revealed" the unchanged selection again. A ref now records the
  last focus revealed, so only a *change* of selection scrolls. The regression
  test had to replace jsdom's `scrollTop` (writes are discarded, so the first
  version passed with the bug in place) and wrap the store calls in `act`
  (the effect had not flushed). With the fix reverted it fails
  `expected 930 to be 30` — thirty rows down, the reported symptom.
- **`⛶ Full screen` would have rendered as bare text.** The global
  `.rk-dash button` reset at (0,1,1) outranks a single class; the parallel
  session's `buttonReset.test.ts` documents the pattern. Scoped to
  `.xctl .xfull`. The portal's own buttons sit outside `.rk-dash` and were
  never affected.

## 6. Explicitly not done

- **The merged "(+N)" job cannot find its cross-check.** It needs either a
  reverse lookup in `get_reconciliation` or `source_job_id` on the merged
  `JobRecord`; both are in files the other session holds. On that job the
  toggle is disabled and the tooltip says where the cross-check lives.
  "Added from SF" marks *do* work there, because they come from the result.
- **The upload-path performance sidecar does not feed the tree.** It has no
  per-page map. A job with an uploaded export and no OAuth crawl shows no GSC
  figures in the tree; the Performance panel on the Jobs view still shows
  them. Adding a `pages` map to `PerformanceSummary` would close this.
- **The printable report ignores the overlay.** `CrawlReport` reads the
  model only.
- **Nothing persists across reloads.** The toggles live in the store, like
  every other tree control.
- **The four OTHERS homepages are reported, not fixed.** The placement
  defect is in the engine's trail builder, not in this view.
- **The lint `--exclude` situation is unchanged**: the other session's
  root-level scratch scripts still fail `ruff`, so the Python gate cannot run
  green from this tree. This cycle changed no Python.

## 7. Gate

```text
> npx vitest run
 Test Files  20 passed (20)
      Tests  202 passed (202)
> npx tsc --noEmit
exit 0
```

New: `treeOverlay.test.ts` (13), `useDashboardStore.test.ts` (4),
`TreeControls.test.tsx` (4), `useCrawlStore.test.ts` (+4). Both servers
were up during the cycle (`vite 200`, `api 200`); the tree hot-reloaded.

## 8. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/lib/treeOverlay.ts` | new — `buildTreeOverlay`, `addedFromFrog`, `REASON_MEANINGS`, summaries |
| `rankuno-ui/src/store/useCrawlStore.ts` | `reconciliation` loaded with the result, job-id guarded |
| `rankuno-ui/src/store/useDashboardStore.ts` | `overlay`, `crossCheckOn`, `missedOnly`, `hiddenReasons`, `fullScreen`; `flatten` takes a mask |
| `rankuno-ui/src/components/tree/VirtualizedTree.tsx` | split into `VirtualizedTree` (controls + list + portal) and `TreeList`; row marks, section counts, integrity footer |
| `rankuno-ui/src/components/tree/TreeControls.tsx` | new — toggle, reason chips, missed-only, full-screen button |
| `rankuno-ui/src/components/tree/FullScreenTree.tsx` | new — portal view |
| `rankuno-ui/src/components/tree/SectionCards.tsx` | new — per-root cards, sortable |
| `rankuno-ui/src/components/tree/OthersInsight.tsx` | new — bucket table and most-clicked OTHERS pages |
| `rankuno-ui/src/components/tree/useTreeOverlay.ts` | new — builds once, publishes to the store |
| `rankuno-ui/src/components/tree/tree-overlay.css` | new — feature styles on design-system tokens |
| `rankuno-ui/src/components/inspector/NodeInspector.tsx` | "Screaming Frog" row |
| tests | as listed in §7 |

Numbered 0069: 0067 and 0068 were taken by the parallel session while this was written.
