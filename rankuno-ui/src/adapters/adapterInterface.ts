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
  /**
   * Why a `partial` crawl stopped early, when it was a stall or an aborted
   * crawl rather than the page ceiling — mirrors `JobRecord.error` on the
   * server, which carries `DiscoveryReport.stopped_reason` verbatim.
   *
   * Absent or `null` for every other status, and for a `partial` that simply
   * hit its ceiling: that case is the common one and needs no explanation.
   * Present here, on the summary, rather than requiring a fetch of the full
   * (possibly 16 MB) result — the job list must stay cheap.
   */
  stoppedReason?: string | null;
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
  /** Pages only this crawl found; `engine_reasons` says how. Left where they are. */
  orphans: number;
  merged: number;
  frog_reasons: Record<string, number>;
  engine_reasons: Record<string, number>;
  /**
   * `"INTERNAL_HTML"` for a real export, `"BARE_URL_LIST"` for a one-column
   * list of URLs. Optional because the engine's summary does not forward the
   * reconciler's marker yet; the panel also infers a bare list from an
   * `UNKNOWN` reason, which only that format produces.
   */
  source_format?: string;
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
  /**
   * URLs both crawlers found.
   *
   * Optional because every cross-check saved before this field existed omits
   * it — the intersection was counted and discarded. A panel reading a stored
   * sidecar must treat its absence as "not recorded", never as "none agreed".
   */
  in_both?: string[];
  /**
   * `defaulter_category` and `validation` are optional: they exist only on a
   * bare-list `UNKNOWN` row (see `DefaulterCategory` in the reconciler), and
   * every `frog_only` row saved before that classification existed omits both.
   * Absence must read as "not applicable or not yet classified", never as
   * "confirmed real".
   */
  frog_only: {
    url: string;
    reason: string;
    defaulter_category?: string | null;
    validation?: {
      checked_at: string;
      gsc_impressions: number | null;
      gsc_clicks: number | null;
      flagged_real: boolean;
    } | null;
  }[];
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

/** One masterfile export service the server offers. */
export interface MasterfileService {
  slug: string;
  label: string;
  description?: string;
  /**
   * Whether this service can report on anything at all.
   *
   * `false` means no export it reads can reach a build, so every run would
   * hand back an empty workbook. The server derives it from what the service
   * declares against the filenames a bundle may carry; nothing here decides
   * it, and no list of slugs is kept on this side.
   */
  measurable: boolean;
  /** Why it cannot be built, in the server's words. Only when unmeasurable. */
  reason?: string | null;
}

