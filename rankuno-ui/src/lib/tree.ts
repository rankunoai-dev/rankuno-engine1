import type { FullPageIntelligenceProfile, HierarchyLevel } from "../types/schema";

/**
 * A node in the site hierarchy.
 *
 * Structure comes from the **URL path**, not `hierarchy_level`. This is the most
 * important decision in the whole visualizer and the least obvious:
 * `hierarchy_level` classifies a page's *role* and deliberately does not imply
 * containment (ADR 0002). An L1 hub can live at any path depth. Nesting by level
 * would produce a tree that contradicts the site's actual structure.
 *
 * The backend's own `tree_visualizer.py` nests by path for the same reason.
 */
export interface TreeNode {
  /** Path segment this node represents, e.g. `services`. */
  segment: string;
  /** Accumulated path, e.g. `/software/order-to-cash/`. Unique; used as the key. */
  path: string;
  /** The classified page, or null for a structural node no crawl returned. */
  profile: FullPageIntelligenceProfile | null;
  children: TreeNode[];
  /** Pages beneath this node, computed once at build time. */
  descendantCount: number;
  /** Depth in the rendered tree. Not the same as `profile.depth_from_l0`. */
  depth: number;
}

/** Sort order for levels. Utility pages last so they do not crowd the structure. */
const LEVEL_ORDER: Record<HierarchyLevel, number> = {
  L0_HOMEPAGE: 0,
  L1_PRIMARY_NAV_HUB: 1,
  L2_SUB_NAV_HUB: 2,
  L3_LEAF_PAGE: 3,
  UTILITY_PAGE: 4,
};

/** Split a normalised URL into path segments, discarding scheme and host. */
export function pathSegments(url: string): string[] {
  const withoutScheme = url.includes("://") ? url.slice(url.indexOf("://") + 3) : url;
  const slash = withoutScheme.indexOf("/");
  const path = slash === -1 ? "" : withoutScheme.slice(slash + 1);
  return path
    .split("?")[0]!
    .split("/")
    .filter((segment) => segment.length > 0);
}

/**
 * Assemble profiles into a nested tree keyed by URL path.
 *
 * Intermediate segments with no crawled page become structural nodes with a null
 * profile, so a child is never orphaned by a parent the crawl did not return —
 * which happens constantly on truncated crawls, and every live crawl so far has
 * been truncated.
 */
export function buildTree(profiles: readonly FullPageIntelligenceProfile[]): TreeNode {
  const root: TreeNode = {
    segment: "/",
    path: "/",
    profile: null,
    children: [],
    descendantCount: 0,
    depth: 0,
  };
  const index = new Map<string, TreeNode>([["/", root]]);

  for (const profile of profiles) {
    const segments = pathSegments(profile.normalized_path);
    if (segments.length === 0) {
      root.profile = profile;
      continue;
    }

    let cursor = root;
    let accumulated = "";
    for (let i = 0; i < segments.length; i += 1) {
      const segment = segments[i]!;
      accumulated = `${accumulated}/${segment}`;
      const key = `${accumulated}/`;
      let child = index.get(key);
      if (!child) {
        child = {
          segment,
          path: key,
          profile: null,
          children: [],
          descendantCount: 0,
          depth: i + 1,
        };
        index.set(key, child);
        cursor.children.push(child);
      }
      cursor = child;
    }
    cursor.profile = profile;
  }

  sortAndCount(root);
  return root;
}

/**
 * Sort children and compute descendant counts in one post-order pass.
 *
 * Iterative rather than recursive: the 8-deep fixture is fine either way, but a
 * pathological site with a deep redirect chain would blow the call stack, and a
 * crash while rendering a client's site is not an acceptable failure mode.
 */
function sortAndCount(root: TreeNode): void {
  const stack: TreeNode[] = [root];
  const order: TreeNode[] = [];

  while (stack.length > 0) {
    const node = stack.pop()!;
    order.push(node);
    for (const child of node.children) stack.push(child);
  }

  for (let i = order.length - 1; i >= 0; i -= 1) {
    const node = order[i]!;
    node.children.sort(compareNodes);
    let total = 0;
    for (const child of node.children) total += 1 + child.descendantCount;
    node.descendantCount = total;
  }
}

function compareNodes(a: TreeNode, b: TreeNode): number {
  const rankA = a.profile ? LEVEL_ORDER[a.profile.hierarchy_level] : 9;
  const rankB = b.profile ? LEVEL_ORDER[b.profile.hierarchy_level] : 9;
  if (rankA !== rankB) return rankA - rankB;
  return a.segment.localeCompare(b.segment);
}

