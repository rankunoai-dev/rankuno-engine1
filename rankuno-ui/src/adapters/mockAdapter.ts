import type { PageClassificationOutput } from "../types/schema";
import type {
  CrawlActivityView,
  CrawlDataAdapter,
  CrawlJobSummary,
  JobProgress,
  WorkerJobView,
  WorkerListView,
} from "./adapterInterface";

/**
 * The shape the fixture generator writes: a crawl result plus provenance.
 *
 * `synthetic` and `label` are not part of `PageClassificationOutput` — they
 * describe the *file*, not the crawl — so they are declared here rather than
 * polluting the generated contract.
 */
interface FixtureFile extends PageClassificationOutput {
  synthetic: boolean;
  label: string;
}

/**
 * Fixture loaders, keyed by module path.
 *
 * Typed as `{ default }` because Vite wraps a JSON import in a default export.
 */
const FIXTURE_MODULES = import.meta.glob<{ default: FixtureFile }>("../data/*.json");

/**
 * Reads fixture JSON produced by `scripts/export_ui_fixtures.py`.
 *
 * Fixtures are loaded **lazily**. The 20,000-page file is ~16 MB; eagerly
 * importing it would block first paint and hold it in memory even when the user
 * is looking at a different crawl.
 */
export class MockAdapter implements CrawlDataAdapter {
  private readonly cache = new Map<string, FixtureFile>();

  private jobIdFor(modulePath: string): string {
    return modulePath.replace("../data/", "").replace(".json", "");
  }

  private async load(jobId: string): Promise<FixtureFile> {
    const cached = this.cache.get(jobId);
    if (cached) return cached;

    const entry = Object.entries(FIXTURE_MODULES).find(
      ([path]) => this.jobIdFor(path) === jobId,
    );
    if (!entry) throw new Error(`No fixture for job '${jobId}'`);

    const loaded = await entry[1]();
    const payload = loaded.default;
    this.cache.set(jobId, payload);
    return payload;
  }

  async listJobs(): Promise<CrawlJobSummary[]> {
    const ids = Object.keys(FIXTURE_MODULES).map((path) => this.jobIdFor(path));

    // Loading every fixture to build the list would defeat lazy loading, so the
    // summary is derived from the filename until a job is actually opened.
    // A real API returns summaries from an index endpoint instead.
    const summaries = await Promise.all(
      ids.map(async (id): Promise<CrawlJobSummary> => {
        const cached = this.cache.get(id);
        if (cached) {
          return {
            id,
            label: cached.label,
            baseUrl: cached.base_url,
            status: cached.discovery.truncated ? "partial" : "succeeded",
            pagesClassified: cached.summary.pages_classified,
            truncated: cached.discovery.truncated,
            synthetic: cached.synthetic,
            // A fixture is a file on disk, not a crawl that ran. Its mtime is
            // when the bundle was built, which is not an answer to "when was
            // this crawled" — so the list says so rather than implying one.
            crawledAt: null,
            hasCheckpoint: false,
            recoverable: false,
          };
        }
        const synthetic = id.startsWith("synthetic");
        const approximate = Number.parseInt(id.replace(/\D/g, ""), 10);
        return {
          id,
          label: synthetic
            ? `Synthetic site (~${approximate.toLocaleString()} pages)`
            : id,
          baseUrl: synthetic ? "https://example.com" : `https://${id}`,
          status: "succeeded",
          pagesClassified: Number.isFinite(approximate) ? approximate : 0,
          truncated: false,
          synthetic,
          crawledAt: null,
          hasCheckpoint: false,
          recoverable: false,
        };
      }),
    );

    return summaries.sort((a, b) => a.pagesClassified - b.pagesClassified);
  }

  async getResult(jobId: string): Promise<PageClassificationOutput> {
    return this.load(jobId);
  }

  /**
   * No worker fleet, and no pretence of one.
   *
   * Fixture mode runs with no engine reachable, so there is no org to scope a
   * fleet to and nothing that could answer `GET /workers`. An empty list is the
   * truthful answer — the launcher renders its "no machine registered yet"
   * explanation instead of an empty dropdown.
   *
   * `previewDispatch`, `confirmDispatch` and `downloadWorkerBundle` are
   * deliberately *absent* rather than implemented as stubs: a preview token is
   * the only evidence of approval ADR 0013 accepts, and a fixture that minted
   * one would be manufacturing approval for a run that cannot happen. Their
   * absence is what makes the launcher disable the control with a reason,
   * instead of offering a button that fails on click.
   *
   * `listUrlListSources` (ADR 0023) is absent for a second, narrower reason.
   * Whether "Orphans Only" is available is decided by a saved Screaming Frog
   * cross-check, which fixture mode has no way to hold; any answer invented
   * here would be the client deciding availability, which is exactly what
   * that endpoint exists to stop. The gap report that launches a list crawl
   * is unreachable in fixture mode anyway — `reconcileScreamingFrog` is
   * absent too, so no cross-check can be produced to read a gap from.
   */
  async listWorkers(): Promise<WorkerListView> {
    return { workers: [], offline_after_s: 60 };
  }

  /** No dispatch can have happened in a mode that cannot dispatch. */
  async listWorkerJobs(): Promise<WorkerJobView[]> {
    return [];
  }

  /** Fixed, plausible figures: fixtures have no org and no running crawls. */
  async getCrawlActivity(): Promise<CrawlActivityView> {
    return { rankuno_active: 2, rankuno_cap: 5, sf_active: 1 };
  }

  async getProgress(jobId: string): Promise<JobProgress> {
    const payload = await this.load(jobId);
    return {
      status: payload.discovery.truncated ? "partial" : "succeeded",
      fraction: 1,
      message: payload.discovery.truncated
        ? "Crawl stopped at its page ceiling — results are incomplete."
        : "Crawl complete.",
    };
  }
}
