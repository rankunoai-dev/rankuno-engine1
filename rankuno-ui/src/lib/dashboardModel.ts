import type { SavedReconciliation } from "../adapters/adapterInterface";
import type {
  ConsensusMethod,
  FullPageIntelligenceProfile,
  HierarchyLevel,
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
  /**
   * What placed this node, accumulated over its whole subtree.
   *
   * A page carries its own `trail_source`. A grouping node has no profile, so
   * it inherits the consensus of the pages beneath it — and `mixed` when they
   * disagree, which is itself worth seeing: a section built partly from the
   * header menu and partly from breadcrumbs is a section whose shape depends on
   * which pages a crawl happened to fetch.
   */
  src: TrailSourceTag;
  /**
   * What kind of row this is.
   *
   * `"page"` and `"group"` are the two kinds every model has always had,
   * distinguished before this field existed by `profile` being set or not —
   * that test still holds for both. `"defaulter"` is new: a bare-list
   * `UNKNOWN` URL quarantined under the "Defaulter / Quarantine" root, with no
   * profile because this engine never crawled it and no evidence beyond the
   * URL's own shape (see `DefaulterCategory` in the reconciler module).
   */
  kind: "page" | "group" | "defaulter";
  /** Set only when `kind` is `"defaulter"`, mirroring `DefaulterCategory`. */
  defaulterCategory?: string;
}

/** `trail_source` plus the value only a grouping node can hold. */
export type TrailSourceTag = "menu" | "breadcrumb" | "mixed" | "none";

export interface DashModel {
  nodes: DashNode[];
  roots: number[];
  /** Lowercased `label + url` per node, for substring search. */
  index: string[];
  /**
   * Counts per lane, 0–3 then OTHERS, then `DEFAULTER_LANE` when defaulters
   * were built.
   *
   * A plain array rather than the fixed 5-tuple this used to be: the sixth
   * slot exists only when `buildDashModel` was called with
   * `includeDefaulters: true` and the reconciliation actually held a
   * quarantined URL, so the length itself carries a fact. With the flag off
   * (the default) this is exactly the 5-element array it always was, value for
   * value — every existing reader indexes it with `?.`, already tolerant of a
   * shorter array under `noUncheckedIndexedAccess`.
   */
  laneCounts: number[];
  /** Pages per confidence band, for the filter chips. */
  bandCounts: Record<ConfidenceBand, number>;
  /**
   * Whether this crawl recorded placement provenance at all.
   *
   * False for every result written before `trail_source` existed, and those are
   * still loadable from `.jobs/`. The distinction is not cosmetic: without it
   * each of highradius' 114 sections renders as "Not placed", which reads as a
   * finding about the site when it is a fact about the file. Badges are hidden
   * and the provenance ordering is skipped rather than asserting an absence the
   * crawl never measured.
   */
  hasProvenance: boolean;
}

/**
 * A page's placement provenance, read defensively.
 *
 * `trail_source` is required by the generated contract, but every crawl stored
 * before it existed lacks the field entirely, and those results are still
 * loadable from `.jobs/`. Reading it through the type alone would put
 * `undefined` behind a non-optional string and render an empty badge on every
 * historical crawl.
 */
export function trailSourceOf(profile: FullPageIntelligenceProfile): TrailSourceTag {
  const raw = (profile as { trail_source?: string }).trail_source;
  return raw === "menu" || raw === "breadcrumb" ? raw : "none";
}

const SRC_RANK: Record<TrailSourceTag, number> = {
  menu: 0,
  mixed: 1,
  breadcrumb: 2,
  none: 3,
};

/**
 * Sort key for a top-level section.
 *
 * `OTHERS` is pinned below even the other unplaced sections. Its own `src` is
 * `none`, so ranking on that alone would sort it alphabetically among them and
 * it would stop being last — and it is the residue, not a section. `navTree`
 * makes the same exception for the same reason.
 */
function rootRank(node: DashNode): number {
  return node.label === OTHERS_LABEL ? 4 : SRC_RANK[node.src];
}

/** Two sources agree, or they do not. `none` is absence, so it never conflicts. */
function merge(a: TrailSourceTag, b: TrailSourceTag): TrailSourceTag {
  if (a === b) return a;
  if (a === "none") return b;
  if (b === "none") return a;
  return "mixed";
}

