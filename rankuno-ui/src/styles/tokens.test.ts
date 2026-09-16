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
import { CSS_TOKENS } from "./tokens";

/** Custom properties declared in the stylesheet's `:root` block. */
function declaredTokens(): Record<string, string> {
  // Comments out first. The `:root` block is heavily commented, and prose such
  // as "the rule that carries --warn over --l0bg: the stale-data notice" reads
  // as a declaration to a regex that has not removed it.
  const css = designSystemCss.replace(/\/\*[\s\S]*?\*\//g, "");
  const start = css.indexOf(":root {");
  const end = css.indexOf("\n}", start);
  if (start === -1 || end === -1) throw new Error("no :root block in design-system.css");

  const found: Record<string, string> = {};
  for (const [, name, value] of css.slice(start, end).matchAll(/(--[\w-]+)\s*:\s*([^;{}]+);/g)) {
    if (name && value) found[name] = value.trim();
  }
  return found;
}

describe("tokens.ts mirrors design-system.css", () => {
  const declared = declaredTokens();

  it("reads the :root block", () => {
    expect(Object.keys(declared).length).toBeGreaterThan(30);
  });

  it.each(Object.entries(CSS_TOKENS))("%s is the stylesheet's value", (name, value) => {
    expect(declared[name]).toBe(value);
  });
});
