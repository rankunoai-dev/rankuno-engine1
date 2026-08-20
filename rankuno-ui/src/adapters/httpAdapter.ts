import type {
  JobTelemetry,
  PageClassificationInput,
  PageClassificationOutput,
} from "../types/schema";
import type {
  CrawlDataAdapter,
  CrawlJobSummary,
  ReconciliationSummary,
  SavedReconciliation,
  JobProgress,
  JobStatus,
} from "./adapterInterface";

/** Mirrors `JobRecord` in `src/core/state_store.py`. */
interface JobRecord {
  id: string;
  tool_name: string;
  label: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  has_result: boolean;
  has_checkpoint: boolean;
  telemetry: JobTelemetry;
}

export const DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1";

/**
 * Polling delays in milliseconds, then the last value repeats forever.
 *
 * Backoff rather than a fixed interval because crawl durations differ by orders
 * of magnitude: a 50-page crawl finishes in seconds and should be noticed
 * immediately, while a 20,000-page crawl runs for hours and polling it every
 * second is ~7,000 pointless requests. Starting fast and slowing down serves
 * both without the caller choosing in advance.
 */
const POLL_SCHEDULE_MS = [500, 1_000, 2_000, 3_000, 5_000] as const;

const TERMINAL: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "succeeded",
  "partial",
  "failed",
]);

/** A failed API call, carrying the HTTP status so callers can branch on it. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApiError";
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Reads crawl data from the local FastAPI server.
 *
 * The counterpart to `MockAdapter`. Components see the same interface, so
 * switching between fixtures and live crawls is one line in `App.tsx`.
 *
 * Results are cached by job id. A finished job is immutable — its status can no
 * longer change — so re-fetching 16 MB when the user switches back to a crawl
 * they already viewed would be pure waste.
 */
export class HttpAdapter implements CrawlDataAdapter {
  private readonly cache = new Map<string, PageClassificationOutput>();