export const TRAIL_SOURCE_BADGE: Record<TrailSourceTag, string> = {
  menu: "Header Menu",
  breadcrumb: "Published Breadcrumbs",
  mixed: "Menu + Breadcrumbs",
  none: "Not placed",
};

/**
 * Why a page sits where it does, in words a client can check against the site.
 *
 * Phrased as evidence and its limits rather than as a verdict. The two sources
 * fail differently and an analyst has to know which one they are arguing with:
 * a menu path is wrong for the whole site at once, a breadcrumb is wrong one
 * page at a time.
 */
export const TRAIL_SOURCE_REASON: Record<TrailSourceTag, string> = {
  menu:
    "The site's header menu links to this page from this section. The menu is read " +
    "once from the homepage, so this placement is the same on every crawl and is the " +
    "route a visitor actually has.",
  breadcrumb:
    "This page publishes its own breadcrumb saying it sits here. It was read from this " +
    "page alone, so pages in the same folder can and sometimes do disagree — the header " +
    "menu does not reach this page.",
  mixed:
    "Some pages in this section were placed by the header menu and others by their own " +
    "breadcrumbs. The section is real, but its exact shape depends on which pages the " +
    "crawl reached.",
  none:
    "Neither the header menu nor a breadcrumb on the page places this URL. Nothing on " +
    "the site says where it belongs, which is why it sits under OTHERS.",
};

export const OTHERS_LANE = 4;

/**
 * The lane the "Defaulter / Quarantine" subtree renders in.
 *
 * One past `OTHERS_LANE` rather than folded into it: OTHERS is "reachable by
 * no navigation path" — pages this engine crawled and classified but could not
 * place. A defaulter is the opposite kind of unknown — a URL this engine never
 * crawled at all, from a list weaker than a status export — and merging the
 * two lanes would let a defaulter's raw count read as a navigation gap.
 */
export const DEFAULTER_LANE = 5;

/** The synthetic root every quarantined URL is built under. */
export const QUARANTINE_ROOT_LABEL = "Defaulter / Quarantine";

/**
 * Short, analyst-facing names for `DefaulterCategory`, for the group label
 * under the quarantine root. Mirrors the meanings in
 * `src/api/server.py::GAP_MEANINGS`, shortened for a tree row rather than a
 * spreadsheet cell.
 */
export const DEFAULTER_CATEGORY_LABELS: Record<string, string> = {
  DAM_HTML_ARCHIVE: "DAM archive (investors)",
  DAM_FORMS_OTHER: "DAM archive (other)",
  CMS_INTERNAL_LEAK: "CMS internal path leak",
  CORRUPTED_URL: "Malformed URL",
};

/**
 * Confidence at or above which a classification is treated as settled.
 *
 * The same threshold the inspector already used to colour its confidence value,
 * lifted here so the filter and the readout cannot disagree about what "high"
 * means.
 */
export const CONFIDENCE_THRESHOLD = 0.85;

export type ConfidenceBand = "high" | "review";

/**
 * Which band a page falls in.
 *
 * This replaced a filter on `consensus_method` — the cascade layer that
 * resolved the page. That is an engine internal: it tells an analyst which code
 * path ran, not whether the answer can be trusted. Two of its four values could
 * never appear at all, because Layers 2 and 3 have no implementation, so the
 * control offered chips that could only ever filter to nothing.
 */
export function confidenceBand(profile: FullPageIntelligenceProfile): ConfidenceBand {
  return profile.final_confidence_score >= CONFIDENCE_THRESHOLD ? "high" : "review";
}

export const BAND_LABELS: Record<ConfidenceBand, string> = {
  high: "High confidence",
  review: "Needs review",
};

/**
 * Whether a result has any published structure to group by.
 *
 * True when a header menu was parsed, or when any page carries its own
 * breadcrumb trail. The second half is what makes the structural view work on
 * sites whose menu cannot be read — a Shopify storefront publishes no parseable
 * menu and a breadcrumb on every product page.
 *
 * Scans until it finds one rather than counting: at 20,000 pages this runs on
 * every model rebuild, and the answer is a boolean.
 */
