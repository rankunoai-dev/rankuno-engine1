import { saveBlob } from "../lib/download";
import type {
  JobTelemetry,
  PageClassificationInput,
  PageClassificationOutput,
} from "../types/schema";
import type {
  CrawlDataAdapter,
  CrawlJobSummary,
  DeliverableRecord,
  DispatchConfirmRequest,
  DispatchPreview,
  DispatchPreviewRequest,
  MasterfileService,
  PerformanceSummary,
  ReconciliationSummary,
  SavedPerformance,
  SavedReconciliation,
  JobProgress,
  JobStatus,
  WorkerJobAccepted,
  WorkerJobView,
  WorkerListView,
  WorkerTemplatesView,
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

/** Mirrors `WorkerJobListView` — the envelope around `GET /workers/jobs`. */
interface WorkerJobListView {
  jobs: WorkerJobView[];
}

export const DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1";

/**
 * Where the engine actually is, honouring the machine-local override.
 *
 * `DEFAULT_API_BASE` is the fallback, not the answer. On a machine where port
 * 8000 belongs to another project the engine runs elsewhere and `.env.local`
 * says so — and a component that reads the constant instead of this builds
 * links to whatever else is on 8000. That is not a 404 an operator can
 * diagnose: the app answers, with someone else's routes.
 *
 * Anything constructing a URL for the browser to follow — a download link, an
 * anchor — must use this. The adapter is already given the resolved base by
 * `App.tsx`, so its own requests are unaffected either way.
 */
export const API_BASE: string = import.meta.env["VITE_API_BASE"] ?? DEFAULT_API_BASE;

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
 * The active session token, or `null` when signed out (ADR 0016).
 *
 * Pushed in by `useAuthStore` through `setAuthToken`, never read from that
 * store directly: `httpAdapter.ts` is API plumbing beneath the store layer —
 * `useCrawlStore` already imports `HttpAdapter` from here — and importing the
 * store back would point that dependency the other way, the same inward-only
 * rule `CLAUDE.md` holds `src/core` to against `src/modules` on the Python
 * side. A module-level binding plus two setters keeps it one-way while still
 * letting every outbound request carry the current token.
 */
let currentToken: string | null = null;

/** What runs when a request comes back `401`. Wired up once, by `useAuthStore`. */
let onSessionExpired: (() => void) | null = null;

/** Called by `useAuthStore` on login, logout, and its start-up restore. */
export function setAuthToken(token: string | null): void {
  currentToken = token;
}

/** Called once by `useAuthStore` to wire up what a dead session should do. */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

/**
 * `fetch`, with the stored session token attached as `Authorization: Bearer
 * <token>` and a `401` treated as a dead session wherever it is felt.
 *
 * `HttpAdapter.request` below is the main caller. `GscAccountsView` and
 * `GscAccountForm` call `fetch` directly instead of going through the class —
 * they predate it — and the routes they call are guarded by ADR 0016 exactly
 * like every job route, so they share this rather than growing a second copy
 * of the same two lines. `403` (a real org-ownership mismatch, not a dead
 * session) is left for the caller to handle like any other non-2xx status;
 * only `401` fires the session-expired callback, matching the server's own
 * distinction between "who are you" and "not your record."
 */
export async function authorizedFetch(url: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (currentToken) headers.set("Authorization", `Bearer ${currentToken}`);
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401) onSessionExpired?.();
  return response;
}

