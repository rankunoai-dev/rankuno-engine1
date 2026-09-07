import { beforeEach, describe, expect, it } from "vitest";
import type { SavedReconciliation } from "../adapters/adapterInterface";
import { buildDashModel } from "../lib/dashboardModel";
import { buildTreeOverlay } from "../lib/treeOverlay";
import { crawl, page } from "../test/factories";
import { useDashboardStore } from "./useDashboardStore";

/**
 * The "missed only" filter and the overlay's binding to its model.
 *
 * The property under test: a filter that reads a per-index array from another
 * file must never apply that array to a tree it was not built for.
 */

function reconciliation(urls: string[]): SavedReconciliation {
  return {
    summary: {
      job_id: "j",
      source_job_id: "j",
      base_url: "https://e.com/",
      frog_rows: 0,
      in_both: 0,
      missed_pages: 0,
      orphans: 0,
      merged: 0,
      frog_reasons: {},
      engine_reasons: {},
    },
    created_at: "",
    missed_pages: [],
    orphans: [],
    frog_only: [],
    engine_only: urls.map((url) => ({ url, reason: "SITEMAP_ORPHAN" })),
  };
}

const PAGES = [
  page("https://e.com/docs/a/", { breadcrumb_path: ["Docs"] }),
  page("https://e.com/docs/b/", { breadcrumb_path: ["Docs"] }),
  page("https://e.com/blog/c/", { breadcrumb_path: ["Blog"] }),
];

beforeEach(() => {
  useDashboardStore.setState({
    overlay: null,
    crossCheckOn: false,
    missedOnly: false,
    hiddenReasons: new Set<string>(),
  });
});

describe("missed only", () => {
  it("keeps the section above a missed page and hides the rest", () => {
    const model = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const store = useDashboardStore.getState();
    store.setModel(model);
    store.expandAll(model, 99);
    store.setOverlay(buildTreeOverlay(model, reconciliation(["https://e.com/docs/b/"])), model);
    useDashboardStore.getState().toggleCrossCheck(model);
    useDashboardStore.getState().toggleMissedOnly(model);

    const shown = useDashboardStore.getState().flat.map((row) => model.nodes[row.i]!.label);
    expect(shown).toEqual(["Docs", "b"]);
  });

  it("does nothing while the cross-check is off", () => {
    const model = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const store = useDashboardStore.getState();
    store.setModel(model);
    store.expandAll(model, 99);
    store.setOverlay(buildTreeOverlay(model, reconciliation(["https://e.com/docs/b/"])), model);
    useDashboardStore.getState().toggleMissedOnly(model);
    expect(useDashboardStore.getState().flat).toHaveLength(model.nodes.length);
  });

  it("ignores an overlay built for a different model", () => {
    /*
     * The model for a new crawl arrives before its overlay does. The previous
     * overlay's indices belong to another tree; applied here they would hide
     * arbitrary rows.
     */
    const previous = buildDashModel(crawl({ pages: PAGES.slice(0, 1) }), "navigation");
    const model = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const store = useDashboardStore.getState();
    store.setModel(model);
    store.expandAll(model, 99);
    store.setOverlay(buildTreeOverlay(previous, reconciliation(["https://e.com/docs/a/"])), model);
    useDashboardStore.getState().toggleCrossCheck(model);
    useDashboardStore.getState().toggleMissedOnly(model);
    expect(useDashboardStore.getState().flat).toHaveLength(model.nodes.length);
  });

  it("re-flattens when the overlay arrives after the filter was switched on", () => {
    const model = buildDashModel(crawl({ pages: PAGES }), "navigation");
    const store = useDashboardStore.getState();
    store.setModel(model);
    store.expandAll(model, 99);
    useDashboardStore.getState().toggleCrossCheck(model);
    useDashboardStore.getState().toggleMissedOnly(model);
    expect(useDashboardStore.getState().flat).toHaveLength(model.nodes.length);

    useDashboardStore
      .getState()
      .setOverlay(buildTreeOverlay(model, reconciliation(["https://e.com/blog/c/"])), model);
    const shown = useDashboardStore.getState().flat.map((row) => model.nodes[row.i]!.label);
    expect(shown).toEqual(["Blog", "c"]);
  });
});
