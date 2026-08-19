import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReconciliationSummary } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { ReconcilePanel } from "./ReconcilePanel";

/**
 * The Screaming Frog upload panel.
 *
 * Written because cycle 0029 shipped two defects here that `tsc` and
 * `vite build` both accepted: antd's `Upload` POSTing the file to an endpoint
 * that does not exist, and a size guard that could only work in the browser.
 * Neither is a type error, and neither is visible without mounting the thing.
 */

const SUMMARY: ReconciliationSummary = {
  job_id: "merged-1",
  source_job_id: "job-1",
  base_url: "https://e.com/",
  frog_rows: 120,
  in_both: 90,
  missed_pages: 12,
  orphans: 340,
  merged: 12,
  frog_reasons: { MISSED_PAGE: 12, REDIRECT: 15, OFF_SITE: 3 },
  engine_reasons: { SITEMAP_ORPHAN: 340, QUERY_VARIANT: 7 },
};

/** Replace the store action, and hand back the spy. */
function stubReconcile(result: ReconciliationSummary | null = SUMMARY) {
  const spy = vi.fn().mockResolvedValue(result);
  useCrawlStore.setState({ reconcileScreamingFrog: spy });
  return spy;
}

/** A CSV file of a chosen apparent size, without allocating that many bytes. */
function csvFile(bytes: number, text = "Address,Status Code\nhttps://e.com/,200"): File {
  const file = new File([text], "internal_html.csv", { type: "text/csv" });
  // `size` is read-only on File, and allocating 200 MB to test a size guard
  // would make the suite slower than the thing it is guarding against.
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

function dropFile(container: HTMLElement, file: File): void {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("the dragger rendered no file input");
  fireEvent.change(input, { target: { files: [file] } });
}

function open() {
  return render(
    <ReconcilePanel jobId="job-1" label="e.com" open onClose={() => {}} />,
  );
}

afterEach(() => {
  useUiStore.setState({ view: "visualizer" });
});

describe("ReconcilePanel", () => {
  it("mounts and asks for the export", () => {
    stubReconcile();
    open();
    expect(screen.getByText(/Drop internal_html.csv/)).toBeInTheDocument();
    // Said explicitly on screen, because "upload" reasonably reads as
    // "send my client's crawl to a third party".
    expect(screen.getByText(/read in your browser/)).toBeInTheDocument();
  });

  it("refuses an oversized file without calling the server", async () => {
    /*
     * The guard has to be client-side: `file.text()` on a 200 MB export makes a
     * 200 MB string in the tab, and a crashed tab shows nothing at all — the
     * server's own refusal is never reached because no request is sent.
     */
    const spy = stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(200 * 1_000_000));

    expect(await screen.findByText(/200 MB/)).toBeInTheDocument();
    // And it names the fix rather than only refusing.
    expect(screen.getAllByText(/Internal/).length).toBeGreaterThan(0);
    expect(spy).not.toHaveBeenCalled();
  });

  it("sends the file text for a file within the limit", async () => {
    const spy = stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(2048, "Address\nhttps://e.com/a/"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const [jobId, text] = spy.mock.calls[0]!;
    expect(jobId).toBe("job-1");
    // The text, not a File or FormData: the endpoint takes a `text/csv` body
    // because `python-multipart` is not a dependency of the engine.
    expect(typeof text).toBe("string");
    expect(text).toContain("https://e.com/a/");
  });

  it("never lets antd upload the file itself", async () => {
    /*
     * `Upload.Dragger` POSTs to its `action` prop by default. There is none —
     * the store owns the request — so without `beforeUpload` returning false it
     * fires a silent network error beside a spinner that never stops.
     *
     * Asserted by failing the test if anything reaches `fetch` or `XHR`, which
     * is the observable consequence rather than the implementation detail.
     */
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const xhrOpen = vi.fn();
    vi.stubGlobal(
      "XMLHttpRequest",
      class {
        open = xhrOpen;
        send = vi.fn();
        setRequestHeader = vi.fn();
        upload = {};
        addEventListener = vi.fn();
      },
    );

    const spy = stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(xhrOpen).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows both directions of the gap once it has one", async () => {
    stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    expect(await screen.findByText(/Screaming Frog found, we did not/)).toBeInTheDocument();
    expect(screen.getByText(/We found, Screaming Frog did not/)).toBeInTheDocument();
    // The counts an analyst reads first.
    expect(screen.getAllByText("340").length).toBeGreaterThan(0);
    expect(screen.getByText("Sitemap orphans")).toBeInTheDocument();
  });

  it("translates the reason codes rather than printing the enum alone", async () => {
    /*
     * Of the seven frog-side reasons only `MISSED_PAGE` is a defect. Untranslated,
     * the table reads as a list of failures when most rows are the engine
     * working correctly.
     */
    stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    expect(await screen.findByText(/merged into the tree/)).toBeInTheDocument();
    expect(screen.getByText(/not pages; their destinations are already held/)).toBeInTheDocument();
    expect(screen.getByText(/no internal link reaches them/)).toBeInTheDocument();
  });

  it("says so when there is nothing to merge, instead of implying a new job", async () => {
    stubReconcile({ ...SUMMARY, merged: 0, missed_pages: 0, job_id: "job-1" });
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    expect(await screen.findByText(/Nothing to merge/)).toBeInTheDocument();
    expect(screen.queryByText(/Open merged tree/)).not.toBeInTheDocument();
  });

  it("offers the merged tree only when something merged", async () => {
    stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    expect(await screen.findByText(/Open merged tree/)).toBeInTheDocument();
  });

  it("reports a failed reconciliation instead of hanging on the spinner", async () => {
    // `null` is what the store returns when the adapter cannot reconcile or the
    // request failed. Silence here would leave "Reconciling…" on screen forever.
    stubReconcile(null);
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(1024));

    expect(await screen.findByText(/reconciliation failed/i)).toBeInTheDocument();
  });
});