/** A deliverable build record (masterfile or workbook). */
export interface DeliverableRecord {
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
  /** `"critical"` reads before everything else; `score` cannot express this. */
  severity?: string;
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
 * Where the export rows that reached no page went.
 *
 * Mirrors `UnmatchedGroup`. The arithmetic behind the match rate: these groups
 * partition the unresolved rows exactly, so a reader can check the percentage
 * rather than take it on trust.
 */
export interface UnmatchedGroup {
  host: string;
  reason: string;
  urls: number;
  clicks: number;
  impressions: number;
  examples: string[];
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
  /**
   * Where the unresolved rows went, largest by clicks first.
   *
   * Optional because a report saved before this existed has no such field, and
   * the panel must tell that apart from an export where everything matched.
   */
  unmatched?: UnmatchedGroup[];
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

/*
 * ---------------------------------------------------------------------------
 * Worker dispatch (ADR 0015) — Screaming Frog on the operator's own machine.
 *
 * Hand-written for the same reason as `ReconciliationSummary` above: these
 * shapes live in `src/api/worker_schemas.py`, and `export_ui_contract.py` reads
 * the crawl contract only. Field names match the wire exactly, so there is no
 * transformation layer to get wrong.
 *
 * These are a *different job system* from `CrawlJobSummary` above. Engine
 * crawls are `/jobs` and carry a `JobStatus`; these are `/workers/jobs` and
 * carry a `WorkerJobStatus`. The ids are not interchangeable and neither are
 * the endpoints.
 * ---------------------------------------------------------------------------
 */

/** One registered desktop worker. Mirrors `WorkerSummary`. */
export interface WorkerSummary {
  worker_id: string;
  org_id: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
  /**
   * When this machine last polled or checked in. `null` means never.
   *
   * The raw fact. `is_online` is the server's verdict on it — never re-derive
   * that here, or the dashboard becomes a second staleness rule that nothing
   * tests and that disagrees with the one the dispatch route enforces.
   */
  last_seen_at: string | null;
  is_online: boolean;
  /** What the machine reported it holds. Empty until its daemon checks in. */
  templates: WorkerTemplate[];
  /**
   * How many `.seospiderconfig` files that machine had to skip because their
   * names are not slugs. Non-zero is the answer to "the folder is full, why is
   * the dropdown empty".
   */
  unrecognised_template_count: number;
}

/**
 * Mirrors `WorkerTemplate`.
 *
 * `description` is what a human wrote beside the config on the worker, and it
 * is the only account of what a `.seospiderconfig` does that can exist — the
 * file is an opaque Java-serialised blob that nothing here can read. It is
 * also **text from a machine outside the trust boundary**: render it as a text
 * node, never as HTML, and never build a URL or a selector out of it.
 */
export interface WorkerTemplate {
  name: string;
  description: string;
}

/**
 * A worker's replacement credential. Mirrors `WorkerCredentialRotateResponse`.
 *
 * `worker_secret` exists in exactly one HTTP response and is never readable
 * again — the server keeps only its hash. Hold it only for as long as the
 * dialog that shows it is open; never put it in a store, a log, or a toast.
 */
export interface WorkerCredentialRotation {
  /** Unchanged by rotation — the daemon's WORKER_ID stays the same. */
  worker_id: string;
  /** The new WORKER_CREDENTIAL. The old one was refused before this arrived. */
  worker_secret: string;
  org_id: string;
}

/** Mirrors `WorkerListView`. */
export interface WorkerListView {
  workers: WorkerSummary[];
  /**
   * The threshold behind `is_online`, in seconds, so the UI can explain the
   * verdict ("last seen 4 min ago, offline after 60s") rather than restate it.
   */
  offline_after_s: number;
}

/** Mirrors `WorkerTemplatesView`. */
export interface WorkerTemplatesView {
  worker_id: string;
  templates: WorkerTemplate[];
  /** How many config files that machine could not offer. See `WorkerSummary`. */
  unrecognised_count: number;
  /**
   * When the worker last told the cloud anything at all.
   *
   * `null` means it never has — which is why `templates` may be empty for a
   * machine that in fact holds several. Absence of a report is not a report of
   * absence, and the picker must say which one it is looking at.
   */
  reported_at: string | null;
}

/*
 * ---------------------------------------------------------------------------
 * `--crawl-list` URL lists (ADR 0023).
 *
 * Hand-written beside the worker shapes above and for the same reason: these
 * live in `src/api/worker_schemas.py`, which `export_ui_contract.py` does not
 * read. Field names match the wire exactly.
 * ---------------------------------------------------------------------------
 */

/**
 * Which subset of a finished crawl's URLs to hand to Screaming Frog.
 *
 * A closed union, like `CrawlSpeed["key"]` below and unlike
 * `WorkerJobView.status`: the UI never branches on this value, it only echoes
 * back the `source` the server put on an option. A member added server-side
 * would still render — label, description and availability all come from the
 * response — so the union costs nothing at runtime.
 */
export type UrlListSource = "orphans" | "all" | "pasted";

/**
 * The subset of `UrlListSource` that names a set of a **finished crawl's** URLs.
 *
 * `GET /jobs/{id}/url-list/sources` only ever offers these two: it is asked
 * about one crawl, and "pasted" has no crawl behind it. Narrower than
 * `UrlListSource` on purpose — it is what keeps a source picked from a crawl
 * from being sent as a paste, which the server would reject for carrying no
 * text.
 */
export type CrawlUrlListSource = Exclude<UrlListSource, "pasted">;

/**
 * One offered — or refused — list source. Mirrors `UrlListSourceOption`.
 *
 * `available` is the **server's** verdict and the only one that exists.
 * "Orphans Only" is unavailable until a Screaming Frog export has been
 * reconciled against the crawl, because that comparison is what defines an
 * orphan, and nothing in the browser can know whether one has been run. Never
 * re-derive it here; render `unavailable_reason`, which is never empty when
 * `available` is false.
 *
 * `candidate_url_count` counts candidates *before* filtering, and is `null`
 * when nothing could be counted. The preview reports the truthful post-filter
 * number.
 */
export interface UrlListSourceOption {
  source: CrawlUrlListSource;
  label: string;
  description: string;
  available: boolean;
  unavailable_reason: string;
  candidate_url_count: number | null;
  /** Counting stopped at the ceiling, so `candidate_url_count` is a floor. */
  exceeds_ceiling: boolean;
}

/** Mirrors `UrlListSourcesView` — `GET /jobs/{id}/url-list/sources`. */
export interface UrlListSourcesView {
  job_id: string;
  label: string;
  /** The crawl's own root. Used as the dispatch seed URL in list mode. */
  base_url: string;
  /** The server's ceiling for one list. Never hardcode it in the UI. */
  max_urls: number;
  sources: UrlListSourceOption[];
}

/**
 * What each filtering stage dropped. Mirrors `UrlListCounts`.
 *
 * `off_domain_dropped` is the number behind "Excluded N external URLs". The
 * fields reconcile exactly: `source_rows` minus every `*_dropped` equals
 * `kept`.
 */
export interface UrlListCounts {
  source_rows: number;
  duplicates_dropped: number;
  non_http_dropped: number;
  off_domain_dropped: number;
  unsafe_host_dropped: number;
  kept: number;
}

/**
 * A generated, stored list as a confirmation modal should render it.
 * Mirrors `UrlListView`.
 *
 * Everything except `sha256` exists so a human can tell *which* list this is —
 * an approval reading "12,431 URLs" with no way to check them is the thing the
 * gate exists to prevent. `sha256` is the only field the server compares, and
 * the confirm must echo it back verbatim.
 */
export interface UrlListView {
  source: UrlListSource;
  /** `""` for a pasted list, which has no source crawl to name. */
  source_job_id: string;
  source_label: string;
  /** The domain every kept URL sits inside — the rule behind the exclusions. */
  registrable_domain: string;
  url_count: number;
  sha256: string;
  sample: string[];
  counts: UrlListCounts;
  /** How the text was read, for a pasted list. Absent or `null` otherwise. */
  paste?: PasteCounts | null;
}

/**
 * Where a list-mode dispatch's URLs come from. Mirrors `UrlListRequest`.
 *
 * A discriminated union, not one object with two optional halves, because the
 * server rejects a request carrying both: which set was approved has to have
 * one answer. `source` is never defaulted — "which URLs" is the decision being
 * approved.
 *
 * The pasted variant sends the operator's **raw text**, unsplit. Counting the
 * lines here and sending an array would make the browser the owner of a rule
 * that decides what gets crawled, and the number in the approval dialog would
 * then be one this code produced rather than one the generated file has.
 */
export type UrlListRequest =
  | { source: "orphans" | "all"; source_job_id: string }
  | { source: "pasted"; urls: string };

/**
 * How a block of pasted text was read. Mirrors `PasteCounts`.
 *
 * Parsing only. Deduplication and the off-domain filter are `UrlListCounts`'.
 * The fields reconcile exactly: `lines` minus `blank_dropped`,
 * `header_dropped` and `malformed_dropped` equals `accepted`.
 * `spreadsheet_rows` and `scheme_added` annotate accepted lines and are
 * outside that sum.
 *
 * `malformed_examples` is operator-supplied text quoted back. Render it as
 * text nodes; it has been nowhere near a sanitiser.
 */
export interface PasteCounts {
  lines: number;
  blank_dropped: number;
  header_dropped: number;
  malformed_dropped: number;
  accepted: number;
  spreadsheet_rows: number;
  scheme_added: number;
  malformed_examples: string[];
}

/** One domain a paste covers. Mirrors `PastedDomain`. */
export interface PastedDomain {
  registrable_domain: string;
  /** Candidates *before* filtering, like `UrlListSourceOption.candidate_url_count`. */
  url_count: number;
  /** An address to seed the dispatch with, if this domain is the chosen one. */
  suggested_seed_url: string;
}

/**
 * What a paste would crawl, before anything is generated. Mirrors
 * `PastedUrlPlanView` — `POST /url-list/paste/plan`.
 *
 * Nothing is stored by the call that returns this and no digest is minted.
 * It exists to answer the one question a pasted list cannot answer for
 * itself: which site it is about. `domains` holding more than one entry is
 * the case only the operator can settle, because one crawl has one in-scope
 * domain and the rest will be excluded and counted.
 */
export interface PastedUrlPlan {
  counts: PasteCounts;
  domains: PastedDomain[];
  /** The largest group's root, or `""` when nothing could be read. */
  suggested_seed_url: string;
  /** The server's ceiling for one list. Never hardcode it in the UI. */
  max_urls: number;
  /** The largest group alone is already over the ceiling, so a preview would refuse. */
  exceeds_ceiling: boolean;
}

/** What `POST /workers/{id}/dispatch/preview` accepts. */
export interface DispatchPreviewRequest {
  seed_url: string;
  template_name: string | null;
  correlation_id: string;
  /**
   * Present for a `--crawl-list` dispatch; omitted for an ordinary crawl.
   *
   * The preview call is what builds and stores the list, before anyone has
   * approved anything, so that the bytes the returned fingerprint names
   * already exist.
   */
  url_list?: UrlListRequest;
}

/**
 * A confirmation-ready preview. Mirrors `DispatchPreviewResponse`.
 *
 * Nothing has run yet. `seed_url` is the server's *normalized* URL, and the
 * confirm must echo it back byte for byte or the token is refused.
 */
export interface DispatchPreview {
  token: string;
  expires_at: string;
  worker_id: string;
  seed_url: string;
  template_name: string | null;
  correlation_id: string;
  /** False here means the confirm will 409 — warn before the operator commits. */
  worker_online: boolean;
  worker_last_seen_at: string | null;
  /**
   * The generated list, when one was asked for. Absent or `null` for an
   * ordinary `--crawl` preview, and for any engine predating ADR 0023.
   */
  url_list?: UrlListView | null;
}

/** What `POST /workers/{id}/dispatch` accepts. The token is the approval. */
export interface DispatchConfirmRequest extends DispatchPreviewRequest {
  token: string;
  /**
   * The preview's `url_list.sha256`, echoed back **verbatim**.
   *
   * Never recomputed, reordered or normalised here: the server checks it
   * inside the same atomic statement that consumes the token, so a confirm
   * naming a different list fails without burning the approval. Echoing it
   * rather than letting the server look it up from the token is what makes
   * the mismatch detectable at all.
   */
  url_list_sha256?: string;
}

/** Mirrors `WorkerJobAccepted`. An id to poll, not a result. */
export interface WorkerJobAccepted {
  id: string;
  status: string;
}

/** Mirrors `WorkerJobEnvelope` — the whole payload a worker is given. */
export interface WorkerJobEnvelope {
  job_id: string;
  seed_url: string;
  template_name: string | null;
  correlation_id: string;
}

/**
 * One dispatch job's cloud-tracked state. Mirrors `WorkerJobView`.
 *
 * `status` is a bare `string`, not a union of the five `WorkerJobStatus`
 * members. A closed union here would compile against today's server and then
 * have the UI fall through every branch — silently rendering nothing — the
 * first time a member is added. Callers map it with an explicit fallback.
 *
 * Every optional field here is optional on the wire too, and records written
 * before a given field existed carry none of it. Absence must read as
 * "not recorded", never as zero.
 *
 * `pages_crawled`, `progress_pct` and `current_phase` are hand-written here
 * rather than generated: `scripts/export_ui_contract.py`'s `MODELS` tuple only
 * covers the page-classifier contract, not `src/api/worker_schemas.py`
 * (build-log 0100 §6/§8, the same gap `GscAccountsView`'s own local
 * `GscAccount` type works around for a different endpoint). `None` until a
 * worker has sent at least one progress report — which may be never, for a
 * job whose worker predates this feature, one still waiting on its first
 * poll tick, or a worker that has gone offline. `progress_pct` is not
 * guaranteed to only increase: Screaming Frog's own denominator grows as it
 * discovers more URLs mid-crawl, so a later report can show a lower number
 * than an earlier one — that is real data, not a bug to smooth over.
 */
export interface WorkerJobView {
  id: string;
  org_id: string;
  worker_id: string;
  kind: string;
  envelope: WorkerJobEnvelope;
  status: string;
  created_at: string;
  updated_at: string;
  dispatched_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  bundle_size_bytes?: number | null;
  pages_crawled?: number | null;
  progress_pct?: number | null;
  current_phase?: "crawling" | "exporting" | null;
  /** How many URLs a list-mode job was given. Absent for an ordinary crawl. */
  url_list_url_count?: number | null;
  /**
   * URLs supplied but never crawled, once both numbers are known.
   *
   * `null` (or absent) means **"cannot say"** — either this was not a list
   * job, or no page count has arrived — and must never be rendered as `0`.
   * `0` is the positive claim that nothing was missed. A positive value is
   * the first truncation signal this system can produce: before a known list
   * length, "the crawl stopped early" and "the site is that size" were
   * indistinguishable, which is how a free-tier licence cap goes unnoticed.
   */
  url_list_shortfall?: number | null;
  /** The explanation of a non-zero shortfall. Empty when there is none. */
  url_list_shortfall_note?: string;
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
   * Every URL a finished crawl found, as an `.xlsx` workbook.
   *
   * A `Blob` rather than a URL for the same reason as `downloadWorkerBundle`:
   * the route is bearer-guarded, and an `<a href>` the browser follows
   * carries no `Authorization` header. Optional like `reconcileScreamingFrog`
   * — fixtures have no server behind them to build the workbook.
   */
  downloadUrlList?(jobId: string): Promise<Blob>;

