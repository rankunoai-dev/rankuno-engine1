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
  DispatchPreview,
  WorkerJobView,
  WorkerSummary,
} from "../adapters/adapterInterface";
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
    // `UNKNOWN`, not `INDEXABLE`. The default fixture describes a page nothing
    // was read from, and a factory that hands every test a healthy verdict is a
    // fixture healthier than production data — which tests nothing. A test that
    // wants a verdict states it.
    indexability: "UNKNOWN",
    indexability_reason: "",
    is_cross_silo_link: false,
    inbound_internal_links_count: 0,
    outbound_internal_links_count: 0,
    discovery_sources: { sitemap: false, dom_link: true, cms_api: false },
    sitemap_source: null,
    signals_evaluated: [],
    final_confidence_score: 0.9,
    consensus_method: "LAYER1_STRUCTURAL",
    gsc_clicks: null,
    gsc_impressions: null,
    gsc_ctr: null,
    gsc_avg_position: null,
    navigation_discovery_method: null,
    navigation_reachability_tier: null,
    navigation_source_authority: null,
    navigation_path_quality: null,
    page_title: "",
    page_title_count: 0,
    page_title_outside_head: false,
    meta_description: "",
    meta_description_count: 0,
    meta_description_outside_head: false,
    h1_text: "",
    h1_count: 0,
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
    sitemap_fetch_attempts: 0,
    sitemaps_blocked: false,
    sitemap_offhost_skipped: 0,
    pages_fetched: 1,
    fetch_failures: 0,
    fetch_outcomes: {},
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
    // `null` by default: the fixture describes a crawl that says nothing about
    // Search Console, which is also the shape of every result stored before the
    // engine recorded an outcome. A test that wants an outcome states it.
    gsc: null,
    ...overrides,
    pages,
  };
}

/*
 * ---------------------------------------------------------------------------
 * Worker dispatch (ADR 0015).
 *
 * Hand-written like the types they build, for the same reason: these shapes
 * come from `src/api/worker_schemas.py`, which the contract exporter does not
 * read. Every default below is the *unhelpful* one — a machine that has never
 * checked in, a job with no bundle — because a fixture healthier than
 * production tests nothing. A test that wants a good state says so.
 * ---------------------------------------------------------------------------
 */

/** One registered desktop worker. Offline and silent unless told otherwise. */
export function worker(overrides: Partial<WorkerSummary> = {}): WorkerSummary {
  return {
    worker_id: "wkr-aaaa",
    org_id: "acme",
    display_name: "Studio desktop",
    is_active: true,
    created_at: "2026-09-01T09:00:00Z",
    last_seen_at: null,
    is_online: false,
    template_names: [],
    ...overrides,
  };
}

/** A minted approval. Expires two minutes out, as the server's TTL does. */
export function dispatchPreview(
  overrides: Partial<DispatchPreview> = {},
): DispatchPreview {
  return {
    token: "tok-1",
    expires_at: new Date(Date.now() + 120_000).toISOString(),
    worker_id: "wkr-aaaa",
    seed_url: "https://www.example.com/",
    template_name: null,
    correlation_id: "ui-test-1",
    worker_online: true,
    worker_last_seen_at: "2026-09-21T10:00:00Z",
    ...overrides,
  };
}

/**
 * One dispatch job.
 *
 * Carries only the required fields by default. Records written before
 * `bundle_size_bytes`, `dispatched_at`, `finished_at` and `error` existed have
 * exactly this shape, and they must render.
 */
export function workerJob(overrides: Partial<WorkerJobView> = {}): WorkerJobView {
  const seed = overrides.envelope?.seed_url ?? "https://www.example.com/";
  return {
    id: "wj-1",
    org_id: "acme",
    worker_id: "wkr-aaaa",
    kind: "screaming_frog_crawl",
    status: "queued",
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides,
    envelope: {
      job_id: overrides.id ?? "wj-1",
      seed_url: seed,
      template_name: null,
      correlation_id: "ui-test-1",
      ...overrides.envelope,
    },
  };
}
