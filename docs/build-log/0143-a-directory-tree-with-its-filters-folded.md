# Cycle 0143: A directory tree with its filters folded

- **Date**: 2026-10-07
- **Scope**: UI only (`rankuno-ui/src/`). The DirectoryTree panel's filter and cross-check controls
  now sit behind a fold that is closed by default, so the virtualised list gets the card's height.
  No Python changed.
- **Commit**: none. Changes are uncommitted in the working tree at time of writing.
- **Quality gate**: UI gate only (implementer's run, §1). The Python gate was not run because no
  Python changed.

**Numbering note**: the highest entry on disk is `0142`; this is `0143`. `0141` remains skipped
(see 0142's numbering note).

## 0. Background

The user reported, with a screenshot, that the DirectoryTree panel showed only about 7 tree rows.
The search box, level chips, confidence chips, toolbar, checkboxes and the "No Screaming Frog
cross-check is saved..." note consumed most of the card's height, leaving little for the list.

## 1. Gate results

Run by the UI implementer from `rankuno-ui`; quoted, not re-run by the scribe:

| Check | Result |
| :--- | :--- |
| `npx tsc --noEmit` | clean |
| `npx vitest run` | Test Files 52 passed (52), Tests 685 passed (685) |
| `npm run contract` | "UI contract is up to date." |
| `npm run build` | built in 23.07s, only the pre-existing chunk-size warning |
| Python gate (`verify.ps1`) | not run, no Python changed |

Test count 685 is up from 682 in 0140; the 3 new tests are in `TreeControls.test.tsx`.

## 2. What landed

| File | Change |
| :--- | :--- |
| `store/useDashboardStore.ts` | `filtersOpen` (default `false`) and `setFiltersOpen` |
| `components/tree/TreeControls.tsx` | Always visible: L1, L2, Expand all, Collapse all, a "Filters and cross-check" fold button, Full screen. The fold button carries `aria-expanded` and `aria-controls="tree-filter-details"` and appends " (on)" when cross-check is active while folded. Inside the fold (`.xdetails`): Cross-check, Include Defaulters, Missed only, reason chips, the Screaming Frog note. Full screen mode always shows the details and has no fold button |
| `components/layout/DashboardShell.tsx` | `LevelFilterRow` chips render only when `filtersOpen`; `TeleportSearch` stays always visible |
| `components/tree/VirtualizedTree.tsx` | A `ResizeObserver` effect in `TreeList` calls the existing `recompute()`, guarded for jsdom (no `ResizeObserver`). `ROW` height, windowing arithmetic, `OVERSCAN` and the footer are untouched |
| `styles/design-system.css` | `.vtree { min-height: 0 }` so the list shrinks and scrolls instead of growing the card |
| `components/tree/tree-overlay.css` | `.xfold`, focus-visible rings, `.xdetails`. The `max-height: 42%` rule near line 183 belongs to `.xcards`, not the controls, and was left alone |
| `components/tree/TreeControls.test.tsx` | `openFilters()` helper, `beforeEach` store reset, 3 new tests (below) |

New tests: starts folded with the depth buttons and Full screen reachable; the button toggles
`aria-expanded` and the store flag and shows/hides the controls; Full screen shows all controls with
no fold button.

## 3. Design decisions

- **Default-collapsed is a UX choice the user can reverse.** It hides the level chips, confidence
  chips and cross-check toggles until the user opens "Filters and cross-check". To reverse it, change
  the default of `filtersOpen` in `useDashboardStore.ts` to `true`.
- **ResizeObserver rather than a one-off recompute.** The window reads `clientHeight`; folding the
  section or resizing the window changes it, and nothing else re-reads it, so the list would leave
  blank space under the last mounted row. The effect reuses the existing `recompute()` and does not
  alter windowing arithmetic.
- **Full screen shows everything.** There the height problem does not exist, so the fold button is
  removed rather than offered.
- **"(on)" suffix.** A cross-check that is active but folded would otherwise be invisible.

## 4. Bugs found and fixed

None found on the way. The change addresses the reported layout complaint, not a defect in code.

## 5. Corrections

None. No earlier entry's claim was found false in this cycle.

## 6. Explicitly not done, and unverified

- **No browser verification of any kind.** No rows were counted before or after, there is no
  screenshot, and Full screen was covered only by jsdom tests. The ">= 20 rows at ~900px" target is
  **UNVERIFIED**; jsdom has no layout, so none of the 685 tests can speak to row count.
- **If the real list still shows ~7 rows**, the cause is above the card: the `.rk-body` KPI strip
  and `NoticeStack` banners stacked above `.split`. The next step is a DevTools check of the `.card`
  height. This change would not help in that case.
- The `ResizeObserver` path is not exercised by any test (guarded out under jsdom).
- Nothing was committed.
- Stale or unfixed items found: none new.

## 7. Files changed

All under `rankuno-ui/src/`: `store/useDashboardStore.ts`, `components/tree/TreeControls.tsx`,
`components/tree/TreeControls.test.tsx`, `components/tree/VirtualizedTree.tsx`,
`components/tree/tree-overlay.css`, `components/layout/DashboardShell.tsx`,
`styles/design-system.css`. `git diff --stat`: 7 files, 135 insertions, 25 deletions.

## 8. Follow-ups

Open the app in a browser, count visible tree rows at ~900px height, and check the `.card` height
in DevTools if the count is still low.
