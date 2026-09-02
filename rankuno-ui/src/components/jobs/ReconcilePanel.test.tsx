import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ReconciliationSummary,
  SavedReconciliation,
} from "../../adapters/adapterInterface";
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

/** A stored cross-check, with the addresses behind each figure. */
function saved(overrides: Partial<SavedReconciliation> = {}): SavedReconciliation {
  return {
    summary: SUMMARY,
    created_at: "2026-08-21T12:00:00Z",
    missed_pages: ["https://e.com/missed-a/", "https://e.com/missed-b/"],
    orphans: ["https://e.com/orphan/"],
    in_both: ["https://e.com/shared/"],
    frog_only: [{ url: "https://e.com/frog/", reason: "MISSED_PAGE" }],
    engine_only: [{ url: "https://e.com/ours/", reason: "SITEMAP_ORPHAN" }],
    ...overrides,
  };
}

function stubSaved(value: SavedReconciliation | null) {
  useCrawlStore.setState({
    adapter: { getReconciliation: vi.fn().mockResolvedValue(value) },
  } as never);
}

/** Capture a download without writing a file. */
function stubDownload() {
  const clicked = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  return clicked;
}

afterEach(() => {
  useUiStore.setState({ view: "visualizer" });
  vi.restoreAllMocks();
});

describe("per-figure downloads", () => {
  it("offers a file for every figure whose addresses were recorded", async () => {
    stubReconcile();
    stubSaved(saved());
    open();

    // Pages we missed (2), Sitemap orphans (1), Found by both (1), and one per
    // gap table. Each is labelled with its own count, so a reader can tell
    // which figure a button belongs to without reading the tile above it.
    expect(await screen.findByRole("button", { name: "Download 2" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Download 1" }).length).toBeGreaterThan(1);
  });

  it("writes the URLs of the figure that was clicked", async () => {
    const clicked = stubDownload();
    stubReconcile();
    stubSaved(saved());
    open();

    fireEvent.click(await screen.findByRole("button", { name: "Download 2" }));
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it("says why the agreement has no file on a cross-check saved before it was kept", async () => {
    /*
     * Every sidecar written before `in_both` was stored omits it — the
     * intersection was counted and discarded. Showing no button and no reason
     * on one tile of four reads as a defect in the app; showing an empty file
     * would be a lie about the site.
     */
    stubReconcile();
    stubSaved(saved({ in_both: undefined }));
    open();

    expect(await screen.findByText(/re-run the cross-check to list these/)).toBeInTheDocument();
  });

  it("gives each gap a workbook split by reason, not a flat list", async () => {
    /*
     * The two gap tables hold several reasons each — SITEMAP_ORPHAN beside
     * QUERY_VARIANT, REDIRECT beside MISSED_PAGE. A single sheet mixing them is
     * what the reader has to sort out by hand, so these point at the workbook
     * endpoint with the side they own rather than building a CSV here.
     */
    stubReconcile();
    stubSaved(saved());
    open();

    const links = await screen.findAllByRole("link", { name: /^Download 1$/ });
    const targets = links.map((link) => link.getAttribute("href") ?? "");
    expect(targets.some((href) => href.includes("reconciliation.xlsx?side=frog"))).toBe(true);
    expect(targets.some((href) => href.includes("reconciliation.xlsx?side=engine"))).toBe(true);
  });

  it("never offers the export back as a download", async () => {
    // 23,500 rows the analyst uploaded themselves. Storing them to hand back
    // their own file would double the sidecar for nothing.
    stubReconcile();
    stubSaved(saved());
    open();

    expect(await screen.findByText("your own export")).toBeInTheDocument();
  });
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

  it("sends the file itself, not its text", async () => {
    const spy = stubReconcile();
    const { baseElement } = open();
    dropFile(baseElement as HTMLElement, csvFile(2048, "Address\nhttps://e.com/a/"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const [jobId, body] = spy.mock.calls[0]!;
    expect(jobId).toBe("job-1");
    // A Blob, not a string. Screaming Frog also exports .xlsx, and reading a
    // workbook with `file.text()` turns it into mojibake the server cannot
    // parse. Handing `fetch` the Blob also lets the browser stream it rather
    // than holding a second copy of a 50 MB export in memory.
    //
    // Still not FormData: the endpoint takes a raw body because
    // `python-multipart` is not a dependency of the engine.
    expect(body).toBeInstanceOf(Blob);
    expect(await (body as Blob).text()).toContain("https://e.com/a/");
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