  /**
   * Every URL a finished crawl found, as a printable PDF.
   *
   * `.xlsx` sibling of `downloadUrlList`, same reasoning throughout: a
   * `Blob` because the route is bearer-guarded, optional because fixtures
   * have no server behind them to build it.
   */
  downloadUrlListPdf?(jobId: string): Promise<Blob>;

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

  /**
   * Names of the Search Console profiles a crawl may select.
   *
   * Names only — the engine never publishes what is behind one. Optional for
   * the same reason as `startJob`: fixtures have no accounts, and an empty
   * list from a live engine means the operator configured none, in which case
   * the modal shows no picker and the default credentials apply.
   */
  listGscAccounts?(): Promise<string[]>;

  /**
   * Desktop workers registered to the caller's org, with the server's own
   * liveness verdict.
   *
   * Optional for the same reason as `startJob`: fixtures have no org, no
   * session token and no worker fleet. When it is absent the Screaming Frog
   * launcher says so rather than rendering an empty machine picker, which
   * would read as "you have no PCs" instead of "this mode cannot ask".
   */
  listWorkers?(): Promise<WorkerListView>;

  /** What one worker reported it holds locally, and when it last reported. */
  getWorkerTemplates?(workerId: string): Promise<WorkerTemplatesView>;

  /**
   * Refuse this worker's credential from now on. Idempotent.
   *
   * The machine's next poll is answered `401` and its daemon stops on
   * purpose. There is no "reactivate": rotating is the only way back, because
   * re-trusting a revoked secret would undo the revoke in exactly the case it
   * exists for. Optional like `listWorkers` — fixtures have no fleet.
   */
  revokeWorker?(workerId: string): Promise<WorkerSummary>;

