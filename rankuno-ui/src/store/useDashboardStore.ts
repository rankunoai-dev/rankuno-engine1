import { create } from "zustand";
import {
  confidenceBand,
  OTHERS_LANE,
  type ConfidenceBand,
  type DashModel,
  type DashNode,
} from "../lib/dashboardModel";
import type { TreeOverlay } from "../lib/treeOverlay";

/** One row of the flattened, filtered view-model the virtual list renders. */
export interface FlatRow {
  i: number;
  depth: number;
}

interface DashboardState {
  /** Expanded node indices. Collapsed by default — see `setModel`. */
  open: Set<number>;
  focus: number | null;
  laneFilter: Set<number>;
  bandFilter: Set<ConfidenceBand>;
  /** Page number per parent, for the focus graph's child pager. */
  childPage: Record<number, number>;
  /** Rebuilt only when the model or a filter changes, never per scroll frame. */
  flat: FlatRow[];

  /**
   * Cross-check and Search Console figures for the current model, or `null`.
   *
   * Held here rather than derived in each component because `flatten` reads
   * it: the "missed only" filter keeps a row when its subtree holds a page
   * Screaming Frog missed, and that count lives on the overlay. Applied only
   * when `overlay.model` is the model being flattened — a new crawl's model
   * arrives before its overlay does, and an old overlay's indices would mark
   * the wrong rows.
   */
  overlay: TreeOverlay | null;
  /** Whether the cross-check marks and counts are drawn. */
  crossCheckOn: boolean;
  /** Show only rows with a Screaming Frog miss somewhere beneath them. */
  missedOnly: boolean;
  /** `engine_only` reasons excluded from the counts. Empty means all count. */
  hiddenReasons: Set<string>;
  /** The whole-screen tree is open. */
  fullScreen: boolean;

  setModel: (model: DashModel) => void;
  setOverlay: (overlay: TreeOverlay | null, model: DashModel) => void;
  toggleCrossCheck: (model: DashModel) => void;
  toggleMissedOnly: (model: DashModel) => void;
  toggleReason: (reason: string) => void;
  setFullScreen: (open: boolean) => void;
  toggleOpen: (index: number, model: DashModel) => void;
  setFocus: (index: number, model: DashModel) => void;
  toggleLane: (lane: number, model: DashModel) => void;
  toggleBand: (band: ConfidenceBand, model: DashModel) => void;
  nextChildPage: (index: number, total: number) => void;
  expandAll: (model: DashModel, toDepth: number) => void;
  collapseAll: (model: DashModel) => void;
  /** Open one node and everything beneath it, however deep. */
  expandBranch: (index: number, model: DashModel) => void;
  /** Close one node and everything beneath it. */
  collapseBranch: (index: number, model: DashModel) => void;
}

/**
 * Every node in the subtree rooted at `index`, including `index` itself.
 *
 * An explicit stack rather than recursion, for the reason `flatten` uses one: a
 * section of a real crawl can nest arbitrarily, and `BLOGS` on gep.com holds
 * 2,937 descendants on its own.
 */
function subtree(model: DashModel, index: number): number[] {
  const found: number[] = [];
  const stack = [index];
  while (stack.length > 0) {
    const current = stack.pop()!;
    found.push(current);
    const node = model.nodes[current];
    if (!node) continue;
    for (const kid of node.kids) stack.push(kid);
  }
  return found;
}

function passes(
  node: DashNode,
  laneFilter: Set<number>,
  bandFilter: Set<ConfidenceBand>,
  missed: Int32Array | null,
): boolean {
  if (!laneFilter.has(node.lv)) return false;
  // Subtree count, not the node's own mark: a section holding a missed page
  // must stay visible or the page beneath it can never be reached.
  if (missed && missed[node.i] === 0) return false;
  // A structural grouping node has no classification of its own. Hiding it
  // because it has no confidence score would hide the whole branch beneath it.
  if (!node.profile) return true;
  return bandFilter.has(confidenceBand(node.profile));
}

/** The miss mask to filter on, or `null` when nothing asks for one. */
function missedMask(state: Pick<DashboardState, "overlay" | "crossCheckOn" | "missedOnly">, model: DashModel): Int32Array | null {
  const { overlay, crossCheckOn, missedOnly } = state;
  if (!crossCheckOn || !missedOnly || !overlay?.crossCheck) return null;
  return overlay.model === model ? overlay.missedCnt : null;
}

function flatten(
  model: DashModel,
  open: Set<number>,
  laneFilter: Set<number>,
  bandFilter: Set<ConfidenceBand>,
  missed: Int32Array | null = null,
): FlatRow[] {
  const rows: FlatRow[] = [];
  // Explicit stack rather than recursion: 20,000 nodes can nest arbitrarily.
  const stack: FlatRow[] = [];
  for (let k = model.roots.length - 1; k >= 0; k -= 1) {
    stack.push({ i: model.roots[k]!, depth: 0 });
  }

  while (stack.length > 0) {
    const row = stack.pop()!;
    const node = model.nodes[row.i]!;
    if (!passes(node, laneFilter, bandFilter, missed)) continue;

    rows.push(row);
    if (!open.has(row.i)) continue;
    for (let k = node.kids.length - 1; k >= 0; k -= 1) {
      stack.push({ i: node.kids[k]!, depth: row.depth + 1 });
    }
  }
  return rows;
}

const ALL_LANES = new Set([0, 1, 2, 3, OTHERS_LANE]);

