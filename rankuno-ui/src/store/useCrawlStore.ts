import { create } from "zustand";
import type {
  CrawlDataAdapter,
  CrawlJobSummary,
  JobStatus,
} from "../adapters/adapterInterface";
import {
  buildSearchIndex,
  buildTree,
  type SearchEntry,
  type TreeNode,
} from "../lib/tree";
import type {
  FullPageIntelligenceProfile,
  PageClassificationOutput,
  PrimaryPageType,
} from "../types/schema";

interface CrawlState {
  adapter: CrawlDataAdapter | null;

  jobs: CrawlJobSummary[];
  activeJobId: string | null;
  status: JobStatus;
  error: string | null;

  result: PageClassificationOutput | null;
  tree: TreeNode | null;
  /** Built once per result. Rebuilding per keystroke is the obvious 20k killer. */
  searchIndex: SearchEntry[];
  /** Profiles by URL, so the drawer is a lookup rather than a scan. */
  byUrl: Map<string, FullPageIntelligenceProfile>;

  query: string;
  typeFilter: PrimaryPageType[];
  selectedUrl: string | null;
  drawerOpen: boolean;

  init: (adapter: CrawlDataAdapter) => Promise<void>;
  selectJob: (jobId: string) => Promise<void>;
  setQuery: (query: string) => void;
  setTypeFilter: (types: PrimaryPageType[]) => void;
  selectNode: (url: string | null) => void;
  closeDrawer: () => void;
}

export const useCrawlStore = create<CrawlState>((set, get) => ({
  adapter: null,

  jobs: [],
  activeJobId: null,
  status: "idle",
  error: null,

  result: null,
  tree: null,
  searchIndex: [],
  byUrl: new Map(),

  query: "",
  typeFilter: [],
  selectedUrl: null,
  drawerOpen: false,

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

    // Clear derived state immediately. Leaving the previous tree on screen under
    // a "running" label is how a user ends up reading one site's structure while
    // believing they are looking at another.
    set({
      activeJobId: jobId,
      status: "running",
      error: null,
      result: null,
      tree: null,
      searchIndex: [],
      byUrl: new Map(),
      selectedUrl: null,
      drawerOpen: false,
      query: "",
    });

    try {
      const result = await adapter.getResult(jobId);
      const tree = buildTree(result.pages);
      const byUrl = new Map(result.pages.map((page) => [page.url, page]));

      set({
        result,
        tree,
        searchIndex: buildSearchIndex(tree),
        byUrl,
        // `partial` is not an error. Every live crawl so far hit a ceiling, and
        // presenting truncated data as complete is the failure mode that
        // matters here.
        status: result.discovery.truncated ? "partial" : "succeeded",
      });
    } catch (cause) {
      set({ status: "failed", error: describe(cause) });
    }
  },

  setQuery(query) {
    set({ query });
  },

  setTypeFilter(typeFilter) {
    set({ typeFilter });
  },

  selectNode(url) {
    set({ selectedUrl: url, drawerOpen: url !== null });
  },

  closeDrawer() {
    set({ drawerOpen: false });
  },
}));

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/** The currently selected profile, or null. */
export function useSelectedProfile(): FullPageIntelligenceProfile | null {
  return useCrawlStore((state) =>
    state.selectedUrl ? (state.byUrl.get(state.selectedUrl) ?? null) : null,
  );
}
