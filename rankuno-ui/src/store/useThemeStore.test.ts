import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The theme store.
 *
 * It reads `localStorage` and `matchMedia` once, at import, so each test that
 * cares about the starting point re-imports the module against a prepared
 * environment instead of poking the live store.
 */

const KEY = "rankuno.theme";
const realMatchMedia = window.matchMedia;

function prefersDark(dark: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: dark && query.includes("prefers-color-scheme: dark"),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

async function freshStore() {
  vi.resetModules();
  return import("./useThemeStore");
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
});

describe("useThemeStore initial theme", () => {
  it("follows the OS on a first visit (light)", async () => {
    prefersDark(false);
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("follows the OS on a first visit (dark)", async () => {
    prefersDark(true);
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("writes nothing to storage until the operator chooses", async () => {
    prefersDark(true);
    await freshStore();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("prefers the stored choice over the OS", async () => {
    prefersDark(true);
    window.localStorage.setItem(KEY, JSON.stringify({ theme: "light" }));
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it.each([
    ["not JSON", "{nope"],
    ["JSON of the wrong shape", JSON.stringify(["dark"])],
    ["an unknown theme name", JSON.stringify({ theme: "sepia" })],
    ["a non-string theme", JSON.stringify({ theme: 1 })],
    ["null", "null"],
  ])("ignores a stored value that is %s", async (_label, raw) => {
    prefersDark(true);
    window.localStorage.setItem(KEY, raw);
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("falls back to the OS when reading storage throws", async () => {
    prefersDark(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("falls back to light when matchMedia throws", async () => {
    window.matchMedia = (() => {
      throw new Error("no matchMedia");
    }) as unknown as typeof window.matchMedia;
    const { useThemeStore } = await freshStore();
    expect(useThemeStore.getState().theme).toBe("light");
  });
});

describe("useThemeStore changes", () => {
  it("toggles, applies the attribute and persists", async () => {
    prefersDark(false);
    const { useThemeStore } = await freshStore();

    useThemeStore.getState().toggleTheme();

    expect(useThemeStore.getState().theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "null")).toEqual({ theme: "dark" });

    useThemeStore.getState().toggleTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "null")).toEqual({ theme: "light" });
  });

  it("restores the persisted choice on the next load", async () => {
    prefersDark(false);
    const first = await freshStore();
    first.useThemeStore.getState().setTheme("dark");

    const second = await freshStore();
    expect(second.useThemeStore.getState().theme).toBe("dark");
  });

  it("still switches when writing storage throws", async () => {
    prefersDark(false);
    const { useThemeStore } = await freshStore();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    expect(() => useThemeStore.getState().setTheme("dark")).not.toThrow();
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
