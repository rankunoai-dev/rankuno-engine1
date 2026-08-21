import { create } from "zustand";
import {
  confidenceBand,
  OTHERS_LANE,
  type ConfidenceBand,
  type DashModel,
  type DashNode,
} from "../lib/dashboardModel";

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

  setModel: (model: DashModel) => void;
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
): boolean {
  if (!laneFilter.has(node.lv)) return false;
  // A structural grouping node has no classification of its own. Hiding it
  // because it has no confidence score would hide the whole branch beneath it.
  if (!node.profile) return true;
  return bandFilter.has(confidenceBand(node.profile));
}

function flatten(
  model: DashModel,
  open: Set<number>,
  laneFilter: Set<number>,
  bandFilter: Set<ConfidenceBand>,
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
    if (!passes(node, laneFilter, bandFilter)) continue;

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

  setModel(model) {
    // Roots open, everything else collapsed. Expanding a 20,000-node tree by
    // default produces a 20,000-row view-model on first paint for a list nobody
    // has scrolled yet.
    const open = new Set(model.roots);
    const bandFilter = new Set<ConfidenceBand>(["high", "review"]);
    const laneFilter = new Set(ALL_LANES);
    set({
      open,
      bandFilter,
      laneFilter,
      childPage: {},
      focus: model.roots[0] ?? null,
      flat: flatten(model, open, laneFilter, bandFilter),
    });
  },

  toggleOpen(index, model) {
    const open = new Set(get().open);
    if (open.has(index)) open.delete(index);
    else open.add(index);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter) });
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
      flat: flatten(model, open, get().laneFilter, get().bandFilter),
    });
  },

  toggleLane(lane, model) {
    const laneFilter = new Set(get().laneFilter);
    if (laneFilter.has(lane)) laneFilter.delete(lane);
    else laneFilter.add(lane);
    set({ laneFilter, flat: flatten(model, get().open, laneFilter, get().bandFilter) });
  },

  toggleBand(band, model) {
    const bandFilter = new Set(get().bandFilter);
    if (bandFilter.has(band)) bandFilter.delete(band);
    else bandFilter.add(band);
    set({ bandFilter, flat: flatten(model, get().open, get().laneFilter, bandFilter) });
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
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter) });
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
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter) });
  },

  expandBranch(index, model) {
    // Merged into the current set rather than replacing it: opening one section
    // in full must not close the others the analyst already opened. That is the
    // difference between this and `expandAll`, which is a whole-tree command.
    const open = new Set(get().open);
    for (const node of subtree(model, index)) open.add(node);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter) });
  },

  collapseBranch(index, model) {
    const open = new Set(get().open);
    for (const node of subtree(model, index)) open.delete(node);
    set({ open, flat: flatten(model, open, get().laneFilter, get().bandFilter) });
  },
}));
