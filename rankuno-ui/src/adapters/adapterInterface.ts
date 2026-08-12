import type {
  JobTelemetry,
  PageClassificationInput,
  PageClassificationOutput,
} from "../types/schema";

/**
 * Lifecycle of a crawl job.
 *
 * Modelled now, while the only adapter reads a static file, because a crawl is
 * inherently long-running: 300 pages took 79 seconds live, and 20,000 pages at
 * polite per-host rates is hours. It can never be a request/response fetch.
 *
 * Building the store synchronously and retrofitting async later would mean
 * rewriting every component that touches crawl state.
 */
export type JobStatus = "idle" | "queued" | "running" | "succeeded" | "failed" | "partial";

/** A crawl the user can select. Summary only — the payload may be megabytes. */
export interface CrawlJobSummary {
  id: string;
  label: string;
  baseUrl: string;
  status: JobStatus;
  /** Pages classified so far. Meaningful while `running`. */
  pagesClassified: number;
  /** True when a ceiling stopped discovery early. Every live crawl so far. */
  truncated: boolean;
  /** Generated rather than crawled. Never quote a synthetic run as evidence. */
  synthetic: boolean;
  /**
   * When the crawl started, ISO-8601, or null if the source recorded none.
   *
   * Nullable rather than defaulted to "now": a bundled fixture was never
   * crawled, and giving it a timestamp would make generated data look like a
   * run that happened.
   */
  crawledAt: string | null;
  /**
   * Partial work survived an interruption and can be rendered.
   *
   * Only meaningful when there is no full result: a finished crawl needs no
   * recovery.
   */
  recoverable?: boolean;
}

/** Progress of a running job. */
export interface JobProgress {
  status: JobStatus;
  /** 0..1, or null when the total is not yet known — the normal early state. */
  fraction: number | null;
  message: string;
  /** Live counters. Absent from adapters that read finished files. */
  telemetry?: JobTelemetry;
}

/**
 * How the UI reaches crawl data.
 *
 * One interface, two implementations: `MockAdapter` today, an HTTP adapter when
 * the API exists. Components must never import fixture data directly, or the
 * swap becomes a rewrite instead of a line in `main.tsx`.
 */
export interface CrawlDataAdapter {
  /** Crawls available to select. */
  listJobs(): Promise<CrawlJobSummary[]>;

  /**
   * Full result for one job.
   *
   * Returns partial results for a `partial` job rather than throwing: a
   * truncated crawl is the normal case, and refusing to display it would hide
   * the majority of real runs.
   */
  getResult(jobId: string): Promise<PageClassificationOutput>;

  /**
   * Poll a running job.
   *
   * Present on the interface even though the mock resolves instantly, so
   * components are written against polling from the start.
   */
  getProgress(jobId: string): Promise<JobProgress>;

  /**
   * Start a new crawl, returning its job id.
   *
   * Optional, and that is the point: `MockAdapter` reads files that were
   * generated ahead of time and genuinely cannot start anything. Declaring it
   * required would force the mock to implement a method that throws, and the UI
   * would have no way to know before calling. Absent here means the "start a
   * crawl" control is simply not rendered.
   *
   * Resolves as soon as the job is *accepted*. Nothing has been crawled yet —
   * poll `getProgress` until the status is terminal.
   */
  startJob?(request: PageClassificationInput): Promise<string>;
}

/**
 * How hard to push the target server.
 *
 * The rate is per host, and a declared `Crawl-delay` is combined with it using
 * `min` — a site asking to be crawled slowly is never sped up by picking Turbo.
 *
 * Polite is the default because most crawls are of somebody else's server.
 * Turbo is a choice to make about a site you own or have permission to crawl at
 * that rate; it is not a free speed-up.
 */
export interface CrawlSpeed {
  key: "polite" | "standard" | "turbo";
  label: string;
  detail: string;
  rate_limit_rps: number;
  concurrency: number;
}

export const CRAWL_SPEEDS: readonly CrawlSpeed[] = [
  {
    key: "polite",
    label: "Polite",
    detail: "1 req/sec · safe on any site you do not own",
    rate_limit_rps: 1,
    concurrency: 5,
  },
  {
    key: "standard",
    label: "Standard",
    detail: "10 req/sec · typical for a site you manage",
    rate_limit_rps: 10,
    concurrency: 20,
  },
  {
    key: "turbo",
    label: "Turbo",
    detail: "25 req/sec · real load on the target — own the site or have permission",
    rate_limit_rps: 25,
    concurrency: 50,
  },
];

/**
 * Sensible defaults for a live crawl, matching the Pydantic model's own.
 *
 * `max_depth: null` is unlimited — bounded by `max_pages`, not by depth.
 */
export const DEFAULT_CRAWL_REQUEST: PageClassificationInput = {
  base_url: "",
  max_pages: 500,
  rate_limit_rps: null,
  max_depth: null,
  crawl_dom: true,
  respect_robots: true,
  llm_spend_cap_usd: 0,
  user_agent: "RankunoBot",
  browser_headers: false,
  concurrency: 5,
  use_async_crawl: true,
  dom_reserve_fraction: 0.2,
};
