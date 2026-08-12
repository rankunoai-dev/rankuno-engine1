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

/**
 * A crawl this browser session started and is still watching.
 *
 * Separate from `CrawlJobSummary`, which is what the server reports about every
 * job that ever ran. This is the live half: telemetry the job list does not
 * carry, and a start time that belongs to the session rather than the record.
 */
export interface LiveJob {
  id: string;
  /** The crawl target, shown before the server has a label for it. */
  label: string;
  status: JobStatus;
  message: string;
  telemetry: JobTelemetry | null;
  /** `Date.now()` at submission, for the elapsed clock. */
  startedAt: number;
  /** Set once the job reaches a terminal status, for the elapsed clock. */
  endedAt: number | null;
  /** Failure reason, when the crawl ended badly. */
  error: string | null;
}

/** Statuses a job can still leave. */
const LIVE: ReadonlySet<JobStatus> = new Set<JobStatus>(["queued", "running"]);

/** Whether a job is still going. */
export function isLive(job: LiveJob): boolean {
  return LIVE.has(job.status);
}

/**
 * The most recently started crawl still running, or `null`.
 *
 * Returns the stored entry itself rather than a derived object, so a zustand
 * selector wrapping this compares by reference and does not re-render every
 * subscriber on each unrelated store write.
 *
 * The header shows one crawl, not all of them: three concurrent runs in a
 * header strip is a status board, and the jobs view is where that belongs. The
 * newest is chosen because it is the one the operator just started and is
 * waiting on.
 */
export function newestLiveJob(liveJobs: Readonly<Record<string, LiveJob>>): LiveJob | null {
  let newest: LiveJob | null = null;
  for (const job of Object.values(liveJobs)) {
    if (isLive(job) && (newest === null || job.startedAt > newest.startedAt)) newest = job;
  }
  return newest;
}

interface CrawlState {
  adapter: CrawlDataAdapter | null;

  jobs: CrawlJobSummary[];
  activeJobId: string | null;
  status: JobStatus;
  error: string | null;

  result: PageClassificationOutput | null;
  /** How the tree is grouped. Navigation mirrors the site's own header menu. */
  grouping: "navigation" | "path";

  /**
   * Crawls started this session, keyed by job id.
   *
   * A map rather than a single "the running crawl", because the engine permits
   * three concurrent jobs and the operator can start all three. The previous
   * single-slot model silently overwrote the first crawl's telemetry with the
   * second's, which looked like the first one stalling.
   *
   * Entries are kept after completion: they hold the only copy of the live
   * telemetry, and the jobs view shows a run that just finished alongside the
   * ones still going.
   */
  liveJobs: Record<string, LiveJob>;

  setGrouping: (grouping: "navigation" | "path") => void;
  init: (adapter: CrawlDataAdapter) => Promise<void>;
  selectJob: (jobId: string) => Promise<void>;
  /** Submit a crawl and return its id. Resolves at submission, not completion. */
  startCrawl: (request: PageClassificationInput) => Promise<string | null>;
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
 *
 * Two lifecycles, deliberately not one
 * ------------------------------------
 * `status`/`result`/`activeJobId` describe **what is on screen**. `liveJobs`
 * describes **what is running**. They used to be the same fields, which is why
 * starting a crawl blanked the dashboard: `startCrawl` set `result: null` and
 * drove the global status through the crawl's whole lifetime, so a twenty-minute
 * crawl meant twenty minutes of being unable to read the site you crawled
 * yesterday. Keeping them apart is the whole of the non-blocking change; the
 * modal was only the visible symptom.
 */

export const useCrawlStore = create<CrawlState>((set, get) => ({
  adapter: null,

  jobs: [],
  activeJobId: null,
  status: "idle",
  error: null,
  liveJobs: {},

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
      return null;
    }

    let jobId: string;
    try {
      jobId = await adapter.startJob(request);
    } catch (cause) {
      // A rejected submission is the one crawl error that belongs on the
      // dashboard: there is no job yet, so the jobs view has nothing to show it
      // against. Everything after this point is reported on the job's own row.
      set({ error: describe(cause) });
      return null;
    }

    patchLiveJob(jobId, {
      label: request.base_url,
      status: "queued",
      message: "Waiting for a free crawl slot.",
      telemetry: null,
      startedAt: Date.now(),
      endedAt: null,
      error: null,
    });
    await get().refreshJobs();

    // Deliberately not awaited. This is the line that makes crawling
    // non-blocking: the caller — a modal's submit handler — returns now, and
    // the poll below keeps running against the store for the crawl's lifetime.
    void watchJob(get, adapter, jobId);

    return jobId;
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

type Getter = () => CrawlState;

/**
 * Merge a patch into one live job without disturbing the others.
 *
 * Uses `setState`'s functional form rather than the closed-over `set`, because
 * two concurrent crawls have two independent pollers writing to this map: a
 * read-modify-write over a captured snapshot would let the slower one restore
 * the faster one's previous telemetry.
 *
 * A fresh object per update, because zustand compares by reference and
 * mutating the entry in place would leave every subscriber unrendered — the
 * progress bar would sit still while the numbers behind it moved.
 */
function patchLiveJob(jobId: string, patch: Partial<LiveJob>): void {
  useCrawlStore.setState((state) => {
    const existing = state.liveJobs[jobId];
    const next: LiveJob = existing
      ? { ...existing, ...patch }
      : {
          id: jobId,
          label: patch.label ?? jobId,
          status: patch.status ?? "queued",
          message: patch.message ?? "",
          telemetry: patch.telemetry ?? null,
          startedAt: patch.startedAt ?? Date.now(),
          endedAt: patch.endedAt ?? null,
          error: patch.error ?? null,
        };
    return { liveJobs: { ...state.liveJobs, [jobId]: next } };
  });
}

/**
 * Poll one crawl to completion, writing progress onto its own entry.
 *
 * Never touches `result` or the global `status`. A crawl finishing does not
 * change what the operator is looking at; it posts a notification and waits to
 * be asked. Jumping the view to a freshly finished crawl would discard whatever
 * analysis was in progress, which is the behaviour this replaced.
 */
async function watchJob(
  get: Getter,
  adapter: CrawlDataAdapter,
  jobId: string,
): Promise<void> {
  try {
    const progress =
      adapter instanceof HttpAdapter
        ? await adapter.waitForCompletion(jobId, (update) => {
            patchLiveJob(jobId, {
              status: update.status,
              message: update.message,
              telemetry: update.telemetry ?? null,
            });
          })
        : await adapter.getProgress(jobId);

    patchLiveJob(jobId, {
      status: progress.status,
      message: progress.message,
      telemetry: progress.telemetry ?? null,
      endedAt: Date.now(),
      error: progress.status === "failed" ? progress.message : null,
    });
  } catch (cause) {
    patchLiveJob(jobId, {
      status: "failed",
      message: describe(cause),
      endedAt: Date.now(),
      error: describe(cause),
    });
  }
  // Refreshed whichever way the crawl ended, so the row picks up
  // `recoverable` and the server's own status for a job that failed with a
  // checkpoint on disk.
  await get().refreshJobs();
}

