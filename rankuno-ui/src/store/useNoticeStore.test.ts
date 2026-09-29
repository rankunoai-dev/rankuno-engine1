import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NoticeId } from "./useNoticeStore";

/**
 * Dismissal of the dashboard safety banners.
 *
 * The invariant under test is one-directional: a *failure* of this store must
 * show more banners, never fewer. Every corrupt, stale, oversized or
 * unrecognised stored shape therefore has to read as "nothing dismissed" — the
 * state a first-ever visit is in — because the alternative is the screen
 * silently withholding a finding like "this is a partial view of the site".
 *
 * Exercised against the store directly, the way `useAuthStore.test.ts`
 * exercises the session; `NoticeStack.test.tsx` covers the banners wired to it.
 */

const STORAGE_KEY = "rankuno.notices";

/** The stored shape, read back. */
function stored(): { crawls: { id: string; ids: NoticeId[] }[] } | null {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw ? (JSON.parse(raw) as { crawls: { id: string; ids: NoticeId[] }[] }) : null;
}

describe("useNoticeStore", () => {
  beforeEach(async () => {
    window.localStorage.clear();
    vi.resetModules();
    const { useNoticeStore } = await import("./useNoticeStore");
    useNoticeStore.setState({ dismissed: {} });
  });

  it("hides one banner on one crawl and leaves every other crawl alone", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");

    useNoticeStore.getState().dismiss("job-a", "truncated");

    expect(useNoticeStore.getState().dismissed["job-a"]).toEqual(["truncated"]);
    // The whole point of the scoping. "This site has 405 pages" and "I looked
    // at 405 pages of this site" are different claims, and a dismissal that
    // leaked here would answer for a crawl nobody has looked at.
    expect(useNoticeStore.getState().dismissed["job-b"]).toBeUndefined();
  });

  it("keeps the other banners on a crawl when one is dismissed", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");

    useNoticeStore.getState().dismiss("job-a", "truncated");
    useNoticeStore.getState().dismiss("job-a", "gsc");

    expect(useNoticeStore.getState().dismissed["job-a"]).toEqual(["truncated", "gsc"]);
  });

  it("ignores a repeat dismissal rather than growing the entry", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");

    useNoticeStore.getState().dismiss("job-a", "truncated");
    const before = useNoticeStore.getState().dismissed;
    useNoticeStore.getState().dismiss("job-a", "truncated");

    // Same object, so no storage write and no re-render either.
    expect(useNoticeStore.getState().dismissed).toBe(before);
  });

  it("brings every hidden banner on a crawl back, and only that crawl's", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");

    useNoticeStore.getState().dismiss("job-a", "truncated");
    useNoticeStore.getState().dismiss("job-a", "gsc");
    useNoticeStore.getState().dismiss("job-b", "synthetic");
    useNoticeStore.getState().restoreAll("job-a");

    // Removed outright, not emptied: an entry hiding nothing would still hold
    // one of the twenty slots.
    expect("job-a" in useNoticeStore.getState().dismissed).toBe(false);
    expect(useNoticeStore.getState().dismissed["job-b"]).toEqual(["synthetic"]);
  });

  it("persists a dismissal so a reload does not undo it", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");
    useNoticeStore.getState().dismiss("job-a", "truncated");

    expect(stored()).toEqual({ crawls: [{ id: "job-a", ids: ["truncated"] }] });

    // The reload: the module is evaluated again against the same storage.
    vi.resetModules();
    const reloaded = await import("./useNoticeStore");

    expect(reloaded.useNoticeStore.getState().dismissed["job-a"]).toEqual(["truncated"]);
  });

  it("clears the key when the last dismissal is restored", async () => {
    const { useNoticeStore } = await import("./useNoticeStore");
    useNoticeStore.getState().dismiss("job-a", "truncated");
    useNoticeStore.getState().restoreAll("job-a");

    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  describe("bounds", () => {
    it("caps the crawls it keeps and evicts the least recently touched", async () => {
      const { useNoticeStore } = await import("./useNoticeStore");

      for (let i = 0; i < 25; i += 1) useNoticeStore.getState().dismiss(`job-${i}`, "truncated");

      const ids = Object.keys(useNoticeStore.getState().dismissed);
      expect(ids).toHaveLength(20);
      expect(ids[0]).toBe("job-5");
      expect(ids.at(-1)).toBe("job-24");
      // Evicted means shown again, which is the safe direction.
      expect(useNoticeStore.getState().dismissed["job-0"]).toBeUndefined();
    });

    it("spares the crawl being worked on from eviction", async () => {
      const { useNoticeStore } = await import("./useNoticeStore");

      useNoticeStore.getState().dismiss("job-old", "truncated");
      for (let i = 0; i < 19; i += 1) useNoticeStore.getState().dismiss(`job-${i}`, "truncated");
      // Touched again just before the entry that would have pushed it out.
      useNoticeStore.getState().dismiss("job-old", "gsc");
      useNoticeStore.getState().dismiss("job-new", "truncated");

      expect(useNoticeStore.getState().dismissed["job-old"]).toEqual(["truncated", "gsc"]);
      expect(useNoticeStore.getState().dismissed["job-0"]).toBeUndefined();
    });
  });

  describe("what comes back out of storage", () => {
    /** Boot a fresh module against this raw stored value. */
    async function bootWith(raw: string): Promise<Record<string, NoticeId[]>> {
      window.localStorage.setItem(STORAGE_KEY, raw);
      vi.resetModules();
      const { useNoticeStore } = await import("./useNoticeStore");
      return useNoticeStore.getState().dismissed;
    }

    it("shows everything when the stored value is not JSON", async () => {
      expect(await bootWith("{not json")).toEqual({});
    });

    it("shows everything when the stored shape is wrong", async () => {
      expect(await bootWith(JSON.stringify({ crawls: "truncated" }))).toEqual({});
      expect(await bootWith(JSON.stringify({ crawls: [{ id: 7, ids: [] }] }))).toEqual({});
      expect(await bootWith(JSON.stringify({ crawls: [{ id: "a", ids: "truncated" }] }))).toEqual({});
      expect(await bootWith(JSON.stringify({ crawls: [null] }))).toEqual({});
      expect(await bootWith(JSON.stringify(["job-a"]))).toEqual({});
    });

    it("shows everything when the stored value is implausibly large", async () => {
      /* Not merely slow to parse: a blob this size was not written by this
         code, and the cheapest correct answer to it is to refuse it. */
      const bloated = JSON.stringify({
        crawls: Array.from({ length: 5000 }, (_, i) => ({ id: `job-${i}`, ids: ["truncated"] })),
      });
      expect(bloated.length).toBeGreaterThan(16_384);
      expect(await bootWith(bloated)).toEqual({});
    });

    it("drops a banner name this build no longer has, keeping the rest", async () => {
      /* A retired banner must not cost the operator the dismissals they still
         have a banner for — but it must not survive as a live dismissal
         either, because nothing would ever show it again. */
      const restored = await bootWith(
        JSON.stringify({
          crawls: [{ id: "job-a", ids: ["truncated", "a-banner-that-was-retired", "gsc"] }],
        }),
      );
      expect(restored["job-a"]).toEqual(["truncated", "gsc"]);
    });

    it("drops a crawl whose banners were all retired", async () => {
      const restored = await bootWith(
        JSON.stringify({ crawls: [{ id: "job-a", ids: ["gone"] }, { id: "job-b", ids: ["gsc"] }] }),
      );
      expect(restored).toEqual({ "job-b": ["gsc"] });
    });

    it("de-duplicates a repeated banner name", async () => {
      const restored = await bootWith(
        JSON.stringify({ crawls: [{ id: "job-a", ids: ["gsc", "gsc", "gsc"] }] }),
      );
      expect(restored["job-a"]).toEqual(["gsc"]);
    });

    it("trims an over-long stored list to the newest crawls rather than dropping it", async () => {
      const restored = await bootWith(
        JSON.stringify({
          crawls: Array.from({ length: 30 }, (_, i) => ({ id: `job-${i}`, ids: ["truncated"] })),
        }),
      );
      expect(Object.keys(restored)).toHaveLength(20);
      expect(Object.keys(restored)[0]).toBe("job-10");
    });

    it("survives storage being unavailable entirely", async () => {
      /* Private mode, a full quota, or storage switched off. The dismissal
         still has to work for the session; only the reload is lost. */
      const getItem = vi
        .spyOn(Storage.prototype, "getItem")
        .mockImplementation(() => {
          throw new Error("storage disabled");
        });
      const setItem = vi
        .spyOn(Storage.prototype, "setItem")
        .mockImplementation(() => {
          throw new Error("storage disabled");
        });
      try {
        vi.resetModules();
        const { useNoticeStore } = await import("./useNoticeStore");
        expect(useNoticeStore.getState().dismissed).toEqual({});

        expect(() => useNoticeStore.getState().dismiss("job-a", "gsc")).not.toThrow();
        expect(useNoticeStore.getState().dismissed["job-a"]).toEqual(["gsc"]);
      } finally {
        getItem.mockRestore();
        setItem.mockRestore();
      }
    });
  });
});