  constructor(private readonly baseUrl: string = DEFAULT_API_BASE) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, init);
    } catch (cause) {
      // fetch rejects only on a transport failure, which here almost always
      // means the server is not running. Say that, rather than surfacing
      // "Failed to fetch" to someone who has no reason to connect the two.
      throw new ApiError(
        0,
        `Cannot reach the engine at ${this.baseUrl}. Is the API server running?`,
        { cause },
      );
    }

    if (!response.ok) {
      throw new ApiError(response.status, await describeFailure(response));
    }
    return (await response.json()) as T;
  }

  async listJobs(): Promise<CrawlJobSummary[]> {
    const records = await this.request<JobRecord[]>("/jobs");
    return records.map((record) => this.toSummary(record));
  }

  private toSummary(record: JobRecord): CrawlJobSummary {
    const cached = this.cache.get(record.id);
    return {
      id: record.id,
      label: record.label || record.id,
      baseUrl: record.label,
      status: record.status,
      // The engine reports no incremental count, so this is 0 until the result
      // exists. Shown as "—" rather than "0 pages", which would read as a
      // finished crawl that found nothing.
      pagesClassified: cached?.summary.pages_classified ?? 0,
      truncated: record.status === "partial",
      synthetic: false,
      // `started_at` is when the crawl actually began; `created_at` is when it
      // was accepted. They differ when a job waits behind the concurrency cap,
      // and a queued job has no start time at all — hence the fallback.
      crawledAt: record.started_at ?? record.created_at,
      hasCheckpoint: record.has_checkpoint,
      recoverable: record.has_checkpoint && !record.has_result,
    };
  }

  /**
   * What a job saved before it was interrupted.
   *
   * Returns the same shape as a finished crawl, so the UI renders it through
   * the ordinary path. Its pages are all `UNKNOWN` and its `stopped_reason`
   * says why — a checkpoint holds URLs, never classifications.
   */
  async getCheckpoint(jobId: string): Promise<PageClassificationOutput> {
    return this.request<PageClassificationOutput>(
      `/jobs/${encodeURIComponent(jobId)}/checkpoint`,
    );
  }

  async getResult(jobId: string): Promise<PageClassificationOutput> {
    const cached = this.cache.get(jobId);
    if (cached) return cached;

    const result = await this.request<PageClassificationOutput>(
      `/jobs/${encodeURIComponent(jobId)}/result`,
    );
    this.cache.set(jobId, result);
    return result;
  }

  async getProgress(jobId: string): Promise<JobProgress> {
    const record = await this.request<JobRecord>(
      `/jobs/${encodeURIComponent(jobId)}`,
    );
    const telemetry = record.telemetry;
    return {
      status: record.status,
      // Real now, from the engine's progress sink — but still `null` until the
      // crawl has discovered enough to have a denominator. An unknown total is
      // not a total of zero, and a bar sitting at 0% says the wrong thing.
      fraction: TERMINAL.has(record.status)
        ? 1
        : telemetry.discovered > 0
          ? Math.min(1, telemetry.completed / telemetry.discovered)
          : null,
      message: describeStatus(record),
      telemetry,
    };
  }

  /**
   * POST an export as `text/csv` and get the gap back.
   *
   * The body is the raw CSV, not `multipart/form-data`: the server accepts it
   * that way because `python-multipart` is not one of its dependencies, and
   * sending the text the browser already read costs nothing.
   */
  async reconcileScreamingFrog(
    jobId: string,
    export_: Blob,
  ): Promise<ReconciliationSummary> {
    return this.request<ReconciliationSummary>(
      `/jobs/${encodeURIComponent(jobId)}/reconcile/screaming-frog`,
      {
        method: "POST",
        // Deliberately generic. The server detects .csv from .xlsx by reading
        // the first bytes, because a Content-Type set by a file picker is
        // whatever the operating system guessed and a renamed file lies.
        headers: { "Content-Type": "application/octet-stream" },
        body: export_,
      },
    );
  }

  /**
   * The last cross-check saved against a job, or `null` if there is none.
   *
   * A reconciliation costs an export somebody produced by hand in another tool,
   * and it used to live only in this dialog's state — closing it threw the
   * result away. `404` is the ordinary answer for a job nobody has cross-checked
   * and is not an error worth surfacing.
   */
  async getReconciliation(jobId: string): Promise<SavedReconciliation | null> {
    try {
      return await this.request<SavedReconciliation>(
        `/jobs/${encodeURIComponent(jobId)}/reconciliation`,
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) return null;
      throw cause;
    }
  }

  async startJob(request: PageClassificationInput): Promise<string> {
    const accepted = await this.request<{ id: string }>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    return accepted.id;
  }

  /**
   * Abandon a running job and give its concurrency slot back.
   *
   * **Releases the slot; does not stop the crawl.** The work runs on a server
   * worker thread that cannot be interrupted from outside, so it keeps fetching
   * until it finishes or the server restarts, and its result is discarded.
   *
   * Worth having anyway: a crawl wedged in network I/O holds a slot
   * indefinitely, and with three slots that is a server which refuses new work
   * while doing none. This restores the ability to crawl; it does not free the
   * bandwidth.
   */
  async cancelJob(jobId: string): Promise<void> {
    await this.request(`/jobs/${jobId}/cancel`, { method: "POST" });
  }

  /**
   * Run a finished job's crawl again with the settings it originally used.
   *
   * Returns the *new* job's id. The engine never mutates the original: its
   * record is the evidence of what ran and when, and a failed crawl is often
   * the finding itself.
   */
  async retryJob(jobId: string): Promise<string> {
    const accepted = await this.request<{ id: string }>(`/jobs/${jobId}/retry`, {
      method: "POST",
    });
    return accepted.id;
  }

  /**
   * Crawl the URLs an interrupted job discovered but never fetched.
   *
   * Returns a new job id. This does **not** merge into the original result —
   * inbound link counts and orphan flags are properties of the whole graph, and
   * a checkpoint holds URLs only, so a merged report would carry wrong numbers
   * for the finding operators rely on most.
   */
  async resumeJob(jobId: string): Promise<string> {
    const accepted = await this.request<{ id: string }>(`/jobs/${jobId}/resume`, {
      method: "POST",
    });
    return accepted.id;
  }

  /**
   * Poll until the job reaches a terminal status, then return its record.
   *
   * Stops the instant the status is terminal rather than after one more
   * interval, so a fast crawl is not made to look slow by the poller.
   *
   * @param signal - Abort to stop polling, e.g. when the user navigates away.
   *   Without it a closed modal would keep issuing requests indefinitely.
   */
  async waitForCompletion(
    jobId: string,
    onProgress?: (progress: JobProgress) => void,
    signal?: AbortSignal,
  ): Promise<JobProgress> {
    for (let attempt = 0; ; attempt += 1) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

      const progress = await this.getProgress(jobId);
      onProgress?.(progress);
      if (TERMINAL.has(progress.status)) return progress;

      const index = Math.min(attempt, POLL_SCHEDULE_MS.length - 1);
      await delay(POLL_SCHEDULE_MS[index] ?? 5_000);
    }
  }
}

/** Pull FastAPI's `detail` out of an error body, falling back to the status. */
async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // A non-JSON error body is not itself an error worth reporting; the status
    // line below is more useful than a parse failure would be.
  }
  return `${response.status} ${response.statusText}`;
}

/** A sentence an operator can act on, for each job state. */
function describeStatus(record: JobRecord): string {
  switch (record.status) {
    case "queued":
      return "Waiting for a free crawl slot.";
    case "running":
      return "Crawling. Large sites can take a long time at polite request rates.";
    case "succeeded":
      return "Crawl complete.";
    case "partial":
      return "Crawl stopped at its page ceiling — results are incomplete.";
    case "failed":
      return record.error ?? "The crawl failed.";
    default:
      return "";
  }
}
