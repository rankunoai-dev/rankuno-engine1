/**
 * Form validation helpers for a crawl target and its rate settings.
 *
 * Kept after the 4-stage crawl wizard was removed: the wizard configured the
 * native Python crawler, which is the wrong engine for most of what it
 * collected, but these rules are engine-agnostic and a Screaming Frog dispatch
 * form needs the same domain, rate and concurrency checks. Nothing in the tree
 * imports the module today except its own tests — that is a known state, not an
 * oversight.
 */

/**
 * A base domain, parsed from whatever the operator typed.
 *
 * Exactly one of the two fields is set. The pair exists so `validateDomain` and
 * `normalizeDomain` can share one parse: they used to be the same problem
 * solved twice, and the duplicate is how the field's help text and its
 * validator came to disagree.
 */
interface ParsedDomain {
  /** The bare, lowercased hostname, or `null` when `error` is set. */
  host: string | null;
  /** The message to show the operator, or `null` when the input is usable. */
  error: string | null;
}

/**
 * One label of a hostname, repeated after each dot.
 *
 * Each dot-separated label must be non-empty and must neither start nor end
 * with a hyphen (RFC 1123 §2.1). Spelling it as a repeated label pattern rather
 * than `([a-z0-9-]*\.)*` is what rejects `example..com`: the older form let a
 * label match the empty string, so any run of consecutive dots passed.
 */
const HOSTNAME_PATTERN =
  /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$/i;

/**
 * Reduce operator input to a base domain.
 *
 * A scheme and a single trailing slash are *stripped*, not rejected: neither
 * can change which site is crawled, and the help text beneath the field has
 * always promised "with or without https://". The validator used to test the
 * raw string against a bare-hostname pattern, so `https://rankuno.com/` — the
 * form the field's own example gives — was refused.
 *
 * A path, query, fragment or port is **rejected**, deliberately, rather than
 * stripped. Each one names something narrower than the domain: someone who
 * pastes `https://example.com/blog/` is asking for a section, and someone who
 * types `example.com:8080` is naming a different origin. Silently widening
 * either to the whole of `example.com` would start a crawl the operator did not
 * ask for, which is worse than making them delete three characters. The message
 * says which part is the problem.
 */
function parseDomain(domain: string | undefined): ParsedDomain {
  if (!domain || !domain.trim()) {
    return { host: null, error: "Domain is required" };
  }

  const trimmed = domain.trim();

  // Checked before anything is stripped: an interior space means two things
  // were pasted into one field, and no amount of normalising fixes that.
  if (/\s/.test(trimmed)) {
    return { host: null, error: "Domain cannot contain spaces" };
  }

  const scheme = /^([a-z][a-z0-9+.-]*):\/\//i.exec(trimmed);
  if (scheme && !/^https?$/i.test(scheme[1] ?? "")) {
    return {
      host: null,
      error: "Only http:// and https:// are supported (e.g., https://www.example.com)",
    };
  }
  const withoutScheme = scheme ? trimmed.slice(scheme[0].length) : trimmed;

  const boundary = withoutScheme.search(/[/?#]/);
  const host = boundary === -1 ? withoutScheme : withoutScheme.slice(0, boundary);
  const remainder = boundary === -1 ? "" : withoutScheme.slice(boundary);

  // `"/"` alone is the trailing slash a browser address bar adds, and carries
  // no information. Anything longer is a path, query or fragment.
  if (remainder !== "" && remainder !== "/") {
    return {
      host: null,
      error: "Enter the base domain only, without a path or query (e.g., www.example.com)",
    };
  }

  if (host.includes(":")) {
    return {
      host: null,
      error: "Enter the base domain only, without a port (e.g., www.example.com)",
    };
  }

  if (!HOSTNAME_PATTERN.test(host)) {
    return { host: null, error: "Invalid domain format (e.g., www.example.com)" };
  }

  if (!host.includes(".")) {
    return { host: null, error: "Domain must include a TLD (e.g., .com, .org)" };
  }

  return { host: host.toLowerCase(), error: null };
}

/**
 * Validate a domain name format.
 *
 * Accepts a bare domain or a full http/https URL of the site root, with or
 * without a trailing slash: `example.com`, `www.example.com`,
 * `https://www.example.co.uk/`. Rejects a path, query or port — see
 * `parseDomain` for why that is a rejection and not a normalisation.
 *
 * @param domain - Domain string
 * @returns Error message or null if valid
 */
export function validateDomain(domain: string | undefined): string | null {
  return parseDomain(domain).error;
}

/**
 * Reduce a validated domain to its bare hostname.
 *
 * The counterpart to `validateDomain`: a form that has shown no error can take
 * the crawl target from here instead of re-implementing the scheme stripping,
 * which is the duplication that let the validator drift from its help text.
 *
 * @param domain - Domain string
 * @returns Lowercased hostname, or null if the input is not a valid base domain
 */
export function normalizeDomain(domain: string | undefined): string | null {
  return parseDomain(domain).host;
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
