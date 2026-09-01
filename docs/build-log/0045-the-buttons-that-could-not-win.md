# Cycle 0045: The buttons that could not win

- **Date**: 2026-08-21
- **Scope**: Make the audit card's controls visible, and reduce the jobs row from
  five wrapping buttons to one action plus a menu.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1526 passed` Python / `90 passed` UI / `Total coverage: 95.83%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 51 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.83%
1526 passed, 1 warning in 133.97s (0:02:13)
PASSED: Tests
 Test Files  10 passed (10)
      Tests  90 passed (90)
PASSED: UI Component Tests
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (26.96s).

---

## 2. The bug: a CSS specificity fight nobody could win

`Download CSV` and `See all 2,101` were reported invisible for the **third**
time. Two previous cycles had restyled them — the second attempt left a comment
in `audit.css` saying the control "could not be found, twice" — and neither
attempt changed anything on screen.

The cause is one rule in `design-system.css`:

```css
.rk-dash button {          /* specificity (0,1,1) */
  background: none;
  border: 0;
  color: inherit;
}
```

`.au-export` and `.au-toggle` are single class selectors — specificity **(0,1,0)**.
The reset outranks them, so every declaration in `audit.css` for those buttons
was discarded by the cascade. The buttons rendered as bare grey words with no
background, no border and no affordance beyond the cursor.

This is why restyling in the component's own stylesheet failed twice: the fix
was never going to take effect, and nothing in the failure said so. The rendered
output looked exactly as it would if the file had not been edited at all.

---

## 3. Design decisions

### 3.1 A shared button class, scoped to outrank the reset

`.rk-dash .rk-btn` — specificity (0,2,0), which beats (0,1,1). Three variants:
`.rk-btn` (default), `.rk-btn-primary` (one per group, the action the card
exists to produce), `.rk-btn-quiet`.

Defined in `design-system.css` beside the reset that broke them, so the next
reader meets the rule and its exception together. The alternative — bumping each
component's selector to `.au-card .au-export` — fixes one site and leaves the
trap armed for the next component to walk into.

### 3.2 Literal colours in that block, not the palette tokens

`:root` in `design-system.css` is a **light** palette; the audit cards and the
jobs table draw their own dark surfaces. `color: var(--ink)` on a `.au-card`
paints `#1d2635` on `#0f1420` — near-black on near-black, which is the same
invisibility being fixed. The rules use literal dark values, with a comment
saying why they cannot use the tokens twenty lines above them.

### 3.3 Five buttons become one plus a menu

The jobs row rendered `View tree`, `Search Console`, `Cross-check`, `Resume` and
`Retry` side by side, wrapping onto a second line inside a 210px column. A table
of crawls read as a wall of controls.

`View tree` is taken almost every time; the other four are optional or
occasional. It stays out; they move behind a single `⋯`. Column narrowed to
150px and `flex-wrap` set to `nowrap` — with at most three children there is
nothing left to wrap.

`Kill` stays visible and outside the menu. It is destructive, and destructive
actions should be deliberate rather than two clicks deep beside four routine
ones. It only appears while the job holds a slot, which is exactly when `View
tree` is disabled, so the row never shows more than three controls.

### 3.4 Menu items explain themselves instead of carrying tooltips

The old buttons each had a `Tooltip` holding the sentence that made the action
comprehensible — *"Optional. Upload a Screaming Frog export to see what each
crawler found and the other did not."* A tooltip inside an already-open menu is
a second hover on top of a first. Each item is now two lines: the action, and
the explanation underneath in muted text.

`Retry` was also renamed `Run again`. Retry implies the previous attempt failed;
the action is offered on successful crawls too.

---

## 4. Bugs found and fixed

**The specificity bug in §2.** Found by reading the cascade rather than the
component: the component's CSS was already correct.

**`PerformancePanel` was using `.au-export` too** and had the same invisible
button for the same reason. Caught by grepping for the class before deleting it,
which is the only reason it was not left behind as the one remaining user of a
rule that no longer exists.

**Two more casualties of the same reset, found by auditing it rather than by
report.** Every `<button>` in the app was checked against the rule:

