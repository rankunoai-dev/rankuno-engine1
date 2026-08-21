import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PerformanceSummary } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import { PerformancePanel } from "./PerformancePanel";

/**
 * The Search Console panel.
 *
 * What is asserted here is mostly what the panel *says* rather than what it
 * renders. Every number in it is derived from a join between Google's URLs and
 * the crawl's, and the failure this component exists to prevent is a reader
 * treating those numbers as complete. So: the unreliable-join warning, the
 * coverage denominator, the skipped kinds and the truncation notice all have
 * tests, because all four are the kind of thing that gets quietly dropped in a
 * later layout change.
 */

function summary(overrides: Partial<PerformanceSummary> = {}): PerformanceSummary {
  return {
    job_id: "job-1",
    base_url: "https://e.com/",
    source_name: "Pages.csv",
    rows: 1000,
    skipped_rows: 0,
    matched: 1000,
    match_rate_pct: 100,
    is_reliable: true,
    pages_with_data: 1000,
    pages: 12787,
    unmatched: [],
    rollup: {
      site: {
        path: [],
        label: "",
        depth: 0,
        pages: 12787,
        pages_with_data: 1000,
        direct_pages: 0,
        direct_clicks: 0,
        clicks: 5400,
        impressions: 120000,
        position: 14.2,
        sessions: 0,
        engaged_sessions: 0,
        engagement_time_sec: 0,
        conversions: 0,
        revenue: 0,
        ctr: 0.045,
        data_coverage: 0.078,
      },
      sections: [
        {
          path: ["Resources"],
          label: "Resources",
          depth: 1,
          pages: 5740,
          pages_with_data: 400,
          direct_pages: 1,
          direct_clicks: 20,
          clicks: 4000,
          impressions: 90000,
          position: 12.5,
          sessions: 0,
          engaged_sessions: 0,
          engagement_time_sec: 0,
          conversions: 0,
          revenue: 0,
          ctr: 0.044,
          data_coverage: 0.07,
        },
        {
          path: ["Resources", "Blog"],
          label: "Blog",
          depth: 2,
          pages: 2000,
          pages_with_data: 100,
          direct_pages: 0,
          direct_clicks: 0,
          clicks: 900,
          impressions: 20000,
          position: 18.0,
          sessions: 0,
          engaged_sessions: 0,
          engagement_time_sec: 0,
          conversions: 0,
          revenue: 0,
          ctr: 0.045,
          data_coverage: 0.05,
        },
      ],
      unattributed: { rows: 0, clicks: 0, impressions: 0, sessions: 0 },
      attributed_share: 1,
    },
    opportunities: {
      opportunities: [
        {
          kind: "orphan_with_traffic",
          url: "https://e.com/white-paper/",
          section: ["Resources"],
          score: 100,
          clicks: 66,
          impressions: 1800,
          position: 8.1,
          inbound_internal_links: 0,
          reference_url: null,
          reason: "Earns 66 search clicks with no internal link pointing at it.",
        },
      ],
      found: { orphan_with_traffic: 149 },
      truncated: { orphan_with_traffic: 99 },
      skipped: {},
      limit_per_kind: 50,
    },
    ...overrides,
  };
}

function stubUpload(result: PerformanceSummary | null = summary()) {
  const spy = vi.fn().mockResolvedValue(result);
  useCrawlStore.setState({ uploadGscExport: spy });
  return spy;
}

