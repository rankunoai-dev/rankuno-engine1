import { message } from "antd";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as download from "../../lib/download";
import {
  MAX_POLL_ATTEMPTS,
  POLL_INTERVAL_MS,
  useMasterfileBuild,
} from "./useMasterfileBuild";
import type { MasterfileAdapter } from "./useMasterfileBuild";

const SERVICE = { slug: "h1", label: "H1 Tags" };
const TARGET = { id: "wj-1", when: "2026-09-21T11:00:00Z" };

function adapter(overrides: Partial<MasterfileAdapter> = {}): MasterfileAdapter {
  return {
    listAvailableMasterfiles: vi.fn().mockResolvedValue([SERVICE]),
    buildMasterfile: vi.fn().mockResolvedValue("dl-1"),
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
});
