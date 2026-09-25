/**
 * Validation utilities for the crawl wizard form.
 *
 * Provides rules and helpers for validating URLs, domains, rates, proxies, etc.
 */

/**
 * Validate a domain name format.
 *
 * Accepts: www.example.com, example.com, sub.domain.co.uk, etc.
 *
 * @param domain - Domain string
 * @returns Error message or null if valid
 */
export function validateDomain(domain: string | undefined): string | null {
  if (!domain || !domain.trim()) {
    return "Domain is required";
  }

  const trimmed = domain.trim();

  // Check basic domain format
  if (!/^[a-z0-9]([a-z0-9-]*\.)*[a-z0-9]([a-z0-9-]*)?$/i.test(trimmed)) {
    return "Invalid domain format (e.g., www.example.com)";
  }

  // Must have at least one dot for a valid domain
  if (!trimmed.includes(".")) {
    return "Domain must include a TLD (e.g., .com, .org)";
  }

  return null;
}

/**
 * Validate a proxy URL.
 *
 * Accepts: socks5://host:port, http://host:port, https://host:port
 *
 * @param proxy - Proxy URL string
 * @returns Error message or null if valid
 */
export function validateProxyUrl(proxy: string | undefined): string | null {
  if (!proxy || !proxy.trim()) {
    return null; // Proxy is optional
  }

  const trimmed = proxy.trim();
  const proxyPattern =
    /^(socks5|socks4|http|https):\/\/([a-z0-9.-]+|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d{1,5})?$/i;

  if (!proxyPattern.test(trimmed)) {
    return "Invalid proxy format (e.g., socks5://proxy.example.com:1080)";
  }

  return null;
}

/**
 * Validate custom rate (requests per second).
 *
 * @param rate - Rate value
 * @returns Error message or null if valid
 */
export function validateRate(rate: number | null | undefined): string | null {
  if (rate === null || rate === undefined) {
    return "Rate is required";
  }

  if (rate < 0.05) {
    return "Rate must be at least 0.05 requests per second";
  }

  if (rate > 25) {
    return "Rate must be at most 25 requests per second";
  }

  return null;
}

/**
 * Validate concurrency value.
 *
 * @param concurrency - Concurrency value
 * @returns Error message or null if valid
 */
export function validateConcurrency(concurrency: number | null | undefined): string | null {
  if (concurrency === null || concurrency === undefined) {
    return "Concurrency is required";
  }

  if (!Number.isInteger(concurrency)) {
    return "Concurrency must be a whole number";
  }

  if (concurrency < 1) {
    return "Concurrency must be at least 1";
  }

  if (concurrency > 200) {
    return "Concurrency must be at most 200";
  }

  return null;
}

/**
 * Validate custom HTTP header format.
 *
 * Checks if the header string is valid JSON or Name: Value format.
 *
 * @param headerString - Header string (JSON or Name: Value format)
 * @returns Parsed headers object or null with error message
 */
export function validateCustomHeaders(
  headerString: string | undefined,
): { headers: Record<string, string> | null; error: string | null } {
  if (!headerString || !headerString.trim()) {
    return { headers: null, error: null };
  }

  const trimmed = headerString.trim();

  // Try JSON parsing first
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed === "object" && parsed !== null) {
        return { headers: parsed, error: null };
      }
      return { headers: null, error: "Headers must be a valid JSON object" };
    } catch {
      return { headers: null, error: "Invalid JSON format for headers" };
    }
  }

  // Parse as Name: Value format (one per line)
  const headers: Record<string, string> = {};
  const lines = trimmed.split("\n");

  for (const line of lines) {
    const trimmedLine = line.trim();
    if (!trimmedLine) continue;

    const colonIndex = trimmedLine.indexOf(":");
    if (colonIndex === -1) {
      return { headers: null, error: `Invalid header format: "${trimmedLine}" (use "Name: Value")` };
    }

    const name = trimmedLine.substring(0, colonIndex).trim();
    const value = trimmedLine.substring(colonIndex + 1).trim();

    if (!name || !value) {
      return { headers: null, error: "Header names and values cannot be empty" };
    }

    headers[name] = value;
  }

  return { headers, error: null };
}

/**
 * Validate GA4 property ID format.
 *
 * GA4 property IDs are typically numeric (e.g., 123456789).
 *
 * @param ga4PropertyId - Property ID string
 * @returns Error message or null if valid
 */
export function validateGA4PropertyId(ga4PropertyId: string | undefined): string | null {
  if (!ga4PropertyId || !ga4PropertyId.trim()) {
    return null; // Optional
  }

  const trimmed = ga4PropertyId.trim();

  if (!/^\d+$/.test(trimmed)) {
    return "GA4 property ID must be numeric (e.g., 123456789)";
  }

  return null;
}

/**
 * Estimate crawl time based on page count and rate.
 *
 * Returns a rough estimate in seconds (single-host floor).
 * Does not account for multi-host fan-out.
 *
 * @param pageCount - Number of pages
 * @param ratePerSecond - Requests per second
 * @returns Estimated time in seconds
 */
export function estimateCrawlSeconds(pageCount: number, ratePerSecond: number): number {
  if (ratePerSecond <= 0) return Infinity;
  return pageCount / ratePerSecond;
}

/**
 * Format crawl time estimate as human-readable string.
 *
 * @param seconds - Time in seconds
 * @returns Formatted string (e.g., "2 hours", "15 minutes")
 */
export function formatCrawlTimeEstimate(seconds: number): string {
  if (!isFinite(seconds)) return "Unknown";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }

  if (minutes > 0) {
    return `${minutes}m`;
  }

  return `${Math.ceil(seconds)}s`;
}
