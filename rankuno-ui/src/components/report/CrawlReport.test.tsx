import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildDashModel } from "../../lib/dashboardModel";
import { crawl, discovery, page } from "../../test/factories";
import { CrawlReport } from "./CrawlReport";

/**
 * The printable report.
 *
 * This component has form: it blanked the entire dashboard in cycle 0021 by
 * calling `.toLocaleString()` on a field absent from every result stored before
 * `media_skipped` was added. React unmounts the whole tree when a render throws
 * uncaught, so the failure mode is a black page with no message. `tsc` cannot
 * see it — the type says the field is there, and the type describes what the
 * engine emits today, not what is on disk.
 */

const AT = new Date("2026-08-19T12:00:00Z");

function renderReport(result = crawl()) {
  const model = buildDashModel(result, "path");
  return render(<CrawlReport model={model} result={result} generatedAt={AT} />);
}

describe("CrawlReport", () => {
  it("mounts and names the site it describes", () => {
    renderReport();
    expect(screen.getByText("Site architecture report")).toBeInTheDocument();
    // Header *and* footer both name the site, so this is deliberately
    // `getAllByText`: asserting one match would fail on a correct report.
    expect(screen.getAllByText(/https:\/\/e\.com\//).length).toBeGreaterThan(0);
  });

  it("renders a field a stored result predates, without throwing", () => {
    /*
     * The cycle-0021 regression, pinned. `malformed_skipped` is the newest
     * counter and is absent from every result written before cycle 0029, so
     * the component must render `—` rather than crash.
     *
     * Deleted through a cast because the *type* insists the field exists; the
     * point of the test is that reality does not.
     */
    const result = crawl();
    const stored = {
      ...result,
      discovery: { ...result.discovery },
    } as PageClassificationOutputLike;
    delete stored.discovery.malformed_skipped;
    delete stored.discovery.media_skipped;

    const model = buildDashModel(result, "path");
    expect(() =>
      render(
        // Cast at the boundary, and the cast *is* the assertion: the prop type
        // insists these counters are present, and this test exists because a
        // stored result on disk disagrees with it.
        <CrawlReport
          model={model}
          result={stored as unknown as ReturnType<typeof crawl>}
          generatedAt={AT}
        />,
      ),
    ).not.toThrow();
    // Two absent counters, both shown as an em dash rather than as zero: a
    // crawl that skipped nothing and a crawl that never counted are different.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("shows the KPI figures the operator reads first", () => {
    renderReport(
      crawl({
        pages: [page("https://e.com/a/"), page("https://e.com/b/")],
        discovery: discovery({ total_urls: 2, pages_fetched: 2, media_skipped: 7 }),
      }),
    );
    expect(screen.getByText("URLs classified")).toBeInTheDocument();
    expect(screen.getByText("Media skipped")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("warns when a crawl stopped early", () => {
    renderReport(crawl({ discovery: discovery({ stopped_reason: "stalled" }) }));
    expect(screen.getByText(/Crawl stopped early/)).toBeInTheDocument();
  });

  it("warns when nothing was fetched over the network", () => {
    /* Classifications then rest on URL patterns alone, and a PDF outlives the
       session, so the caveat has to be on the page and not just on screen. */
    renderReport(crawl({ discovery: discovery({ pages_fetched: 0 }) }));
    expect(screen.getByText(/No page was fetched/)).toBeInTheDocument();
  });

  it("stays silent when there is nothing to warn about", () => {
    renderReport();
    expect(screen.queryByText(/Crawl stopped early/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No page was fetched/)).not.toBeInTheDocument();
  });

  it("prints sections rather than every leaf", () => {
    /*
     * `REPORT_MAX_DEPTH` is why the report is readable: kinsta.com's first
     * three tree levels hold 3,456 individual pages, and printing them made a
     * 70-page PDF that the Windows spooler refused outright.
     *
     * Ten sibling leaves under one root must not each earn a row.
     */
    const pages = Array.from({ length: 10 }, (_, i) =>
      page(`https://e.com/blog/post-${i}/`, { breadcrumb_path: ["Blog"] }),
    );
    const { container } = renderReport(crawl({ pages }));
    const rows = container.querySelectorAll(".rep-tree tbody tr");
    expect(rows.length).toBeLessThan(pages.length);
  });
});

/**
 * The shape a *stored* result really has.
 *
 * `DiscoveryReport` declares every counter required, which describes what the
 * engine emits today. A result written months ago simply has no key for a
 * counter added since, so the two newest are re-declared optional here — both
 * to model reality and because `delete` refuses a non-optional property.
 */
type PageClassificationOutputLike = Omit<ReturnType<typeof crawl>, "discovery"> & {
  discovery: Omit<
    ReturnType<typeof crawl>["discovery"],
    "malformed_skipped" | "media_skipped"
  > & { malformed_skipped?: number; media_skipped?: number };
};
