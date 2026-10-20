/**
 * Path categories for URLs: the same rule as `url_category.py` in the engine.
 *
 * The export groups every URL by its first path segment, lowercased. This copy
 * exists so the UI can group the same way. It is not wired into the tree: the
 * tree groups by the profile's normalised path, and that behaviour is unchanged.
 *
 * Parity is enforced by `tests/fixtures/url_category/parity.json`, which both
 * this file and the Python module are tested against. The address is split with
 * the same regular expression as the Python side, not with `new URL()`. The two
 * parsers disagree about percent-encoding (`new URL` encodes a space in the path;
 * Python does not), and a parity test would then be testing the parsers.
 */

export const HOMEPAGE_CATEGORY = "/";

export const UNCATEGORISED = "(uncategorised)";

const ABSOLUTE_HTTP = /^https?:\/\/([^/?#]*)([^?#]*)/i;

/** The category an address belongs to. Mirrors `url_category.category_key`. */
export function categoryKey(url: string): string {
  const match = ABSOLUTE_HTTP.exec(url);
  if (match === null || !match[1]) {
    return UNCATEGORISED;
  }
  const segment = (match[2] ?? "").split("/").find((part) => part.length > 0);
  return segment === undefined ? HOMEPAGE_CATEGORY : segment.toLowerCase();
}
