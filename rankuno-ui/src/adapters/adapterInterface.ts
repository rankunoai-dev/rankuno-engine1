import type { PageClassificationOutput } from "../types/schema";

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
}

/** Progress of a running job. */
export interface JobProgress {
  status: JobStatus;
  /** 0..1, or null when the total is not yet known — the normal early state. */
  fraction: number | null;
  message: string;
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
}