  /**
   * Replace this worker's credential; the old one is refused at once.
   *
   * Also re-enables a revoked worker. The returned secret is shown once.
   */
  rotateWorkerCredential?(workerId: string): Promise<WorkerCredentialRotation>;

  /**
   * Available masterfile export services (slugs and labels).
   *
   * Optional like `startJob`: fixtures have no server behind them to build
   * masterfiles, and the menu item is hidden rather than shown and failing
   * on click.
   */
  listAvailableMasterfiles?(): Promise<MasterfileService[]>;

  /**
   * Build a masterfile export for a finished crawl.
   *
   * Returns a deliverable id to poll. Optional like `startJob` for the same
   * reason.
   */
  buildMasterfile?(jobId: string, serviceSlug: string): Promise<string>;

  /**
   * Build every measurable masterfile for a job and ZIP them.
   *
   * Returns a deliverable id to poll. The download is a `.zip` containing
   * one `<slug>.xlsx` per service that succeeded.
   */
  buildAllMasterfiles?(jobId: string): Promise<string>;

  /**
   * Get the status of a deliverable (masterfile or other workbook build).
   *
   * Optional like `startJob` for the same reason.
   */
  getDeliverable?(deliverableId: string): Promise<DeliverableRecord>;

  /**
   * Download a finished deliverable as a binary blob.
   *
   * A `Blob` rather than a URL for the same reason as `downloadUrlList`:
   * the route is bearer-guarded. Optional like `startJob` for the same reason.
   */
  downloadDeliverable?(deliverableId: string): Promise<Blob>;