* **`.gn` — the focus graph's node cards.** `background: #fff` and
  `border: 1.5px solid` are the two declarations that make them cards, and both
  are exactly what the reset clears. They were rendering without their surface
  or their outline.
* **`.rit` — the left nav rail items.** `color: var(--dim)` lost, so the rail
  inherited its colour instead of taking the muted tone it asks for.

`.crumbs .cb` was already written as a descendant selector and had been winning
all along — the existing precedent for the fix in §3.1, and evidence that this
trap has been stepped around before without being named.

**Fixing `.gn` nearly broke the lane colours, which is the trap one level
down.** `.g0`–`.go` carry each card's `border-color` at (0,1,0). They had been
losing to the reset; scoping `.gn` to `.rk-dash .gn` would have made them lose to
*that* instead, and every node card would have taken a `currentcolor` border
rather than its lane colour — a fix that swaps one silent visual defect for
another. The variants are lifted to matching specificity and declared after
`.gn`, so equal specificity resolves in their favour.

---

## 5. Corrections

**Build-log 0038 §4 describes a `collapseAll` semantic that is no longer true.**
That entry says "collapse all closes every section but keeps the roots
themselves open, so the tree never collapses to nothing", and documents a test
written to pin it. `collapseAll` now seeds an **empty** set and closes the roots
as well. The tree still cannot collapse to nothing — `flatten` always emits the
roots and only descends into open nodes — so the stated safety property holds
for a different reason than 0038 gives.

The change landed in a parallel session with its own justification: seeding the
roots meant "Collapse all" on highradius still showed About Us, Customers and
Partners open, so the button did not do the one thing it exists for. The
behaviour is better; 0038's description of it is stale from this cycle onward.
Left intact there and corrected here, per the build-log rules.

---

## 6. Explicitly not done

- **The rest of the app still uses antd `Button`.** Only the audit card and
  `PerformancePanel` use `.rk-btn`. The jobs table, header and tree controls are
  antd components, which carry their own styling and are unaffected by the
  reset. Two button systems now coexist; unifying them is a larger pass than
  this one and would touch every view.
- **`.vrow`, `.bgpill` and `.hit` were checked and left alone.** They are
  `<button>` elements under the reset, but none of them declares `background`,
  `border` or `color` at the top level, so the reset takes nothing from them.
  Left unscoped rather than changed defensively: a rule that does not need the
  specificity should not carry it, or the next reader cannot tell which ones
  do.
- **No test pins the specificity fix.** jsdom applies stylesheets but asserting
  a computed background here would test the CSS engine rather than the app. The
  guard is that `.au-export` and `.au-toggle` no longer exist in any stylesheet
  or component, so the losing rules cannot be silently resurrected.
- **The `⋯` menu is not keyboard-openable from the row.** antd's `Dropdown`
  handles focus on the trigger correctly, but the trigger is `click` only —
  keyboard users get no hover path. Consistent with the rest of the table, and
  not worse than the five buttons it replaces.
- **Column widths are otherwise untouched.** Only the actions column changed,
  from 210px to 150px.
- **No visual regression testing exists.** Three cycles have now shipped a
  styling change that did nothing, and nothing in the gate could detect it. That
  is the real gap this cycle exposes.

---

## 7. Files changed

```
rankuno-ui/src/styles/design-system.css              .rk-btn system beside the
                                                     reset that necessitated it
rankuno-ui/src/components/audit/audit.css            losing rules deleted, only
                                                     layout kept
rankuno-ui/src/components/audit/AuditView.tsx        uses .rk-btn
rankuno-ui/src/components/jobs/PerformancePanel.tsx  uses .rk-btn
rankuno-ui/src/components/jobs/CrawlJobsView.tsx     ActionCell: one action + ⋯
rankuno-ui/src/components/jobs/jobs.css              nowrap, menu item styles
```

---

## 8. Follow-ups

1. **A visual check in the gate** (§6). Even a screenshot diff of three views
   would have caught all three instances of this.
2. **One button system.** Either antd everywhere or `.rk-btn` everywhere.
3. **Delete the reset.** Now that every `<button>` under it has been audited,
   `.rk-dash button` earns nothing it could not get from a single `.rk-btn-bare`
   class, and it will keep silently disarming the next component's styling until
   it is gone.
