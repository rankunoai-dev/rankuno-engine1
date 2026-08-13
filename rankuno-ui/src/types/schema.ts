// GENERATED FILE - DO NOT EDIT.
//
// Produced by scripts/export_ui_contract.py from the Pydantic models in
// src/modules/seo/page_classifier/. Edit those and re-run the exporter.
//
// tests/test_ui_contract.py fails if this file is stale, so a model change
// that is not re-exported breaks the Python quality gate.

// ---------------------------------------------------------------- enums

export type HierarchyLevel =
  | "L0_HOMEPAGE"
  | "L1_PRIMARY_NAV_HUB"
  | "L2_SUB_NAV_HUB"
  | "L3_LEAF_PAGE"
  | "UTILITY_PAGE";

export const HIERARCHY_LEVEL_VALUES: readonly HierarchyLevel[] = ["L0_HOMEPAGE", "L1_PRIMARY_NAV_HUB", "L2_SUB_NAV_HUB", "L3_LEAF_PAGE", "UTILITY_PAGE"] as const;

export type PrimaryPageType =
  | "HOMEPAGE"
  | "SERVICE_CATEGORY_HUB"
  | "SERVICE_DETAIL_PAGE"
  | "PRODUCT_CATEGORY_HUB"
  | "PRODUCT_DETAIL_PAGE"
  | "BLOG_HUB"
  | "BLOG_ARTICLE"
  | "COMPANY_ABOUT"
  | "COMMERCIAL_LEAD_GEN"
  | "FACETED_FILTER"
  | "UTILITY_LEGAL"
  | "CASE_STUDY"
  | "TOOL_APPLICATION"
  | "UNKNOWN";

export const PRIMARY_PAGE_TYPE_VALUES: readonly PrimaryPageType[] = ["HOMEPAGE", "SERVICE_CATEGORY_HUB", "SERVICE_DETAIL_PAGE", "PRODUCT_CATEGORY_HUB", "PRODUCT_DETAIL_PAGE", "BLOG_HUB", "BLOG_ARTICLE", "COMPANY_ABOUT", "COMMERCIAL_LEAD_GEN", "FACETED_FILTER", "UTILITY_LEGAL", "CASE_STUDY", "TOOL_APPLICATION", "UNKNOWN"] as const;

export type SearchIntent =
  | "INFORMATIONAL"
  | "COMMERCIAL_INVESTIGATION"
  | "TRANSACTIONAL"
  | "NAVIGATIONAL";

export const SEARCH_INTENT_VALUES: readonly SearchIntent[] = ["INFORMATIONAL", "COMMERCIAL_INVESTIGATION", "TRANSACTIONAL", "NAVIGATIONAL"] as const;

export type ConversionRole =
  | "DIRECT_SALE"
  | "LEAD_GENERATION"
  | "BRAND_AWARENESS"
  | "INFORMATIONAL_SUPPORT"
  | "NONE";

export const CONVERSION_ROLE_VALUES: readonly ConversionRole[] = ["DIRECT_SALE", "LEAD_GENERATION", "BRAND_AWARENESS", "INFORMATIONAL_SUPPORT", "NONE"] as const;

export type SignalSource =
  | "ARIA_NAV_TREE"
  | "CMS_API_ENDPOINT"
  | "SITEMAP_INDEX"
  | "SCHEMA_JSONLD"
  | "LINK_IN_DEGREE"
  | "LLM_ZERO_SHOT";

export const SIGNAL_SOURCE_VALUES: readonly SignalSource[] = ["ARIA_NAV_TREE", "CMS_API_ENDPOINT", "SITEMAP_INDEX", "SCHEMA_JSONLD", "LINK_IN_DEGREE", "LLM_ZERO_SHOT"] as const;

export type ConsensusMethod =
  | "LAYER0_FAST_PATH"
  | "LAYER1_STRUCTURAL"
  | "LAYER2_LOCAL_ML"
  | "LAYER3_LLM_FALLBACK"
  | "WEIGHTED_CONSENSUS";

export const CONSENSUS_METHOD_VALUES: readonly ConsensusMethod[] = ["LAYER0_FAST_PATH", "LAYER1_STRUCTURAL", "LAYER2_LOCAL_ML", "LAYER3_LLM_FALLBACK", "WEIGHTED_CONSENSUS"] as const;

export type CmsFamily =
  | "WORDPRESS"
  | "SHOPIFY"
  | "HEADLESS"
  | "UNKNOWN";

export const CMS_FAMILY_VALUES: readonly CmsFamily[] = ["WORDPRESS", "SHOPIFY", "HEADLESS", "UNKNOWN"] as const;