  /**
   * Validate a dispatch and mint the single-use approval token.
   *
   * Runs nothing (ADR 0013: starting an external binary is MANDATORY_HITL and
   * the token is the only evidence of approval that exists). The returned
   * `seed_url` is normalized and must be echoed back unchanged.
   */
  previewDispatch?(
    workerId: string,
    request: DispatchPreviewRequest,
  ): Promise<DispatchPreview>;

  /** Spend a preview token and queue the job. Not idempotent: a token is used once. */
  confirmDispatch?(
    workerId: string,
    request: DispatchConfirmRequest,
  ): Promise<WorkerJobAccepted>;

  /**
   * Which `--crawl-list` sources a finished crawl can offer, and the ceiling.
   *
   * Asked rather than worked out locally: "Orphans Only" exists only for a
   * crawl that has already been cross-checked against a Screaming Frog
   * export, and the browser has no way to know that. Optional like
   * `startJob` — fixture mode has no engine to ask, so the control is absent
   * rather than offering a choice that fails on click.
   */
  listUrlListSources?(jobId: string): Promise<UrlListSourcesView>;

  /**
   * What a pasted block of text would crawl, read by the server.
   *
   * Asked rather than worked out locally for the same reason as
   * `listUrlListSources`, and one more: this call proposes the `seed_url` a
   * pasted list has no source crawl to take one from, and the seed's
   * registrable domain is what the whole list is filtered against. A browser
   * that derived it would own a rule that decides what gets crawled.
   *
   * Nothing is stored and no digest is minted. Optional like its sibling:
   * absent means the paste control is not offered at all.
   */
  planPastedUrlList?(urls: string): Promise<PastedUrlPlan>;