/**
 * Fetch an authenticated export and hand it to the browser as a local file.
 *
 * Every export route this app links to — reconciliation, performance, the
 * worker bundle — has required a bearer token since ADR 0016, and a plain
 * `<a href>` pointing straight at the API cannot carry one: a browser
 * navigation has no mechanism to attach a custom header, so the request
 * arrives with none and the server answers `401`. This is the one place that
 * fetches such a file, so every download link in the app should call it
 * rather than render an `<a href={API_BASE}...}>` of its own.
 *
 * `401` has already fired the shared session-expired handler by the time this
 * throws, the same as any other call through `authorizedFetch`; a caller does
 * not need to handle that status specially. Any other non-2xx is surfaced as
 * an `ApiError` for the caller to show, typically via antd's `message.error`.
 *
 * @param url - Absolute URL to fetch.
 * @param fallbackFilename - Used when the response carries no
 *   `Content-Disposition`, or one this cannot parse. Every server route here
 *   does set it (`server.py`'s `_csv_response` / `_workbook_response`), so
 *   this is normally only reached on an error response or a route this
 *   helper has not been taught about yet.
 */
export async function downloadFile(url: string, fallbackFilename: string): Promise<void> {
  let response: Response;
  try {
    response = await authorizedFetch(url);
  } catch (cause) {
    throw new ApiError(0, "Cannot reach the engine. Is the API server running?", { cause });
  }
  if (!response.ok) {
    throw new ApiError(response.status, await describeFailure(response));
  }
  const filename =
    filenameFromContentDisposition(response.headers.get("Content-Disposition")) ??
    fallbackFilename;
  saveBlob(filename, await response.blob());
}

