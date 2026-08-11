import { create } from "zustand";
import type {
  CrawlDataAdapter,
  CrawlJobSummary,
  JobStatus,
} from "../adapters/adapterInterface";
import { HttpAdapter } from "../adapters/httpAdapter";
import type {
  JobTelemetry,
  PageClassificationInput,
  PageClassificationOutput,
} from "../types/schema";

interface CrawlState {
  adapter: CrawlDataAdapter | null;

  jobs: CrawlJobSummary[];
  activeJobId: string | null;
  status: JobStatus;
  error: string | null;

  result: PageClassificationOutput | null;
  /** How the tree is grouped. Navigation mirrors the site's own header menu. */
  grouping: "navigation" | "path";

  /** Message shown while a live crawl runs, or null when none is running. */
  liveMessage: string | null;
  /** Live counters while a crawl runs. Null when none is. */
  telemetry: JobTelemetry | null;
  /** Wall-clock seconds since the running crawl was submitted. */
  startedAt: number | null;

  setGrouping: (grouping: "navigation" | "path") => void;
  init: (adapter: CrawlDataAdapter) => Promise<void>;
  selectJob: (jobId: string) => Promise<void>;
  startCrawl: (request: PageClassificationInput) => Promise<void>;
  refreshJobs: () => Promise<void>;
  loadCheckpoint: (jobId: string) => Promise<void>;
}

/*
 * This store owns the *crawl*: which job is selected, its result, and the
 * lifecycle of starting a new one. Everything about how that result is
 * displayed — expansion, focus, filters, search — belongs to
 * `useDashboardStore`, which derives it from `result`.
 *
 * The split matters because the derived structures are expensive at 20,000
 * pages. Keeping them here meant rebuilding them on every job-status change.
 */

export const useCrawlStore = create<CrawlState>((set, get) => ({
  adapter: null,

  jobs: [],
  activeJobId: null,
  status: "idle",
  error: null,
  liveMessage: null,
  telemetry: null,
  startedAt: null,

  result: null,
  grouping: "navigation",

  async init(adapter) {
    set({ adapter, status: "queued", error: null });
    try {
      const jobs = await adapter.listJobs();
      set({ jobs, status: "idle" });
      const first = jobs[0];
      if (first) await get().selectJob(first.id);
    } catch (cause) {
      set({ status: "failed", error: describe(cause) });
    }
  },

  async selectJob(jobId) {
    const adapter = get().adapter;
    if (!adapter) return;

    // Cleared immediately. Leaving the previous crawl on screen under a new
    // job's label is how a user ends up reading one site's structure while
    // believing they are looking at another.
    set({
      activeJobId: jobId,
      status: "running",
      error: null,
      result: null,
    });

    try {
      const result = await adapter.getResult(jobId);
      set({
        result,
        // Navigation grouping needs a menu to group by. Falling back to the path
        // view when none was parsed is the honest default: with no menu there is
        // no published structure, and one OTHERS bucket holding the whole site
        // is worse than the path view it replaced.
        grouping: result.navigation.roots.length > 0 ? get().grouping : "path",
        // `partial` is not an error. Every live crawl so far hit a ceiling, and
        // presenting truncated data as complete is the failure mode that
        // matters here.
        status: result.discovery.truncated ? "partial" : "succeeded",
      });
    } catch (cause) {
      set({ status: "failed", error: describe(cause) });
    }
  },

  async refreshJobs() {
    const adapter = get().adapter;
    if (!adapter) return;
    try {
      set({ jobs: await adapter.listJobs() });
    } catch (cause) {
      set({ error: describe(cause) });
    }
  },

  async startCrawl(request) {
    const adapter = get().adapter;
    if (!adapter?.startJob) {
      set({ error: "This data source cannot start crawls." });
      return;
    }

    set({
      status: "queued",
      error: null,
      liveMessage: "Submitting…",
      result: null,
      telemetry: null,
      startedAt: Date.now(),
    });

    try {
      const jobId = await adapter.startJob(request);
      set({ activeJobId: jobId });
      await get().refreshJobs();

      // Polling is delegated to the adapter, which owns the backoff schedule.
      // Duplicating the interval here would let the two drift apart.
      const progress =
        adapter instanceof HttpAdapter
          ? await adapter.waitForCompletion(jobId, (update) => {
              set({
                status: update.status,
                liveMessage: update.message,
                telemetry: update.telemetry ?? null,
              });
            })
          : await adapter.getProgress(jobId);

      set({ liveMessage: null, telemetry: null, startedAt: null });

      if (progress.status === "failed") {
        set({ status: "failed", error: progress.message });
        await get().refreshJobs();
        return;
      }

      // `selectJob` fetches the result and rebuilds every derived structure, so
      // a finished live crawl lands in exactly the same state as a selected one.
      await get().selectJob(jobId);
      await get().refreshJobs();
    } catch (cause) {
      set({
        status: "failed",
        error: describe(cause),
        liveMessage: null,
        telemetry: null,
        startedAt: null,
      });
    }
  },

  async loadCheckpoint(jobId) {
    const adapter = get().adapter;
    if (!(adapter instanceof HttpAdapter)) return;

    set({ status: "running", error: null, result: null, activeJobId: jobId });
    try {
      const result = await adapter.getCheckpoint(jobId);
      set({
        result,
        // `partial`, never `succeeded`. The tree is real; the classifications
        // in it are placeholders, and the banner reads off `stopped_reason`.
        status: "partial",
        grouping: "path",
      });
    } catch (cause) {
      set({ status: "failed", error: describe(cause) });
    }
  },

  setGrouping(grouping) {
    // Only the flag is stored. `DashboardShell` rebuilds its model from
    // `result` and `grouping`, so there is no derived state here to keep in
    // step — which is what made the previous version easy to leave stale.
    set({ grouping });
  },
}));

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

