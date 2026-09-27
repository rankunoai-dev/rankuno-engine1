/**
 * URL parsing and domain extraction for an uploaded URL list.
 *
 * Handles CSV, TXT, and plain text file formats with flexible URL parsing.
 *
 * Kept after the 4-stage crawl wizard was removed (it configured the native
 * Python crawler, which is the wrong engine for those settings). This module is
 * engine-agnostic: a Screaming Frog `--crawl-list` upload needs exactly this
 * parsing and domain grouping, so it stays rather than being rewritten later.
 * `DomainOption` lives here, with the function that produces it, because the
 * wizard-only type module it used to live in went with the wizard.
 */

/**
 * A domain extracted from an uploaded URL list, with how many of the uploaded
 * URLs belong to it.
 */
export interface DomainOption {
  domain: string;
  urlCount: number;
}

/**
 * Extract domain from a full URL string.
 *
 * Handles both http/https URLs and bare domain strings.
 * Returns null if the URL is malformed.
 *
 * @param urlString - Full URL or domain string
 * @returns Domain (www.example.com) or null if invalid
 */
export function extractDomain(urlString: string): string | null {
  const trimmed = urlString.trim();
  if (!trimmed) return null;

  try {
    // Try parsing as URL
    const url = new URL(trimmed);
    return url.hostname || null;
  } catch {
    // Not a valid URL, try as bare domain
    // Basic domain validation: must have at least one dot
    if (/^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,}$/i.test(trimmed)) {
      return trimmed;
    }
    return null;
  }
}

/**
 * Validate a URL string (accepts both full URLs and domains).
 *
 * @param urlString - URL or domain to validate
 * @returns true if valid
 */
export function isValidUrl(urlString: string): boolean {
  return extractDomain(urlString) !== null;
}

/**
 * Parse CSV file contents into array of URLs.
 *
 * Handles:
 * - Single column of URLs (simplest case)
 * - Multiple columns (tries to find URL in each row)
 * - Headers (skips rows that look like headers)
 * - Empty rows (skips)
 *
 * @param csvContent - Raw CSV file contents
 * @returns Array of extracted URLs
 */
export function parseCSV(csvContent: string): string[] {
  const lines = csvContent.split(/\r?\n/);
  const urls: string[] = [];

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line || !line.trim()) continue; // Skip empty lines

    // Split by comma (simplified CSV parsing)
    const cells = line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, ""));

    // Skip header-like rows: only check first row, only check first cell
    if (i === 0 && cells[0] && looksLikeHeader(cells[0])) continue;

    // Look for a URL in this row
    for (const cell of cells) {
      if (cell && isValidUrl(cell)) {
        urls.push(cell);
        break; // Take first URL in row and move to next row
      }
    }
  }

  return urls;
}

/**
 * Check if a string looks like a CSV header.
 *
 * Headers are short words that typically label columns.
 * Only match if the entire cell (trimmed and lowercased) is one of the patterns.
 *
 * @param cell - Cell value to check
 * @returns true if it looks like a header
 */
function looksLikeHeader(cell: string): boolean {
  const lower = cell.toLowerCase().trim();
  const headerPatterns = [
    "url",
    "link",
    "address",
    "uri",
    "href",
    "domain",
  ];
  // Exact match only, not substring match
  return headerPatterns.includes(lower);
}

/**
 * Parse plain text file contents into array of URLs.
 *
 * Handles:
 * - One URL per line
 * - Empty lines (skips)
 * - Whitespace trimming
 *
 * @param textContent - Raw text file contents
 * @returns Array of extracted URLs
 */
export function parsePlainText(textContent: string): string[] {
  return textContent
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Parse uploaded file contents based on file type.
 *
 * Detects CSV by extension or attempts to parse as such.
 * Defaults to plain text parsing.
 *
 * @param file - File object with name and contents
 * @param contents - File contents as string
 * @returns Array of extracted URLs
 */
export function parseUploadedFile(file: File, contents: string): string[] {
  const lower = file.name.toLowerCase();

  if (lower.endsWith(".csv")) {
    return parseCSV(contents);
  }

  if (lower.endsWith(".txt")) {
    return parsePlainText(contents);
  }

  // Try CSV parsing first, fall back to plain text
  const csvUrls = parseCSV(contents);
  return csvUrls.length > 0 ? csvUrls : parsePlainText(contents);
}

/**
 * Extract unique domains from a list of URLs.
 *
 * Deduplicates domains and counts URLs per domain.
 *
 * @param urls - Array of URL strings
 * @returns Array of domain options sorted by URL count (descending)
 */
export function extractDomainsWithCounts(urls: string[]): DomainOption[] {
  const domainMap = new Map<string, number>();

  for (const url of urls) {
    const domain = extractDomain(url);
    if (domain) {
      const lower = domain.toLowerCase();
      domainMap.set(lower, (domainMap.get(lower) ?? 0) + 1);
    }
  }

  // Sort by URL count descending, then alphabetically
  return Array.from(domainMap.entries())
    .map(([domain, urlCount]) => ({ domain, urlCount }))
    .sort((a, b) => b.urlCount - a.urlCount || a.domain.localeCompare(b.domain));
}

/**
 * Filter URLs by domain.
 *
 * Case-insensitive domain matching.
 *
 * @param urls - Array of URL strings
 * @param domain - Domain to filter by
 * @returns URLs from the specified domain
 */
export function filterUrlsByDomain(urls: string[], domain: string): string[] {
  const targetDomain = domain.toLowerCase();
  return urls.filter((url) => {
    const extracted = extractDomain(url);
    return extracted && extracted.toLowerCase() === targetDomain;
  });
}
