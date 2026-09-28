import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CrawlDataAdapter } from "../adapters/adapterInterface";
import { crawl } from "../test/factories";
import { useCrawlStore } from "./useCrawlStore";

/**
 * The polling half of the crawl store.
 *
 * Written for one defect: a banner that reported a past event as a present
 * condition. `refreshJobs` set `error` when a poll failed and never cleared it
 * when the next one worked, so restarting the API — which happens constantly in
 * development — left "Cannot reach the engine" on screen above a job list that
 * the engine had just supplied. Nothing short of a page reload took it down.
 */

function adapter(listJobs: CrawlDataAdapter["listJobs"]): CrawlDataAdapter {
  return {
    listJobs,
    getResult: vi.fn(),
    getProgress: vi.fn(),
  } as unknown as CrawlDataAdapter;
}

describe("refreshJobs", () => {
  beforeEach(() => {
    useCrawlStore.setState({ adapter: null, jobs: [], error: null });
  });

  it("reports a failed poll", async () => {
    useCrawlStore.setState({
      adapter: adapter(vi.fn().mockRejectedValue(new Error("Cannot reach the engine at /api/v1."))),
    });
    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().error).toMatch(/Cannot reach the engine/);
  });

  it("takes its own banner back down when the engine returns", async () => {
    const listJobs = vi
      .fn()
      .mockRejectedValueOnce(new Error("Cannot reach the engine at /api/v1."))
      .mockResolvedValueOnce([]);
    useCrawlStore.setState({ adapter: adapter(listJobs) });

    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().error).not.toBeNull();

    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().error).toBeNull();
  });

  it("leaves an error it did not raise alone", async () => {
    /*
     * "This data source cannot start crawls" is still true after a successful
     * poll. Only the connection message describes something a poll can disprove,
     * so only that one is cleared.
     */
    useCrawlStore.setState({
      adapter: adapter(vi.fn().mockResolvedValue([])),
      error: "This data source cannot start crawls.",
    });
    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().error).toBe("This data source cannot start crawls.");
  });

  it("does not clear a fresh error raised after the failed poll", async () => {
    /*
     * The operator does something that fails between two polls. The later
     * success disproves the connection error, not theirs.
     */
    const listJobs = vi
      .fn()
      .mockRejectedValueOnce(new Error("Cannot reach the engine at /api/v1."))
      .mockResolvedValueOnce([]);
    useCrawlStore.setState({ adapter: adapter(listJobs) });

    await useCrawlStore.getState().refreshJobs();
    useCrawlStore.setState({ error: "That upload failed." });

    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().error).toBe("That upload failed.");
  });

  it("still updates the list on a successful poll", async () => {
    const jobs = [{ id: "a", label: "e.com", status: "succeeded" }];
    useCrawlStore.setState({ adapter: adapter(vi.fn().mockResolvedValue(jobs)) });
    await useCrawlStore.getState().refreshJobs();
    expect(useCrawlStore.getState().jobs).toEqual(jobs);
  });
});

