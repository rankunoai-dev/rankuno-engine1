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
