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
  /** Where "back to the engine" lands, instead of always the visualizer. */
  lastEngineView: EngineView;
  setView: (view: RailView) => void;
  /** Enter a product from the Launch screen, landing on its main view. */
  enterMode: (mode: ProductMode) => void;
}

/**
 * The product a view belongs to, or `null` for Launch, which is shared.
 *
 * The only source of truth for "which product is on screen". There is
 * deliberately no stored mode beside it: a mode field that could be set
 * independently of the view is what put the engine's rail and header over the
 * Launch chooser, because Launch belongs to neither product and the stored
 * value answered for it.
 */
export function modeOfView(view: RailView): ProductMode | null {
  if (view === "launch") return null;
  return view === "screaming-frog" ? "screaming-frog" : "engine";
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
 * persist `view` alone — every piece of product chrome derives from it through
 * `modeOfView`, so there is no second field a restore could contradict.
 *
 * `launch` is the opening view rather than `visualizer`. A session starts with
 * nothing loaded, and the visualizer's answer to that was one line of grey text
 * — which left "how do I start a crawl?" answered only by a button in the
 * header. The two crawlers are also genuinely different tools with separate job
 * systems, and a screen that names both is what keeps that distinction visible
 * instead of hidden behind one ambiguous "New crawl".
 *
 * Launch shows no product's destinations at all. It used to fall back to the
 * last product used, which put the engine's five tabs on the chooser; the way
 * into the engine without starting a crawl is now a control on the engine card
 * itself, so a rail that shows nothing strands nobody — including in fixture
 * mode, where no crawl can be started but the bundled results still open.
 */
export const useUiStore = create<UiState>((set) => ({
  view: "launch",
  lastEngineView: "visualizer",
  setView: (view) =>
    set(() => {
      // Only an engine view is remembered: "back to the engine" must never
      // land on Launch or on the other product.
      if (view === "launch" || view === "screaming-frog") return { view };
      return { view, lastEngineView: view };
    }),
  enterMode: (mode) =>
    set((state) => ({
      view: mode === "engine" ? state.lastEngineView : "screaming-frog",
    })),
}));
