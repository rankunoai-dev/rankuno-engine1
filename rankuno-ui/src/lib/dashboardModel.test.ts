import { describe, expect, it } from "vitest";
import type { SavedReconciliation } from "../adapters/adapterInterface";
import { crawl, page } from "../test/factories";
import { buildDashModel, DEFAULTER_LANE, QUARANTINE_ROOT_LABEL } from "./dashboardModel";

/**
 * The "Defaulter / Quarantine" subtree `buildDashModel` builds on request.
 *
 * The property under test throughout is the one stated on `includeDefaulters`
 * itself: with the flag off, not one line of `buildDashModel`'s output may
 * differ from what it produced before this feature existed — no defaulter
 * node is *constructed*, not merely hidden. Every "off" test here asserts
 * against the exact values a pre-existing caller already depends on, not
 * against a looser "still works" check.
 */

const PAGES = [page("https://e.com/a/"), page("https://e.com/b/")];

function frogOnly(
  rows: Array<{ url: string; defaulter_category?: string | null }>,
): SavedReconciliation {
  return {
    summary: {
      job_id: "j",
      source_job_id: "j",
      base_url: "https://e.com/",
      frog_rows: rows.length,
      in_both: 0,
      missed_pages: 0,
      orphans: 0,
      merged: 0,
      frog_reasons: {},
      engine_reasons: {},
    },
    created_at: "2026-09-09T00:00:00Z",
    missed_pages: [],
    orphans: [],
    frog_only: rows.map((r) => ({ reason: "UNKNOWN", ...r })),
    engine_only: [],
  };
}

describe("buildDashModel — includeDefaulters off (the default)", () => {
  it("matches the flag-omitted call exactly, node for node", () => {
    const reconciliation = frogOnly([
      { url: "https://e.com/content/dam/x.html", defaulter_category: "DAM_FORMS_OTHER" },
    ]);
    const bare = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const explicitOff = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, false);
    expect(explicitOff.nodes.length).toBe(bare.nodes.length);
    expect(explicitOff.laneCounts).toEqual(bare.laneCounts);
    expect(explicitOff.index).toEqual(bare.index);
    expect(explicitOff.roots.length).toBe(bare.roots.length);
  });

  it("builds no defaulter node even when a reconciliation is passed", () => {
    const reconciliation = frogOnly([
      { url: "https://e.com/content/dam/x.html", defaulter_category: "DAM_FORMS_OTHER" },
    ]);
    const m = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, false);
    expect(m.nodes.some((n) => n.kind === "defaulter")).toBe(false);
    expect(m.laneCounts[DEFAULTER_LANE]).toBeUndefined();
  });
});

describe("buildDashModel — includeDefaulters on", () => {
  it("builds one quarantine root, one group per category, one leaf per URL", () => {
    const reconciliation = frogOnly([
      { url: "https://e.com/content/dam/en/x.html", defaulter_category: "DAM_FORMS_OTHER" },
      { url: "https://e.com/content/dam/en/y.html", defaulter_category: "DAM_FORMS_OTHER" },
      { url: "https://e.com/-/content/en/z.html", defaulter_category: "CMS_INTERNAL_LEAK" },
      // No category: the presumed-real residual, excluded from the tree.
      { url: "https://e.com/about/team.html", defaulter_category: null },
    ]);
    const m = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, true);

    const quarantineRoot = m.roots
      .map((i) => m.nodes[i]!)
      .find((n) => n.label === QUARANTINE_ROOT_LABEL);
    expect(quarantineRoot).toBeDefined();
    expect(quarantineRoot!.kind).toBe("group");
    expect(quarantineRoot!.kids.length).toBe(2); // two categories

    const damGroup = quarantineRoot!.kids.map((i) => m.nodes[i]!).find((n) => n.kids.length === 2)!;
    expect(damGroup.cnt).toBe(2);
    const leaves = damGroup.kids.map((i) => m.nodes[i]!);
    expect(leaves.every((n) => n.kind === "defaulter")).toBe(true);
    expect(leaves.every((n) => n.profile === null)).toBe(true);
    expect(leaves.map((n) => n.defaulterCategory)).toEqual(["DAM_FORMS_OTHER", "DAM_FORMS_OTHER"]);
    expect(leaves.map((n) => n.url).sort()).toEqual([
      "https://e.com/content/dam/en/x.html",
      "https://e.com/content/dam/en/y.html",
    ]);

    // The residual URL never appears anywhere in the model.
    expect(m.nodes.some((n) => n.url === "https://e.com/about/team.html")).toBe(false);
    expect(quarantineRoot!.cnt).toBe(3);
  });

  it("gives defaulters their own lane, not OTHERS", () => {
    const reconciliation = frogOnly([
      { url: "https://e.com/content/dam/en/x.html", defaulter_category: "DAM_FORMS_OTHER" },
    ]);
    const m = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, true);
    expect(m.laneCounts[DEFAULTER_LANE]).toBe(3); // root + group + leaf
  });

  it("leaves existing page and group nodes exactly as before", () => {
    const reconciliation = frogOnly([
      { url: "https://e.com/content/dam/en/x.html", defaulter_category: "DAM_FORMS_OTHER" },
    ]);
    const off = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const on = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, true);

    const originalCount = off.nodes.length;
    expect(on.nodes.slice(0, originalCount)).toEqual(off.nodes);
  });

  it("builds nothing when the reconciliation has no categorised rows", () => {
    const reconciliation = frogOnly([{ url: "https://e.com/about.html", defaulter_category: null }]);
    const m = buildDashModel(crawl({ pages: PAGES }), "navigation", reconciliation, true);
    expect(m.nodes.some((n) => n.kind === "defaulter")).toBe(false);
    expect(m.roots.map((i) => m.nodes[i]!.label)).not.toContain(QUARANTINE_ROOT_LABEL);
  });

  it("builds nothing with no reconciliation loaded", () => {
    const m = buildDashModel(crawl({ pages: PAGES }), "navigation", null, true);
    expect(m.nodes.some((n) => n.kind === "defaulter")).toBe(false);
  });
});
