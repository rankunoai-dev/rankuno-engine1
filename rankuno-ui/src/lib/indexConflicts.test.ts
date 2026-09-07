import { describe, expect, it } from "vitest";
import { buildFindings } from "./audit";
import { crawl, page } from "../test/factories";
import type { FullPageIntelligenceProfile } from "../types/schema";

/**
 * The findings that need both halves of the indexing picture.
 *
 * The risk these guard against is a report that reads absence from a Search
 * Console export as proof of exclusion. Every finding here fires only on pages
 * Google has *confirmed* — ones with impressions — so no page can be accused of
 * being unindexed on the strength of a missing row.
 */

const blocked = page("https://e.com/blocked", {
  indexability: "NOINDEX",
  indexability_reason: "The page says 'noindex'. Google honours this.",
  gsc_impressions: 4200,
  gsc_clicks: 90,
});

const quietNoindex = page("https://e.com/tag/x", {
  indexability: "NOINDEX",
  gsc_impressions: 0,
  gsc_clicks: 0,
});

const healthy = page("https://e.com/good", {
  indexability: "INDEXABLE",
  gsc_impressions: 900,
  gsc_clicks: 30,
});

function findingIds(pages: FullPageIntelligenceProfile[]): string[] {
  return buildFindings(crawl({ pages })).map((finding) => finding.id);
}

describe("index conflict findings", () => {
  it("reports a noindex page that is still earning impressions", () => {
    const found = buildFindings(crawl({ pages: [blocked, healthy] })).find(
      (finding) => finding.id === "noindex-earning",
    );
    expect(found?.count).toBe(1);
    // The impressions are the cost of the decision, so they belong in the text.
    expect(found?.detail).toContain("4,200");
  });

  it("does not report a noindex page that earns nothing", () => {
    // It is doing exactly what it was told. A tag page with no impressions is
    // not a defect, and reporting it would bury the one that is.
    expect(findingIds([quietNoindex, healthy])).not.toContain("noindex-earning");
  });

  it("stays silent when no Search Console data was loaded", () => {
    // Without the second axis there is nothing to disagree with. Firing here
    // would accuse pages on the strength of one side talking to itself.
    const noGsc = page("https://e.com/blocked", { indexability: "NOINDEX" });
    expect(findingIds([noGsc])).not.toContain("noindex-earning");
  });

  it("never reports a page for merely being absent from the export", () => {
    // The central rule: absence is unexplained, not excluded. An indexable page
    // with no impressions must produce no indexing finding at all.
    const unseen = page("https://e.com/quiet", {
      indexability: "INDEXABLE",
      gsc_impressions: 0,
      gsc_clicks: 0,
    });
    const ids = findingIds([unseen, healthy]);
    expect(ids).not.toContain("noindex-earning");
    expect(ids).not.toContain("dead-earning");
    expect(ids).not.toContain("canonical-overruled");
  });

  it("reports a canonical Google overruled", () => {
    const overruled = page("https://e.com/dupe", {
      indexability: "CANONICALISED_AWAY",
      gsc_impressions: 300,
      gsc_clicks: 4,
    });
    expect(findingIds([overruled, healthy])).toContain("canonical-overruled");
  });

  it("reports a dead URL that still draws impressions", () => {
    const dead = page("https://e.com/gone", {
      indexability: "NOT_A_PAGE",
      indexability_reason: "Answered 404. A page that errors is not indexed.",
      gsc_impressions: 80,
      gsc_clicks: 1,
    });
    expect(findingIds([dead, healthy])).toContain("dead-earning");
  });

  it("orders the worklist by what it costs, not by URL", () => {
    const smaller = page("https://e.com/a-small", {
      indexability: "NOINDEX",
      gsc_impressions: 10,
      gsc_clicks: 0,
    });
    const found = buildFindings(crawl({ pages: [smaller, blocked] })).find(
      (finding) => finding.id === "noindex-earning",
    );
    // `blocked` sorts first on 4,200 impressions despite the later URL.
    expect(found?.pages?.[0]?.url).toBe("https://e.com/blocked");
  });

  it("carries the pages so the finding opens as a worklist", () => {
    const found = buildFindings(crawl({ pages: [blocked] })).find(
      (finding) => finding.id === "noindex-earning",
    );
    expect(found?.pages).toHaveLength(1);
  });
});
