import { beforeEach, describe, expect, it } from "vitest";
import { modeOfView, useUiStore, type RailView } from "./useUiStore";

/**
 * The rail and header show one product at a time, so the one invariant that
 * matters is that the product they render never differs from the page on
 * screen. `modeOfView` is the whole of that answer: these pin that nothing
 * else is consulted, and the "come back to where you were" behaviour.
 */

beforeEach(() => {
  useUiStore.setState({ view: "launch", lastEngineView: "visualizer" });
});

describe("useUiStore", () => {
  it("opens on Launch, which belongs to neither product", () => {
    const state = useUiStore.getState();
    expect(state.view).toBe("launch");
    expect(modeOfView(state.view)).toBeNull();
  });

  it("moves the page off an engine view when Screaming Frog is entered", () => {
    useUiStore.getState().setView("visualizer");
    useUiStore.getState().setView("launch");
    useUiStore.getState().enterMode("screaming-frog");

    const state = useUiStore.getState();
    expect(state.view).toBe("screaming-frog");
    expect(modeOfView(state.view)).toBe("screaming-frog");
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

    expect(modeOfView(useUiStore.getState().view)).toBe("engine");
  });

  it("stores no product mode that a view could contradict", () => {
    /* The regression this store used to carry: a `lastMode` field, settable
       independently of the view, which answered for Launch with whatever was
       used last and so put the engine's tabs on the chooser. There is nothing
       to restore, persist or set out of step with the view any more. */
    expect(Object.keys(useUiStore.getState())).toEqual([
      "view",
      "lastEngineView",
      "setView",
      "enterMode",
    ]);
  });

  it("neither product answers for Launch, however it was reached", () => {
    expect(modeOfView("launch")).toBeNull();

    for (const view of ["visualizer", "jobs", "audit", "gsc-accounts", "screaming-frog"] as const) {
      useUiStore.getState().setView(view);
      useUiStore.getState().setView("launch");
      expect(modeOfView(useUiStore.getState().view)).toBeNull();
    }
  });

  it("names the product of every view that has one", () => {
    const engine: RailView[] = ["visualizer", "jobs", "audit", "gsc-accounts"];
    for (const view of engine) expect(modeOfView(view)).toBe("engine");
    expect(modeOfView("screaming-frog")).toBe("screaming-frog");
  });

  it("never remembers Launch or Screaming Frog as the engine view to return to", () => {
    useUiStore.getState().setView("gsc-accounts");
    useUiStore.getState().setView("screaming-frog");
    useUiStore.getState().setView("launch");

    expect(useUiStore.getState().lastEngineView).toBe("gsc-accounts");
  });
});
