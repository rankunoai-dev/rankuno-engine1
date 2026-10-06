/**
 * Link-target guard for URLs that came from crawled data.
 *
 * Every URL this UI links to was read off a third-party site — a sitemap, a
 * redirect target, a nav menu — or arrived in an imported bundle (ADR 0034). The
 * engine stores `url` as a non-empty string, not a validated `HttpUrl`, so a page
 * can carry `javascript:` or `data:` and React will put it in `href` as given:
 * React 18 only warns about `javascript:` URLs, it does not block them.
 *
 * The check is an allow-list, not a deny-list. Browsers strip tabs, newlines and
 * leading control characters and fold case before reading the scheme, so
 * `java\tscript:` and ` JavaScript:` are the same as `javascript:` to them;
 * matching on the string misses those. Parsing with the same WHATWG parser the
 * browser uses, then admitting only http and https, sees what the browser sees.
 */

const LINKABLE_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * The URL to put in `href`, or null when it must be rendered as plain text.
 *
 * Parsed without a base, so a protocol-relative (`//host`) or relative value
 * throws and is refused rather than resolved against this app's own origin.
 *
 * Args:
 *   url: A URL string from crawled or imported data.
 *
 * Returns:
 *   The input unchanged when it is an absolute http(s) URL with a host;
 *   otherwise null.
 */
export function safeHref(url: string | null | undefined): string | null {
  if (url == null || url === "") return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (!LINKABLE_PROTOCOLS.has(parsed.protocol) || parsed.hostname === "") return null;
  return url;
}
