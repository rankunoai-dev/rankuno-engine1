import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { message } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import type { CrawlJobSummary } from "../../adapters/adapterInterface";
import { HttpAdapter } from "../../adapters/httpAdapter";
import { saveBlob } from "../../lib/download";
import { useCrawlStore } from "../../store/useCrawlStore";
import { CrawlJobsView } from "./CrawlJobsView";

/**
 * The job-row downloads driven through a real `HttpAdapter`, not a mock object.
 *
 * `CrawlJobsView.test.tsx` builds its adapter as a plain object of `vi.fn()`s.
 * A plain function never reads `this`, so those tests passed while production
 * threw "Cannot read properties of undefined (reading 'baseUrl')": the view
 * had selected `state.adapter?.downloadUrlList` out of the store and called it
 * detached from the instance. Only a real class instance, whose methods read
 * `this.baseUrl`, exposes that. Any component that calls adapter methods
 * should have one test in this shape; only `fetch` and the save are stubbed.
 */

vi.mock("../../lib/download", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/download")>()),
  saveBlob: vi.fn(),
}));

const API = "http://engine.test";

const JOB: CrawlJobSummary = {
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

let fetchMock: ReturnType<typeof vi.fn>;
let errorToast: MockInstance<typeof message.error>;

beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(new Blob(["bytes"]), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  errorToast = vi.spyOn(message, "error");
  useCrawlStore.setState({ jobs: [JOB], liveJobs: {}, adapter: new HttpAdapter(API) });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(saveBlob).mockReset();
  useCrawlStore.setState({ jobs: [], liveJobs: {}, adapter: null });
});

async function clickMenuItem(label: string): Promise<void> {
  render(<CrawlJobsView />);
  fireEvent.click(screen.getByRole("button", { name: /more actions for this crawl/i }));
  fireEvent.click(await screen.findByText(label));
}

/** Wait until the click has either saved a file or raised a toast. */
async function settled(): Promise<void> {
  await waitFor(() =>
    expect(vi.mocked(saveBlob).mock.calls.length + errorToast.mock.calls.length).toBe(1),
  );
}

describe("CrawlJobsView downloads through a real HttpAdapter", () => {
  it("Download URLs requests urls.xlsx and saves it", async () => {
    await clickMenuItem("Download URLs");

    await settled();
    expect(errorToast).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(`${API}/jobs/job-1/urls.xlsx`, expect.anything());
    expect(vi.mocked(saveBlob).mock.calls[0]?.[0]).toBe("urls-job-1-2026-09-11.xlsx");
  });

  it("Download URLs (PDF) requests urls.pdf and saves it", async () => {
    await clickMenuItem("Download URLs (PDF)");

    await settled();
    expect(errorToast).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(`${API}/jobs/job-1/urls.pdf`, expect.anything());
    expect(vi.mocked(saveBlob).mock.calls[0]?.[0]).toBe("urls-job-1-2026-09-11.pdf");
  });
});
