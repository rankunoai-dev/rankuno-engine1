/**
 * Tests for useCrawlWizard hook.
 */

import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCrawlWizard } from "./useCrawlWizard";

describe("useCrawlWizard", () => {
  it("initializes with stage 1", () => {
    const { result } = renderHook(() => useCrawlWizard());
    expect(result.current.currentStage).toBe(1);
  });

  it("navigates between stages", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.nextStage();
    });
    expect(result.current.currentStage).toBe(2);

    act(() => {
      result.current.nextStage();
    });
    expect(result.current.currentStage).toBe(3);

    act(() => {
      result.current.prevStage();
    });
    expect(result.current.currentStage).toBe(2);
  });

  it("prevents navigation beyond bounds", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.goToStage(4);
    });
    expect(result.current.currentStage).toBe(4);

    act(() => {
      result.current.nextStage();
    });
    expect(result.current.currentStage).toBe(4); // Stays at 4
  });

  it("updates form data", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({ domain: "example.com" });
    });
    expect(result.current.formData.domain).toBe("example.com");
  });

  it("resets to initial state", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({ domain: "example.com" });
      result.current.nextStage();
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.currentStage).toBe(1);
    expect(result.current.formData.domain).toBe("");
  });

  it("serializes form data to payload", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({
        domain: "example.com",
        configPreset: "polite",
      });
    });

    const payload = result.current.serializeToPayload();
    expect(payload.base_url).toContain("example.com");
    expect(payload.rate_limit_rps).toBeGreaterThan(0);
  });

  it("handles custom rate and concurrency", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({
        domain: "example.com",
        configPreset: "custom",
        customRate: 2.5,
        customConcurrency: 10,
      });
    });

    const payload = result.current.serializeToPayload();
    expect(payload.rate_limit_rps).toBe(2.5);
    expect(payload.concurrency).toBe(10);
  });

  it("includes proxy and auth in payload", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({
        domain: "example.com",
        proxy: "socks5://proxy:1080",
        auth: { username: "user", password: "pass" },
      });
    });

    const payload = result.current.serializeToPayload();
    expect(payload.proxy).toBe("socks5://proxy:1080");
    expect(payload.auth?.username).toBe("user");
  });

  it("gets available domains from uploaded URLs", () => {
    const { result } = renderHook(() => useCrawlWizard());

    act(() => {
      result.current.updateFormData({
        uploadedUrls: [
          "https://example.com/page1",
          "https://example.com/page2",
          "https://other.com/page1",
        ],
      });
    });

    const domains = result.current.getAvailableDomains();
    expect(domains).toHaveLength(2);
    expect(domains).toContain("example.com");
    expect(domains).toContain("other.com");
  });
});
