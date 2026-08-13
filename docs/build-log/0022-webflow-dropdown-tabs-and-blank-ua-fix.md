# Cycle 0022: Breadcrumb Hierarchy Extraction, Webflow Dropdown Tabs, and UI Badging Fixes

- **Date**: 2026-08-13
- **Scope**: Dual JSON-LD + DOM breadcrumb hierarchy extraction (`breadcrumb_parser.py`); exclude breadcrumbs from header nav parsing; Webflow nested `div`/`button` dropdown toggles; UI `profile.hierarchy_level` badging & inspector split; blank-UA fix.
- **Commit**: (Pending commit for cycle 0022)
- **Quality gate**: `1150 passed, 0 warnings in 42.15s` / `Total coverage: 95.54%`

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
Required test coverage of 85.0% reached. Total coverage: 95.54%
1150 passed in 42.15s
PASSED: Tests

=== Drift Check ===
PASSED: no drift detected across 66 markdown files.
ALL GATES PASSED.
```

---

## 2. What Landed

### 1. Dual Breadcrumb Hierarchy Extractor (`breadcrumb_parser.py`)
To handle Schema.org structure variance across different site archetypes, two complement extractors were implemented:
- **JSON-LD Extractor**: Parses `<script type="application/ld+json">` for `@type: "BreadcrumbList"` or `itemListElement`. Handles Yoast `@graph` arrays (item as string), AEM nested objects (`item.@id`), and escaped URLs (`https:\/\/`).
- **DOM `aria-label` Extractor**: Parses `<nav aria-label="breadcrumb">` / `<ol>` / `<ul>` for Shopify (`allbirds`), React (`caelius`), and custom DOMs. Sorts items by declared `position` or document order.

### 2. Header Navigation Pollution Excluded (`nav_tree_parser.py`)
- **Fix**: Excluded elements matching `aria-label="breadcrumb"` or `.breadcrumb` from `_NavLinkExtractor` in `nav_tree_parser.py`. This stops breadcrumbs (e.g. Allbirds `Home / Mens / Shoes`) from polluting top-level header tabs.

### 3. Decoupled UI Row Badges & Inspector Split (`VirtualizedTree.tsx`, `DashboardShell.tsx`)
- **Fix**: Row badges in the visualizer tree now display `profile.hierarchy_level` (e.g., `L3`, `L2`, `L1`) rather than tree path depth (`LANE_LABELS[node.lv]`).
- **Inspector**: Separated inspector readout into two explicit rows: **Position** (path depth location) and **Classified** (`hierarchy_level` taxonomy).
- **Grouping-Aware Labels & Warning Banner**: In path mode, lane labels read `Path depth 0 · one URL segment`. Fixed warning banner logic to distinguish between `0 menu entries` and `pages_fetched === 0` (WAF 403 blocks).

### 4. Webflow `div` / `button` Dropdown Header Toggle Extraction
- **Fix**: Added `div`, `button`, and `summary` to `_HEADING_TAGS` in list items (`_list_depth > 0`). Bottom-up leaf pruning (`_prune_unlinked_leaves`) removes unlinked CTA buttons and mobile navigation duplicates.

---

## 3. Bugs Found and Fixed

| Defect | Impact | Fix |
| :--- | :--- | :--- |
| **Breadcrumbs Polluting Header Tabs** | `Home / Mens / Shoes` surfaced as header tabs on Allbirds. | Excluded `aria-label="breadcrumb"` containers from `_NavLinkExtractor`. |
| **Flat URLs Badged as L0 in UI** | Single-segment URLs (`/contact-sales`) badged `L0` despite being classified `L3_LEAF_PAGE`. | Badges now display `profile.hierarchy_level` (`L3`), not tree depth `lv`. |
| **Collapsed Webflow Dropdown Tabs** | `Transparency` misattributed to `Policy`; `Commitments` missing. | Admitted unlinked `div`/`button` inside `<li>` and tracked nested `<nav>` depth. |
| **Zero Pages Fetched Banner False Negative** | 403 blocked crawls showed "menu not parsed". | Banner now detects `pages_fetched === 0` (WAF 403 block). |

---

## 4. Explicitly Not Done

- **Per-Page Breadcrumb Source Metrics**: Storing `breadcrumb_source` (jsonld/dom/none) per page requires an API response model contract change; deferred as a follow-up.
- **Corpus Accuracy Benchmark**: Golden corpus currently holds 13 labels across 1 archetype; 99% accuracy assertions remain unverified until corpus expansion.

---

## 5. Files Changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/breadcrumb_parser.py` | New dual JSON-LD + DOM breadcrumb extractor. |
| `src/modules/seo/page_classifier/signal_parsers.py` | Integrated `parse_breadcrumb_signal()` into structural consensus. |
| `src/modules/seo/page_classifier/nav_tree_parser.py` | Added breadcrumb exclusion to header nav collector; Webflow dropdown fix. |
| `rankuno-ui/src/components/tree/VirtualizedTree.tsx` | Row badges display `profile.hierarchy_level`. |
| `rankuno-ui/src/components/inspector/*` | Inspector splits Position vs Classified Level. |
| `docs/build-log/0022-webflow-dropdown-tabs-and-blank-ua-fix.md` | Documented cycle 0022 build log. |

