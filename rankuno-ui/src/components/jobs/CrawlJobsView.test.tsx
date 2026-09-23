import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CrawlDataAdapter, CrawlJobSummary } from "../../adapters/adapterInterface";
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
  useCrawlStore.setState({ jobs: [], liveJobs: {}, adapter: null });
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

/**
 * "Download URLs" in the job-row `...` menu.
 *
 * One click, no panel: the workbook is fetched as a `Blob` and handed to
 * `saveBlob` the moment the item is clicked, the same shape as
 * `WorkerJobsPanel`'s bundle download — never through an `<a href>`, which
 * would carry no `Authorization` header against a bearer-guarded route.
 */
describe("CrawlJobsView download URLs", () => {
  it("offers Download URLs for a finished job and downloads the workbook on click", async () => {
    const blob = new Blob(["xlsx"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const downloadUrlList = vi.fn().mockResolvedValue(blob);
    withJob({ status: "succeeded" });
    useCrawlStore.setState({
      adapter: { downloadUrlList } as unknown as CrawlDataAdapter,
    });
    // jsdom implements neither; the anchor-click download trick needs both.
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    render(<CrawlJobsView />);
    fireEvent.click(screen.getByRole("button", { name: /more actions for this crawl/i }));
    fireEvent.click(await screen.findByText("Download URLs"));

    await waitFor(() => {
      expect(downloadUrlList).toHaveBeenCalledWith("job-1");
    });
  });

  it("does not open a panel when Download URLs is clicked", async () => {
    const downloadUrlList = vi.fn().mockResolvedValue(new Blob(["xlsx"]));
    withJob({ status: "succeeded" });
    useCrawlStore.setState({
      adapter: { downloadUrlList } as unknown as CrawlDataAdapter,
    });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    render(<CrawlJobsView />);
    fireEvent.click(screen.getByRole("button", { name: /more actions for this crawl/i }));
    fireEvent.click(await screen.findByText("Download URLs"));

    await waitFor(() => expect(downloadUrlList).toHaveBeenCalled());
    // No dialog role exists anywhere — the click fetched a blob and saved it,
    // it did not open `ReconcilePanel` or `PerformancePanel`.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hides Download URLs when the adapter cannot build the workbook", () => {
    withJob({ status: "succeeded" });
    // No adapter set at all — `MockAdapter` and a fixture session both leave
    // `downloadUrlList` undefined.
    render(<CrawlJobsView />);
    expect(
      screen.queryByRole("button", { name: /more actions for this crawl/i }),
    ).not.toBeInTheDocument();
  });

  it("hides Download URLs for a job that has not finished", () => {
    const downloadUrlList = vi.fn();
    withJob({ status: "running" });
    useCrawlStore.setState({
      adapter: { downloadUrlList } as unknown as CrawlDataAdapter,
    });

    render(<CrawlJobsView />);
    // `running` offers no other menu item either, so the `...` trigger itself
    // must be absent, not merely missing this one entry.
    expect(
      screen.queryByRole("button", { name: /more actions for this crawl/i }),
    ).not.toBeInTheDocument();
  });
});
