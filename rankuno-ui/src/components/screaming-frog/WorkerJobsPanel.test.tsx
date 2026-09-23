import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { workerJob } from "../../test/factories";
import { WorkerJobsPanel } from "./WorkerJobsPanel";

const NAMES = { "wkr-aaaa": "Studio desktop" } as const;

function renderPanel(api: WorkerDispatchAdapter) {
  const onReuse = vi.fn();
  render(
    <WorkerJobsPanel api={api} refreshSignal={0} onReuse={onReuse} workerNames={NAMES} />,
  );
  return { onReuse };
}

describe("WorkerJobsPanel", () => {
  it("renders a record carrying only the fields the first release wrote", async () => {
    // No `dispatched_at`, `finished_at`, `error` or `bundle_size_bytes`. Jobs
    // stored before those existed look exactly like this, and a panel that
    // reads one without checking takes the whole view down with it.
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([workerJob()]),
    };

    renderPanel(api);

    expect(await screen.findByText("https://www.example.com/")).toBeInTheDocument();
    expect(screen.getByText("QUEUED")).toBeInTheDocument();
  });

  it("says a bundle size is not recorded rather than calling it zero bytes", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi
        .fn()
        .mockResolvedValue([workerJob({ status: "succeeded", finished_at: "2026-09-21T11:00:00Z" })]),
      downloadWorkerBundle: vi.fn(),
    };

    renderPanel(api);

    expect(await screen.findByText(/bundle ready · size not recorded/i)).toBeInTheDocument();
  });

  it("states that no progress detail exists rather than drawing a bar", async () => {
    // The old, pre-telemetry placeholder state: a `dispatched` job whose
    // worker has not (yet, or ever) sent a progress report. All three fields
    // are null, same as a job dispatched before this feature existed.
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({ status: "dispatched", dispatched_at: new Date().toISOString() }),
      ]),
    };

    renderPanel(api);

    expect(
      await screen.findByText(/no progress detail is available/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("draws a live progress bar for a dispatched job that is crawling", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({
          status: "dispatched",
          dispatched_at: new Date().toISOString(),
          pages_crawled: 3718,
          progress_pct: 40.43,
          current_phase: "crawling",
        }),
      ]),
    };

    renderPanel(api);

    const bar = await screen.findByRole("progressbar");
    expect(bar).toBeInTheDocument();
    expect(await screen.findByText("Crawling: 3,718 pages (40%).")).toBeInTheDocument();
    expect(screen.queryByText(/no progress detail is available/i)).not.toBeInTheDocument();
  });

  it("shows the exporting phase once the crawl has moved past discovery", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({
          status: "dispatched",
          dispatched_at: new Date().toISOString(),
          pages_crawled: 9204,
          progress_pct: 100,
          current_phase: "exporting",
        }),
      ]),
    };

    renderPanel(api);

    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(
      await screen.findByText("Exporting the crawl bundle — 9,204 pages found."),
    ).toBeInTheDocument();
  });

  it("renders a decreasing percentage as-is, without treating it as an error", async () => {
    // Screaming Frog's own denominator grows as it discovers more URLs
    // mid-crawl, so a later report can show a lower percentage than an
    // earlier one — real data, not a bug to guard against.
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({
          status: "dispatched",
          dispatched_at: new Date().toISOString(),
          pages_crawled: 500,
          progress_pct: 12.5,
          current_phase: "crawling",
        }),
      ]),
    };

    renderPanel(api);

    expect(await screen.findByText("Crawling: 500 pages (13%).")).toBeInTheDocument();
  });

  it("does not draw a progress bar for a job that is not dispatched", async () => {
    // A defensive check: even if a stray progress report existed on a
    // terminal-status record, only a `dispatched` row draws the bar.
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({
          status: "succeeded",
          finished_at: "2026-09-21T11:00:00Z",
          pages_crawled: 500,
          progress_pct: 100,
          current_phase: "exporting",
        }),
      ]),
    };

    renderPanel(api);

    await screen.findByText("SUCCEEDED");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("offers the bundle for a finished job, with its size", async () => {
    const blob = new Blob(["zip"], { type: "application/zip" });
    const downloadWorkerBundle = vi.fn().mockResolvedValue(blob);
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({
          status: "succeeded",
          finished_at: "2026-09-21T11:00:00Z",
          bundle_size_bytes: 2_621_440,
        }),
      ]),
      downloadWorkerBundle,
    };
    // jsdom implements neither, and the anchor trick needs both. Assigned the
    // same way the four existing CSV export suites do it.
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    renderPanel(api);

    const button = await screen.findByRole("button", { name: /download \(2\.5 MB\)/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(downloadWorkerBundle).toHaveBeenCalledWith("wj-1");
    });
  });

  it("shows a licence failure verbatim and offers no way to re-run it", async () => {
    const reason = "Screaming Frog licence is invalid or expired on this machine";
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi
        .fn()
        .mockResolvedValue([workerJob({ status: "failed", error: reason })]),
    };

    const { onReuse } = renderPanel(api);

    expect(await screen.findByText(reason)).toBeInTheDocument();
    // ADR 0013 condition 6: a licence is a state of the machine, and re-running
    // spends minutes arriving at the identical error.
    expect(
      screen.queryByRole("button", { name: /use these settings again/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/fix the Screaming Frog licence/i)).toBeInTheDocument();
    expect(onReuse).not.toHaveBeenCalled();
  });

  it("does offer the settings back for an ordinary failure", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({ status: "failed", error: "the worker daemon stopped responding" }),
      ]),
    };

    const { onReuse } = renderPanel(api);

    fireEvent.click(
      await screen.findByRole("button", { name: /use these settings again/i }),
    );
    // Fills the form. It does not launch anything — a dispatch still needs its
    // own approval.
    expect(onReuse).toHaveBeenCalledTimes(1);
  });

  it("says nothing has been dispatched rather than showing an empty table", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([]),
    };

    renderPanel(api);

    expect(
      await screen.findByText(/no Screaming Frog crawl has been dispatched yet/i),
    ).toBeInTheDocument();
  });

  it("renders nothing at all when the adapter cannot list dispatches", () => {
    const { container } = render(
      <WorkerJobsPanel api={{}} refreshSignal={0} onReuse={vi.fn()} workerNames={{}} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
