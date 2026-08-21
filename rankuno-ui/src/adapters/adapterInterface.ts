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
   * Partial work was saved, whether or not a result also exists.
   *
   * Distinct from `recoverable`, which means "saved work and *no* result, so
   * offer the partial tree". A crawl that hit its ceiling has both a result and
   * a checkpoint: there is nothing to recover, but there is something to
   * resume.
   */
  hasCheckpoint: boolean;
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
 * What a Screaming Frog reconciliation found, and what it did about it.
 *
 * Mirrors `ReconciliationSummary` in `src/api/server.py`. Hand-written rather
 * than generated: `schema.ts` covers the crawl contract, and this belongs to
 * the API layer, which the exporter does not read.
 */
export interface ReconciliationSummary {
  /** The merged result. Equals `source_job_id` when nothing was merged. */
  job_id: string;
  source_job_id: string;
  base_url: string;
  frog_rows: number;
  in_both: number;
  /** Live, in-scope pages the engine never reached. These were merged. */
  missed_pages: number;
  /** Published pages no internal link reaches. Left where they are. */
  orphans: number;
  merged: number;
  frog_reasons: Record<string, number>;
  engine_reasons: Record<string, number>;
}

/**
 * A cross-check saved against a job, with the URLs behind the counts.
 *
 * Mirrors what `GET /jobs/{id}/reconciliation` returns. The lists are the point:
 * "892 missed pages" is the headline and the 892 addresses are the work, and
 * before this existed both were lost the moment the dialog closed.
 */
export interface SavedReconciliation {
  summary: ReconciliationSummary;
  created_at: string;
  missed_pages: string[];
  orphans: string[];
  frog_only: { url: string; reason: string }[];
  engine_only: { url: string; reason: string }[];
}

/**
 * Totals for one navigation section and everything beneath it.
 *
 * Mirrors `SectionPerformance` in `src/modules/seo/performance/schemas.py`.
 * Hand-written for the same reason as `ReconciliationSummary`: this reaches the
 * UI through the API layer, which the contract exporter does not read.
 *
 * `path` is the identity, not `label`. Up to 68 labels per crawl are reused
 * under different parents, so keying a row by its label merges unrelated
 * sections.
 */
export interface SectionPerformance {
  path: string[];
  label: string;
  depth: number;
  pages: number;
  /** How many of those pages any export row reached. */
  pages_with_data: number;
  /** Pages whose trail is exactly `path`, excluding descendants. */
  direct_pages: number;
  direct_clicks: number;
  clicks: number;
  impressions: number;
  /** Impression-weighted. `null` when the subtree drew no impressions — never
   *  `0`, which would read as better than rank 1. */
  position: number | null;
  sessions: number;
  engaged_sessions: number;
  engagement_time_sec: number;
  conversions: number;
  revenue: number;
  ctr: number;
  data_coverage: number;
}

/** One ranked recommendation. Mirrors `Opportunity` in the scorer. */
export interface Opportunity {
  kind: string;
  url: string;
  section: string[];
  /** Rank within this kind, 0-100. Not comparable across kinds. */
  score: number;
  clicks: number;
  impressions: number;
  position: number | null;
  inbound_internal_links: number;
  reference_url: string | null;
  reason: string;
}

/** Mirrors `OpportunityReport`. */
export interface OpportunityReport {
  opportunities: Opportunity[];
  found: Record<string, number>;
  /** How many of each kind the cap dropped. */
  truncated: Record<string, number>;
  /** Kinds not evaluated, and why. Absence of a finding is not absence of one. */
  skipped: Record<string, string>;
  limit_per_kind: number;
}

/**
 * What a Search Console upload produced against one crawl.
 *
 * Mirrors `PerformanceSummary` in `src/api/server.py`. The resolution figures
 * come first here as they do there: every total below them is derived from a
 * join, and a reader who sees the sections without knowing a third of the
 * export failed to resolve is reading a confident understatement.
 */
export interface PerformanceSummary {
  job_id: string;
  base_url: string;
  /** The archive entry or worksheet the rows came from. */
  source_name: string;
  rows: number;
  skipped_rows: number;
  matched: number;
  match_rate_pct: number;
  is_reliable: boolean;
  /** Against `pages`, the coverage question the match rate cannot answer. */
  pages_with_data: number;
  pages: number;
  rollup: {
    site: SectionPerformance;
    sections: SectionPerformance[];
    unattributed: { rows: number; clicks: number; impressions: number; sessions: number };
    attributed_share: number;
  };
  opportunities: OpportunityReport;
}

/** A performance report saved against a job. */
export interface SavedPerformance {
  summary: PerformanceSummary;
  created_at: string;
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
   * Cross-check a finished job against a Screaming Frog export.
   *
   * Optional on the interface, like `startJob`: fixtures cannot reconcile, and
   * a UI that offers the control then fails on click is worse than one that
   * hides it.
   */
  reconcileScreamingFrog?(jobId: string, export_: Blob): Promise<ReconciliationSummary>;

  /** The last cross-check saved against a job, or `null` if there is none. */
  getReconciliation?(jobId: string): Promise<SavedReconciliation | null>;

  /**
   * Attach a Search Console page export to a finished job.
   *
   * Optional like `reconcileScreamingFrog`, and for the same reason: fixtures
   * have no Search Console data, and a control that fails on click is worse
   * than one that is not there.
   */
  uploadGscExport?(jobId: string, export_: Blob): Promise<PerformanceSummary>;

  /** The last Search Console report saved against a job, or `null`. */
  getPerformance?(jobId: string): Promise<SavedPerformance | null>;

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
  // Empty for an operator-started crawl. Only a resume supplies these, and the
  // engine builds that request itself from the original job's checkpoint —
  // there is no UI control for it, and there should not be: a hand-typed seed
  // list is not a resume, it is a different crawl.
  seed_urls: [],
  // Empty for anything an operator starts. Only a resume fills this, and the
  // engine derives it from the interrupted job's checkpoint — there is no UI
  // control for it, and there should not be: hand-typing "do not fetch these"
  // is not a resume.
  exclude_urls: [],
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
