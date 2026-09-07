import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import GscIntegratedReport from "./GscIntegratedReport";

describe("GscIntegratedReport Component", () => {
  it("renders table with crawl and GSC data", () => {
    const mockPages = [
      {
        url: "https://example.com/solutions/ai",
        hierarchyLevel: "L2_SUB_HUB",
        primaryPageType: "PRODUCT_HUB",
        gscMetrics: {
          clicks: 120,
          impressions: 4000,
          ctr: 0.03,
          avgPosition: 4.2,
        },
        navigationContext: {
          discoveryMethod: "PRIMARY_NAV",
          reachabilityTier: "TIER_1_STANDARD",
        },
      },
      {
        url: "https://example.com/blog/tips",
        hierarchyLevel: "L3_LEAF_PAGE",
        primaryPageType: "BLOG_ARTICLE",
        gscMetrics: {
          clicks: 5,
          impressions: 200,
          ctr: 0.005,
          avgPosition: 28.5,
        },
      },
    ];

    render(
      <GscIntegratedReport
        pages={mockPages}
        totalPages={2}
        baseUrl="https://example.com"
      />
    );

    expect(screen.getByText("Crawl Results with GSC Integration")).toBeDefined();
    expect(screen.getByText("/solutions/ai")).toBeDefined();
    expect(screen.getByText("/blog/tips")).toBeDefined();
    expect(screen.getByText("120")).toBeDefined();
    expect(screen.getByText("4,000")).toBeDefined();
  });

  it("handles empty pages array gracefully", () => {
    render(
      <GscIntegratedReport
        pages={[]}
        totalPages={0}
        baseUrl="https://example.com"
      />
    );

    expect(screen.getByText("Crawl Results with GSC Integration")).toBeDefined();
    expect(screen.getByText("No pages match your filter. Try adjusting your search.")).toBeDefined();
  });
});
