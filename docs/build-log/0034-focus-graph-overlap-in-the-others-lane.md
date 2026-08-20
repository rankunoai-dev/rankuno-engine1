# Cycle 0034: The focus graph drew a lane on top of itself

- **Date**: 2026-08-20
- **Scope**: Stop the focus graph stacking a node, its ancestors and its
  children on the same pixel. Reported from a screenshot of the OTHERS lane.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1369 passed` Python / `29 passed` UI / `Total coverage: 95.50%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.50%
1369 passed, 1 warning in 108.12s (0:01:48)
PASSED: Tests
 Test Files  5 passed (5)
      Tests  29 passed (29)
PASSED: UI Component Tests
ALL GATES PASSED.
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (10.54s).

---

## 2. What the screenshot showed

The OTHERS lane held ten child cards, the focused card `SERVICE_DETAIL_PAGE`
drawn *through* one of them, wires running flat across the full width of the
stage, and a pager floating below the lane over the node-count hint. It was
unreadable, and the cause was one line of layout.

Lane assignment is deliberate: **everything beneath OTHERS is given the OTHERS
lane**, because those pages are there precisely for having no navigation depth
(`dashboardModel`, cycle 0014 — spreading them across L0–L3 would read as though
they had positions they do not have).

The consequence was never handled. On that branch the ancestor chain and the
children occupy the *same lane*, and the two were positioned independently:

```ts
// chain
positions.set(index, { x: clampX(raw, width), y: centres[lane] ?? 0 });
// children
y: (centres[lane] ?? 0) + (row - (rowCount - 1) / 2) * rowSpacing
```

Both centre on `centres[lane]`. With one row of children, `(row - 0) * spacing`
is zero and every card — chain and children alike — landed on the identical y.
The wires then ran between points at the same height, which is what produced the
long flat curves across the whole stage rather than short vertical hops.

Anywhere else in the tree the chain sits in shallower lanes, so the collision
never appeared. OTHERS is the one place a node and its children share a lane,
and OTHERS is where the bulk of a real crawl ends up — 8,106 of highradius'
nodes in the screenshot.

---

## 3. What landed

**Rows are counted from the lane's top edge, and row 0 belongs to the chain.**
`rowCentre` replaces the centre-relative arithmetic. When any chain node shares
the expanded lane, one row is reserved and the children begin on the next.

**The pager is an ordinary grid slot.** It was positioned at `width - 110` with
a y derived from the row block, which put it on top of whatever card occupied
that corner and outside the lane once the rows grew. It now takes the slot after
the last child, so it cannot collide and reads as the end of the row.

**Wires are quieter** — 1px at 0.3 opacity, from 1.3px at 0.55. Ten edges leave
a single parent; each has to be faint enough that the fan reads as texture. The
selected path keeps its full weight, which is the one being followed.

---

## 4. Tested as arithmetic, because it cannot be tested as a component

jsdom has no layout engine. Every `getBoundingClientRect` is zero, and
`FocusGraphStage` populates no positions at all when `width` is 0 — a rendered
assertion would be an assertion about an empty stage.

`rowCentre` was therefore lifted out of the component as a pure function and
tested directly: six tests covering row separation, no two rows sharing a y, the
block staying centred in the lane, and the unmeasured first paint still
separating rows rather than collapsing them onto the centre.

This is the honest boundary of the cycle-0030 test runner and worth stating
plainly: it can pin the *maths* of a layout, and it cannot see the layout.

---

## 5. Explicitly not done

- **Nothing was viewed in a browser.** The arithmetic is tested and the build is
  clean; whether the lane now *looks* right is unverified. That needs the
  screenshot retaken.
- **The 180px card and its truncated label are unchanged.** `10-r2r-use-cases-proving-…`
  is still ellipsised to nothing useful. Widening the card means fewer columns;
  that is a design trade this cycle did not make.
- **80 pages of 10 is still 80 pages.** The pager no longer overlaps anything,
  but paging through 788 OTHERS children ten at a time is not a way to read
  them. The tree pane and search are; the graph is a neighbourhood view and
  arguably should say so rather than offer the pagination.
- **Edge routing is unchanged.** Wires are thinner, not smarter. Ten curves from
  one origin still cross each other; a proper fan-out would bundle them or
  route around cards.
- **The lane cap can still compress rows.** `spareForExpanded` bounds the
  expanded lane so it cannot push the others out, so at three rows in a short
  stage the spacing tightens to about 48px rather than 52. Rows stay separate —
  that is what the test pins — but they are closer than designed.

---

## 6. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/components/graph/FocusGraphStage.tsx` | `rowCentre`, reserved chain row, pager as a grid slot |
| `rankuno-ui/src/components/graph/FocusGraphStage.test.tsx` | New — 6 tests |
| `rankuno-ui/src/styles/design-system.css` | Wire weight and opacity |

## 7. Follow-ups

- Retake the OTHERS screenshot and confirm.
- Decide whether the graph should page through OTHERS at all, or send the
  operator to the tree pane once a section exceeds a few dozen children.
- Consider widening cards and dropping to three columns; the label is the thing
  an operator reads and it is currently the thing being sacrificed.
