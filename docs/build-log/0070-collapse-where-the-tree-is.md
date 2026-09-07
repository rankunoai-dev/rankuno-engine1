# Cycle 0070: Collapse belongs where the tree is

- **Date**: 2026-09-07
- **Scope**: Give the full-screen tree the expand/collapse commands it never
  had, by moving them out of the dashboard toolbar into the tree's own control
  row.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI `213 passed` / 20 files, `tsc` clean, `vite build` exit 0.

---

## 1. Gate results

```
> npx vitest run
 Test Files  20 passed (20)
      Tests  213 passed (213)

> npx tsc --noEmit
 (no output)

> npx vite build
 ✓ built in 13.67s   [exit 0]
```

The build's only warning is the 16 MB `synthetic-20000` performance fixture
exceeding the chunk-size limit. Pre-existing and untouched by this cycle.

---

## 2. The controls existed, in the one view that did not need them most

Reported against the full-screen tree: no way to collapse or expand. The
commands were not missing from the app — `L1`, `L2`, `Expand all` and
`Collapse all` were in `DashboardShell`, rendered above the inline visualizer's
tree card.

`FullScreenTree` portals to `document.body` and renders `TreeControls` +
`TreeList` directly. It never saw the dashboard toolbar. So the view with the
most rows on screen, and the most need to close them, was the only one with no
way to.

Moved into `TreeControls`, which both views already render. One definition
rather than a copy, so the two cannot drift.

---

## 3. Design

### 3.1 Depth first, then the overlay

The row now reads: depth commands · Cross-check · Missed only · reason chips ·
Full screen. You shape the tree, then compare it against something. A vertical
rule separates the two groups — the previous complaint about this screen was
that the controls read as "so cumbersome", and an undifferentiated bank of
seven controls is what that looks like.

### 3.2 The specificity trap, avoided deliberately

`design-system.css` declares `.rk-dash button { background: none; border: 0 }`
at specificity (0,1,1), which beats any button styled on a single class. Three
sets of controls have been reported invisible for exactly this reason.

The new rules are `.xctl .xbtn` — (0,2,0). This would also have failed in a way
that looked intermittent rather than broken: the inline visualizer sits inside
`.rk-dash` and the full-screen tree portals outside it, so a single-class rule
would have rendered correctly in one view and as bare grey text in the other.

### 3.3 One slot at the right of the row, two states

Added after the first pass, on the same report: there was no way back to the
dashboard from the control row. `FullScreenTree` does carry a `✕ Close` in its
own header, but that strip sits above the section cards and is the first thing
scrolled past once you start reading the tree.

The `.xfull` slot — right-aligned by `margin-left: auto` — now renders
`⛶ Full screen` on the way in and `⧉ Main tree view` on the way back. Full
screen is a place you go and a place you return from, and one slot holding both
directions is smaller than two controls that each do half.

The icon is antd's `ApartmentOutlined`, matching `HeaderBar`'s use of
`FilePdfOutlined`, rather than a tree emoji: these controls are monochrome and
inherit their colour, and 🌳 would have been the only coloured glyph on the
screen.

The button is **withheld inline**, where it would be a dead control — a button
reading "main tree view" while you are looking at the main tree goes nowhere.

---

## 4. Bugs found and fixed

None in the shipped code. Two of my own tests were wrong and were corrected
rather than the code:

* An assertion that a collapsed tree hides `https://e.com/docs/a/` — tree rows
  do not render full URLs. Rewritten against `flat.length`, which is how the
  neighbouring tree tests already assert.
* An `L1` assertion expecting fewer rows than the full tree. The fixture is two
  levels deep, so "open the first level" *is* the whole tree and `3 < 3` failed
  correctly. The test was removed rather than weakened: L1/L2 are pre-existing
  and a deeper fixture would be testing them, not this change.

---

## 5. Explicitly not done

- **Verified by eye, but not by this session.** No browser driver is installed
  here. The four depth buttons were confirmed rendering correctly in a
  screenshot the operator supplied between the two passes of this cycle — so
  the §3.2 specificity reasoning held, and the fourth "buttons are invisible"
  report did not happen. `⧉ Main tree view` (§3.3) landed after that screenshot
  and has **not** been seen; it reuses `.xfull`, which was already proven by the
  `⛶ Full screen` button it replaces in that slot.
- **No automated guard on the button reset.** A test parsing the stylesheets
  for under-scoped button rules was written and then removed: vitest stubs
  `.css` imports to `""`, `node:fs` needs Node types this tsconfig deliberately
  omits, and `import.meta.glob(..., { query: "?raw" })` returned nothing. Every
  route left the assertions passing vacuously against an empty string, which is
  worse than no test. The recurring bug still has no regression test.
- **`L1` and `L2` were not renamed or removed**, only relocated.

---

## 6. Files changed

```
rankuno-ui/src/components/tree/TreeControls.tsx       the four commands;
                                                     the way back (§3.3)
rankuno-ui/src/components/tree/tree-overlay.css       .xctl .xdepth / .xbtn
rankuno-ui/src/components/tree/TreeControls.test.tsx  +6 tests
rankuno-ui/src/components/layout/DashboardShell.tsx   removed the duplicate
```

---

## 7. Follow-ups

1. **A regression test for the button reset**, by whatever route makes the
   stylesheets readable in this test environment (§5). Three occurrences and no
   test is the standing risk on this codebase's UI.