/** A file of a chosen apparent size, without allocating that many bytes. */
function exportFile(bytes: number, name = "Search-Console.zip"): File {
  const file = new File(["x"], name, { type: "application/zip" });
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

function dropFile(container: HTMLElement, file: File): void {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("the dragger rendered no file input");
  fireEvent.change(input, { target: { files: [file] } });
}

function open() {
  return render(<PerformancePanel jobId="job-1" label="e.com" open onClose={() => {}} />);
}

describe("PerformancePanel", () => {
  it("asks for the file Search Console actually produces", () => {
    stubUpload();
    open();
    // The default download is a ZIP. Asking for "the CSV" sends people looking
    // for a file they do not have.
    expect(screen.getByText(/ZIP straight from/)).toBeInTheDocument();
  });

  it("sends the file itself, not its text", async () => {
    const spy = stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const [jobId, body] = spy.mock.calls[0]!;
    expect(jobId).toBe("job-1");
    // A Blob, never a string. The export is normally a ZIP, and decoding an
    // archive to text turns it into mojibake the server cannot parse.
    expect(body).toBeInstanceOf(Blob);
    expect(typeof body).not.toBe("string");
  });

  it("refuses an oversized file without calling the server", async () => {
    const spy = stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(90 * 1_000_000));

    expect(await screen.findByText(/90 MB/)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("warns when the join is unreliable, before showing any total", async () => {
    /*
     * The whole reason this panel orders itself the way it does. Section totals
     * built on a two-thirds join understate traffic by an unknown amount, and
     * the loss is not spread evenly — a reader who is not told treats them as
     * the site's real numbers.
     */
    stubUpload(summary({ is_reliable: false, match_rate_pct: 61.4, matched: 614 }));
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText(/Only 61.4% of the export matched/)).toBeInTheDocument();
    expect(screen.getByText(/not spread evenly/)).toBeInTheDocument();
  });

  it("shows coverage with its denominator, which the match rate cannot say", async () => {
    /*
     * A 1,000-row UI export against a 12,787-page site matches every row — 100%
     * — while describing 8% of the site. Two different questions, and only this
     * one is ever wrong in the flattering direction.
     */
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText("7.8%")).toBeInTheDocument();
    expect(screen.getByText(/1,000 of 12,787 pages/)).toBeInTheDocument();
  });

  it("lists only top-level sections, not every trail prefix", async () => {
    /*
     * The rollup carries one row per prefix — 928 of them on a 12,787-page
     * crawl. A flat table of all of them is not something anyone reads, and the
     * tree already exists for going deeper.
     */
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText("Resources")).toBeInTheDocument();
    expect(screen.queryByText("Blog")).not.toBeInTheDocument();
  });

  it("shows an em dash for an unmeasured position, never a zero", async () => {
    /*
     * Position zero reads as better than rank 1 and would sort an unmeasured
     * section to the top of the table.
     */
    const base = summary();
    stubUpload(
      summary({
        rollup: {
          ...base.rollup,
          sections: [{ ...base.rollup.sections[0]!, position: null }],
        },
      }),
    );
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    await screen.findByText("Resources");
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows where the unmatched rows went, grouped by host", async () => {
    /*
     * The arithmetic behind the match rate. "41.5% matched" asks to be taken on
     * trust; this partitions the other 58.5% so it can be checked. On the first
     * real export the two largest groups were single hosts carrying 558 rows of
     * indexed spam between them, and no other grouping would have put them next
     * to each other.
     */
    stubUpload(
      summary({
        rows: 1000,
        matched: 415,
        match_rate_pct: 41.5,
        is_reliable: false,
        unmatched: [
          {
            host: "smartstaging-auth.e.com",
            reason: "other_subdomain",
            urls: 283,
            clicks: 400000,
            impressions: 5000000,
            examples: ["http://smartstaging-auth.e.com/cop/video/x-138.html"],
          },
          {
            host: "e.com",
            reason: "not_crawled",
            urls: 16,
            clicks: 900,
            impressions: 40000,
            examples: [],
          },
        ],
      }),
    );
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    // The count is stated against the total, not left as a percentage.
    expect(await screen.findByText(/Rows that matched no page \(585 of 1,?000\)/)).toBeInTheDocument();
    expect(screen.getByText("smartstaging-auth.e.com")).toBeInTheDocument();
    // And the reason reads as a sentence, not an enum.
    expect(
      screen.getByText(/A subdomain of this site the crawl never covered/),
    ).toBeInTheDocument();
    expect(screen.queryByText("other_subdomain")).not.toBeInTheDocument();
  });

  it("says nothing about unmatched rows when every row matched", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    await screen.findByText("Resources");
    expect(screen.queryByText(/Rows that matched no page/)).not.toBeInTheDocument();
  });

  it("says when a recommendation kind was not evaluated", async () => {
    /*
     * The most important thing this panel does. A list with a silent omission
     * invites the reader to conclude the site has no orphans, when the truth is
     * that this crawl could not tell.
     */
    stubUpload(
      summary({
        opportunities: {
          opportunities: [],
          found: {},
          truncated: {},
          skipped: { orphan_with_traffic: "inbound_links_unreliable" },
          limit_per_kind: 50,
        },
      }),
    );
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText(/Not evaluated/)).toBeInTheDocument();
    expect(screen.getByText(/stopped at its page ceiling/)).toBeInTheDocument();
  });

  it("says how many findings the scoring ceiling dropped", async () => {
    /*
     * Distinct from the on-screen limit, and the wording keeps them apart. This
     * count means the rows do not exist: they were scored, counted into
     * `truncated`, and discarded before the response was built, so no download
     * can produce them.
     */
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    // Matched across nodes: JSX splits `· {count} beyond…` into three text
    // nodes, so a single-node regex cannot see the sentence.
    // `findAllBy`, because a textContent match also hits every ancestor of the
    // span. The assertion is that the sentence is on screen, not that exactly
    // one element carries it.
    const notice = await screen.findAllByText((_, element) =>
      (element?.textContent ?? "").includes("99 beyond the scoring ceiling were not kept"),
    );
    expect(notice.length).toBeGreaterThan(0);
  });

  it("counts the sections it lists", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    const heading = await screen.findByRole("heading", { name: /Sections/ });
    // The fixture carries one depth-1 section.
    expect(heading.textContent).toMatch(/Sections\s*1/);
  });

  it("says the section list is not the visualizer's tab list", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    // Measured on gep.com: 30 sections here against 36 tabs there, because the
    // visualizer splits a localised page out by its URL prefix and this rolls
    // it up under its published breadcrumb. Same count on highradius.com and
    // still different sets — a near-match is what makes stating this necessary.
    expect(await screen.findByText(/the visualizer.s tabs also split by/)).toBeInTheDocument();
  });

  it("offers a download on the section itself, not only on the panel", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    // Each section goes to a different owner: the internal-link findings are a
    // content job, the navigation-depth ones an information-architecture job.
    expect(await screen.findByRole("button", { name: /Download 1/ })).toBeInTheDocument();
    expect(screen.getByText("Download CSV")).toBeInTheDocument();
  });

  it("says the dropped findings are not in the section file either", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    // The honest part. Capping happens in the scorer before anything is stored,
    // so those rows are not on the server and no download can produce them.
    // What the button *does* deliver is every scored row, not a screenful.
    const button = await screen.findByRole("button", { name: /Download 1/ });
    const title = button.getAttribute("title") ?? "";
    expect(title).toMatch(/Download all 1 scored rows/);
    expect(title).toMatch(/beyond the scoring ceiling/);
    expect(button.getAttribute("title")).toMatch(/not stored anywhere/);
  });

  it("writes the section file when asked", async () => {
    const clicked = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    fireEvent.click(await screen.findByRole("button", { name: /Download 1/ }));
    expect(clicked).toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("renders the reason in words rather than the enum", async () => {
    stubUpload();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText(/Earning clicks with no internal link/)).toBeInTheDocument();
    expect(screen.queryByText("orphan_with_traffic")).not.toBeInTheDocument();
  });

  it("distinguishes 'evaluated and found none' from 'not evaluated'", async () => {
    stubUpload(
      summary({
        opportunities: {
          opportunities: [],
          found: {},
          truncated: {},
          skipped: {},
          limit_per_kind: 50,
        },
      }),
    );
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText(/Every kind was evaluated/)).toBeInTheDocument();
  });

  it("reports an upload failure instead of hanging on the spinner", async () => {
    stubUpload(null);
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, exportFile(2048));

    expect(await screen.findByText(/The upload failed/)).toBeInTheDocument();
  });
});
