import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import indexHtml from "../../index.html?raw";
import { THEME_STORAGE_KEY } from "./useThemeStore";

/**
 * The inline script in index.html sets the theme before first paint, outside the
 * bundle, so it cannot import the store's rules. It is a second implementation
 * of them; this runs the real script text against the same situations the store
 * is tested for, so the two cannot drift apart unnoticed.
 */

function prepaintSource(): string {
  const match = /<script>([\s\S]*?)<\/script>/.exec(indexHtml);
  if (!match?.[1]) throw new Error("no inline script in index.html");
  return match[1];
}

function run(): string | null {
  // eslint-disable-next-line no-new-func -- evaluating the shipped script text is the point
  new Function(prepaintSource())();
  return document.documentElement.getAttribute("data-theme");
}

const realMatchMedia = window.matchMedia;

function prefersDark(dark: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: dark,
    media: query,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
});

describe("index.html pre-paint theme script", () => {
  it("reads the same storage key as the store", () => {
    expect(prepaintSource()).toContain(`"${THEME_STORAGE_KEY}"`);
  });

  it("runs before the stylesheet and the bundle", () => {
    expect(indexHtml.indexOf("<script>")).toBeLessThan(indexHtml.indexOf("fonts.googleapis"));
    expect(indexHtml.indexOf("<script>")).toBeLessThan(indexHtml.indexOf("/src/main.tsx"));
  });

  it("follows the OS with nothing stored", () => {
    prefersDark(true);
    expect(run()).toBe("dark");
    prefersDark(false);
    expect(run()).toBe("light");
  });

  it("prefers the stored choice", () => {
    prefersDark(true);
    window.localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ theme: "light" }));
    expect(run()).toBe("light");
  });

  it.each(["{nope", JSON.stringify({ theme: "sepia" }), JSON.stringify(["dark"]), "null"])(
    "ignores a stored value of the wrong shape (%s)",
    (raw) => {
      prefersDark(true);
      window.localStorage.setItem(THEME_STORAGE_KEY, raw);
      expect(run()).toBe("dark");
    },
  );

  it("keeps the OS preference when storage throws", () => {
    prefersDark(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(run()).toBe("dark");
  });

  it("falls back to light when matchMedia throws", () => {
    window.matchMedia = (() => {
      throw new Error("no matchMedia");
    }) as unknown as typeof window.matchMedia;
    expect(run()).toBe("light");
  });
});