// ----------------------------------------------------------- data contracts

/** One signal's independent opinion about a page. */
export interface SignalScore {
  source: SignalSource;
  suggested_level: HierarchyLevel;
  suggested_page_type: PrimaryPageType;
  confidence: number;
  notes: string;
}

/** The complete classification of a single URL. */
export interface FullPageIntelligenceProfile {
  url: string;
  canonical_url: string;
  normalized_path: string;
  hierarchy_level: HierarchyLevel;
  primary_page_type: PrimaryPageType;
  depth_from_l0: number;
  nav_parent_url: string | null;
  breadcrumb_path: string[];
  topical_category: string;
  sub_topic: string | null;
  search_intent: SearchIntent;
  conversion_role: ConversionRole;
  is_cross_silo_link: boolean;
  inbound_internal_links_count: number;
  outbound_internal_links_count: number;
  signals_evaluated: SignalScore[];
  final_confidence_score: number;
  consensus_method: ConsensusMethod;
}

/** A content record retrieved from a CMS API. */
export interface CmsRecord {
  record_type: string;
  parent_id: number | null;
  parent_url: string | null;
  has_children: boolean;
}

/** Which paths surfaced a URL. */
export interface DiscoverySource {
  sitemap: boolean;
  dom_link: boolean;
  cms_api: boolean;
}

/** One URL in the site graph, with everything discovery learned about it. */
export interface DiscoveredNode {
  url: string;
  normalized: string;
  sources: DiscoverySource;
  sitemap_source: string | null;
  cms_record: CmsRecord | null;
  inbound_links: number;
  outbound_links: number;
  depth: number | null;
}

/** Summary of one discovery pass. */
export interface DiscoveryReport {
  base_url: string;
  total_urls: number;
  from_sitemap: number;
  from_dom: number;
  from_cms: number;
  sitemap_only: number;
  dom_only: number;
  orphans: number;
  sitemaps_fetched: number;
  pages_fetched: number;
  fetch_failures: number;
  media_skipped: number;
  traps_skipped: number;
  truncated: boolean;
  stopped_reason: string | null;
  dom_reserve: number;
  dom_reserve_used: number;
}

/** What one probe pass discovered about a site. */
export interface SiteProfile {
  cms_family: CmsFamily;
  renders_client_side: boolean;
  has_catalogue: boolean;
  locale_prefixes: string[];
}

/** Which weight vector a crawl actually used, and why. */
export interface WeightProfileReport {
  profile_name: string;
  adaptive_enabled: boolean;
  detected_profile_name: string;
}

/** Where a navigation tree came from, and how much it found. */
export interface NavSource {
  strategy: string;
  containers: number;
  link_count: number;
}

/** One entry in the header menu. */
export interface NavNode {
  label: string;
  url: string | null;
  depth: number;
  children: NavNode[];
}

/** A parsed header menu. */
export interface NavigationTree {
  roots: NavNode[];
  source: NavSource;
}

/** How much of the site the navigation menu actually accounts for. */
export interface NavCoverageReport {
  total_urls: number;
  exact_matches: number;
  inherited_matches: number;
  unmatched: number;
  nav_entries: number;
  groups: string[];
}

/** Live progress for a running job. */
export interface JobTelemetry {
  completed: number;
  discovered: number;
  rate_per_sec: number;
  eta_seconds: number | null;
  recent_items: string[];
  updated_at: string | null;
}

/** Aggregate outcome of one crawl. */
export interface CrawlSummary {
  pages_classified: number;
  escalated_to_llm: number;
  escalation_rate: number;
  unknown_pages: number;
  low_confidence_pages: number;
  orphan_pages: number;
  llm_spend_usd: number;
}

/** What to crawl, and the limits that apply to it. */
export interface PageClassificationInput {
  base_url: string;
  max_pages: number | null;
  max_depth: number | null;
  crawl_dom: boolean;
  respect_robots: boolean;
  llm_spend_cap_usd: number;
  rate_limit_rps: number | null;
  user_agent: string;
  browser_headers: boolean;
  seed_urls: string[];
  concurrency: number;
  use_async_crawl: boolean;
  dom_reserve_fraction: number;
}

/** Everything one crawl job produced. */
export interface PageClassificationOutput {
  base_url: string;
  site_profile: SiteProfile;
  weight_profile: WeightProfileReport;
  discovery: DiscoveryReport;
  summary: CrawlSummary;
  pages: FullPageIntelligenceProfile[];
  navigation: NavigationTree;
  nav_coverage: NavCoverageReport;
}
