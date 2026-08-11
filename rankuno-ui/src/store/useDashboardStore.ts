import { create } from "zustand";
import type { ConsensusMethod } from "../types/schema";
import { OTHERS_LANE, type DashModel, type DashNode } from "../lib/dashboardModel";

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
  methodFilter: Set<ConsensusMethod>;
  /** Page number per parent, for the focus graph's child pager. */
  childPage: Record<number, number>;
  /** Rebuilt only when the model or a filter changes, never per scroll frame. */
  flat: FlatRow[];

  setModel: (model: DashModel) => void;
  toggleOpen: (index: number, model: DashModel) => void;
  setFocus: (index: number, model: DashModel) => void;
  toggleLane: (lane: number, model: DashModel) => void;
  toggleMethod: (method: ConsensusMethod, model: DashModel) => void;
  nextChildPage: (index: number, total: number) => void;
  expandAll: (model: DashModel, toDepth: number) => void;
  collapseAll: (model: DashModel) => void;
}

function passes(
  node: DashNode,
  laneFilter: Set<number>,
  methodFilter: Set<ConsensusMethod>,
): boolean {
  if (!laneFilter.has(node.lv)) return false;
  // A structural grouping node has no classification of its own. Hiding it
  // because it lacks a consensus method would hide the whole branch beneath it.
  if (!node.profile) return true;
  return methodFilter.has(node.profile.consensus_method);
}

function flatten(
  model: DashModel,
  open: Set<number>,
  laneFilter: Set<number>,
  methodFilter: Set<ConsensusMethod>,
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
    if (!passes(node, laneFilter, methodFilter)) continue;

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
  methodFilter: new Set<ConsensusMethod>(),
  childPage: {},
  flat: [],

  setModel(model) {
    // Roots open, everything else collapsed. Expanding a 20,000-node tree by
    // default produces a 20,000-row view-model on first paint for a list nobody
    // has scrolled yet.
    const open = new Set(model.roots);
    const methodFilter = new Set(model.methodsPresent);
    const laneFilter = new Set(ALL_LANES);
    set({
      open,
      methodFilter,
      laneFilter,
      childPage: {},
      focus: model.roots[0] ?? null,
      flat: flatten(model, open, laneFilter, methodFilter),
    });
  },

  toggleOpen(index, model) {
    const open = new Set(get().open);
    if (open.has(index)) open.delete(index);
    else open.add(index);
    set({ open, flat: flatten(model, open, get().laneFilter, get().methodFilter) });
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
      flat: flatten(model, open, get().laneFilter, get().methodFilter),
    });
  },

  toggleLane(lane, model) {
    const laneFilter = new Set(get().laneFilter);
    if (laneFilter.has(lane)) laneFilter.delete(lane);
    else laneFilter.add(lane);
    set({ laneFilter, flat: flatten(model, get().open, laneFilter, get().methodFilter) });
  },

  toggleMethod(method, model) {
    const methodFilter = new Set(get().methodFilter);
    if (methodFilter.has(method)) methodFilter.delete(method);
    else methodFilter.add(method);
    set({ methodFilter, flat: flatten(model, get().open, get().laneFilter, methodFilter) });
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
    set({ open, flat: flatten(model, open, get().laneFilter, get().methodFilter) });
  },

  collapseAll(model) {
    const open = new Set(model.roots);
    set({ open, flat: flatten(model, open, get().laneFilter, get().methodFilter) });
  },
}));
