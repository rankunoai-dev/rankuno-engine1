import { describe, expect, it } from "vitest";
import type { SavedReconciliation } from "../adapters/adapterInterface";
import { buildDashModel, OTHERS_LANE } from "./dashboardModel";
import { addedFromFrog, buildTreeOverlay } from "./treeOverlay";
import { crawl, page } from "../test/factories";

/**
 * The cross-check and Search Console overlay.
 *
 * Every shape here was measured on a stored gep.com job before it was written
 * as a fixture: OTHERS split across locale roots, three-quarters of the misses
 * being pagination, the merged job's seven imported pages, and a sidecar that
 * predates the field it is read for.
 */

function reconciliation(
  engineOnly: Array<{ url: string; reason: string }>,
  inBoth: number,
): SavedReconciliation {
  return {
    summary: {
      job_id: "j",
      source_job_id: "j",
      base_url: "https://e.com/",
      frog_rows: 0,
      in_both: inBoth,
      missed_pages: 0,
      orphans: 0,
      merged: 0,
      frog_reasons: {},
      engine_reasons: {},
    },
    created_at: "2026-09-04T00:00:00Z",
    missed_pages: [],
    orphans: [],
    frog_only: [],
    engine_only: engineOnly,
  };
}

const PAGES = [
  page("https://e.com/kb/a/", { breadcrumb_path: ["Knowledge Bank"], gsc_clicks: 10, gsc_impressions: 100 }),
  page("https://e.com/kb/a/?page=2", { breadcrumb_path: ["Knowledge Bank"] }),
  page("https://e.com/kb/b/", { breadcrumb_path: ["Knowledge Bank"], gsc_clicks: 5, gsc_impressions: 50 }),
  page("https://e.com/loose/", { breadcrumb_path: ["OTHERS", "UNKNOWN"], gsc_clicks: 250, gsc_impressions: 1000 }),
  page("https://e.com/es-es/", {
    breadcrumb_path: ["OTHERS", "HOMEPAGE"],
    primary_page_type: "HOMEPAGE",
    gsc_clicks: 1473,
    gsc_impressions: 9000,
  }),
];

const ENGINE_ONLY = [
  { url: "https://e.com/kb/a/?page=2", reason: "QUERY_VARIANT" },
  { url: "https://e.com/loose/", reason: "SITEMAP_ORPHAN" },
];

function model() {
  return buildDashModel(crawl({ pages: PAGES }), "navigation");
}

