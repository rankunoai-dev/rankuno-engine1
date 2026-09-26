/**
 * Phase 2 New Crawl Wizard types.
 *
 * `CrawlWizardFormData` is wizard-local state, deliberately wider than the
 * crawl request: the advanced stage collects proxy, auth, custom headers, SSL
 * verification and a GA4 property that no backend field consumes yet, so
 * `useCrawlWizard.serializeToPayload` drops them and posts a plain
 * `PageClassificationInput`. There is intentionally no "request plus Phase 2
 * extras" type here — one existed, and because it widened the payload type it
 * let six undeclared keys reach a `StrictModel` (`extra="forbid"`) endpoint,
 * which answered `422` and stopped every crawl. Add a field to the Pydantic
 * model before adding it to a payload type.
 */

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
 * Domain option extracted from uploaded URL list.
 * Shows the domain and count of URLs from that domain.
 */
export interface DomainOption {
  domain: string;
  urlCount: number;
}
