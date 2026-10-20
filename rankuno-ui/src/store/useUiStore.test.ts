import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "./useAuthStore";
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
 * Both stores, freshly loaded into one module registry.
 *
 * The restore runs at module load, and the sign-in subscription needs the auth
 * store to be the same instance the UI store imported, so both are reset and
 * imported together rather than one of them from the static import above.
 */
async function bootBoth(): Promise<{
  ui: typeof useUiStore;
  auth: typeof useAuthStore;
}> {
  vi.resetModules();
  const ui = await import("./useUiStore");
  const auth = await import("./useAuthStore");
  return { ui: ui.useUiStore, auth: auth.useAuthStore };
}

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
    const { ui } = await bootBoth();
    return ui;
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

  it("reopens the stored view on a reload while still signed in", async () => {
    /* A reload inside one session is the case the restore exists for. The
       session is restored from its own key, and no sign-in happens, so the
       view must survive the module load untouched. */
    window.localStorage.setItem(
      "rankuno.auth",
      JSON.stringify({ token: "restored", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" }),
    );
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: "audit" }));

    const { ui, auth } = await bootBoth();

    expect(auth.getState().token).toBe("restored");
    expect(ui.getState().view).toBe("audit");
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

/**
 * The view across sign-in and sign-out.
 *
 * A reload keeps the view; a new sign-in does not. Both are driven through the
 * real `login` and `logout` actions, with `fetch` stubbed, so the subscription
 * is exercised on the transitions it actually sees rather than on a state write.
 */
describe("useUiStore — the view across sign-in and sign-out", () => {
  const UI_KEY = "rankuno.ui";
  const fetchMock = vi.fn();

  function loginResponse(): Response {
    return new Response(
      JSON.stringify({
        token: "session-token",
        token_type: "bearer",
        org_id: "acme",
        expires_at: "2099-01-01T00:00:00Z",
      }),
      { status: 200 },
    );
  }

  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lands on Launch after a fresh sign-in, whatever view was stored", async () => {
    window.localStorage.setItem(UI_KEY, JSON.stringify({ view: "visualizer" }));
    const { ui, auth } = await bootBoth();
    // The restore still happens at load: the reload behaviour is unchanged.
    expect(ui.getState().view).toBe("visualizer");

    fetchMock.mockResolvedValueOnce(loginResponse());
    await expect(auth.getState().login("op-1", "correct-horse")).resolves.toBe(true);

    expect(ui.getState().view).toBe("launch");
    expect(modeOfView(ui.getState().view)).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(UI_KEY) ?? "null")).toEqual({ view: "launch" });
  });

  it("lands on Launch after sign-out then sign-in in the same tab", async () => {
    const { ui, auth } = await bootBoth();
    fetchMock.mockResolvedValueOnce(loginResponse());
    await auth.getState().login("op-1", "correct-horse");
    ui.getState().setView("audit");
    expect(JSON.parse(window.localStorage.getItem(UI_KEY) ?? "null")).toEqual({ view: "audit" });

    auth.getState().logout();
    expect(window.localStorage.getItem(UI_KEY)).toBeNull();

    fetchMock.mockResolvedValueOnce(loginResponse());
    await auth.getState().login("op-1", "correct-horse");
    expect(ui.getState().view).toBe("launch");
    expect(ui.getState().lastEngineView).toBe("visualizer");
  });

  it("does not reset the view when a token is written directly", async () => {
    /* The reason a sign-in is keyed on `signedInAt` and not on `token`: a
       direct write is not a new start, and the rail must not jump under the
       operator while a test or a restore sets the session. */
    const { ui, auth } = await bootBoth();
    ui.getState().setView("jobs");

    auth.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });

    expect(ui.getState().view).toBe("jobs");
  });
});