  /** Every Screaming Frog dispatch for the caller's org. Not `/jobs`. */
  listWorkerJobs?(): Promise<WorkerJobView[]>;

  /**
   * A finished job's crawl bundle, as a zip.
   *
   * A `Blob` rather than a URL because the route is bearer-guarded: an
   * `<a href>` the browser follows carries no `Authorization` header and would
   * 401 every time.
   */
  downloadWorkerBundle?(jobId: string): Promise<Blob>;

  /**
   * How many crawls are running for the caller's org, on any device.
   *
   * Optional like `startJob`: fixtures have no server to ask, and the header
   * indicator is simply not rendered when this is absent.
   */
  getCrawlActivity?(): Promise<CrawlActivityView>;
}

/**
 * `GET /crawl-activity`. Hand-written: the generated schema does not cover it.
 *
 * `rankuno_cap` is the server's own concurrent-crawl limit and must be read
 * from here, never hardcoded in the UI.
 */
export interface CrawlActivityView {
  /** Running Rankuno-engine crawls in the caller's org, all users and devices. */
  rankuno_active: number;
  /** The server's concurrent Rankuno crawl limit. */
  rankuno_cap: number;
  /** Running Screaming Frog desktop-worker crawls in the caller's org. */
  sf_active: number;
}

/**
 * The worker-dispatch slice of the adapter.
 *
 * Every member is optional on `CrawlDataAdapter` and stays optional here, so a
 * component holding one of these still has to ask before calling — which is the
 * whole point: fixture mode implements two of the six, and "the control is
 * absent" is a different, better outcome than "the control fails on click".
 */
export type WorkerDispatchAdapter = Pick<
  CrawlDataAdapter,
  | "listWorkers"
  | "getWorkerTemplates"
  | "revokeWorker"
  | "rotateWorkerCredential"
  | "previewDispatch"
  | "confirmDispatch"
  | "listUrlListSources"
  | "planPastedUrlList"
  | "listWorkerJobs"
  | "downloadWorkerBundle"
  | "listAvailableMasterfiles"
  | "buildMasterfile"
  | "getDeliverable"
  | "downloadDeliverable"
> &
  /**
   * The engine's own crawls, which list mode takes its URLs from.
   *
   * `Partial` and not a plain `Pick`: `listJobs` is *required* on
   * `CrawlDataAdapter`, and widening it here would force every test double
   * in this folder to implement a method the launcher needs only in list
   * mode. It also keeps the rule above true — ask before calling, always.
   *
   * These are `/jobs` ids: the engine's own crawl records. They are not
   * `/workers/jobs` ids, and the two are never interchangeable. A URL list
   * is built from a crawl **this engine** ran, never from a Screaming Frog
   * dispatch, and `listUrlListSources` takes the former.
   */
  Partial<Pick<CrawlDataAdapter, "listJobs">>;

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
  gsc_property_url: null,
  // `null` is the flat default credentials, not "no account". A name here
  // must be one the engine lists, or the crawl is refused at admission.
  gsc_account: null,
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
  // No URL filtering unless the operator asks for it. `null`, not `[]`: an
  // empty include list would read as "match nothing" to a future reader even
  // though the engine treats both as "no restriction".
  include_patterns: null,
  exclude_patterns: null,
};
