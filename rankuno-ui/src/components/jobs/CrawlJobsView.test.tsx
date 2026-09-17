import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { CrawlJobSummary } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import { CrawlJobsView } from "./CrawlJobsView";

/**
 * `partial` covers two causes the server's own contract keeps separate: a
 * page ceiling (a planned stop) and a stalled or aborted crawl
 * (`stoppedReason`, sourced from `JobRecord.error`). Before this fix the
 * server also reported the second cause as `succeeded`; this only tests the
 * display side — `tests/api/test_server.py` covers the status itself.
 */

const BASE: CrawlJobSummary = {
  id: "job-1",
  label: "e.com",
  baseUrl: "https://e.com/",
  status: "succeeded",
  pagesClassified: 40,
  truncated: false,
  synthetic: false,
  crawledAt: "2026-09-11T12:00:00Z",
  hasCheckpoint: false,
};

function withJob(overrides: Partial<CrawlJobSummary>): void {
  useCrawlStore.setState({ jobs: [{ ...BASE, ...overrides }], liveJobs: {} });
}

afterEach(() => {
  useCrawlStore.setState({ jobs: [], liveJobs: {} });
});

describe("CrawlJobsView status detail", () => {
  it("labels a clean finish as finished", () => {
    withJob({ status: "succeeded" });
    render(<CrawlJobsView />);
    expect(screen.getByText("finished")).toBeInTheDocument();
  });

  it("labels a ceiling-only partial distinctly from a stalled one", () => {
    withJob({ status: "partial", truncated: true, stoppedReason: null });
    render(<CrawlJobsView />);
    expect(screen.getByText("hit page ceiling")).toBeInTheDocument();
    expect(screen.queryByText("stalled/aborted")).not.toBeInTheDocument();
  });

  it("labels a partial with a stoppedReason as stalled/aborted", () => {
    withJob({
      status: "partial",
      truncated: true,
      stoppedReason: "no page completed in 30s with 4 requests in flight",
    });
    render(<CrawlJobsView />);
    expect(screen.getByText("stalled/aborted")).toBeInTheDocument();
    expect(screen.queryByText("hit page ceiling")).not.toBeInTheDocument();
  });

  it("shows no status detail for a failed job", () => {
    withJob({ status: "failed" });
    render(<CrawlJobsView />);
    expect(screen.queryByText("finished")).not.toBeInTheDocument();
    expect(screen.queryByText("hit page ceiling")).not.toBeInTheDocument();
    expect(screen.queryByText("stalled/aborted")).not.toBeInTheDocument();
  });
});