export function hasStructure(result: PageClassificationOutput): boolean {
  if ((result.navigation?.roots.length ?? 0) > 0) return true;
  return result.pages.some((page) => page.breadcrumb_path.length > 0);
}

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
 * Lane descriptions for a tree built from URL paths rather than a menu.
 *
 * The navigation wording above is a *claim*, and in path mode it is false: a
 * lane number there is how many slashes are in the URL, and nothing about the
 * site's menu. Saying "top navigation tab" over a flat site put every
 * single-segment URL — `/about`, `/contact-sales`, `/api-scale-tier` — under a
 * label asserting it was a top-level navigation tab, when the engine had in
 * fact classified 1,569 of openai.com's 1,575 pages as `L3_LEAF_PAGE`.
 */
export const PATH_LANE_DESCRIPTIONS = [
  "Path depth 0 · one URL segment",
  "Path depth 1 · two URL segments",
  "Path depth 2 · three URL segments",
  "Path depth 3+ · four or more URL segments",
  "OTHERS · reachable by no navigation path",
] as const;

/**
 * The engine's own classification, as a short badge.
 *
 * Distinct from the lane. A lane says *where this node sits in the tree on
 * screen*; this says *what the engine decided the page is*. They coincide when
 * a header menu was parsed and diverge sharply when one was not — which is
 * exactly when showing only the lane misleads, because the lane then carries
 * URL-path depth while looking like a classification.
 */
export const LEVEL_BADGE: Record<HierarchyLevel, { label: string; lane: number }> = {
  L0_HOMEPAGE: { label: "L0", lane: 0 },
  L1_PRIMARY_NAV_HUB: { label: "L1", lane: 1 },
  L2_SUB_NAV_HUB: { label: "L2", lane: 2 },
  L3_LEAF_PAGE: { label: "L3", lane: 3 },
  UTILITY_PAGE: { label: "UTIL", lane: 4 },
};

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
 *
 * @param reconciliation - The saved Screaming Frog cross-check, or `null`.
 *   Read only when `includeDefaulters` is true; every other call site can omit
 *   it.
 * @param includeDefaulters - Build the "Defaulter / Quarantine" subtree from
 *   `reconciliation.frog_only`'s categorised bare-list rows. Defaults to
 *   `false`, in which case no defaulter node is constructed at all — not
 *   merely hidden — so `laneCounts`, `index` and every node count are
 *   identical to what this function has always returned.
 */
export function buildDashModel(
  result: PageClassificationOutput,
  grouping: "navigation" | "path",
  reconciliation: SavedReconciliation | null = null,
  includeDefaulters = false,
): DashModel {
  // Gated on the pages actually carrying a trail, not on the menu having been
  // parsed. A page's own breadcrumb now fills `breadcrumb_path` too, so a site
  // with breadcrumbs and an unreadable menu — a Shopify storefront, a React
  // marketing site — has real structure to group by even though `navigation`
  // is empty. Keying this off `navigation.roots` discarded it.
  const useNav = grouping === "navigation" && hasStructure(result);
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
      src: node.profile ? trailSourceOf(node.profile) : "none",
      kind: node.profile ? "page" : "group",
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
    if (node.p !== null) {
      const parent = nodes[node.p]!;
      parent.cnt += node.cnt;
      // Same reverse pass as the counts, for the same reason: children always
      // hold a higher index than their parent, so one pass settles the whole
      // tree. A grouping node starts at `none` and takes the first real source
      // it sees, then degrades to `mixed` on the first disagreement.
      parent.src = merge(parent.src, node.src);
    }
  }

  // Top-level sections ordered by the strength of the evidence that built them:
  // header menu, then menu-and-breadcrumb, then breadcrumb alone, then whatever
  // nothing placed. A reader works down the tree in one direction and the
  // confidence only ever decreases, instead of a menu-backed section and a
  // single self-published page sitting side by side as apparent equals.
  //
  // Sorted here rather than in `navTree`, which orders every level: `src` is not
  // known until the pass above has walked the whole subtree. Only the roots are
  // reordered — inside a section, alphabetical order is what makes a named
  // section scannable, and regrouping it by provenance would scatter it.
  //
  // The sort is stable, so sections sharing a source keep the alphabetical order
  // `navTree` gave them.
  const hasProvenance = result.pages.some((page) => "trail_source" in page);
  if (hasProvenance) {
    roots.sort((a, b) => rootRank(nodes[a]!) - rootRank(nodes[b]!));
  }

  // Appended after the sort, never inside it: the quarantine root has no
  // `trail_source` of its own to rank by, and always belongs last regardless
  // of whether this result carries provenance at all.
  if (includeDefaulters && reconciliation) {
    buildDefaulterSubtree(nodes, roots, reconciliation);
  }

  const laneCounts: number[] = [0, 0, 0, 0, 0];
  const bandCounts: Record<ConfidenceBand, number> = { high: 0, review: 0 };
  for (const node of nodes) {
    // `lv` is clamped to 0..5 at construction, but `noUncheckedIndexedAccess`
    // cannot know that from the array type.
    laneCounts[node.lv] = (laneCounts[node.lv] ?? 0) + 1;
    if (node.profile) bandCounts[confidenceBand(node.profile)] += 1;
  }

  return {
    nodes,
    roots,
    index: nodes.map((node) => `${node.label} ${node.url}`.toLowerCase()),
    laneCounts,
    bandCounts,
    hasProvenance,
  };
}

