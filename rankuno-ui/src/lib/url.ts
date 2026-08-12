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
