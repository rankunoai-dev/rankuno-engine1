import { describe, expect, it } from "vitest";
import type { FullPageIntelligenceProfile } from "../types/schema";
import { page } from "../test/factories";
import {
  googleStateOf,
  hasGscData,
  indexConflictOf,
  indexabilityOf,
  measuredIndexability,
} from "./indexing";

/**
 * The rule under test is a negative one: nothing here may conclude that a URL
 * is *not* indexed. Search Console reports only URLs that drew impressions, so
 * absence is unexplained rather than excluded, and every assertion below exists
 * to keep that distinction from collapsing into a boolean.
 */

const withGsc = (url: string, impressions: number, extra = {}): FullPageIntelligenceProfile =>
  page(url, { gsc_impressions: impressions, gsc_clicks: 0, ...extra });

describe("googleStateOf", () => {
  it("confirms a URL that drew impressions", () => {
    expect(googleStateOf(withGsc("https://e.com/a", 40), true)).toBe("CONFIRMED");
  });

  it("says a URL is absent from the export, never that it is unindexed", () => {
    // The distinction the whole module exists for.
    expect(googleStateOf(withGsc("https://e.com/b", 0), true)).toBe("NOT_IN_EXPORT");
  });

  it("keys on impressions, not clicks", () => {
    // A page can rank for months without a click. Keying on clicks would report
    // every one of those as unseen by Google.
    const ranked = page("https://e.com/c", { gsc_impressions: 900, gsc_clicks: 0 });
    expect(googleStateOf(ranked, true)).toBe("CONFIRMED");
  });

  it("separates a crawl with no GSC data from a page that earned nothing", () => {
    // Both are "no impressions" on screen; only one is a site problem.
    expect(googleStateOf(page("https://e.com/d"), false)).toBe("NO_GSC_DATA");
  });
});

describe("hasGscData", () => {
  it("is false when no page was ever matched", () => {
    expect(hasGscData([page("https://e.com/a"), page("https://e.com/b")])).toBe(false);
  });

  it("is true on a zero-impression row, which is still a row", () => {
    expect(hasGscData([page("https://e.com/a"), withGsc("https://e.com/b", 0)])).toBe(true);
  });
});

describe("indexabilityOf", () => {
  it("reads UNKNOWN off a stored crawl that predates the field", () => {
    // `GET /jobs/{id}/result` returns stored JSON unvalidated, so the key is
    // absent rather than defaulted — the shape that once blanked the dashboard.
    const { indexability: _dropped, ...rest } = page("https://e.com/a", {
      indexability: "INDEXABLE",
    });
    expect(indexabilityOf(rest as FullPageIntelligenceProfile)).toBe("UNKNOWN");
  });

  it("never reports an unmeasured page as indexable", () => {
    // Absence of a prohibition is not the same as absence of a look.
    expect(indexabilityOf(page("https://e.com/a", { indexability: "UNKNOWN" }))).not.toBe(
      "INDEXABLE",
    );
  });
});

describe("measuredIndexability", () => {
  it("is false for a crawl stored before the field existed", () => {
    expect(measuredIndexability([page("https://e.com/a"), page("https://e.com/b")])).toBe(false);
  });

  it("is true once any page carries a verdict", () => {
    expect(
      measuredIndexability([
        page("https://e.com/a", { indexability: "UNKNOWN" }),
        page("https://e.com/b", { indexability: "NOINDEX" }),
      ]),
    ).toBe(true);
  });
});

describe("indexConflictOf", () => {
  it("flags a noindex page that is still earning impressions", () => {
    // The highest-value row in the report: traffic about to disappear.
    const blocked = withGsc("https://e.com/a", 500, { indexability: "NOINDEX" });
    expect(indexConflictOf(blocked, true)).toBe("BLOCKED_BUT_EARNING");
  });

  it("flags a canonical Google overruled", () => {
    const overruled = withGsc("https://e.com/b", 12, { indexability: "CANONICALISED_AWAY" });
    expect(indexConflictOf(overruled, true)).toBe("CANONICAL_OVERRULED");
  });

  it("flags a dead URL still drawing impressions", () => {
    const dead = withGsc("https://e.com/c", 3, { indexability: "NOT_A_PAGE" });
    expect(indexConflictOf(dead, true)).toBe("DEAD_BUT_EARNING");
  });

  it("reports no conflict for a healthy page", () => {
    expect(indexConflictOf(withGsc("https://e.com/d", 90, { indexability: "INDEXABLE" }), true)).toBe(
      null,
    );
  });

  it("reports no conflict for a noindex page drawing nothing", () => {
    // The page is doing exactly what it was told. Not a finding.
    const quiet = withGsc("https://e.com/e", 0, { indexability: "NOINDEX" });
    expect(indexConflictOf(quiet, true)).toBe(null);
  });

  it("never invents a conflict when no GSC data was loaded", () => {
    // Without an export there is no second axis, so there is nothing to disagree
    // with — and a "conflict" here would be one side talking to itself.
    const blocked = page("https://e.com/f", { indexability: "NOINDEX" });
    expect(indexConflictOf(blocked, false)).toBe(null);
  });
});