/**
 * Append the "Defaulter / Quarantine" subtree to an already-built model.
 *
 * Every bare-list `UNKNOWN` row that matched a `DefaulterCategory` pattern —
 * an AEM asset path, a leaked author path, a malformed address — becomes one
 * leaf here, grouped under its category. The presumed-real residual (a
 * bare-list row with no category) is deliberately excluded: it is the Excel
 * report's and the GSC revalidation's concern, not this quarantine view's —
 * folding it in would bury the URLs this feature exists to isolate under a
 * bucket the pattern match could not actually justify hiding.
 *
 * Mutates `nodes` and `roots` in place rather than returning new arrays,
 * matching how the rest of `buildDashModel` grows the same two arrays through
 * its own construction loop.
 */
function buildDefaulterSubtree(
  nodes: DashNode[],
  roots: number[],
  reconciliation: SavedReconciliation,
): void {
  const byCategory = new Map<string, string[]>();
  for (const gap of reconciliation.frog_only) {
    const category = gap.defaulter_category;
    if (!category) continue;
    const urls = byCategory.get(category);
    if (urls) urls.push(gap.url);
    else byCategory.set(category, [gap.url]);
  }
  if (byCategory.size === 0) return;

  const quarantineRoot = nodes.length;
  nodes.push({
    i: quarantineRoot,
    lv: DEFAULTER_LANE,
    label: QUARANTINE_ROOT_LABEL,
    url: "",
    p: null,
    kids: [],
    cnt: 0,
    profile: null,
    src: "none",
    kind: "group",
  });
  roots.push(quarantineRoot);

  // Sorted so two builds of the same sidecar produce the same tree — the same
  // reason `reconcile` itself sorts `frog_only` before writing it.
  for (const category of [...byCategory.keys()].sort()) {
    const urls = byCategory.get(category)!;
    const groupIndex = nodes.length;
    nodes.push({
      i: groupIndex,
      lv: DEFAULTER_LANE,
      label: DEFAULTER_CATEGORY_LABELS[category] ?? category,
      url: "",
      p: quarantineRoot,
      kids: [],
      cnt: 0,
      profile: null,
      src: "none",
      kind: "group",
    });
    nodes[quarantineRoot]!.kids.push(groupIndex);

    for (const url of [...urls].sort()) {
      const leafIndex = nodes.length;
      nodes.push({
        i: leafIndex,
        lv: DEFAULTER_LANE,
        label: url,
        url,
        p: groupIndex,
        kids: [],
        cnt: 1,
        profile: null,
        src: "none",
        kind: "defaulter",
        defaulterCategory: category,
      });
      nodes[groupIndex]!.kids.push(leafIndex);
    }
    nodes[groupIndex]!.cnt = urls.length;
    nodes[quarantineRoot]!.cnt += urls.length;
  }
}

export const EMPTY_MODEL: DashModel = {
  nodes: [],
  roots: [],
  index: [],
  // No crawl loaded, so nothing to claim either way. Nothing renders from this
  // model anyway; `false` is the value that asserts least.
  hasProvenance: false,
  laneCounts: [0, 0, 0, 0, 0],
  bandCounts: { high: 0, review: 0 },
};
