# Cycle 0160: Leaf rows showed Search Console clicks next to the title

- **Date**: 2026-10-19
- **Scope**: UI bug fix, CSS only, plus one structural test. In the directory tree, section rows pushed the GSC clicks figure to the far right, while leaf rows showed it inline after the title. Leaves now use the same right-hand column as sections.
- **Numbering**: the entry was first written as 0157, but 0157 was taken by a committed entry from another session (the support-bot guide). Renumbered to 0160, because 0159 was taken by a committed entry from another session.
- **Commit**: none. Nothing is committed; the working tree is dirty.
- **Quality gate**: UI gate green on the implementer's run (§1). Not verified in a browser (§5).

## 1. Gate results

Figures below were reported by the ui-engineer. The scribe did not re-run them. The only command the scribe ran is `drift_check.py`, and only if README or ARCHITECTURE links changed (§6).

| Command | Result (reported) |
| :--- | :--- |
| `npx vitest run src/components/tree/VirtualizedTree.test.tsx` | 24 / 24 passed |
| `npm run test` | 58 files / 787 tests passed |
| `npm run typecheck` | clean |
| `npm run build` | built in 46.46s (pre-existing chunk-size warning only) |
| `npm run contract` | not run (no API surface changed) |

The Python gate was not run. No Python file changed.

## 2. What landed

Both files are under `rankuno-ui/src/components/tree/`.

Modified:

- `tree-overlay.css`: added a rule after `.tgsc`:

  ```css
  .vrow:not(:has(> .tbranch)) > .tgsc {
    margin-left: auto;
  }
  ```

  with a comment explaining why. `.tbranch` in `styles/design-system.css` (lines 1421-1422) has `margin-left: auto`, so a section row's branch control takes the free space and pushes the meta group right. `.tgsc` had only `margin-left: 8px`, so a leaf row had free space after its title and the clicks sat inline there. The `:has` guard keeps two auto margins from splitting the free space on a section row.

- `VirtualizedTree.test.tsx`: one test in a new `describe("Search Console clicks column")` block. It renders a leaf and a section with `gsc_clicks` set and asserts that `.tgsc` is the last child of both rows, that the section's `.tbranch` comes before `.tgsc` in the DOM, and that the leaf reads `31 clicks`. The test imports `TreeList` and `buildTreeOverlay` for this.

## 3. Bugs found and fixed

- **Leaf clicks not in the right-hand column.** Cause: the auto margin existed only on `.tbranch`, which renders only when a row has children (`VirtualizedTree.tsx:277`). Leaves have no `.tbranch`, so nothing absorbed the free space. Fix: the rule in §2.
- **The new test cannot catch the original bug.** jsdom does not apply stylesheets, so the test passes on the old CSS too. It pins DOM ordering only, which is the structure the CSS depends on. It is a guard against a markup change, not a regression test for the layout. Anyone who reads it as a layout test is misreading it.

## 4. Corrections

None to earlier entries.

The earlier session wrongly described GSC enrichment as reaching the tree views only through the overlay. That description is not repeated here and this cycle does not change it.

## 5. Explicitly not done

- **Not verified in a browser.** Still unchecked: normal and narrow widths; inline and full-screen views; that the badges follow the label; that hovering a section row does not shift its count. Any of these may differ from what the CSS reasoning predicts.
- **Behavior change for the user to judge.** Leaf clicks now sit flush right like section rows. They are 6px (the flex gap) from the preceding item, down from 14px (the 8px margin plus the 6px gap). This is the intended alignment, but it is a visible change and the user has not yet reviewed it.
- **Browser support of `:has()`.** The rule needs Chromium 105+, Safari 15.4+, or Firefox 121+. Where `:has()` is unsupported the rule is dropped, and leaves would be expected to fall back to the old inline layout. That fallback was not tested.
- **No fail-before test.** The test does not fail on the old CSS (§3). A real regression test would need a browser or a layout-aware test runner, which the repo does not have.
- **Not committed.**

## 6. Drift check

No README or ARCHITECTURE file changed, and no new module, route, or UI surface was added, so `scripts/drift_check.py` was not run for this entry.

## 7. Notes for the next cycle

- If a browser check shows the leaf gap is too tight or too loose, the flex `gap` on the row is the lever, not the auto margin.
