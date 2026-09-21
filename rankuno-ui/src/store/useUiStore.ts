import { create } from "zustand";

/** Which rail destination is on screen. */
export type RailView =
  | "launch"
  | "visualizer"
  | "jobs"
  | "audit"
  | "gsc-accounts"
  | "screaming-frog";

interface UiState {
  view: RailView;
  setView: (view: RailView) => void;
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
 * `launch` is the opening view rather than `visualizer`. A session starts with
 * nothing loaded, and the visualizer's answer to that was one line of grey text
 * — which left "how do I start a crawl?" answered only by a button in the
 * header. The two crawlers are also genuinely different tools with separate job
 * systems, and a screen that names both is what keeps that distinction visible
 * instead of hidden behind one ambiguous "New crawl".
 */
export const useUiStore = create<UiState>((set) => ({
  view: "launch",
  setView: (view) => set({ view }),
}));
