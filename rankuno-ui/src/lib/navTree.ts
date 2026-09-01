import type { FullPageIntelligenceProfile } from "../types/schema";
import type { TreeNode } from "./tree";

/** Root group for pages no navigation section contains. Mirrors the backend. */
export const OTHERS_LABEL = "OTHERS";

/**
 * Locale codes recognised in a leading path segment.
 *
 * Mirrors `_ISO_639_1` in `url_rules.py`, including its two deliberate
 * omissions: `it` and `hr` collide with extremely common English sections —
 * `/it/` for IT services, `/hr/` for human resources — and mistaking a content
 * section for a language is a worse failure than missing a locale.
 */
const LOCALES = new Set([
  "ar", "bg", "bn", "cs", "da", "de", "el", "en", "es", "et", "fa", "fi", "fr",
  "he", "hi", "hu", "id", "is", "ja", "ko", "lt", "lv", "ms", "nl", "no", "pl",
  "pt", "ro", "ru", "sk", "sl", "sr", "sv", "th", "tr", "uk", "ur", "vi", "zh",
]);

/**
 * The shape of a region-qualified locale — `en-gb`, `pt_BR`.
 *
 * Necessary but **not sufficient**; see `isRegionalLocale`. Shape alone matched
 * 116 distinct segments over 19,865 pages across the stored corpus, 31 of which
 * were not locales.
 */
const REGIONAL = /^[a-z]{2}[-_][a-z]{2,4}$/i;

/**
 * Languages eligible to appear in a hyphenated locale.
 *
 * `it` and `hr` are added to `LOCALES` here and nowhere else. They are omitted
 * from the bare list because `/it/` and `/hr/` are far more often IT services
 * and human resources; hyphenated, `it-it` and `it-hr` are unambiguous.
 */
const REGIONAL_LANGUAGES = new Set([...LOCALES, "it", "hr"]);

/**
 * Whether an `en-gb`-shaped segment is really a locale rather than a slug.
 *
 * Shape alone put fake language tabs in the tree: `highradius.com/lp-demo/` sat
 * beside `en-gb` and `fr`, and postman.com contributed **29** workspace slugs —
 * `jd-bots`, `cv-core`, `mb-api` — each rendering as its own language.
 *
 * One half must be a real language. Either half, not the first: `jp-ja` (132
 * pages on gep.com) and `hk-zh` (infosys.com) put the region first, and a rule
 * checking only the left side would delete both.
 *
 * Mirrors `_is_regional_locale` in `url_rules.py`, including its one known
 * residual — `cs-demo` is kept, because `cs` is Czech.
 */
function isRegionalLocale(segment: string): boolean {
  if (!REGIONAL.test(segment)) return false;
  const [left, right] = segment.split(/[-_]/, 2);
  return REGIONAL_LANGUAGES.has(left ?? "") || REGIONAL_LANGUAGES.has(right ?? "");
}

/**
 * The locale a URL is served under, or `null` for the default language.
 *
 * Read from the URL rather than from breadcrumb labels, because the labels are
 * themselves translated: HighRadius publishes `Home`, `Accueil` and
 * `Startseite` as three roots for one concept, and 481 of its 917 localised
 * pages had no localised root at all — they scattered into OTHERS and into the
 * English tree. The path prefix is the one unambiguous signal.
 */
export function localeOf(url: string): string | null {
  try {
    const first = new URL(url).pathname.split("/").filter(Boolean)[0];
    if (!first) return null;
    const lower = first.toLowerCase();
    return LOCALES.has(lower) || isRegionalLocale(lower) ? lower : null;
  } catch {
    return null;
  }
}

/**
 * Group pages by the site's own header menu instead of by URL path.
 *
 * A URL-path tree answers "where does this file live?". The header menu answers
 * "where would a visitor look for this?", and on a flat-URL site the first
 * question has no useful answer at all — every page sits at depth 1, so the path
 * tree is one long list regardless of how the site is organised.
 *
 * The grouping comes from `breadcrumb_path`, which the engine fills from the
 * parsed menu. That field has been on the profile contract since Phase 1 was
 * specified and was populated by nothing until now.
 *
 * Emits the same `TreeNode` shape as `buildTree`, so the pane renders either
 * view without knowing which it was given.
 */
