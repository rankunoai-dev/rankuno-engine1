import { describe, expect, it } from "vitest";
import { localeOf } from "./navTree";

/**
 * Locale detection, which decides the tree's top-level tabs.
 *
 * A false positive here is not cosmetic: the segment becomes a root, so the
 * pages under it are lifted out of the section they belong to and presented to
 * a client as a language the site does not publish.
 *
 * Mirrors `TestRegionalLocaleShape` in `tests/modules/seo/test_url_rules.py`.
 * The two implementations are separate by necessity — one groups the tree in
 * the browser, the other strips locales in the crawler — so they are pinned by
 * matching tests rather than by a shared module.
 */

const url = (segment: string) => `https://e.com/${segment}/page/`;

describe("localeOf", () => {
  it.each(["en-gb", "de-de", "fr-fr", "es-es", "zh-cn", "nl-be", "sv-fi"])(
    "recognises %s",
    (segment) => {
      expect(localeOf(url(segment))).toBe(segment);
    },
  );

  it.each(["jp-ja", "hk-zh"])("accepts %s, where the language is second", (segment) => {
    // 132 pages on gep.com are under `/jp-ja/`. A rule checking only the left
    // half would drop every one of them out of its locale root.
    expect(localeOf(url(segment))).toBe(segment);
  });

  it.each(["lp-demo", "jd-bots", "cv-core", "mb-api", "zs-zpa", "ho-erp", "ai-seo"])(
    "refuses %s, which is a slug shaped like a locale",
    (segment) => {
      // The reported defect and the 30 others measured beside it — 29 of them
      // workspace slugs on postman.com, each of which became a language tab.
      expect(localeOf(url(segment))).toBeNull();
    },
  );

  it.each(["it-it", "it-hr"])("accepts hyphenated %s", (segment) => {
    expect(localeOf(url(segment))).toBe(segment);
  });

  it.each(["it", "hr"])("still refuses the bare code %s", (segment) => {
    // `/it/` is IT services and `/hr/` is human resources far more often than
    // they are Italian and Croatian.
    expect(localeOf(url(segment))).toBeNull();
  });

  it("keeps cs-demo, the one known residual", () => {
    // `cs` is Czech and nothing in the segment says otherwise. Asserted so the
    // behaviour is on the record rather than rediscovered as a surprise.
    expect(localeOf(url("cs-demo"))).toBe("cs-demo");
  });

  it("returns null for an ordinary first segment", () => {
    expect(localeOf(url("software"))).toBeNull();
    expect(localeOf("https://e.com/")).toBeNull();
  });

  it("returns null rather than throwing on an unparseable URL", () => {
    expect(localeOf("http://[")).toBeNull();
  });
});
