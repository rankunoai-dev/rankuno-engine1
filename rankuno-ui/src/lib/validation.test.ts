/**
 * Tests for validation utility.
 */

import { describe, it, expect } from "vitest";
import {
  validateDomain,
  validateProxyUrl,
  validateRate,
  validateConcurrency,
  validateCustomHeaders,
  validateGA4PropertyId,
  estimateCrawlSeconds,
  formatCrawlTimeEstimate,
} from "./validation";

describe("validation", () => {
  describe("validateDomain", () => {
    it("accepts valid domains", () => {
      expect(validateDomain("example.com")).toBeNull();
      expect(validateDomain("www.example.com")).toBeNull();
      expect(validateDomain("example.co.uk")).toBeNull();
    });

    it("rejects domains without TLD", () => {
      expect(validateDomain("localhost")).not.toBeNull();
      expect(validateDomain("example")).not.toBeNull();
    });

    it("rejects empty domain", () => {
      expect(validateDomain("")).not.toBeNull();
      expect(validateDomain(undefined)).not.toBeNull();
    });

    it("rejects invalid characters", () => {
      expect(validateDomain("example..com")).not.toBeNull();
      expect(validateDomain("-example.com")).not.toBeNull();
    });
  });

  describe("validateProxyUrl", () => {
    it("accepts valid proxy URLs", () => {
      expect(validateProxyUrl("socks5://proxy.example.com:1080")).toBeNull();
      expect(validateProxyUrl("http://proxy.example.com:8080")).toBeNull();
      expect(validateProxyUrl("https://proxy.example.com:443")).toBeNull();
    });

    it("allows optional proxy", () => {
      expect(validateProxyUrl("")).toBeNull();
      expect(validateProxyUrl(undefined)).toBeNull();
    });

    it("rejects invalid format", () => {
      expect(validateProxyUrl("proxy.example.com:1080")).not.toBeNull();
      expect(validateProxyUrl("invalid://url")).not.toBeNull();
    });
  });

  describe("validateRate", () => {
    it("accepts valid rates", () => {
      expect(validateRate(1.0)).toBeNull();
      expect(validateRate(0.05)).toBeNull();
      expect(validateRate(25)).toBeNull();
    });

    it("rejects out-of-range rates", () => {
      expect(validateRate(0.01)).not.toBeNull();
      expect(validateRate(30)).not.toBeNull();
    });

    it("rejects invalid input", () => {
      expect(validateRate(null)).not.toBeNull();
      expect(validateRate(undefined)).not.toBeNull();
    });
  });

  describe("validateConcurrency", () => {
    it("accepts valid concurrency values", () => {
      expect(validateConcurrency(1)).toBeNull();
      expect(validateConcurrency(5)).toBeNull();
      expect(validateConcurrency(200)).toBeNull();
    });

    it("requires whole numbers", () => {
      expect(validateConcurrency(5.5)).not.toBeNull();
    });

    it("rejects out-of-range values", () => {
      expect(validateConcurrency(0)).not.toBeNull();
      expect(validateConcurrency(250)).not.toBeNull();
    });
  });

  describe("validateCustomHeaders", () => {
    it("accepts valid JSON headers", () => {
      const result = validateCustomHeaders('{"X-Custom": "value"}');
      expect(result.error).toBeNull();
      expect(result.headers).toEqual({ "X-Custom": "value" });
    });

    it("accepts Name: Value format", () => {
      const result = validateCustomHeaders("X-Custom: value\nX-Other: value2");
      expect(result.error).toBeNull();
      expect(result.headers?.["X-Custom"]).toBe("value");
    });

    it("allows empty headers", () => {
      const result = validateCustomHeaders("");
      expect(result.error).toBeNull();
      expect(result.headers).toBeNull();
    });

    it("rejects invalid JSON", () => {
      const result = validateCustomHeaders("{invalid json}");
      expect(result.error).not.toBeNull();
    });

    it("rejects invalid Name: Value format", () => {
      const result = validateCustomHeaders("InvalidFormat");
      expect(result.error).not.toBeNull();
    });
  });

  describe("validateGA4PropertyId", () => {
    it("accepts numeric GA4 IDs", () => {
      expect(validateGA4PropertyId("123456789")).toBeNull();
    });

    it("rejects non-numeric IDs", () => {
      expect(validateGA4PropertyId("ABC123")).not.toBeNull();
    });

    it("allows empty GA4 ID", () => {
      expect(validateGA4PropertyId("")).toBeNull();
      expect(validateGA4PropertyId(undefined)).toBeNull();
    });
  });

  describe("estimateCrawlSeconds", () => {
    it("calculates crawl time", () => {
      expect(estimateCrawlSeconds(1000, 1.0)).toBe(1000);
      expect(estimateCrawlSeconds(100, 10)).toBe(10);
    });

    it("handles zero rate", () => {
      expect(estimateCrawlSeconds(1000, 0)).toBe(Infinity);
    });

    it("handles negative rate", () => {
      expect(estimateCrawlSeconds(1000, -1)).toBe(Infinity);
    });
  });

  describe("formatCrawlTimeEstimate", () => {
    it("formats seconds", () => {
      expect(formatCrawlTimeEstimate(30)).toBe("30s");
    });

    it("formats minutes", () => {
      expect(formatCrawlTimeEstimate(300)).toContain("m");
    });

    it("formats hours", () => {
      expect(formatCrawlTimeEstimate(3600)).toContain("h");
    });

    it("combines hours and minutes", () => {
      expect(formatCrawlTimeEstimate(3660)).toContain("h");
      expect(formatCrawlTimeEstimate(3660)).toContain("m");
    });

    it("handles infinity", () => {
      expect(formatCrawlTimeEstimate(Infinity)).toBe("Unknown");
    });
  });
});