export const useDashboardStore = create<DashboardState>((set, get) => ({
  open: new Set<number>(),
  focus: null,
  laneFilter: new Set(ALL_LANES),
  bandFilter: new Set<ConfidenceBand>(["high", "review"]),
  childPage: {},
  flat: [],
  overlay: null,
  crossCheckOn: false,
  missedOnly: false,
  hiddenReasons: new Set<string>(),
  fullScreen: false,

  setOverlay(overlay, model) {
    // Re-flattened only when the mask can change what is shown. The overlay
    // arrives on every model rebuild, and most of those have the filter off.
    const before = missedMask(get(), model);
    const after = missedMask({ ...get(), overlay }, model);
    if (before === after) {
      set({ overlay });
      return;
    }
    set({ overlay, flat: flatten(model, get().open, get().laneFilter, get().bandFilter, after) });
  },

  toggleCrossCheck(model) {
    const crossCheckOn = !get().crossCheckOn;
    const next = { ...get(), crossCheckOn };
    set({
      crossCheckOn,
      flat: flatten(model, get().open, get().laneFilter, get().bandFilter, missedMask(next, model)),
    });
  },

  toggleMissedOnly(model) {
    const missedOnly = !get().missedOnly;
    const next = { ...get(), missedOnly };
    set({
      missedOnly,
      flat: flatten(model, get().open, get().laneFilter, get().bandFilter, missedMask(next, model)),
    });
  },

  toggleReason(reason) {
    // Only the set changes here. The overlay's counts depend on it, so the
    // component that builds the overlay rebuilds, and `setOverlay` re-flattens.
    const hiddenReasons = new Set(get().hiddenReasons);
    if (hiddenReasons.has(reason)) hiddenReasons.delete(reason);
    else hiddenReasons.add(reason);
    set({ hiddenReasons });
  },

  setFullScreen(fullScreen) {
    set({ fullScreen });
  },

  setModel(model) {
    // Roots open, everything else collapsed. Expanding a 20,000-node tree by
    // default produces a 20,000-row view-model on first paint for a list nobody
    // has scrolled yet.
    const open = new Set(model.roots);
    const bandFilter = new Set<ConfidenceBand>(["high", "review"]);
    const laneFilter = new Set(ALL_LANES);
    // The toggles survive a job switch; the previous job's overlay does not
    // apply to this model (its indices belong to another tree) and is ignored
    // by `missedMask` until the new one arrives. Nothing to reset here.
    set({
      open,
      bandFilter,
      laneFilter,
      childPage: {},
      focus: model.roots[0] ?? null,
      flat: flatten(model, open, laneFilter, bandFilter, missedMask(get(), model)),
    });
  },

  toggleOpen(index, model) {
    const open = new Set(get().open);
    if (open.has(index)) open.delete(index);
    else open.add(index);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)) });
  },

  setFocus(index, model) {
    // Reveal: every ancestor must be expanded or the row cannot be scrolled to.
    const open = new Set(get().open);
    let parent = model.nodes[index]?.p ?? null;
    while (parent !== null) {
      open.add(parent);
      parent = model.nodes[parent]?.p ?? null;
    }
    set({
      focus: index,
      open,
      flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)),
    });
  },

  toggleLane(lane, model) {
    const laneFilter = new Set(get().laneFilter);
    if (laneFilter.has(lane)) laneFilter.delete(lane);
    else laneFilter.add(lane);
    set({ laneFilter, flat: flatten(model, get().open, laneFilter, get().bandFilter, missedMask(get(), model)) });
  },

  toggleBand(band, model) {
    const bandFilter = new Set(get().bandFilter);
    if (bandFilter.has(band)) bandFilter.delete(band);
    else bandFilter.add(band);
    set({ bandFilter, flat: flatten(model, get().open, get().laneFilter, bandFilter, missedMask(get(), model)) });
  },

  nextChildPage(index, total) {
    const pages = Math.max(1, total);
    set({
      childPage: { ...get().childPage, [index]: ((get().childPage[index] ?? 0) + 1) % pages },
    });
  },

  expandAll(model, toDepth) {
    const open = new Set<number>();
    const stack: FlatRow[] = model.roots.map((i) => ({ i, depth: 0 }));
    while (stack.length > 0) {
      const row = stack.pop()!;
      if (row.depth >= toDepth) continue;
      open.add(row.i);
      for (const kid of model.nodes[row.i]!.kids) {
        stack.push({ i: kid, depth: row.depth + 1 });
      }
    }
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)) });
  },

  collapseAll(model) {
    // Empty, not `new Set(model.roots)`. Seeding the roots left every top-level
    // tab expanded, so "Collapse all" on highradius still showed About Us,
    // Customers and Partners open and the analyst closed them by hand — the
    // one thing the button exists to save.
    //
    // The tree cannot collapse to nothing: `flatten` always emits the roots and
    // only descends into open nodes, so an empty set renders exactly the top
    // level, closed. That is what makes this safe, and it is why the seeding
    // was never needed.
    //
    // `setModel` still opens the roots on load. A first paint showing only
    // closed tabs hides the site behind a click; collapsing is a thing the
    // analyst asks for.
    const open = new Set<number>();
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)) });
  },

  expandBranch(index, model) {
    // Merged into the current set rather than replacing it: opening one section
    // in full must not close the others the analyst already opened. That is the
    // difference between this and `expandAll`, which is a whole-tree command.
    const open = new Set(get().open);
    for (const node of subtree(model, index)) open.add(node);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)) });
  },

  collapseBranch(index, model) {
    const open = new Set(get().open);
    for (const node of subtree(model, index)) open.delete(node);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter, missedMask(get(), model)) });
  },
}));
