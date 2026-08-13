import type { FullPageIntelligenceProfile } from "../types/schema";
import type { TreeNode } from "./tree";

/** Root group for pages no navigation section contains. Mirrors the backend. */
export const OTHERS_LABEL = "OTHERS";

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
    const trail =
      profile.breadcrumb_path.length > 0
        ? profile.breadcrumb_path
        : [OTHERS_LABEL];

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