describe("selectJob and the cross-check", () => {
  const result = crawl();

  function withReconciliation(getReconciliation: unknown): CrawlDataAdapter {
    return {
      listJobs: vi.fn().mockResolvedValue([]),
      getResult: vi.fn().mockResolvedValue(result),
      getProgress: vi.fn(),
      getReconciliation,
    } as unknown as CrawlDataAdapter;
  }

  beforeEach(() => {
    useCrawlStore.setState({ adapter: null, reconciliation: null, result: null, error: null });
  });

  it("loads the saved cross-check with the result", async () => {
    const saved = { summary: { job_id: "a" }, engine_only: [] };
    useCrawlStore.setState({ adapter: withReconciliation(vi.fn().mockResolvedValue(saved)) });
    await useCrawlStore.getState().selectJob("a");
    expect(useCrawlStore.getState().reconciliation).toBe(saved);
  });

  it("stores null, not an error, when there is none", async () => {
    useCrawlStore.setState({ adapter: withReconciliation(vi.fn().mockResolvedValue(null)) });
    await useCrawlStore.getState().selectJob("a");
    expect(useCrawlStore.getState().reconciliation).toBeNull();
    expect(useCrawlStore.getState().error).toBeNull();
  });

  it("keeps the tree when the sidecar read fails", async () => {
    useCrawlStore.setState({
      adapter: withReconciliation(vi.fn().mockRejectedValue(new Error("boom"))),
    });
    await useCrawlStore.getState().selectJob("a");
    expect(useCrawlStore.getState().result).toBe(result);
    expect(useCrawlStore.getState().error).toBeNull();
  });

  it("drops a cross-check that arrives after another job was selected", async () => {
    /*
     * The sidecar is per-index once it reaches the tree. A late arrival for job
     * A applied to job B's model would mark unrelated rows.
     */
    let release: (value: unknown) => void = () => {};
    const slow = new Promise((resolve) => {
      release = resolve;
    });
    const getReconciliation = vi
      .fn()
      .mockImplementationOnce(() => slow)
      .mockResolvedValueOnce(null);
    useCrawlStore.setState({ adapter: withReconciliation(getReconciliation) });

    const first = useCrawlStore.getState().selectJob("a");
    await useCrawlStore.getState().selectJob("b");
    release({ summary: { job_id: "a" }, engine_only: [] });
    await first;

    expect(useCrawlStore.getState().activeJobId).toBe("b");
    expect(useCrawlStore.getState().reconciliation).toBeNull();
  });
});

/**
 * Restoring the crawl the operator was reading, across a reload.
 *
 * The reported bug was "reloading is not persisting page UI" — the tab came
 * back on the Launch chooser with nothing loaded. `useUiStore` restores the
 * view; this half restores what was on it, because a visualizer restored to
 * "No crawl loaded" is the same complaint one screen along.
 *
 * Only the id is stored, never the result: results reach the size of the 16 MB
 * synthetic fixture, and `localStorage` is neither large enough nor fast enough
 * for that.
 */