export function buildNavTree(
  profiles: readonly FullPageIntelligenceProfile[],
): TreeNode {
  const root: TreeNode = {
    segment: "/",
    path: "/",
    profile: null,
    children: [],
    descendantCount: 0,
    depth: 0,
  };

  const index = new Map<string, TreeNode>();

  for (const profile of profiles) {
    // A page the engine could not place carries no breadcrumb. It still has to
    // appear somewhere — dropping it would make the tree disagree with the page
    // count shown in the header.
    const base =
      profile.breadcrumb_path.length > 0
        ? profile.breadcrumb_path
        : [OTHERS_LABEL];

    // A localised page is rooted under its locale. Without this the French and
    // German sections of a site are not represented at all: their pages sit
    // beside English ones under a translated root, or fall into OTHERS, and the
    // site's language structure — separately indexed, separately ranked — is
    // invisible in the tree that is supposed to describe the architecture.
    const locale = localeOf(profile.url);
    const trail = locale === null ? base : [locale, ...base];

    let parent = root;
    let accumulated = "";

    for (const [depth, label] of trail.entries()) {
      accumulated += `/${label}`;
      let node = index.get(accumulated);
      if (!node) {
        node = {
          segment: label,
          path: accumulated,
          profile: null,
          children: [],
          descendantCount: 0,
          depth: depth + 1,
        };
        index.set(accumulated, node);
        parent.children.push(node);
      }
      parent = node;
    }

    // The section node itself may be a real page (a menu item usually is). Only
    // the exact match claims it: without this check, every page inheriting a
    // section would overwrite the section's own profile in turn, and the last
    // one processed would win at random.
    const isSectionPage = profile.nav_parent_url === profile.url;
    if (isSectionPage && parent.profile === null) {
      parent.profile = profile;
    } else {
      const leafPath = `${parent.path}#${profile.url}`;
      parent.children.push({
        segment: leafSegment(profile.url),
        path: leafPath,
        profile,
        children: [],
        descendantCount: 0,
        depth: parent.depth + 1,
      });
    }
  }

  sortAndCount(root);
  return root;
}

/** The last meaningful URL segment, for labelling a leaf under its section. */
function leafSegment(url: string): string {
  try {
    const { pathname, search } = new URL(url);
    const parts = pathname.split("/").filter(Boolean);
    const last = parts[parts.length - 1] ?? "/";
    // The query is part of the label, not decoration. Dropping it made eleven
    // distinct URLs — `/company/awards-and-recognition` and its `?page=1`…`10`
    // variants — render as eleven identical rows, which reads as a duplication
    // bug and hides a real finding: ten paginated URLs indexed separately.
    return search ? `${last}${search}` : last;
  } catch {
    return url;
  }
}

/**
 * Sort children and accumulate descendant counts, iteratively.
 *
 * Iterative rather than recursive for the same reason `buildTree` is: a 20,000
 * page tree can nest deeply enough to blow the call stack, and the failure is a
 * blank screen rather than an error message.
 *
 * `OTHERS` sorts last wherever it appears — it is the residue, not a section.
 */
function sortAndCount(root: TreeNode): void {
  const order: TreeNode[] = [];
  const stack: TreeNode[] = [root];

  while (stack.length > 0) {
    const node = stack.pop()!;
    order.push(node);
    node.children.sort(compareNodes);
    stack.push(...node.children);
  }

  for (let index = order.length - 1; index >= 0; index -= 1) {
    const node = order[index]!;
    node.descendantCount = node.children.reduce(
      (total, child) => total + child.descendantCount + (child.profile ? 1 : 0),
      0,
    );
  }
}

function compareNodes(a: TreeNode, b: TreeNode): number {
  if (a.segment === OTHERS_LABEL) return 1;
  if (b.segment === OTHERS_LABEL) return -1;
  // Sections (which have children) before individual pages, then alphabetical.
  const aSection = a.children.length > 0 ? 0 : 1;
  const bSection = b.children.length > 0 ? 0 : 1;
  if (aSection !== bSection) return aSection - bSection;
  return a.segment.localeCompare(b.segment);
}
