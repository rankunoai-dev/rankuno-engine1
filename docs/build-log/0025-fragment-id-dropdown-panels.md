# Cycle 0025: Fragment-ID mega-menu dropdown panel detection

- **Date**: 2026-08-19
- **Scope**: Fix header navigation parsing for mega-menus using `href="#fragment"` toggles and `<div>` panel boundaries (`kinsta.com`), restoring root tabs without affecting standard list menus.
- **Commit**: `e9972b1`
- **Quality gate**: `1,218 passed`, `Total coverage: 95.39%`

## 1. Gate results

```
=== Format ===
PASSED: Format

=== Lint ===
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.39%
1218 passed, 1 warning in 102.71s
ALL GATES PASSED.
```

UI, separately: `tsc --noEmit` clean.

---

## 2. What landed

### `nav_tree_parser.py` — Fragment-ID Panel Boundary Matching

- **Problem**: On sites like `kinsta.com`, top-level tabs (`Platform`, `Solutions`, `Resources`) link to fragment IDs (e.g. `<a href="#megamenu-item-0__child">Platform</a>`), which `_usable_href()` rejects (`url = None`). Inside the dropdown, column headers (e.g., `<h6>Product</h6>`) arrive at `depth 0` before the inner `<ul>` opens. This caused `_build_tree()` to collapse `Platform` as childless and prune it, while promoting 15 column headings to fake top-level tabs.
- **Fix**: Implemented Fragment-ID Panel Boundary Matching inside `_NavCollector`:
  1. When an anchor carries a pure fragment `href` (anchored `^#[^#]+$`), remember the target element ID.
  2. When an HTML container tag matching that ID opens inside header navigation, increment `_dropdown_depth += 1`.
  3. Panel closing tracks element-stack depth to ensure nested `<div>`s close correctly.
  4. Stack popping handles unclosed `<li>` tags cleanly.

### Benchmark Delta Measurement Across 6 Archetypes

| Site | Roots (Before -> After) | Nodes (Before -> After) | Status |
| :--- | :--- | :--- | :--- |
| **`kinsta.com`** | `15 -> 6` | `55 -> 58` | **CHANGED** (Restored `Platform`, `Solutions`, `Resources`) |
| **`linear.app`** | `1 -> 1` | `8 -> 8` | Unchanged |
| **`rankuno.com`** | `4 -> 4` | `31 -> 31` | Unchanged |
| **`gep.com`** | `5 -> 5` | `165 -> 165` | Unchanged |
| **`highradius.com`** | `11 -> 11` | `79 -> 79` | Unchanged |
| **`postman.com`** | `49 -> 49` | `49 -> 49` | Unchanged |

Zero regressions across all 5 non-target sites.
