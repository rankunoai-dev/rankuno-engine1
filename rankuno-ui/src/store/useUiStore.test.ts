import { beforeEach, describe, expect, it, vi } from "vitest";
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
      // A one-shot navigation request, not a mode: it names a crawl, never a
      // product, and it is cleared the moment the launcher reads it. Listed
      // here so that anything added beside it has to be argued for.
      "listCrawlSourceJobId",
      "startListCrawl",
      "clearListCrawl",
    ]);
  });

  it("carries a crawl to the Screaming Frog launcher, once, and never stores it", () => {
    /* "Run in Screaming Frog" on a cross-check. The request is consumed by the
       launcher; left standing it would re-arm list mode on every later visit,
       which is a crawl setting the operator chose once. */
    useUiStore.getState().startListCrawl("job-1");

    expect(useUiStore.getState().view).toBe("screaming-frog");
    expect(useUiStore.getState().listCrawlSourceJobId).toBe("job-1");

    useUiStore.getState().clearListCrawl();
    expect(useUiStore.getState().listCrawlSourceJobId).toBeNull();

    // And nothing about it survives a reload: only `view` is written, so a
    // session resumed days later cannot point the launcher at a crawl nobody
    // remembers choosing.
    const stored = window.localStorage.getItem("rankuno.ui");
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored as string)).toEqual({ view: "screaming-frog" });
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

/**
 * Restoring the view across a reload.
 *
 * The reported bug: a reload dropped the operator back on the Launch chooser
 * from wherever they were. The store is read once at module load, so each test
 * here plants storage, resets the module registry and imports a fresh copy —
 * the statically imported store above is a different instance and is not used.
 *
 * Every case that is not a view this build renders must come out as the
 * chooser, because a rail derived from a name nothing renders shows a
 * product's tabs over a broken page.
 */
describe("useUiStore — restoring the view", () => {
  const STORAGE_KEY = "rankuno.ui";

  async function boot(): Promise<typeof useUiStore> {
    vi.resetModules();
    const module = await import("./useUiStore");
    return module.useUiStore;
  }

  beforeEach(() => {
    window.localStorage.clear();
  });

  it("opens on the chooser on a first-ever visit", async () => {
    const store = await boot();

    expect(store.getState().view).toBe("launch");
    expect(store.getState().lastEngineView).toBe("visualizer");
  });

  it("reopens the view the last session left open", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: "audit" }));

    const store = await boot();

    expect(store.getState().view).toBe("audit");
    // Re-derived, never stored: "back to the engine" must not contradict the
    // engine view already on screen.
    expect(store.getState().lastEngineView).toBe("audit");
  });

  it("reopens the other product's view without inventing an engine view", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: "screaming-frog" }));

    const store = await boot();

    expect(store.getState().view).toBe("screaming-frog");
    expect(modeOfView(store.getState().view)).toBe("screaming-frog");
    expect(store.getState().lastEngineView).toBe("visualizer");
  });

  it("falls back to the chooser for a view this build no longer has", async () => {
    /* A name from an older build, or a hand edit. The rail is derived from the
       view, so an unknown name would render a product's tabs beside a page
       that does not exist. */
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: "screaming-frog-legacy" }));

    const store = await boot();

    expect(store.getState().view).toBe("launch");
  });

  it("falls back to the chooser for a value of the wrong type", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: 7 }));

    const store = await boot();

    expect(store.getState().view).toBe("launch");
  });

  it("boots at all when storage is corrupt", async () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json at all");

    const store = await boot();

    expect(store.getState().view).toBe("launch");
  });

  it("boots when the stored payload is not an object", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify("visualizer"));

    const store = await boot();

    expect(store.getState().view).toBe("launch");
  });

  it("writes the view on every navigation, however it was made", async () => {
    const store = await boot();

    store.getState().enterMode("engine");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
      view: "visualizer",
    });

    store.getState().setView("gsc-accounts");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
      view: "gsc-accounts",
    });
  });

  it("stores the view and nothing else", async () => {
    /* No product mode, and nothing identifying. `lastMode` was deleted because
       a mode stored apart from the view could contradict it; the session token
       has its own storage and is not duplicated here. */
    const store = await boot();
    store.getState().setView("jobs");

    const raw = window.localStorage.getItem(STORAGE_KEY) ?? "null";
    expect(Object.keys(JSON.parse(raw) as object)).toEqual(["view"]);
    expect(raw).not.toMatch(/token|org|mode/i);
  });

  it("survives storage being unavailable entirely", async () => {
    /* Private mode, or a full quota. Failing to remember the view is a far
       smaller loss than a rail button that throws. */
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });

    try {
      const store = await boot();
      expect(store.getState().view).toBe("launch");
      expect(() => store.getState().setView("audit")).not.toThrow();
      expect(store.getState().view).toBe("audit");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });
});
