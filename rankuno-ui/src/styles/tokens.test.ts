/**
 * Holds `tokens.ts` to `design-system.css`.
 *
 * The palette is duplicated into TypeScript because antd takes colour values
 * rather than `var()` references. Duplication that nothing checks is how the
 * antd theme and the stylesheet drifted apart before; this is the check.
 *
 * The stylesheet is read through Vite's `?raw` import rather than `node:fs`,
 * because `@types/node` is not a dependency of this package and adding one to
 * read a file that Vite can already hand over as a string would be the wrong
 * trade.
 */

import { describe, expect, it } from "vitest";
import designSystemCss from "./design-system.css?raw";
import { CSS_TOKENS, CSS_TOKENS_DARK, token } from "./tokens";

/** Custom properties declared in the stylesheet block opened by `opener`. */
function declaredTokens(opener = ":root {"): Record<string, string> {
  // Comments out first. The `:root` block is heavily commented, and prose such
  // as "the rule that carries --warn over --l0bg: the stale-data notice" reads
  // as a declaration to a regex that has not removed it.
  const css = designSystemCss.replace(/\/\*[\s\S]*?\*\//g, "");
  const start = css.indexOf(opener);
  const end = css.indexOf("\n}", start);
  if (start === -1 || end === -1) throw new Error(`no ${opener} block in design-system.css`);

  const found: Record<string, string> = {};
  for (const [, name, value] of css.slice(start, end).matchAll(/(--[\w-]+)\s*:\s*([^;{}]+);/g)) {
    if (name && value) found[name] = value.trim();
  }
  return found;
}

const DARK_OPENER = ':root[data-theme="dark"] {';

describe("tokens.ts mirrors design-system.css", () => {
  const declared = declaredTokens();

  it("reads the :root block", () => {
    expect(Object.keys(declared).length).toBeGreaterThan(30);
  });

  it.each(Object.entries(CSS_TOKENS))("%s is the stylesheet's value", (name, value) => {
    expect(declared[name]).toBe(value);
  });
});

describe("tokens.ts mirrors the dark theme block", () => {
  const light = declaredTokens();
  const dark = declaredTokens(DARK_OPENER);

  it("reads the dark block", () => {
    expect(Object.keys(dark).length).toBeGreaterThan(60);
  });

  // A token the dark block does not redeclare is inherited from `:root`, so the
  // value antd should see is the light one. `--sans` and `--progress-*` are that
  // case on purpose.
  it.each(Object.entries(CSS_TOKENS_DARK))("%s is the dark stylesheet's value", (name, value) => {
    expect(dark[name] ?? light[name]).toBe(value);
  });

  it("covers exactly the keys the light mirror has", () => {
    expect(Object.keys(CSS_TOKENS_DARK).sort()).toEqual(Object.keys(CSS_TOKENS).sort());
  });

  it("redeclares every token that the light theme paints surfaces and text with", () => {
    // If a surface token were left at its light value in dark, a white panel
    // would sit in a dark app. These are the ones that must always move.
    for (const name of ["--bg", "--panel", "--line", "--ink", "--dim", "--faint"] as const) {
      expect(dark[name], name).toBeDefined();
      expect(dark[name], name).not.toBe(light[name]);
    }
  });

  it("keeps the glass seam neutral in light and active in dark", () => {
    expect(light["--glass-filter"]).toBe("none");
    expect(dark["--glass-filter"]).toMatch(/blur\(/);
    expect(dark["--glass-bg"]).toMatch(/^rgba\(/);
  });

  it("selects by theme name", () => {
    expect(token("--panel")).toBe(CSS_TOKENS["--panel"]);
    expect(token("--panel", "light")).toBe(CSS_TOKENS["--panel"]);
    expect(token("--panel", "dark")).toBe(CSS_TOKENS_DARK["--panel"]);
  });
});
