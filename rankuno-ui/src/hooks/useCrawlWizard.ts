/**
 * State management hook for the 4-stage New Crawl Wizard.
 *
 * Handles form state, navigation between stages, and payload serialization.
 */

import { useCallback, useState } from "react";
import { CRAWL_SPEEDS, DEFAULT_CRAWL_REQUEST } from "../adapters/adapterInterface";
import type { CrawlJobInput } from "../types/crawlWizard";
import type { CrawlWizardFormData, CrawlSource, CrawlConfigPreset } from "../types/crawlWizard";

/**
 * Wizard state manager.
 */
export function useCrawlWizard() {
  const [currentStage, setCurrentStage] = useState<1 | 2 | 3 | 4>(1);
  const [formData, setFormData] = useState<CrawlWizardFormData>({
    // Stage 1
    source: "full_site",
    uploadedUrls: [],

    // Stage 2
    domain: "",

    // Stage 3
    configPreset: "polite",

    // Stage 4
    verifySsl: true,

    // Common
    crawlDom: DEFAULT_CRAWL_REQUEST.crawl_dom,
    respectRobots: DEFAULT_CRAWL_REQUEST.respect_robots,
    browserHeaders: DEFAULT_CRAWL_REQUEST.browser_headers,
    userAgent: DEFAULT_CRAWL_REQUEST.user_agent,
  });

  /**
   * Navigate to a specific stage.
   */
  const goToStage = useCallback((stage: 1 | 2 | 3 | 4) => {
    setCurrentStage(stage);
  }, []);

  /**
   * Move to next stage.
   */
  const nextStage = useCallback(() => {
    setCurrentStage((prev) => (prev < 4 ? ((prev + 1) as 1 | 2 | 3 | 4) : prev));
  }, []);

  /**
   * Move to previous stage.
   */
  const prevStage = useCallback(() => {
    setCurrentStage((prev) => (prev > 1 ? ((prev - 1) as 1 | 2 | 3 | 4) : prev));
  }, []);

  /**
   * Update form data field(s).
   */
  const updateFormData = useCallback((updates: Partial<CrawlWizardFormData>) => {
    setFormData((prev) => ({ ...prev, ...updates }));
  }, []);

  /**
   * Reset the wizard to initial state.
   */
  const reset = useCallback(() => {
    setCurrentStage(1);
    setFormData({
      source: "full_site",
      uploadedUrls: [],
      domain: "",
      configPreset: "polite",
      verifySsl: true,
      crawlDom: DEFAULT_CRAWL_REQUEST.crawl_dom,
      respectRobots: DEFAULT_CRAWL_REQUEST.respect_robots,
      browserHeaders: DEFAULT_CRAWL_REQUEST.browser_headers,
      userAgent: DEFAULT_CRAWL_REQUEST.user_agent,
    });
  }, []);

  /**
   * Get available domains from uploaded URLs.
   */
  const getAvailableDomains = useCallback((): string[] => {
    const domains = new Set<string>();
    for (const url of formData.uploadedUrls) {
      try {
        const urlObj = new URL(url);
        domains.add(urlObj.hostname || "");
      } catch {
        // Ignore invalid URLs
      }
    }
    return Array.from(domains).filter((d) => d).sort();
  }, [formData.uploadedUrls]);

  /**
   * Serialize form data to crawl job input payload.
   *
   * Converts wizard form data to the API payload format.
   * Maps UI fields to backend fields (e.g., maxPages -> max_pages).
   */
  const serializeToPayload = useCallback((): CrawlJobInput => {
    // Get rate and concurrency from preset or custom
    let rateLimitRps = DEFAULT_CRAWL_REQUEST.rate_limit_rps;
    let concurrency = DEFAULT_CRAWL_REQUEST.concurrency;

    if (formData.configPreset === "custom") {
      rateLimitRps = formData.customRate ?? DEFAULT_CRAWL_REQUEST.rate_limit_rps;
      concurrency = formData.customConcurrency ?? DEFAULT_CRAWL_REQUEST.concurrency;
    } else {
      const preset = CRAWL_SPEEDS.find((s) => s.key === formData.configPreset);
      if (preset) {
        rateLimitRps = preset.rate_limit_rps;
        concurrency = preset.concurrency;
      }
    }

    // Build base URL from domain
    let baseUrl = formData.domain;
    if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
      baseUrl = `https://${baseUrl}`;
    }

    // Prepare seed URLs (from URL list source)
    const seedUrls =
      formData.source === "url_list"
        ? formData.uploadedUrls.filter((url) => {
            const domain = url;
            try {
              const urlObj = new URL(url);
              return urlObj.hostname === formData.domain || url.includes(formData.domain);
            } catch {
              return url.includes(formData.domain);
            }
          })
        : [];

    // Build payload
    const payload: CrawlJobInput = {
      ...DEFAULT_CRAWL_REQUEST,
      base_url: baseUrl,
      rate_limit_rps: rateLimitRps,
      concurrency,
      max_pages: formData.maxPages ?? DEFAULT_CRAWL_REQUEST.max_pages,
      max_depth: formData.maxDepth ?? DEFAULT_CRAWL_REQUEST.max_depth,
      crawl_dom: formData.crawlDom,
      respect_robots: formData.respectRobots,
      browser_headers: formData.browserHeaders,
      user_agent: formData.userAgent,
      seed_urls: seedUrls,

      // Phase 2 additions
      source: formData.source,
      proxy: formData.proxy ?? null,
      auth: formData.auth ?? null,
      custom_headers: formData.customHeaders,
      verify_ssl: formData.verifySsl,
      ga4_property_id: formData.ga4PropertyId ?? null,
    };

    return payload;
  }, [formData]);

  return {
    currentStage,
    formData,
    goToStage,
    nextStage,
    prevStage,
    updateFormData,
    reset,
    getAvailableDomains,
    serializeToPayload,
  };
}
