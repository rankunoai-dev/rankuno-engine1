import { describe, expect, it } from "vitest";
import { page } from "../test/factories";
import { buildNavTree, FLAT_URLS_LABEL, localeOf, othersTrail, OTHERS_LABEL } from "./navTree";
import type { TreeNode } from "./tree";

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

describe("othersTrail", () => {
  /**
   * Where an unplaced page sits under OTHERS. Every shape here was counted on
   * gep.com's 1,781 OTHERS pages before it became a fixture: 80 flat, the rest
   * in 59 folders up to five deep, with 36 query variants among them.
   */
  it("groups by every folder in the URL, not just the first", () => {
    expect(othersTrail("https://e.com/mind/blog/tag/ai/")).toEqual([
      OTHERS_LABEL,
      "mind",
      "blog",
      "tag",
    ]);
  });

  it("files a URL with no folder under FLAT_URLS", () => {
    expect(othersTrail("https://e.com/cookie-policy")).toEqual([OTHERS_LABEL, FLAT_URLS_LABEL]);
    expect(othersTrail("https://e.com/cookie-policy/")).toEqual([OTHERS_LABEL, FLAT_URLS_LABEL]);
  });

  it("drops the locale prefix, which is already the page's root", () => {
    expect(othersTrail("https://e.com/es-es/company/contact-us")).toEqual([OTHERS_LABEL, "company"]);
    // A locale's own homepage has no folder left once the prefix goes.
    expect(othersTrail("https://e.com/es-es/")).toEqual([OTHERS_LABEL, FLAT_URLS_LABEL]);
  });

  it("ignores the query string", () => {
    expect(othersTrail("https://e.com/podcasts?page=3")).toEqual([OTHERS_LABEL, FLAT_URLS_LABEL]);
    expect(othersTrail("https://e.com/mind/blog?page=3")).toEqual([OTHERS_LABEL, "mind"]);
  });

  it("decodes a percent-encoded folder for its label", () => {
    expect(othersTrail("https://e.com/caf%C3%A9/menu/")).toEqual([OTHERS_LABEL, "café"]);
  });
});

describe("buildNavTree and OTHERS", () => {
  function pageAt(url: string, breadcrumb_path: string[] = ["OTHERS", "UNKNOWN"]) {
    return page(url, { breadcrumb_path });
  }

  function childLabels(node: TreeNode): string[] {
    return node.children.map((child) => child.segment);
  }

  it("regroups the engine's OTHERS > <type> trail by URL folder", () => {
    const root = buildNavTree([
      pageAt("https://e.com/podcasts/ep-1/"),
      pageAt("https://e.com/podcasts/ep-2/", ["OTHERS", "BLOG_ARTICLE"]),
      pageAt("https://e.com/cookie-policy"),
    ]);
    const others = root.children.find((child) => child.segment === OTHERS_LABEL)!;
    expect(childLabels(others)).toEqual(["podcasts", FLAT_URLS_LABEL]);
    expect(others.children[0]!.descendantCount).toBe(2);
  });

  it("pins FLAT_URLS below the folder groups", () => {
    const root = buildNavTree([
      pageAt("https://e.com/a-flat-page"),
      pageAt("https://e.com/zeta/one/"),
      pageAt("https://e.com/alpha/one/"),
    ]);
    const others = root.children.find((child) => child.segment === OTHERS_LABEL)!;
    expect(childLabels(others)).toEqual(["alpha", "zeta", FLAT_URLS_LABEL]);
  });

  it("treats a crawl with no trail at all the same way", () => {
    /* Results stored before `breadcrumb_path` was populated. */
    const root = buildNavTree([pageAt("https://e.com/docs/x/", [])]);
    const others = root.children.find((child) => child.segment === OTHERS_LABEL)!;
    expect(childLabels(others)).toEqual(["docs"]);
  });

  it("leaves placed pages alone", () => {
    const root = buildNavTree([pageAt("https://e.com/company/about/", ["Company"])]);
    expect(childLabels(root)).toEqual(["Company"]);
  });
});
