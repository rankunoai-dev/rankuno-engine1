/**
 * Contract-valid fixtures for component tests.
 *
 * Built from the generated types rather than cast from `{}` or `as any`. A cast
 * would let a test keep passing after the engine dropped a field the component
 * reads, which is the class of bug this suite exists to catch — the printable
 * report blanked the whole dashboard in cycle 0021 for exactly that reason, and
 * a stubbed fixture would have hidden it.
 */

import type {
  DiscoveryReport,
  FullPageIntelligenceProfile,
  PageClassificationOutput,
} from "../types/schema";

/** A classified page. Overrides are shallow-merged. */
export function page(
  url: string,
  overrides: Partial<FullPageIntelligenceProfile> = {},
): FullPageIntelligenceProfile {
  return {
    url,
    canonical_url: url,
    final_url: url,
    redirect_chain: [],
    normalized_path: url,
    hierarchy_level: "L3_LEAF_PAGE",
    primary_page_type: "BLOG_ARTICLE",
    depth_from_l0: 1,
    nav_parent_url: null,
    breadcrumb_path: [],
    own_breadcrumb: [],
    trail_source: "none",
    topical_category: "",
    sub_topic: null,
    search_intent: "INFORMATIONAL",
    conversion_role: "NONE",
    is_cross_silo_link: false,
    inbound_internal_links_count: 0,
    outbound_internal_links_count: 0,
    discovery_sources: { sitemap: false, dom_link: true, cms_api: false },
    sitemap_source: null,
    signals_evaluated: [],
    final_confidence_score: 0.9,
    consensus_method: "LAYER1_STRUCTURAL",
    ...overrides,
  };
}

export function discovery(overrides: Partial<DiscoveryReport> = {}): DiscoveryReport {
  return {
    base_url: "https://e.com/",
    total_urls: 0,
    from_sitemap: 0,
    from_dom: 0,
    from_cms: 0,
    sitemap_only: 0,
    dom_only: 0,
    orphans: 0,
    sitemaps_fetched: 0,
    pages_fetched: 1,
    fetch_failures: 0,
    media_skipped: 0,
    malformed_skipped: 0,
    loop_urls_skipped: 0,
    traps_skipped: 0,
    truncated: false,
    stopped_reason: null,
    dom_reserve: 0,
    dom_reserve_used: 0,
    ...overrides,
  };
}

/** A whole crawl result. */
export function crawl(
  overrides: Partial<PageClassificationOutput> = {},
): PageClassificationOutput {
  const pages = overrides.pages ?? [page("https://e.com/a/")];
  return {
    base_url: "https://e.com/",
    site_profile: {
      cms_family: "UNKNOWN",
      renders_client_side: false,
      has_catalogue: false,
      locale_prefixes: [],
    },
    weight_profile: {
      profile_name: "default",
      adaptive_enabled: false,
      detected_profile_name: "default",
    },
    discovery: discovery({ total_urls: pages.length }),
    summary: {
      pages_classified: pages.length,
      escalated_to_llm: 0,
      escalation_rate: 0,
      unknown_pages: 0,
      low_confidence_pages: 0,
      orphan_pages: 0,
      llm_spend_usd: 0,
    },
    navigation: { roots: [], source: { strategy: "none", containers: 0, link_count: 0 } },
    nav_coverage: {
      total_urls: pages.length,
      exact_matches: 0,
      inherited_matches: 0,
      breadcrumb_matches: 0,
      unmatched: pages.length,
      nav_entries: 0,
      groups: [],
    },
    ...overrides,
    pages,
  };
}