/** The `filename` an `attachment; filename="..."` `Content-Disposition` names. */
function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match?.[1]?.trim() || null;
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
      response = await authorizedFetch(`${this.baseUrl}${path}`, init);
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
      // Only meaningful on `partial`: `record.error` is also set for `failed`,
      // where the job list already renders it through the ordinary error path.
      stoppedReason: record.status === "partial" ? record.error : null,
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
   * Every URL a finished crawl found, as an `.xlsx` workbook.
   *
   * Bypasses `request` for the same reason as `downloadWorkerBundle`: the
   * body is binary, not JSON. One click from the closed job-row menu — no
   * panel needs to be open first, unlike `reconciliation.xlsx`, which the UI
   * only ever fetches through an `<a href>` inside an already-open panel.
   */
  async downloadUrlList(jobId: string): Promise<Blob> {
    const url = `${this.baseUrl}/jobs/${encodeURIComponent(jobId)}/urls.xlsx`;
    let response: Response;
    try {
      response = await authorizedFetch(url);
    } catch (cause) {
      throw new ApiError(
        0,
        `Cannot reach the engine at ${this.baseUrl}. Is the API server running?`,
        { cause },
      );
    }
    if (!response.ok) {
      throw new ApiError(response.status, await describeFailure(response));
    }
    return response.blob();
  }

  /*
   * -------------------------------------------------------------------------
   * Worker dispatch (ADR 0015). A *different* job system from `/jobs` above:
   * these ids address `/workers/jobs`, and passing one to `getProgress` would
   * 404. Kept adjacent to `reconcileScreamingFrog` because both concern
   * Screaming Frog, and deliberately not merged with it — that route reads a
   * CSV an operator exported by hand, these ones run the crawler.
   * -------------------------------------------------------------------------
   */

  /** Registered desktop workers for this org, with the server's liveness verdict. */
  async listWorkers(): Promise<WorkerListView> {
    return this.request<WorkerListView>("/workers");
  }

  /**
   * What one worker reported it holds locally.
   *
   * Not `/screaming-frog/templates`: that lists the *API host's* own directory,
   * which on a container has no `.seospiderconfig` files in it and is the wrong
   * machine besides.
   */
  async getWorkerTemplates(workerId: string): Promise<WorkerTemplatesView> {
    return this.request<WorkerTemplatesView>(
      `/workers/${encodeURIComponent(workerId)}/templates`,
    );
  }

  /**
   * Mint the approval token. Nothing runs yet.
   *
   * The response carries the server's normalized `seed_url`; `confirmDispatch`
   * must send that value back, not the one the operator typed, or the token is
   * refused with a `403`.
   */
  async previewDispatch(
    workerId: string,
    request: DispatchPreviewRequest,
  ): Promise<DispatchPreview> {
    return this.request<DispatchPreview>(
      `/workers/${encodeURIComponent(workerId)}/dispatch/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
    );
  }

  /** Spend the token and queue the job. `409` when the machine is offline. */
  async confirmDispatch(
    workerId: string,
    request: DispatchConfirmRequest,
  ): Promise<WorkerJobAccepted> {
    return this.request<WorkerJobAccepted>(
      `/workers/${encodeURIComponent(workerId)}/dispatch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
    );
  }

  /**
   * Every Screaming Frog dispatch for this org, newest last as the store
   * returns them.
   *
   * Worth polling rather than caching: this call is also what sweeps jobs
   * abandoned by a daemon that died, so a dashboard that never makes it shows
   * a dead job as "running" forever.
   */
  async listWorkerJobs(): Promise<WorkerJobView[]> {
    const view = await this.request<WorkerJobListView>("/workers/jobs");
    return view.jobs;
  }

  /**
   * A finished job's bundle, as a zip.
   *
   * Bypasses `request` because the body is binary, not JSON. The failure
   * statuses are worth naming: `404` is "never uploaded, or past its retention
   * window", `500` names `WORKER_BUNDLE_ENCRYPTION_SECRET`, and neither ever
   * returns a partial or ciphertext body — so anything that resolves here is a
   * whole, decrypted archive.
   */
  async downloadWorkerBundle(jobId: string): Promise<Blob> {
    const url = `${this.baseUrl}/workers/jobs/${encodeURIComponent(jobId)}/bundle`;
    let response: Response;
    try {
      response = await authorizedFetch(url);
    } catch (cause) {
      throw new ApiError(
        0,
        `Cannot reach the engine at ${this.baseUrl}. Is the API server running?`,
        { cause },
      );
    }
    if (!response.ok) {
      throw new ApiError(response.status, await describeFailure(response));
    }
    return response.blob();
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

  /**
   * Attach a Search Console page export to a finished job.
   *
   * The `File` goes straight to `fetch` as the body — no `FormData`, no
   * base64. The browser streams it, and the server detects the container by
   * reading the first bytes rather than trusting a `Content-Type` that a file
   * picker guessed from an extension.
   *
   * Whatever Search Console produced is accepted: the ZIP from Export → CSV is
   * the default download and the one an analyst actually has.
   */
  async uploadGscExport(jobId: string, export_: Blob): Promise<PerformanceSummary> {
    return this.request<PerformanceSummary>(
      `/jobs/${encodeURIComponent(jobId)}/performance/gsc`,
      {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: export_,
      },
    );
  }

  /**
   * The last Search Console report saved against a job, or `null`.
   *
   * `404` is the ordinary answer for a job nobody has uploaded an export
   * against, and is not an error worth surfacing.
   */
  async getPerformance(jobId: string): Promise<SavedPerformance | null> {
    try {
      return await this.request<SavedPerformance>(
        `/jobs/${encodeURIComponent(jobId)}/performance`,
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) return null;
      throw cause;
    }
  }

  /**
   * Profile names the engine will accept in `gsc_account`, sorted.
   *
   * Not cached: a profile is added by editing `.env.local` and restarting the
   * engine, and a picker holding yesterday's list would offer a name the
   * engine now refuses.
   */
  async listGscAccounts(): Promise<string[]> {
    const view = await this.request<{ accounts: string[] }>("/gsc/accounts");
    return view.accounts;
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

  /**
   * Available masterfile export services, sorted by slug.
   */
  async listAvailableMasterfiles(): Promise<MasterfileService[]> {
    const response = await this.request<{ services: string[] }>("/masterfiles/available");
    return response.services.map((slug) => ({
      slug,
      label: this.masterfileLabel(slug),
      description: this.masterfileDescription(slug),
    }));
  }

  /**
   * Build a masterfile for a finished crawl.
   *
   * Returns the deliverable id to poll.
   */
  async buildMasterfile(jobId: string, serviceSlug: string): Promise<string> {
    const accepted = await this.request<{ id: string }>(
      `/jobs/${encodeURIComponent(jobId)}/masterfile/${encodeURIComponent(serviceSlug)}`,
      { method: "POST" },
    );
    return accepted.id;
  }

  /**
   * Get the status of a deliverable build.
   */
  async getDeliverable(deliverableId: string): Promise<DeliverableRecord> {
    return this.request<DeliverableRecord>(
      `/deliverables/${encodeURIComponent(deliverableId)}`,
    );
  }

  /**
   * Download a finished deliverable as a binary blob.
   *
   * Bypasses `request` for the same reason as `downloadUrlList`: the body is
   * binary, not JSON.
   */
  async downloadDeliverable(deliverableId: string): Promise<Blob> {
    const url = `${this.baseUrl}/deliverables/${encodeURIComponent(deliverableId)}/download`;
    let response: Response;
    try {
      response = await authorizedFetch(url);
    } catch (cause) {
      throw new ApiError(
        0,
        `Cannot reach the engine at ${this.baseUrl}. Is the API server running?`,
        { cause },
      );
    }
    if (!response.ok) {
      throw new ApiError(response.status, await describeFailure(response));
    }
    return response.blob();
  }

  /**
   * Human-readable label for a masterfile service slug.
   *
   * Maps service slugs to friendly display names for menu items.
   */
  private masterfileLabel(slug: string): string {
    const labels: Record<string, string> = {
      response_codes: "Response Codes",
      page_titles: "Page Titles",
      meta_description: "Meta Descriptions",
      h1: "H1 Tags",
      canonicals: "Canonicals",
      directives: "Directives",
      sitemaps: "Sitemaps",
      security: "Security",
      content_issues: "Content Issues",
      duplicate_content: "Duplicate Content",
      functional_internal_links: "Functional Internal Links",
      non_functional_internal_links: "Non-Functional Internal Links",
      pagination: "Pagination",
      lorem_ipsum: "Lorem Ipsum",
      url_issues: "URL Issues",
      custom_search_ga4_gtm: "Custom Search (GA4/GTM)",
      custom_search_og_twitter: "Custom Search (OG/Twitter)",
      hreflang: "hreflang",
      structured_data: "Structured Data",
      custom_extraction: "Custom Extraction",
      overview_report: "Overview Report",
    };
    return labels[slug] ?? slug;
  }

  /**
   * Brief description for a masterfile service slug.
   */
  private masterfileDescription(slug: string): string {
    const descriptions: Record<string, string> = {
      overview_report: "Complete technical SEO overview",
      response_codes: "HTTP status codes for all pages",
      page_titles: "Title tags and analysis",
      meta_description: "Meta descriptions and length checks",
      h1: "H1 tags and uniqueness",
      canonicals: "Canonical tags",
      directives: "Robots and X-Robots headers",
      sitemaps: "Sitemap references",
      security: "SSL/HTTPS configuration",
      content_issues: "Content quality issues",
      duplicate_content: "Duplicate content analysis",
      functional_internal_links: "Working internal links",
      non_functional_internal_links: "Broken internal links",
      pagination: "Pagination markup",
      lorem_ipsum: "Lorem ipsum detection",
      url_issues: "URL structure issues",
      custom_search_ga4_gtm: "GA4 and GTM implementations",
      custom_search_og_twitter: "Open Graph and Twitter Card tags",
      hreflang: "Hreflang implementation",
      structured_data: "Schema.org markup",
      custom_extraction: "Custom data extraction",
    };
    return descriptions[slug] ?? "";
  }
}

/** Pull FastAPI's `detail` out of an error body, falling back to the status. */
export async function describeFailure(response: Response): Promise<string> {
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
