import { describe, expect, it } from "vitest";
import { CATEGORY_CSV_HEADERS, categoryCsv, categoryFilename, categoryPages } from "./categoryCsv";
import { buildDashModel, EMPTY_MODEL, type DashModel, type DashNode } from "./dashboardModel";
import { crawl, page } from "../test/factories";

/*
 * Fixture: a path-grouped tree with a nested category, a sibling, a root-level
 * page and a group (`docs`) that is not itself a page. The expected URL set is
 * written out by hand so the test cannot pass by reusing the code under test.
 */
const BLOG_PAGES = [
  "https://e.com/blog/",
  "https://e.com/blog/a/",
  "https://e.com/blog/a/deep/",
  "https://e.com/blog/a/deep/x,y/",
  "https://e.com/blog/b/",
];
const OTHER_PAGES = ["https://e.com/shop/", "https://e.com/docs/guide/intro/"];

function fixture(): DashModel {
  const pages = [...BLOG_PAGES, ...OTHER_PAGES].map((url) => page(url));
  return buildDashModel(crawl({ pages }), "path");
}

function indexOfLabel(model: DashModel, label: string): number {
  const node = model.nodes.find((candidate) => candidate.label === label);
  if (!node) throw new Error(`no node labelled ${label}`);
  return node.i;
}

describe("categoryPages", () => {
  it("returns exactly the URLs under the category, nested descendants included", () => {
    const model = fixture();
    const urls = categoryPages(model, indexOfLabel(model, "blog")).map((node) => node.url);
    expect(urls.sort()).toEqual([...BLOG_PAGES].sort());
  });

  it("does not leak URLs from a sibling category", () => {
    const model = fixture();
    const urls = categoryPages(model, indexOfLabel(model, "a")).map((node) => node.url);
    expect(urls.sort()).toEqual([
      "https://e.com/blog/a/",
      "https://e.com/blog/a/deep/",
      "https://e.com/blog/a/deep/x,y/",
    ]);
    expect(urls).not.toContain("https://e.com/blog/b/");
  });

  it("excludes grouping nodes, whose url is a path and not a fetched address", () => {
    const model = fixture();
    const docs = categoryPages(model, indexOfLabel(model, "docs"));
    expect(docs.map((node) => node.url)).toEqual(["https://e.com/docs/guide/intro/"]);
    expect(docs.every((node) => node.kind !== "group")).toBe(true);
  });

  it("returns one entry per URL, in document order, with no duplicates", () => {
    const model = fixture();
    const urls = categoryPages(model, indexOfLabel(model, "blog")).map((node) => node.url);
    expect(new Set(urls).size).toBe(urls.length);
    expect(urls[0]).toBe("https://e.com/blog/");
  });

  it("agrees with the node count the control displays", () => {
    const model = fixture();
    for (const node of model.nodes) {
      if (node.kids.length === 0) continue;
      expect(categoryPages(model, node.i)).toHaveLength(node.cnt);
    }
  });

  it("returns nothing for an out-of-range index", () => {
    const model = fixture();
    expect(categoryPages(model, 10_000)).toEqual([]);
  });
});

describe("categoryCsv", () => {
  it("writes the real-field headers", () => {
    expect(CATEGORY_CSV_HEADERS).toEqual(["URL", "Path", "Hierarchy level", "Page type"]);
    const model = fixture();
    const [header] = categoryCsv(model, indexOfLabel(model, "blog")).split("\r\n");
    expect(header).toBe("URL,Path,Hierarchy level,Page type");
  });

  it("writes one row per URL and nothing else", () => {
    const model = fixture();
    const lines = categoryCsv(model, indexOfLabel(model, "blog")).split("\r\n");
    // Header plus one row per URL. The comma in the last URL is quoted, so a
    // naive split on "," would miscount; the line count is the honest check.
    expect(lines).toHaveLength(BLOG_PAGES.length + 1);
  });

  it("quotes a URL that contains a comma", () => {
    const model = fixture();
    const csv = categoryCsv(model, indexOfLabel(model, "deep"));
    expect(csv).toContain('"https://e.com/blog/a/deep/x,y/"');
  });

  it("fills the profile columns from the page's own fields", () => {
    const model = buildDashModel(
      crawl({
        pages: [
          page("https://e.com/blog/post/", {
            hierarchy_level: "L2_SUB_NAV_HUB",
            primary_page_type: "BLOG_ARTICLE",
          }),
        ],
      }),
      "path",
    );
    const csv = categoryCsv(model, indexOfLabel(model, "blog"));
    expect(csv.split("\r\n")[1]).toBe(
      "https://e.com/blog/post/,https://e.com/blog/post/,L2_SUB_NAV_HUB,BLOG_ARTICLE",
    );
  });

  it("neutralises cells a spreadsheet would read as formulas", () => {
    const model = hand([
      { i: 0, kind: "group", kids: [1], url: "" },
      {
        i: 1,
        kind: "page",
        kids: [],
        url: "https://e.com/x/",
        profile: page("https://e.com/x/", { normalized_path: "=HYPERLINK(\"http://evil\")" }),
      },
    ]);
    const row = categoryCsv(model, 0).split("\r\n")[1]!;
    // Prefixed with an apostrophe, then quoted by csv.ts because it holds quotes.
    expect(row).toBe(
      `https://e.com/x/,"'=HYPERLINK(""http://evil"")",L3_LEAF_PAGE,BLOG_ARTICLE`,
    );
  });

  it("leaves profile cells empty for a quarantined defaulter, which has no profile", () => {
    const model = hand([
      { i: 0, kind: "group", kids: [1], url: "" },
      { i: 1, kind: "defaulter", kids: [], url: "https://e.com/asset.pdf", profile: null },
    ]);
    const lines = categoryCsv(model, 0).split("\r\n");
    expect(lines[1]).toBe("https://e.com/asset.pdf,,,");
  });

  it("handles a 20,000-URL category without a DOM and inside a generous bound", () => {
    const pages = Array.from({ length: 20_000 }, (_, i) =>
      page(`https://e.com/big/p-${i}/`),
    );
    const model = buildDashModel(crawl({ pages }), "path");
    const started = performance.now();
    const csv = categoryCsv(model, indexOfLabel(model, "big"));
    const elapsed = performance.now() - started;
    expect(csv.split("\r\n")).toHaveLength(20_001);
    // A bound, not a benchmark: it catches an accidental quadratic walk and
    // tolerates a slow CI runner.
    expect(elapsed).toBeLessThan(5_000);
  });
});

describe("categoryFilename", () => {
  it("slugs the label into a csv filename", () => {
    expect(categoryFilename("Header Menu / Blog")).toBe("urls-header-menu-blog.csv");
  });

  it("falls back to a stable name when nothing is left after slugging", () => {
    expect(categoryFilename("!!!")).toBe("urls-category.csv");
  });
});

/** A hand-built model for shapes `buildDashModel` cannot produce on demand. */
function hand(partial: Array<Partial<DashNode> & Pick<DashNode, "i" | "kind" | "kids" | "url">>): DashModel {
  const nodes: DashNode[] = partial.map((node) => ({
    lv: 0,
    label: node.url || "group",
    p: null,
    cnt: 0,
    profile: null,
    src: "none",
    ...node,
  }));
  return { ...EMPTY_MODEL, nodes, roots: [0] };
}