describe("init — restoring the crawl across a reload", () => {
  const STORAGE_KEY = "rankuno.crawl";
  const result = crawl();

  /** Two finished crawls, the restorable one deliberately not first. */
  const JOBS = [
    { id: "job-newest", label: "newest.com", status: "succeeded" },
    { id: "job-older", label: "older.com", status: "succeeded" },
  ];

  function restoring(
    getResult: CrawlDataAdapter["getResult"],
    jobs: unknown[] = JOBS,
  ): CrawlDataAdapter {
    return {
      listJobs: vi.fn().mockResolvedValue(jobs),
      getResult,
      getProgress: vi.fn(),
    } as unknown as CrawlDataAdapter;
  }

  function stored(): unknown {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
  }

  beforeEach(() => {
    useCrawlStore.setState({
      adapter: null,
      jobs: [],
      activeJobId: null,
      result: null,
      reconciliation: null,
      status: "idle",
      error: null,
    });
    // After the reset, not before: clearing `activeJobId` is itself a change
    // the store persists, so a clear that ran first would be undone by it.
    window.localStorage.clear();
  });

  it("writes the job id whenever the crawl on screen changes", async () => {
    useCrawlStore.setState({ adapter: restoring(vi.fn().mockResolvedValue(result)) });

    await useCrawlStore.getState().selectJob("job-older");

    expect(stored()).toEqual({ jobId: "job-older" });
  });

  it("reopens the crawl the last session was reading, not the newest one", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: "job-older" }));
    const getResult = vi.fn().mockResolvedValue(result);

    await useCrawlStore.getState().init(restoring(getResult));

    expect(getResult).toHaveBeenCalledWith("job-older");
    expect(getResult).not.toHaveBeenCalledWith("job-newest");
    expect(useCrawlStore.getState().activeJobId).toBe("job-older");
    expect(useCrawlStore.getState().result).toBe(result);
    expect(useCrawlStore.getState().status).toBe("succeeded");
    expect(useCrawlStore.getState().error).toBeNull();
  });

  it("opens the newest crawl on a first-ever visit, as it always did", async () => {
    const getResult = vi.fn().mockResolvedValue(result);

    await useCrawlStore.getState().init(restoring(getResult));

    expect(getResult).toHaveBeenCalledWith("job-newest");
    expect(useCrawlStore.getState().activeJobId).toBe("job-newest");
  });

  it("does not ask for a stored job the engine no longer lists", async () => {
    /* Deleted, expired, belonging to another org, or stored on a machine that
       talks to a different engine. The list already answers that, so the 404
       round trip and the banner it would raise never happen. */
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: "job-deleted" }));
    const getResult = vi.fn().mockResolvedValue(result);

    await useCrawlStore.getState().init(restoring(getResult));

    expect(getResult).not.toHaveBeenCalledWith("job-deleted");
    expect(useCrawlStore.getState().activeJobId).toBe("job-newest");
    expect(useCrawlStore.getState().error).toBeNull();
    expect(stored()).toEqual({ jobId: "job-newest" });
  });

  it("lands on the empty state, with no banner, when there is nothing to fall back to", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: "job-deleted" }));
    const getResult = vi.fn();

    await useCrawlStore.getState().init(restoring(getResult, []));

    expect(getResult).not.toHaveBeenCalled();
    expect(useCrawlStore.getState().activeJobId).toBeNull();
    expect(useCrawlStore.getState().result).toBeNull();
    expect(useCrawlStore.getState().status).toBe("idle");
    expect(useCrawlStore.getState().error).toBeNull();
    // The unusable id is dropped rather than retried on every future boot.
    expect(stored()).toBeNull();
  });

  it("lands on the empty state when the restored job is listed but will not load", async () => {
    /* Still running, so it has no result yet, or its result was pruned from
       under it. An error banner naming a crawl the operator never selected
       this session is the first thing they would see, and there is nothing
       they can do about it. */
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: "job-older" }));
    const getResult = vi.fn().mockRejectedValue(new Error("404 job not found"));

    await useCrawlStore.getState().init(restoring(getResult));

    expect(getResult).toHaveBeenCalledWith("job-older");
    expect(useCrawlStore.getState().activeJobId).toBeNull();
    expect(useCrawlStore.getState().result).toBeNull();
    expect(useCrawlStore.getState().status).toBe("idle");
    expect(useCrawlStore.getState().error).toBeNull();
    expect(stored()).toBeNull();
  });

  it("still reports a genuine failure of the job the operator picked", async () => {
    /* The quiet landing above is for the restore only. A crawl chosen by hand
       that fails to load must still say so. */
    useCrawlStore.setState({ adapter: restoring(vi.fn().mockRejectedValue(new Error("boom"))) });

    await useCrawlStore.getState().selectJob("job-older");

    expect(useCrawlStore.getState().status).toBe("failed");
    expect(useCrawlStore.getState().error).toBe("boom");
  });

  it("boots normally when the stored value is corrupt", async () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json at all");
    const getResult = vi.fn().mockResolvedValue(result);

    await expect(useCrawlStore.getState().init(restoring(getResult))).resolves.toBeUndefined();

    expect(useCrawlStore.getState().activeJobId).toBe("job-newest");
    expect(useCrawlStore.getState().error).toBeNull();
  });

  it("ignores a stored value of the wrong shape", async () => {
    /* An older build, a hand edit, or a write truncated by a quota error.
       Nothing out of storage is trusted to be the shape it was written in. */
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: 42 }));
    const getResult = vi.fn().mockResolvedValue(result);

    await useCrawlStore.getState().init(restoring(getResult));

    expect(useCrawlStore.getState().activeJobId).toBe("job-newest");
  });

  it("restores nothing but an id — no result is ever written to storage", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId: "job-older" }));

    await useCrawlStore.getState().init(restoring(vi.fn().mockResolvedValue(result)));

    expect(Object.keys(stored() as object)).toEqual(["jobId"]);
    // The 16 MB argument, pinned: nothing in storage may grow with the crawl.
    expect((window.localStorage.getItem(STORAGE_KEY) ?? "").length).toBeLessThan(200);
  });
});
