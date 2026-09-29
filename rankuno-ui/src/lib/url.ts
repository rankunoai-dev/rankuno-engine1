/**
 * URL presentation helpers.
 *
 * Display only. Nothing here validates or normalises a URL for fetching — that
 * is the engine's job, and `url_rules.py` is where those rules live.
 */

/**
 * The host, for places too narrow to hold a full URL.
 *
 * A label that will not parse is returned as it stands rather than blanked: a
 * job whose target cannot be parsed still has to be identifiable in a list.
 */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * The path, for places too narrow to hold a full URL.
 *
 * `url` on `FullPageIntelligenceProfile` is `Field(min_length=1)` on the engine
 * side — a non-empty string, not a validated `HttpUrl` — so nothing guarantees
 * `new URL()` can parse it. The opportunity list in `GscPerformanceSection` threw
 * on `new URL(page.url).pathname` for exactly this reason before this guard
 * existed: a render exception there is caught by the report's `ErrorBoundary`
 * and replaces the whole printable report with an error banner, so a PDF export
 * that reaches this row fails outright instead of printing the one row wrong.
 */
export function pathnameOf(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}
