# Cycle 0038: Expand one branch, not the whole tree

- **Date**: 2026-08-20
- **Scope**: Whole-branch expand and collapse on any tree row, and honest labels
  on the whole-tree buttons.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1398 passed` Python / `76 passed` UI / `Total coverage: 95.50%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.50%
1398 passed, 1 warning in 120.78s (0:02:00)
PASSED: Tests
 Test Files  9 passed (9)
      Tests  76 passed (76)
PASSED: UI Component Tests
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (18.21s).

---

## 2. What was missing

Whole-tree expand and collapse already existed — the buttons were labelled `All`
and `Collapse`, sitting beside `L1` and `L2`, which made them read as two more
depth *filters* rather than as the commands they are. Renamed to `Expand all`
and `Collapse all`, each with a title saying what it will do and, for expand-all,
how many nodes that is.

What did not exist was the operation actually wanted on a real crawl. On the
reported gep.com tree, `BLOGS` holds **2,937** descendants and `KNOWLEDGE BANK`
holds **1,106**. Opening one of them meant clicking a twisty per level, and the
only alternative was `Expand all`, which opens all 8,511 nodes and buries the one
section under everything else.

---

## 3. Design decisions

### 3.1 Branch expansion merges into the open set; whole-tree expansion replaces it

`expandAll` builds a fresh `open` set — correct for a whole-tree command.
`expandBranch` deliberately does not:

```ts
const open = new Set(get().open);
for (const node of subtree(model, index)) open.add(node);
```

Opening one section in full must not close the others an analyst already has
open. That is the entire behavioural difference between the two, and it is what
the third test pins.

### 3.2 Two ways in, because they serve different moments

* A **`⇊` / `⇈` control on the row**, revealed on hover. Discoverable — the
  affordance appears where the decision is being made, with a title naming the
  section and its page count.
* **Shift-click on the twisty**, for someone doing this thirty times in a row.

Both call the same two store actions. The row control is held at `opacity: 0`
rather than `display: none` so it keeps its box: revealing it on hover must not
shift the count sitting beside it.

### 3.3 A `span`, not a `button`

The row is itself a `<button>`, and nesting a button inside a button is invalid
HTML — which is why the existing twisty is a span with `stopPropagation`. The new
control follows that established pattern rather than introducing a second,
contradictory one. Stated plainly because it is a real accessibility limitation
of this component, not a preference: the branch control is not keyboard
reachable, and neither is the twisty it sits opposite.

---

## 4. Bugs found and fixed

**No product bug this cycle. One test was wrong and the code was right** — worth
recording because the mistake was a misreading of a deliberate behaviour.

The first version of the shift-click test collapsed the tree, shift-clicked the
first row, and asserted the row count grew. It failed: `expected 1 to be greater
than 2`. The click had *collapsed*, not expanded.

The cause is a design decision in `collapseAll` that predates this cycle:

```ts
collapseAll(model) {
  const open = new Set(model.roots);   // roots stay open
```

"Collapse all" closes every section but keeps the roots themselves open, so the
tree never collapses to nothing. A root is therefore *open* immediately after
collapse-all, and its branch control correctly reads as collapse. The code was
right; the test assumed the tree collapsed further than it does.

Fixed by closing the target explicitly first, and a second test was added to pin
the `collapseAll` semantic that caused the confusion, so the next reader meets it
as an assertion rather than as a surprise.

---

## 5. Corrections

Nothing published in an earlier entry is corrected here.

---

## 6. Explicitly not done

- **The control is not keyboard reachable.** See §3.3. Fixing it properly means
  making the row a `div` with roving tabindex rather than a `button`, which
  touches selection, focus and the virtual window together — a cycle of its own,
  not a change to attach to this one. The existing twisty has the same gap.
- **`⇈` does not mean "this branch is fully open".** The control toggles on
  whether the node itself is open, not on whether every descendant is. A node
  that is open with closed children still shows `⇈`, and pressing it collapses
  the branch rather than completing the expansion. Inferring true "fully
  expanded" state costs a subtree walk per rendered row per scroll frame — up to
  8,511 nodes × 25 rows — and the windowing exists precisely to avoid work of
  that shape.
- **No expand/collapse memory across crawls.** Selecting another crawl calls
  `setModel`, which resets to roots-open. Unchanged.
- **The tab strip is untouched.** `L1` / `L2` still set an absolute depth and
  replace the open set; only their two neighbours were renamed.
- **No guard on expanding a very large branch.** `Expand all` on a 29,248-node
  crawl builds a 29,248-row view-model. It always has; the row control makes
  reaching that state easier but does not change its cost.

---

## 7. Files changed

```
rankuno-ui/src/store/useDashboardStore.ts            subtree(), expandBranch,
                                                     collapseBranch
rankuno-ui/src/components/tree/VirtualizedTree.tsx   row control + shift-click
rankuno-ui/src/components/layout/DashboardShell.tsx  Expand all / Collapse all
rankuno-ui/src/styles/design-system.css              .tbranch
rankuno-ui/src/components/tree/VirtualizedTree.test.tsx  +7 tests
```

---

## 8. Follow-ups

1. **Keyboard navigation for the tree** (§6). The largest accessibility gap in
   the app.
2. **A cheap "fully expanded" signal**, if the `⇈` ambiguity in §6 proves to
   matter in use — a per-node open-descendant count maintained in the store
   would give it in O(1) per row.
