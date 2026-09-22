import { create } from "zustand";

/** Which rail destination is on screen. */
export type RailView =
  | "launch"
  | "visualizer"
  | "jobs"
  | "audit"
  | "gsc-accounts"
  | "screaming-frog";

/**
 * Which product the operator is working in.
 *
 * The engine and Screaming Frog are separate tools with separate job systems;
 * the rail shows one product's destinations at a time so that neither is read
 * as part of the other.
 */
export type ProductMode = "engine" | "screaming-frog";

/** The views that belong to the engine, in rail order. */
export type EngineView = Exclude<RailView, "launch" | "screaming-frog">;

interface UiState {
  view: RailView;
  /**
   * The product last chosen. Consulted *only* while `view` is `launch`, which
   * belongs to neither product; everywhere else the mode is derived from the
   * view by `selectMode`, so the two cannot disagree.
   */
  lastMode: ProductMode;
  /** Where "back to the engine" lands, instead of always the visualizer. */
  lastEngineView: EngineView;
  setView: (view: RailView) => void;
  /** Enter a product from the Launch screen, landing on its main view. */
  enterMode: (mode: ProductMode) => void;
}

/** The product a view belongs to, or `null` for Launch, which is shared. */
export function modeOfView(view: RailView): ProductMode | null {
  if (view === "launch") return null;
  return view === "screaming-frog" ? "screaming-frog" : "engine";
}

/**
 * The mode the rail and header should render.
 *
 * Derived from the view whenever the view names a product. `lastMode` is only
 * the tie-breaker for Launch. Storing the mode as an independent field would
 * let any `setState({ view })` — or a future persisted restore — produce a rail
 * showing one product over a page from the other.
 */
export function selectMode(state: Pick<UiState, "view" | "lastMode">): ProductMode {
  return modeOfView(state.view) ?? state.lastMode;
}

/*
 * Rail navigation, kept out of the other two stores on purpose.
 *
 * `useDashboardStore` holds the derived tree view-model, which is rebuilt from
 * a 20,000-node walk. Putting the current tab in there would make every
 * subscriber to that store re-render on a tab change, which is precisely the
 * coupling the crawl/dashboard split was introduced to avoid.
 *
 * No router: there is one window, a handful of destinations, and no URLs to be
 * deep linked to. A router would add a dependency and a build step to express
 * an enum.
 *
 * Not persisted: a reload always opens on Launch. If persistence is added,
 * persist `view` and `lastMode` together — `selectMode` keeps a restored view
 * authoritative over a restored mode, so the pair cannot contradict.
 *
 * `launch` is the opening view rather than `visualizer`. A session starts with
 * nothing loaded, and the visualizer's answer to that was one line of grey text
 * — which left "how do I start a crawl?" answered only by a button in the
 * header. The two crawlers are also genuinely different tools with separate job
 * systems, and a screen that names both is what keeps that distinction visible
 * instead of hidden behind one ambiguous "New crawl".
 *
 * The opening mode is `engine`, not "none". In fixture mode both Launch cards
 * are disabled, so a Launch-only rail would leave the bundled results
 * unreachable; and the engine is what the rest of this dashboard is built on.
 */
export const useUiStore = create<UiState>((set) => ({
  view: "launch",
  lastMode: "engine",
  lastEngineView: "visualizer",
  setView: (view) =>
    set(() => {
      // Launch belongs to neither product, so it leaves the mode where it was.
      if (view === "launch") return { view };
      if (view === "screaming-frog") return { view, lastMode: "screaming-frog" };
      return { view, lastMode: "engine", lastEngineView: view };
    }),
  enterMode: (mode) =>
    set((state) => ({
      lastMode: mode,
      view: mode === "engine" ? state.lastEngineView : "screaming-frog",
    })),
}));
