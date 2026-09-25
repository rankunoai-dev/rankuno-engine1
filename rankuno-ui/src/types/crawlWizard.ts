/**
 * Phase 2 New Crawl Wizard types.
 *
 * Extends PageClassificationInput with Phase 2 fields (proxy, auth, headers, etc).
 * These fields are stored but not yet consumed by the crawl engine (deferred to Phase 2C/2D).
 */

import type { PageClassificationInput } from "./schema";

/**
 * Source selection for crawl: full domain or uploaded URL list.
 */
export type CrawlSource = "full_site" | "url_list";

/**
 * Crawl configuration preset.
 */
export type CrawlConfigPreset = "polite" | "aggressive" | "custom";

/**
 * Authentication credentials for the crawl target.
 */
export interface BasicAuthCredentials {
  username: string;
  password: string;
}

/**
 * Phase 2 crawl form state, spanning all 4 wizard stages.
 */
export interface CrawlWizardFormData {
  // Stage 1: Source Selection
  source: CrawlSource;
  uploadedUrls: string[];

  // Stage 2: Domain Selection
  domain: string;

  // Stage 3: Configuration
  configPreset: CrawlConfigPreset;
  customRate?: number;
  customConcurrency?: number;

  // Stage 4: Advanced Options
  proxy?: string | null;
  auth?: BasicAuthCredentials | null;
  customHeaders?: Record<string, string>;
  userAgent: string;
  verifySsl: boolean;
  gscProperty?: string | null;
  ga4PropertyId?: string | null;

  // Common fields (from existing form)
  maxPages?: number | null;
  maxDepth?: number | null;
  crawlDom: boolean;
  respectRobots: boolean;
  browserHeaders: boolean;
}

/**
 * Extended PageClassificationInput with Phase 2 additions.
 *
 * These fields are sent to the backend but may not be consumed until later phases.
 * - proxy: stored, not used by crawl engine yet (Phase 2C)
 * - auth: stored, not used by crawl engine yet (Phase 2C)
 * - custom_headers: stored, not sent in crawl requests yet (Phase 2C)
 * - verify_ssl: stored, not validated in crawl yet (Phase 2C)
 * - ga4_property_id: stored, not used for enrichment yet (Phase 2D)
 * - source: metadata about how the crawl was triggered
 */
export type CrawlJobInput = PageClassificationInput & {
  /** Source of the crawl: full_site or url_list */
  source?: CrawlSource;
  /** Proxy server URL (socks5://host:port or http://host:port) */
  proxy?: string | null;
  /** Basic authentication credentials */
  auth?: BasicAuthCredentials | null;
  /** Custom HTTP headers to send with requests */
  custom_headers?: Record<string, string>;
  /** Whether to verify SSL certificates */
  verify_ssl?: boolean;
  /** GA4 measurement ID for optional enrichment */
  ga4_property_id?: string | null;
};

/**
 * Domain option extracted from uploaded URL list.
 * Shows the domain and count of URLs from that domain.
 */
export interface DomainOption {
  domain: string;
  urlCount: number;
}
