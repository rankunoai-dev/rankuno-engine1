import { message } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import * as download from "../../lib/download";
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

/**
 * Masterfiles, built from a finished dispatch row.
 *
 * The build route reads the uploaded Screaming Frog bundle, so it wants the
 * WORKER job id (`wj-1` here) and answers a native crawl id with a 409. The
 * control lives on this table for that reason, and only on rows with a bundle.
 */
describe("WorkerJobsPanel masterfiles", () => {
  const SERVICES = [
    { slug: "response_codes", label: "Response Codes", description: "HTTP status codes" },
    { slug: "page_titles", label: "Page Titles" },
  ];
  const DONE = {
    status: "succeeded" as const,
    finished_at: "2026-09-21T11:00:00Z",
    bundle_size_bytes: 1024,
  };

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function masterfileApi(overrides: Partial<WorkerDispatchAdapter> = {}) {
    const api = {
      listWorkerJobs: vi.fn().mockResolvedValue([workerJob(DONE)]),
      listAvailableMasterfiles: vi.fn().mockResolvedValue(SERVICES),
      buildMasterfile: vi.fn().mockResolvedValue("dl-1"),
      getDeliverable: vi
        .fn()
        .mockResolvedValue({ id: "dl-1", status: "succeeded", has_result: true }),
      downloadDeliverable: vi.fn().mockResolvedValue(new Blob(["xlsx"])),
      ...overrides,
    };
    return api as typeof api & WorkerDispatchAdapter;
  }

  async function openMenu(): Promise<void> {
    fireEvent.click(await screen.findByRole("button", { name: /masterfiles for/i }));
    await screen.findByRole("group", { name: /masterfile services/i });
  }

  it("shows the control for a bundle row, listing services the adapter returned", async () => {
    const api = masterfileApi({
      listAvailableMasterfiles: vi
        .fn()
        .mockResolvedValue([{ slug: "only_one", label: "The Only Service" }]),
    });
    renderPanel(api);

    await openMenu();

    expect(screen.getByRole("button", { name: "The Only Service" })).toBeInTheDocument();
    // Not a constant: the two services in SERVICES are absent.
    expect(screen.queryByRole("button", { name: "Response Codes" })).not.toBeInTheDocument();
    expect(api.listAvailableMasterfiles).toHaveBeenCalledTimes(1);
  });

  it("hides the control for a row with no bundle", async () => {
    const api = masterfileApi({
      listWorkerJobs: vi.fn().mockResolvedValue([
        workerJob({ status: "partial", finished_at: "2026-09-21T11:00:00Z" }),
        workerJob({ id: "wj-2", status: "failed", error: "boom" }),
        workerJob({ id: "wj-3", status: "queued" }),
      ]),
    });
    renderPanel(api);

    await screen.findByText("PARTIAL");
    expect(screen.queryByRole("button", { name: /masterfiles for/i })).not.toBeInTheDocument();
  });

  it("hides the control when the adapter cannot build masterfiles", async () => {
    const api: WorkerDispatchAdapter = {
      listWorkerJobs: vi.fn().mockResolvedValue([workerJob(DONE)]),
      downloadWorkerBundle: vi.fn(),
    };
    renderPanel(api);

    await screen.findByText("SUCCEEDED");
    expect(screen.queryByRole("button", { name: /masterfiles for/i })).not.toBeInTheDocument();
  });

  it("builds from the worker job id, polls, then saves the blob", async () => {
    const blob = new Blob(["xlsx"]);
    const save = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const success = vi.spyOn(message, "success").mockImplementation(() => ({}) as never);
    const getDeliverable = vi
      .fn()
      .mockResolvedValueOnce({ id: "dl-1", status: "dispatched", has_result: false })
      .mockResolvedValueOnce({ id: "dl-1", status: "succeeded", has_result: true });
    const api = masterfileApi({
      getDeliverable,
      downloadDeliverable: vi.fn().mockResolvedValue(blob),
    });
    renderPanel(api);
    await openMenu();

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Response Codes" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(api.buildMasterfile).toHaveBeenCalledWith("wj-1", "response_codes");
    expect(getDeliverable).toHaveBeenCalledTimes(1);
    expect(save).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(getDeliverable).toHaveBeenCalledTimes(2);
    expect(api.downloadDeliverable).toHaveBeenCalledWith("dl-1");
    expect(save).toHaveBeenCalledWith("response_codes-wj-1-2026-09-21.xlsx", blob);
    expect(success).toHaveBeenCalled();
  });

  it("disables only the building service while in flight, then re-enables it", async () => {
    vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    vi.spyOn(message, "success").mockImplementation(() => ({}) as never);
    let finish: (value: { id: string; status: string; has_result: boolean }) => void = () => {};
    const api = masterfileApi({
      getDeliverable: vi.fn().mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      ),
    });
    renderPanel(api);
    await openMenu();

    const button = screen.getByRole("button", { name: "Response Codes" });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    expect(button.className).toContain("ant-btn-loading");
    expect(screen.getByRole("button", { name: "Page Titles" })).toBeEnabled();
    // A second click on a disabled button starts nothing.
    fireEvent.click(button);
    expect(api.buildMasterfile).toHaveBeenCalledTimes(1);

    await act(async () => {
      finish({ id: "dl-1", status: "succeeded", has_result: true });
    });
    await waitFor(() => expect(button).toBeEnabled());
  });

  it.each([
    [409, "This crawl has no uploaded bundle to build from."],
    [410, "The bundle has expired."],
    [429, "The server is busy building masterfiles. Try again in a moment."],
    [500, "the exporter fell over"],
  ])("says something readable for a %i on the build request", async (status, expected) => {
    const error = vi.spyOn(message, "error").mockImplementation(() => ({}) as never);
    const api = masterfileApi({
      buildMasterfile: vi.fn().mockRejectedValue(new ApiError(status, "the exporter fell over")),
    });
    renderPanel(api);
    await openMenu();

    const button = screen.getByRole("button", { name: "Response Codes" });
    fireEvent.click(button);

    await waitFor(() => expect(error).toHaveBeenCalledWith(expected));
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("reports a build the server marked failed, using its own error", async () => {
    const error = vi.spyOn(message, "error").mockImplementation(() => ({}) as never);
    const api = masterfileApi({
      getDeliverable: vi.fn().mockResolvedValue({
        id: "dl-1",
        status: "failed",
        has_result: false,
        error: "bad bundle",
      }),
    });
    renderPanel(api);
    await openMenu();

    fireEvent.click(screen.getByRole("button", { name: "Response Codes" }));

    await waitFor(() => expect(error).toHaveBeenCalledWith("bad bundle"));
    expect(api.downloadDeliverable).not.toHaveBeenCalled();
  });
});
