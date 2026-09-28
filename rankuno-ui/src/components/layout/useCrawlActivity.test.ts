import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CrawlActivityView, CrawlDataAdapter } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { useAuthStore } from "../../store/useAuthStore";
import { useCrawlStore } from "../../store/useCrawlStore";
import { HIDDEN_POLL_MS, VISIBLE_POLL_MS, useCrawlActivity } from "./useCrawlActivity";

/**
 * The polling hook behind the header's crawl-activity indicator.
 *
 * Fake timers throughout: the contract here is entirely about *when* requests
 * happen, so real time would make every test either slow or flaky.
 */

const VALUE: CrawlActivityView = { rankuno_active: 2, rankuno_cap: 5, sf_active: 1 };

let visibility: DocumentVisibilityState = "visible";

function setVisibility(next: DocumentVisibilityState): void {
  visibility = next;
  document.dispatchEvent(new Event("visibilitychange"));
}

function useAdapter(getCrawlActivity: (() => Promise<CrawlActivityView>) | undefined): void {
  useCrawlStore.setState({ adapter: { getCrawlActivity } as unknown as CrawlDataAdapter });
}

/** Lets already-resolved promises run their continuations under fake timers. */
async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  useAuthStore.setState({ token: "token" });
});

afterEach(() => {
  // Hooks are still mounted here; the store writes that end the session belong
  // inside `act`. Timers stay fake until after, so nothing real is left running.
  act(() => {
    useAuthStore.setState({ token: null });
    useCrawlStore.setState({ adapter: null });
  });
  vi.useRealTimers();
});

describe("useCrawlActivity", () => {
  it("fetches at once, then every 10 seconds while visible", async () => {
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());

    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current).toEqual(VALUE);

    await advance(VISIBLE_POLL_MS - 1);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await advance(VISIBLE_POLL_MS);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("slows to 60 seconds while the tab is hidden", async () => {
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    renderHook(() => useCrawlActivity());
    await flush();

    act(() => setVisibility("hidden"));
    await advance(VISIBLE_POLL_MS * 3);
    expect(fetcher).toHaveBeenCalledTimes(1);

    await advance(HIDDEN_POLL_MS);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("fetches immediately when the tab becomes visible again", async () => {
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    renderHook(() => useCrawlActivity());
    await flush();
    act(() => setVisibility("hidden"));
    await advance(1_000);
    expect(fetcher).toHaveBeenCalledTimes(1);

    act(() => setVisibility("visible"));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("never overlaps requests: a slow response is not overtaken by the next tick", async () => {
    let release: (value: CrawlActivityView) => void = () => {};
    const fetcher = vi.fn().mockImplementation(
      () => new Promise<CrawlActivityView>((resolve) => (release = resolve)),
    );
    useAdapter(fetcher);
    renderHook(() => useCrawlActivity());
    await flush();

    // 35 seconds pass with the first request still open, and a visibility flip
    // (which fetches eagerly) lands in the middle of it.
    await advance(15_000);
    act(() => setVisibility("visible"));
    await advance(20_000);
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => release(VALUE));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);
    await advance(VISIBLE_POLL_MS);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops polling on unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    const { unmount } = renderHook(() => useCrawlActivity());
    await flush();

    unmount();
    await advance(VISIBLE_POLL_MS * 5);
    act(() => setVisibility("hidden"));
    act(() => setVisibility("visible"));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not poll when logged out", async () => {
    useAuthStore.setState({ token: null });
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());

    await advance(VISIBLE_POLL_MS * 3);
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  it("does not poll when the adapter lacks the method", async () => {
    useAdapter(undefined);
    const { result } = renderHook(() => useCrawlActivity());

    await advance(VISIBLE_POLL_MS * 3);
    expect(result.current).toBeNull();
  });

  it("stops and clears the value when the session ends", async () => {
    const fetcher = vi.fn().mockResolvedValue(VALUE);
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());
    await flush();
    expect(result.current).toEqual(VALUE);

    act(() => useAuthStore.setState({ token: null }));
    await advance(VISIBLE_POLL_MS * 3);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
  });

  it("keeps the last good value on error and backs off", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(VALUE)
      .mockRejectedValue(new ApiError(503, "unavailable"));
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());
    await flush();

    await advance(VISIBLE_POLL_MS); // second call: fails
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual(VALUE);

    // Next attempt is 2x later, not another 10 s on.
    await advance(VISIBLE_POLL_MS);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await advance(VISIBLE_POLL_MS);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(result.current).toEqual(VALUE);
  });

  it("does not throw or retry-storm on a 401", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ApiError(401, "expired"));
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());
    await flush();

    await advance(VISIBLE_POLL_MS * 10);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
  });

  it("survives a transport failure with no value yet", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    useAdapter(fetcher);
    const { result } = renderHook(() => useCrawlActivity());
    await flush();
    expect(result.current).toBeNull();
  });
});
