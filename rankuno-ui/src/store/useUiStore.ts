import { create } from "zustand";

/** Which rail destination is on screen. */
export type RailView = "visualizer" | "jobs";

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
 * No router: there is one window, two destinations, and no URLs to be deep
 * linked to. A router would add a dependency and a build step to express a
 * boolean.
 */
export const useUiStore = create<UiState>((set) => ({
  view: "visualizer",
  setView: (view) => set({ view }),
}));
