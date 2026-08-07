# 🌳 Interactive Multi-Level Site Hierarchy Tree Report Specification

> **Document ID**: `RKN-TREE-VIS-2026-V1.0`  
> **Status**: Binding Reporting Interface Specification  
> **Module Location**: `src/modules/seo/page_classifier/tree_visualizer.py`  

---

## 1. Executive Summary

Displaying URLs in a flat list or CSV table destroys the value of website architecture auditing. To make every single URL of a domain navigable, Rankuno generates an **Interactive Multi-Level Hierarchical Site Tree Report** (`.html`).

---

## 2. Decoupled Tree Visualization Architecture

### 1. Multi-Level Structural Tree Rendering ($L0 \rightarrow L1 \rightarrow L2 \rightarrow L3$)
Every URL in the domain graph $G=(V,E)$ is organized into a nested, collapsible tree structure matching its true parent-child ancestry:

```text
L0_HOMEPAGE (Apex Node: https://www.highradius.com/)
└── L1_PRIMARY_NAV_HUB (/software/order-to-cash/)
    └── L2_SUB_NAV_HUB (/software/order-to-cash/credit-cloud/)
        ├── L3_LEAF_PAGE (.../credit-application-processing/)
        └── L3_LEAF_PAGE (.../credit-scoring-automation/)
└── L1_PRIMARY_NAV_HUB (/resources/)
    └── L2_SUB_NAV_HUB (/resources/blog/)
        ├── L3_LEAF_PAGE (.../agentic-ai-invoice-processing/)
        └── L3_LEAF_PAGE (.../cash-flow-forecasting/)
```

### 2. Dual Classification Overlay on Every Node
Every node in the visual tree displays two distinct classification badges:
- **Structural Level Badge**: `L0`, `L1`, `L2`, `L3`, `UTILITY` (identifies position in graph hierarchy).
- **Color-Coded `PrimaryPageType` Badge**:
  - `HOMEPAGE` (Cyan `#00f2fe`)
  - `PRODUCT_CATEGORY_HUB` (Royal Blue `#4facfe`)
  - `PRODUCT_DETAIL_PAGE` (Light Blue `#00c6ff`)
  - `SERVICE_CATEGORY_HUB` (Purple `#a855f7`)
  - `BLOG_HUB` & `BLOG_ARTICLE` (Blue `#3b82f6` / `#60a5fa`)
  - `COMMERCIAL_LEAD_GEN` (Emerald Green `#10b981`)
  - `CASE_STUDY` (Amber `#f59e0b`)
  - `UTILITY_LEGAL` (Slate Gray `#64748b`)

### 3. Interactive Filtering & Real-Time JavaScript Controls
- **Expand / Collapse All Levels**: Instantly expand or collapse 10+ levels deep.
- **Instant Search Filter**: Live keyword filtering across URLs and `PrimaryPageType` badges.
- **Node Count Rollups**: Parent hubs display total child URL counts (e.g. `/resources/` rollup shows 2,220 URLs).
- **Standalone HTML Output**: `tree_visualizer.py` converts the SQLite graph into a self-contained `.html` file openable in any browser.

---

*Maintained by the AI Lead & Systems Engineering Team at Rankuno.*
