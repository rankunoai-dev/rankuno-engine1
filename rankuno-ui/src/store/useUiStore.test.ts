import { beforeEach, describe, expect, it } from "vitest";
import { modeOfView, selectMode, useUiStore, type RailView } from "./useUiStore";

/**
 * The rail shows one product at a time, so the one invariant that matters is
 * that the mode it renders never names a different product from the page on
 * screen. These pin that, and the "come back to where you were" behaviour.
 */

beforeEach(() => {
  useUiStore.setState({ view: "launch", lastMode: "engine", lastEngineView: "visualizer" });
});

describe("useUiStore", () => {
  it("opens on Launch in engine mode", () => {
    const state = useUiStore.getState();
    expect(state.view).toBe("launch");
    expect(selectMode(state)).toBe("engine");
  });

  it("moves the page off an engine view when Screaming Frog is entered", () => {
    useUiStore.getState().setView("visualizer");
    useUiStore.getState().setView("launch");
    useUiStore.getState().enterMode("screaming-frog");

    const state = useUiStore.getState();
    expect(state.view).toBe("screaming-frog");
    expect(selectMode(state)).toBe("screaming-frog");
  });

  it("returns to the engine view last open, not a fixed default", () => {
    useUiStore.getState().setView("audit");
    useUiStore.getState().enterMode("screaming-frog");
    useUiStore.getState().setView("launch");
    useUiStore.getState().enterMode("engine");

    expect(useUiStore.getState().view).toBe("audit");
  });

  it("follows a jump into an engine view from Screaming Frog mode", () => {
    /* `CrawlNotifier`'s "Open tree" and the header pill call `setView`
       directly. The rail must switch product with the page. */
    useUiStore.getState().enterMode("screaming-frog");
    useUiStore.getState().setView("visualizer");

    expect(selectMode(useUiStore.getState())).toBe("engine");
  });

  it("never lets a stored mode contradict a product view", () => {
    /* A restore (or any direct `setState`) that pairs a view with the other
       product's mode: the view wins, so the rail still matches the page. */
    const views: RailView[] = ["visualizer", "jobs", "audit", "gsc-accounts", "screaming-frog"];
    for (const view of views) {
      for (const lastMode of ["engine", "screaming-frog"] as const) {
        useUiStore.setState({ view, lastMode });
        expect(selectMode(useUiStore.getState())).toBe(modeOfView(view));
      }
    }
  });

  it("uses the stored mode only on Launch, which belongs to neither", () => {
    expect(modeOfView("launch")).toBeNull();
    useUiStore.setState({ view: "launch", lastMode: "screaming-frog" });
    expect(selectMode(useUiStore.getState())).toBe("screaming-frog");
  });
});
