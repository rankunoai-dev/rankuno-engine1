// GENERATED FILE - DO NOT EDIT.
//
// Produced by scripts/export_ui_contract.py from the Pydantic models in
// src/modules/seo/page_classifier/. Edit those and re-run the exporter.
//
// tests/test_ui_contract.py fails if this file is stale, so a model change
// that is not re-exported breaks the Python quality gate.

import type { PrimaryPageType } from "../types/schema";

/** Badge colour per page type, from TREE_VISUALIZER_SPECIFICATION.md. */
export const PAGE_TYPE_COLORS: Record<PrimaryPageType, string> = {
  BLOG_ARTICLE: "#60a5fa",
  BLOG_HUB: "#3b82f6",
  CASE_STUDY: "#f59e0b",
  COMMERCIAL_LEAD_GEN: "#10b981",
  COMPANY_ABOUT: "#38bdf8",
  FACETED_FILTER: "#94a3b8",
  HOMEPAGE: "#00f2fe",
  PRODUCT_CATEGORY_HUB: "#4facfe",
  PRODUCT_DETAIL_PAGE: "#00c6ff",
  SERVICE_CATEGORY_HUB: "#a855f7",
  SERVICE_DETAIL_PAGE: "#c084fc",
  TOOL_APPLICATION: "#ec4899",
  UNKNOWN: "#ef4444",
  UTILITY_LEGAL: "#64748b",
};

/** Swimlane accent per hierarchy level. */
export const LEVEL_COLORS = {
  L0_HOMEPAGE: "#f5c518",
  L1_PRIMARY_NAV_HUB: "#7f00ff",
  L2_SUB_NAV_HUB: "#00f2fe",
  L3_LEAF_PAGE: "#10b981",
  UTILITY_PAGE: "#64748b",
} as const;

/** Short badge label per hierarchy level. */
export const LEVEL_LABELS = {
  L0_HOMEPAGE: "L0",
  L1_PRIMARY_NAV_HUB: "L1",
  L2_SUB_NAV_HUB: "L2",
  L3_LEAF_PAGE: "L3",
  UTILITY_PAGE: "UTIL",
} as const;
