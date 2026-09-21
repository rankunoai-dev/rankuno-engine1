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
