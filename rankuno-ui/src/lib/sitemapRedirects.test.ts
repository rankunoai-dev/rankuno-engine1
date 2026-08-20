import { describe, expect, it } from "vitest";
import { buildFindings } from "./audit";
import { crawl, page } from "../test/factories";

/**
 * Sitemap entries that redirect.
 *
 * Every assertion here is about what the finding refuses to report. On a fresh
 * 300-page crawl of highradius.com only 3% of fetched pages redirect at all,
 * and exactly one of those was in the sitemap — a finding that fires on 1 URL
 * in 300 is a specific defect somebody can act on. The exclusions are what keep
 * it that sharp, and each one below is a real case from that crawl.
 */

const listed = { sitemap: true, dom_link: false, cms_api: false };
const linked = { sitemap: false, dom_link: true, cms_api: false };

function find(pages: ReturnType<typeof page>[]) {
  return buildFindings(crawl({ pages })).find((f) => f.id === "sitemap-redirects");
}

describe("sitemap entries that redirect", () => {
  it("reports a sitemap URL that moves elsewhere", () => {
    const moved = page("https://e.com/about/csr-policy/", {
      discovery_sources: listed,
      final_url: "https://e.com/",
    });
    expect(find([moved])?.count).toBe(1);
  });

  it("ignores a redirect that lands back on the same address", () => {
    /**
     * `/demo-request/` on highradius carries a redirect hop and ends exactly
     * where it started — a scheme or trailing-slash normalisation. Every site
     * does this and no client needs to hear about it.
     */
    const samePlace = page("https://e.com/demo-request/", {
      discovery_sources: listed,
      final_url: "https://www.e.com/demo-request",
    });
    expect(find([samePlace])).toBeUndefined();
  });

  it("ignores a redirect the sitemap does not list", () => {
    /** Three `/record-to-report/*` pages redirect properly, found by links. */
    const viaLink = page("https://e.com/old/", {
      discovery_sources: linked,
      final_url: "https://e.com/new/",
    });
    expect(find([viaLink])).toBeUndefined();
  });

  it("ignores a crawl that predates redirect recording", () => {
    /**
     * Absent is not "did not redirect" — it is "nobody looked". Accusing a site
     * of a defect on the strength of a missing column is how `trail_source`
     * once made every historical crawl read as unplaced.
     */
    const old = page("https://e.com/a/", { discovery_sources: listed });
    expect(find([old])).toBeUndefined();
  });

  it("calls out a redirect to the homepage separately", () => {
    /** Search engines read this as gone, not moved — a worse defect. */
    const toHome = page("https://e.com/about/csr-policy/", {
      discovery_sources: listed,
      final_url: "https://e.com/",
    });
    expect(find([toHome])?.detail).toContain("lands on the homepage");
  });

  it("reads correctly at a count of one", () => {
    const one = page("https://e.com/a/", {
      discovery_sources: listed,
      final_url: "https://e.com/b/",
    });
    expect(find([one])?.title).toBe("1 sitemap entry that redirects elsewhere");
  });

  it("reads correctly at a count above one", () => {
    const pages = ["a", "b"].map((slug) =>
      page(`https://e.com/${slug}/`, {
        discovery_sources: listed,
        final_url: `https://e.com/${slug}-new/`,
      }),
    );
    expect(find(pages)?.title).toBe("2 sitemap entries that redirect elsewhere");
  });

  it("hands over every page, not just the examples", () => {
    const pages = Array.from({ length: 8 }, (_, index) =>
      page(`https://e.com/p${index}/`, {
        discovery_sources: listed,
        final_url: `https://e.com/p${index}-new/`,
      }),
    );
    const finding = find(pages);
    expect(finding?.examples).toHaveLength(5);
    expect(finding?.pages).toHaveLength(8);
  });
});
