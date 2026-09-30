import { message } from "antd";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as download from "../../lib/download";
import {
  BATCH_MAX_POLL_ATTEMPTS,
  MAX_POLL_ATTEMPTS,
  POLL_INTERVAL_MS,
  useMasterfileBuild,
} from "./useMasterfileBuild";
import type { MasterfileAdapter } from "./useMasterfileBuild";

const SERVICE = { slug: "h1", label: "H1 Tags", measurable: true };
const TARGET = { id: "wj-1", when: "2026-09-21T11:00:00Z" };

function adapter(overrides: Partial<MasterfileAdapter> = {}): MasterfileAdapter {
  return {
    listAvailableMasterfiles: vi.fn().mockResolvedValue([SERVICE]),
    buildMasterfile: vi.fn().mockResolvedValue("dl-1"),
    buildAllMasterfiles: vi.fn().mockResolvedValue("dl-batch"),
    getDeliverable: vi
      .fn()
      .mockResolvedValue({ id: "dl-1", status: "dispatched", has_result: false }),
    downloadDeliverable: vi.fn().mockResolvedValue(new Blob(["x"])),
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useMasterfileBuild", () => {
  it("stops polling and clears its timer when the component unmounts", async () => {
    const api = adapter();
    const { result, unmount } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    vi.useFakeTimers();
    act(() => {
      void result.current.build(TARGET, SERVICE);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(api.getDeliverable).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);

    unmount();

    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);
    expect(api.getDeliverable).toHaveBeenCalledTimes(1);
  });

  it("gives up after the poll limit and says so", async () => {
    const error = vi.spyOn(message, "error").mockImplementation(() => ({}) as never);
    const save = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const api = adapter();
    const { result } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    vi.useFakeTimers();
    act(() => {
      void result.current.build(TARGET, SERVICE);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (MAX_POLL_ATTEMPTS + 1));
    });

    expect(api.getDeliverable).toHaveBeenCalledTimes(MAX_POLL_ATTEMPTS);
    expect(error).toHaveBeenCalledWith(expect.stringMatching(/timed out/i));
    expect(save).not.toHaveBeenCalled();
    expect(result.current.isBuilding("wj-1", "h1")).toBe(false);
  });

  it("is unsupported, and lists nothing, for an adapter with no masterfile methods", () => {
    const { result } = renderHook(() => useMasterfileBuild({}));
    expect(result.current.supported).toBe(false);
    expect(result.current.services).toEqual([]);
  });

  it("does not start a second build of the same service for the same job", async () => {
    const api = adapter();
    const { result } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    vi.useFakeTimers();
    act(() => {
      void result.current.build(TARGET, SERVICE);
      void result.current.build(TARGET, SERVICE);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(api.buildMasterfile).toHaveBeenCalledTimes(1);
  });

  it("buildAll triggers the batch endpoint and saves a zip", async () => {
    const save = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const success = vi.spyOn(message, "success").mockImplementation(() => ({}) as never);
    const api = adapter({
      getDeliverable: vi
        .fn()
        .mockResolvedValue({ id: "dl-batch", status: "succeeded", has_result: true }),
    });
    const { result } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    await act(async () => {
      await result.current.buildAll(TARGET);
    });

    expect(api.buildAllMasterfiles).toHaveBeenCalledWith("wj-1");
    expect(save).toHaveBeenCalledWith(expect.stringMatching(/masterfiles-.*\.zip$/), expect.any(Blob));
    expect(success).toHaveBeenCalledWith("All masterfiles downloaded.");
  });

  it("isBuildingAll tracks the batch flight key", async () => {
    const api = adapter();
    const { result } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    vi.useFakeTimers();
    act(() => {
      void result.current.buildAll(TARGET);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.isBuildingAll("wj-1")).toBe(true);
  });

  it("buildAll gives up after the batch poll limit", async () => {
    const error = vi.spyOn(message, "error").mockImplementation(() => ({}) as never);
    const api = adapter();
    const { result } = renderHook(() => useMasterfileBuild(api));
    await waitFor(() => expect(result.current.services).toHaveLength(1));

    vi.useFakeTimers();
    act(() => {
      void result.current.buildAll(TARGET);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (BATCH_MAX_POLL_ATTEMPTS + 1));
    });

    expect(api.getDeliverable).toHaveBeenCalledTimes(BATCH_MAX_POLL_ATTEMPTS);
    expect(error).toHaveBeenCalledWith(expect.stringMatching(/timed out/i));
  });
});
