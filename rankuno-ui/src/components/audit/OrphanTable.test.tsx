import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildFindings, orphanKind, orphanPages } from "../../lib/audit";
import { toCsv } from "../../lib/csv";
import { crawl, page } from "../../test/factories";
import type { FullPageIntelligenceProfile } from "../../types/schema";
import { OrphanTable } from "./OrphanTable";

/**
 * The orphan worklist.
 *
 * The assertions worth having are about the *split*, not the rendering. A table
 * that lists 2,000 URLs is easy; one that tells a sitemap orphan apart from a
 * CMS record nobody published is the reason this exists, and it is the part
 * that silently regresses if the discovery flags stop being carried onto the
 * profile.
 */

const sitemapOrphan = page("https://e.com/published/", {
  inbound_internal_links_count: 0,
  discovery_sources: { sitemap: true, dom_link: false, cms_api: false },
  sitemap_source: "blog-pages-sitemap.xml",
});

const cmsOrphan = page("https://e.com/draft/", {
  inbound_internal_links_count: 0,
  discovery_sources: { sitemap: false, dom_link: false, cms_api: true },
});

const linked = page("https://e.com/linked/", {
  inbound_internal_links_count: 4,
  discovery_sources: { sitemap: true, dom_link: true, cms_api: false },
});

/**
 * A page exactly as `GET /jobs/{id}/result` serves it for a crawl stored before
 * `discovery_sources` existed: the key is absent, not false. The endpoint returns
 * the stored mapping without re-validating it through the model, so no default
 * is ever filled in — which is why the generated type cannot be trusted here.
 */
function storedBeforeTheField(url: string): FullPageIntelligenceProfile {
  const { discovery_sources: _dropped, ...rest } = page(url, {
    inbound_internal_links_count: 0,
  });
  return rest as FullPageIntelligenceProfile;
}

describe("results that predate the discovery flags", () => {
  it("classifies an orphan instead of throwing on the missing field", () => {
    // The regression. Reading `page.discovery_sources.sitemap` directly threw a
    // TypeError inside buildFindings, which took the entire app to a blank page.
    expect(() => orphanKind(storedBeforeTheField("https://e.com/old/"))).not.toThrow();
    expect(orphanKind(storedBeforeTheField("https://e.com/old/"))).toBe("unlinked");
  });

  it("builds the audit findings for a whole stored crawl", () => {
    const legacy = crawl({ pages: [storedBeforeTheField("https://e.com/old/")] });
    expect(() => buildFindings(legacy)).not.toThrow();
    expect(buildFindings(legacy)[0]?.count).toBe(1);
  });

  it("renders the table without a provenance split", () => {
    render(
      <OrphanTable pages={[storedBeforeTheField("https://e.com/old/")]} baseUrl="https://e.com/" />,
    );
    expect(screen.getByText(/ran before the engine recorded which path/)).toBeInTheDocument();
    expect(screen.getByText("https://e.com/old/")).toBeInTheDocument();
  });
});

describe("orphan classification", () => {
  it("separates a published orphan from a CMS-only record", () => {
    expect(orphanKind(sitemapOrphan)).toBe("sitemap");
    expect(orphanKind(cmsOrphan)).toBe("cms");
  });

  it("keeps a linked page out of the list however it was discovered", () => {
    const pages = orphanPages(crawl({ pages: [sitemapOrphan, cmsOrphan, linked] }));
    expect(pages.map((item) => item.url)).toEqual([sitemapOrphan.url, cmsOrphan.url]);
  });

  it("puts sitemap orphans first, because they are the actionable ones", () => {
    const pages = orphanPages(crawl({ pages: [cmsOrphan, sitemapOrphan] }));
    expect(orphanKind(pages[0]!)).toBe("sitemap");
  });

  it("counts every orphan but attributes only the published ones", () => {
    const [finding] = buildFindings(crawl({ pages: [sitemapOrphan, cmsOrphan, linked] }));
    expect(finding?.count).toBe(2);
    // The detail line must not report both as published pages: that is the
    // overstatement this split exists to prevent.
    expect(finding?.detail).toContain("1 page of them");
    expect(finding?.pages).toHaveLength(2);
  });
});

describe("OrphanTable", () => {
  it("filters to one kind without changing the totals it offers", () => {
    render(<OrphanTable pages={[sitemapOrphan, cmsOrphan]} baseUrl="https://www.e.com/" />);

    expect(screen.getByText("https://e.com/published/")).toBeInTheDocument();
    expect(screen.getByText("https://e.com/draft/")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Sitemap 1"));

    expect(screen.getByText("https://e.com/published/")).toBeInTheDocument();
    expect(screen.queryByText("https://e.com/draft/")).not.toBeInTheDocument();
    // The segmented control still advertises the full set, so a filtered view
    // never reads as a smaller crawl.
    expect(screen.getByText("All 2")).toBeInTheDocument();
  });

  it("exports what is on screen rather than the whole set", () => {
    const clicked = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    render(<OrphanTable pages={[sitemapOrphan, cmsOrphan]} baseUrl="https://www.e.com/" />);
    fireEvent.click(screen.getByText("CMS only 1"));

    const button = screen.getByRole("button", { name: /Export CSV \(1\)/ });
    fireEvent.click(button);
    expect(clicked).toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("declines to split a crawl that never recorded the discovery path", () => {
    // Every result stored before this field existed deserialises this way.
    // Labelling all of them "Crawl only" would be a fabricated finding.
    const legacy = page("https://e.com/old/", {
      inbound_internal_links_count: 0,
      discovery_sources: { sitemap: false, dom_link: false, cms_api: false },
    });
    render(<OrphanTable pages={[legacy]} baseUrl="https://www.e.com/" />);

    expect(screen.getByText(/ran before the engine recorded which path/)).toBeInTheDocument();
    expect(screen.queryByText(/^Sitemap \d/)).not.toBeInTheDocument();
    // The list itself still works: the URLs are the deliverable either way.
    expect(screen.getByText("https://e.com/old/")).toBeInTheDocument();
  });

  it("names the grouped sitemap that listed the page", () => {
    render(<OrphanTable pages={[sitemapOrphan]} baseUrl="https://www.e.com/" />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("blog-pages-sitemap.xml")).toBeInTheDocument();
  });
});

describe("toCsv", () => {
  it("quotes a value carrying the delimiter, so columns cannot shift", () => {
    expect(toCsv(["url"], [["https://e.com/?a=1,2"]])).toBe('url\r\n"https://e.com/?a=1,2"');
  });

  it("doubles an embedded quote rather than truncating the field", () => {
    expect(toCsv(["t"], [['say "hi"']])).toBe('t\r\n"say ""hi"""');
  });

  it("writes an empty field for a missing sitemap rather than the word null", () => {
    expect(toCsv(["a", "b"], [["x", null]])).toBe("a,b\r\nx,");
  });
});
