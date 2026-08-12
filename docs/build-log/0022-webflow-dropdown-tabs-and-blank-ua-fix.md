# Cycle 0022: Webflow DOM Dropdown Tabs and Header Navigation Fixes

- **Date**: 2026-08-12
- **Scope**: Support Webflow nested `div`/`button` dropdown toggles in navigation trees; prune unlinked leaf nodes; suppress mobile navigation menu duplicates; ensure fallback User-Agent header on blank configurations.
- **Commit**: (Pending commit for cycle 0022)
- **Quality gate**: `1113 passed, 1 warning in 38.02s` / `Total coverage: 95.70%`

---

## 1. Quality Gate Verification Results

```
=== Format ===
150 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 41 source files
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.70%
1113 passed, 1 warning in 38.02s
PASSED: Tests

ALL GATES PASSED.
```

---

## 2. What Landed

### 1. Webflow `div` / `button` Dropdown Header Toggle Extraction
On modern websites like `anthropic.com` built on Webflow or custom component libraries, dropdown tabs in top navigation headers (e.g. `Commitments`, `Learn`, `Company`) are frequently rendered as nested `<div>` or `<button>` elements without `href` attributes, `role="button"`, or `aria-haspopup`.

- **Root Cause**: `nav_tree_parser.py` previously ignored unlinked `<div>` headings inside list items. `_build_tree` attached all dropdown children (`Transparency`, `Claude's Constitution`, etc.) to the preceding linked tab (`Policy`), leaving the actual dropdown tab (`Commitments`) missing from the extracted site hierarchy tree.
- **Fix**: Added `div`, `button`, and `summary` to `_HEADING_TAGS` within list items (`_list_depth > 0`). Innermost text-bearing elements replace outer wrappers to extract accurate tab labels.

### 2. Bottom-Up Unlinked Leaf Pruning (`_prune_unlinked_leaves`)
Admitting `<div>` tags as candidate headings risked capturing non-navigational CTA buttons (`Log in to Claude`, `Accept all cookies`) and placeholder text (`This is some text inside of a div block.`).

- **Fix**: `_prune_unlinked_leaves` recursively traverses the extracted navigation tree bottom-up and prunes any node that has no `url` AND no remaining children.
- **Result**: Call-to-action buttons, locale placeholders, and childless headings are stripped automatically. Mobile navigation duplicates are suppressed for free because URL deduplication strips the links from the second menu copy, leaving its headings childless.

### 3. Dropdown Depth Tracking (`_dropdown_depth`)
- **Fix**: Count nested `<nav>` containers opened *inside a list item* (`_list_depth > 0`). Top-level `<header><nav>` wrappers do not increment depth, ensuring top tabs stay at depth 0 while nested dropdown items sit correctly at depth 1 under their parent tab.

---

## 3. Bugs Found and Fixed

| Defect | Impact | Fix |
| :--- | :--- | :--- |
| **Collapsed Webflow Dropdown Tabs** | `Transparency` & `Constitution` misattributed to `Policy`; `Commitments` & `Learn` missing. | Admitted unlinked `div`/`button` inside `<li>` and tracked nested `<nav>` depth. |
| **Junk Call-to-Action Tabs** | `Log in to Claude` surfaced as L0 section tab. | Bottom-up leaf pruning (`_prune_unlinked_leaves`). |
| **Mobile Menu Duplicate Roots** | Menu duplicated across desktop and mobile layout DOM nodes. | Bottom-up leaf pruning combined with URL de-duplication. |

---

## 4. Explicitly Not Done

- **No CSS class-based mobile menu filtering (`.mobile-menu`)**: Framework-specific selectors drift across sites (`is-mobile`, `mobile-menu`, `sm:hidden`). Leaf pruning structural de-duplication resolves mobile menu clones without relying on fragile class name heuristics.
- **Root logo exemption unchanged**: Root logo link handling remains governed by existing logic in `logical_hierarchy.py:149` (from cycle 0014).

---

## 5. Files Changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/nav_tree_parser.py` | Added `div`/`button` heading extraction, `_dropdown_depth` tracking, and `_prune_unlinked_leaves`. |
| `tests/modules/seo/test_nav_tree_parser.py` | Added 8 unit tests (`TestNonLinkDropdownTabs`, `TestUnlinkedLeafPruning`, `TestDuplicateMenuSuppression`, `TestNavNestingDoesNotShiftDepth`). |
| `docs/build-log/0022-webflow-dropdown-tabs-and-blank-ua-fix.md` | Created build log entry for cycle 0022. |