describe("buildTreeOverlay", () => {
  it("marks each missed page and counts the subtree", () => {
    const m = model();
    const overlay = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 3));
    expect(overlay.crossCheck).toBe(true);

    const kb = m.roots.map((i) => m.nodes[i]!).find((n) => n.label === "Knowledge Bank")!;
    expect(kb.cnt).toBe(3);
    expect(overlay.missedCnt[kb.i]).toBe(1);

    const paged = m.nodes.find((n) => n.profile?.url.endsWith("?page=2"))!;
    expect(overlay.mark[paged.i]).toBe("missed");
    expect(overlay.reason[paged.i]).toBe("QUERY_VARIANT");
  });

  it("keeps the mark but drops the count for a hidden reason", () => {
    /*
     * 1,332 of gep.com's 1,817 misses are `?page=N` variants Screaming Frog
     * filters on purpose. An analyst can stop counting them; the row still says
     * why it is not counted.
     */
    const m = model();
    const overlay = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 3), new Set(["QUERY_VARIANT"]));
    const kb = m.roots.map((i) => m.nodes[i]!).find((n) => n.label === "Knowledge Bank")!;
    expect(overlay.missedCnt[kb.i]).toBe(0);
    const paged = m.nodes.find((n) => n.profile?.url.endsWith("?page=2"))!;
    expect(overlay.mark[paged.i]).toBe("missed");
    expect(overlay.reasons).toEqual({ QUERY_VARIANT: 1, SITEMAP_ORPHAN: 1 });
  });

  it("gathers OTHERS across locale roots, not only the node named OTHERS", () => {
    /*
     * `navTree` roots `/es-es/` under `es-es > OTHERS > HOMEPAGE`. gep.com's four
     * most-clicked OTHERS pages are localised homepages, and a summary that read
     * only the top-level OTHERS node would report none of them.
     */
    const m = model();
    const overlay = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 3));
    expect(m.laneCounts[OTHERS_LANE]).toBeGreaterThan(0);
    expect(overlay.others.applicable).toBe(true);
    expect(overlay.others.pages).toBe(2);
    expect(overlay.others.missed).toBe(1);
    expect(overlay.others.clicks).toBe(1723);
    expect(overlay.others.topPages[0]?.url).toBe("https://e.com/es-es/");
    expect(overlay.others.topPages[0]?.locale).toBe("es-es");
    // Buckets are URL folders now, and both fixture pages are flat: `/loose/`
    // has no folder, and `/es-es/` has none once its locale prefix is dropped.
    expect(overlay.others.buckets.map((b) => b.label)).toEqual(["FLAT_URLS"]);
    expect(overlay.others.buckets[0]?.clicks).toBe(1723);
    // The split the tree row cannot show: the panel's total against each
    // root's own OTHERS. Most clicked first, so `es-es` precedes the site's.
    expect(overlay.others.byRoot.map((r) => [r.label, r.pages, r.clicks])).toEqual([
      ["es-es", 1, 1473],
      ["OTHERS", 1, 250],
    ]);
  });

  it("totals Search Console figures per root and reports the source", () => {
    const m = model();
    const overlay = buildTreeOverlay(m, null);
    expect(overlay.gsc).toBe(true);
    const kb = overlay.roots.find((r) => r.label === "Knowledge Bank")!;
    expect(kb.clicks).toBe(15);
    expect(kb.impressions).toBe(150);
    expect(kb.gscPages).toBe(2);
    expect(overlay.others.clickShare).toBeCloseTo(1723 / 1738);
  });

  it("reports no cross-check as absence, not as zero misses", () => {
    const m = model();
    const overlay = buildTreeOverlay(m, null);
    expect(overlay.crossCheck).toBe(false);
    expect(overlay.crossCheckUnavailable).toMatch(/No Screaming Frog cross-check/);
    expect(overlay.integrity).toBeNull();
  });

  it("refuses a sidecar saved before engine_only existed", () => {
    const m = model();
    const stale = { ...reconciliation([], 0) } as Partial<SavedReconciliation>;
    delete stale.engine_only;
    const overlay = buildTreeOverlay(m, stale as SavedReconciliation);
    expect(overlay.crossCheck).toBe(false);
    expect(overlay.crossCheckUnavailable).toMatch(/Re-upload/);
  });

  it("checks pages − missed against the sidecar's in_both", () => {
    const m = model();
    const good = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 3));
    expect(good.integrity).toEqual({ expected: 3, actual: 3 });
    const drifted = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 4));
    expect(drifted.integrity).toEqual({ expected: 4, actual: 3 });
  });

  it("matches loosely only for the residue, and counts what still misses", () => {
    const m = model();
    const overlay = buildTreeOverlay(
      m,
      reconciliation(
        [
          { url: "https://E.COM/kb/b", reason: "SITEMAP_ORPHAN" },
          { url: "https://e.com/never-crawled/", reason: "SITEMAP_ORPHAN" },
        ],
        3,
      ),
    );
    const b = m.nodes.find((n) => n.profile?.url === "https://e.com/kb/b/")!;
    expect(overlay.mark[b.i]).toBe("missed");
    expect(overlay.unmatched).toBe(1);
  });

  it("marks every node sharing a duplicated URL", () => {
    const pages = [...PAGES, page("https://e.com/loose/", { breadcrumb_path: ["OTHERS", "UNKNOWN"] })];
    const m = buildDashModel(crawl({ pages }), "navigation");
    const overlay = buildTreeOverlay(m, reconciliation(ENGINE_ONLY, 3));
    const marked = m.nodes.filter((n) => n.profile?.url === "https://e.com/loose/");
    expect(marked).toHaveLength(2);
    expect(marked.every((n) => overlay.mark[n.i] === "missed")).toBe(true);
    // Integrity reasons about URLs, so the duplicate counts once.
    expect(overlay.integrity).toEqual({ expected: 3, actual: 3 });
  });

  it("is not applicable to a path-grouped tree", () => {
    const m = buildDashModel(crawl({ pages: PAGES }), "path");
    const overlay = buildTreeOverlay(m, null);
    expect(overlay.others.applicable).toBe(false);
  });
});

describe("addedFromFrog", () => {
  it("recognises a profile merged from an export", () => {
    const imported = page("https://e.com/x/", {
      discovery_sources: { sitemap: false, dom_link: false, cms_api: false },
    });
    expect(addedFromFrog(imported)).toBe(true);
    expect(addedFromFrog(page("https://e.com/y/"))).toBe(false);
  });

  it("treats a profile with no discovery_sources as unknown, never as added", () => {
    /* 98% of the stored corpus predates the field. */
    const old = page("https://e.com/z/");
    delete (old as { discovery_sources?: unknown }).discovery_sources;
    expect(addedFromFrog(old)).toBe(false);
  });

  it("counts imported pages on the merged job without a sidecar", () => {
    const pages = [
      ...PAGES,
      page("https://e.com/from-sf/", {
        breadcrumb_path: ["Knowledge Bank"],
        discovery_sources: { sitemap: false, dom_link: false, cms_api: false },
      }),
    ];
    const m = buildDashModel(crawl({ pages }), "navigation");
    const overlay = buildTreeOverlay(m, null);
    const kb = m.roots.map((i) => m.nodes[i]!).find((n) => n.label === "Knowledge Bank")!;
    expect(overlay.addedCnt[kb.i]).toBe(1);
    expect(overlay.roots.find((r) => r.label === "Knowledge Bank")?.added).toBe(1);
  });
});
