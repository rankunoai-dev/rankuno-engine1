import type {
  ConsensusMethod,
  FullPageIntelligenceProfile,
  PageClassificationOutput,
} from "../types/schema";
import { buildNavTree, OTHERS_LABEL } from "./navTree";
import { buildTree, type TreeNode } from "./tree";

/**
 * A node in the dashboard's flat, index-addressed model.
 *
 * Flat and integer-keyed on purpose. The virtualized list, the search index and
 * the focus graph all address nodes by position thousands of times per second
 * while scrolling; a nested object graph would mean walking it on every frame.
 */
export interface DashNode {
  /** Index into the node array. Stable for the lifetime of one crawl result. */
  i: number;
  /** Navigation depth, 0–3, or 4 for OTHERS. Lane assignment reads this. */
  lv: number;
  label: string;
  url: string;
  /** Parent index, or null for a root. */
  p: number | null;
  kids: number[];
  /** Pages in this subtree, accumulated once at build time. */
  cnt: number;
  /** The classified page, absent on structural grouping nodes. */
  profile: FullPageIntelligenceProfile | null;
}

export interface DashModel {
  nodes: DashNode[];
  roots: number[];
  /** Lowercased `label + url` per node, for substring search. */
  index: string[];
  /** Counts per lane, 0–3 then OTHERS. */
  laneCounts: [number, number, number, number, number];
  /** Consensus methods actually present, so no filter chip is a dead control. */
  methodsPresent: ConsensusMethod[];
}

export const OTHERS_LANE = 4;

/** Lane labels. Nav depth, not `HierarchyLevel` — those are different things. */
export const LANE_LABELS = ["L0", "L1", "L2", "L3", "OTH"] as const;

export const LANE_DESCRIPTIONS = [
  "L0 · top navigation tab",
  "L1 · menu section",
  "L2 · menu item",
  "L3 · page beneath a menu item",
  "OTHERS · reachable by no navigation path",
] as const;

/**
 * Human names for the cascade layers, keyed by `ConsensusMethod`.
 *
 * `WEIGHTED_CONSENSUS` is included because the engine really does emit it —
 * the reference design had four resolver chips and no slot for it.
 */
export const METHOD_LABELS: Record<ConsensusMethod, string> = {
  LAYER0_FAST_PATH: "Layer 0 · URL rules",
  LAYER1_STRUCTURAL: "Layer 1 · structural signals",
  LAYER2_LOCAL_ML: "Layer 2 · local ML",
  LAYER3_LLM_FALLBACK: "Layer 3 · LLM",
  WEIGHTED_CONSENSUS: "Weighted consensus",
};

/** Cascade order, for the inspector's trace. */
export const METHOD_ORDER: ConsensusMethod[] = [
  "LAYER0_FAST_PATH",
  "LAYER1_STRUCTURAL",
  "LAYER2_LOCAL_ML",
  "LAYER3_LLM_FALLBACK",
  "WEIGHTED_CONSENSUS",
];

/**
 * Layers with no implementation behind them.
 *
 * `ZeroShotClassifier` and `LlmPageClassifier` are protocols with no concrete
 * provider, so no crawl can produce these. The inspector marks them
 * "not implemented" rather than "skipped" — "skipped" would suggest the cascade
 * chose not to use a layer that exists.
 */
export const UNAVAILABLE_METHODS: ReadonlySet<ConsensusMethod> = new Set<ConsensusMethod>([
  "LAYER2_LOCAL_ML",
  "LAYER3_LLM_FALLBACK",
]);

/**
 * Build the dashboard model from a crawl result.
 *
 * Grouped by the site's header menu when one was parsed, and by URL path when
 * it was not. The lane a node lands in is its depth in whichever tree was
 * built — so with no menu the lanes mean path depth, and the UI says so rather
 * than implying the site published a structure it did not.
 */
export function buildDashModel(
  result: PageClassificationOutput,
  grouping: "navigation" | "path",
): DashModel {
  const useNav = grouping === "navigation" && result.navigation.roots.length > 0;
  const root = useNav ? buildNavTree(result.pages) : buildTree(result.pages);

  const nodes: DashNode[] = [];
  const roots: number[] = [];

  // Iterative, not recursive: a 20,000-page path tree nests deeply enough to
  // overflow the stack, and the failure mode is a blank screen with no error.
  const stack: Array<{ node: TreeNode; parent: number | null; othersBranch: boolean }> =
    root.children.map((child) => ({
      node: child,
      parent: null,
      othersBranch: child.segment === OTHERS_LABEL,
    }));
  stack.reverse();

  while (stack.length > 0) {
    const { node, parent, othersBranch } = stack.pop()!;

    const depth = parent === null ? 0 : nodes[parent]!.lv + 1;
    const index = nodes.length;
    nodes.push({
      i: index,
      // Everything under OTHERS shares the OTHERS lane: it is one bucket, and
      // spreading its contents across the L0–L3 lanes would read as though
      // those pages had navigation positions. They are there precisely because
      // they do not.
      lv: othersBranch ? OTHERS_LANE : Math.min(depth, 3),
      label: node.segment,
      url: node.profile?.url ?? node.path,
      p: parent,
      kids: [],
      cnt: 0,
      profile: node.profile,
    });

    if (parent === null) roots.push(index);
    else nodes[parent]!.kids.push(index);

    for (let k = node.children.length - 1; k >= 0; k -= 1) {
      stack.push({
        node: node.children[k]!,
        parent: index,
        othersBranch: othersBranch || node.children[k]!.segment === OTHERS_LABEL,
      });
    }
  }

  // Subtree page counts, accumulated leaf-upward in one reverse pass. Children
  // always have a higher index than their parent because the walk above is
  // pre-order, which is what makes a single pass sufficient.
  for (let index = nodes.length - 1; index >= 0; index -= 1) {
    const node = nodes[index]!;
    if (node.profile) node.cnt += 1;
    if (node.p !== null) nodes[node.p]!.cnt += node.cnt;
  }

  const laneCounts: [number, number, number, number, number] = [0, 0, 0, 0, 0];
  const methods = new Set<ConsensusMethod>();
  for (const node of nodes) {
    // `lv` is clamped to 0..4 at construction, but `noUncheckedIndexedAccess`
    // cannot know that from the tuple type.
    laneCounts[node.lv] = (laneCounts[node.lv] ?? 0) + 1;
    if (node.profile) methods.add(node.profile.consensus_method);
  }

  return {
    nodes,
    roots,
    index: nodes.map((node) => `${node.label} ${node.url}`.toLowerCase()),
    laneCounts,
    methodsPresent: METHOD_ORDER.filter((method) => methods.has(method)),
  };
}

export const EMPTY_MODEL: DashModel = {
  nodes: [],
  roots: [],
  index: [],
  laneCounts: [0, 0, 0, 0, 0],
  methodsPresent: [],
};
