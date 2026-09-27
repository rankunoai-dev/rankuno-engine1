/**
 * Tests for validation utility.
 */

import { describe, it, expect } from "vitest";
import {
  validateDomain,
  normalizeDomain,
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
      expect(validateDomain("example-.com")).not.toBeNull();
    });

    /*
     * The case the single `example..com` assertion above never reached. The
     * help text beneath this field says "with or without https://" and offers
     * `https://example.co.uk` as an example, while the validator tested the raw
     * string against a bare-hostname pattern and answered "Invalid domain
     * format" — so the field rejected its own documented example.
     */
    it("accepts a scheme and a trailing slash", () => {
      expect(validateDomain("https://rankuno.com/")).toBeNull();
      expect(validateDomain("http://rankuno.com")).toBeNull();
      expect(validateDomain("https://www.example.co.uk/")).toBeNull();
      expect(validateDomain("HTTPS://Example.COM")).toBeNull();
      expect(validateDomain("  https://example.com/  ")).toBeNull();
    });

    it("still rejects a malformed host behind a scheme", () => {
      expect(validateDomain("https://example..com")).not.toBeNull();
      expect(validateDomain("https://-example.com")).not.toBeNull();
      expect(validateDomain("https://example-.com")).not.toBeNull();
      expect(validateDomain("https://localhost")).not.toBeNull();
      expect(validateDomain("https://example")).not.toBeNull();
      expect(validateDomain("https://")).not.toBeNull();
    });

    it("rejects a scheme other than http or https", () => {
      expect(validateDomain("ftp://example.com")).toMatch(/http/i);
      expect(validateDomain("file://example.com")).toMatch(/http/i);
    });

    /*
     * Rejected rather than normalised, on purpose: a path names a section and a
     * port names a different origin, so silently widening either to the whole
     * domain would start a crawl nobody asked for. The message has to name the
     * offending part, or the rejection is indistinguishable from the scheme bug
     * this test file was extended to cover.
     */
    it("rejects a path, query or fragment and says which", () => {
      expect(validateDomain("https://example.com/some/page")).toMatch(/path or query/i);
      expect(validateDomain("example.com/blog")).toMatch(/path or query/i);
      expect(validateDomain("example.com?utm_source=x")).toMatch(/path or query/i);
      expect(validateDomain("example.com#top")).toMatch(/path or query/i);
    });

    it("rejects a port and says so", () => {
      expect(validateDomain("example.com:8080")).toMatch(/port/i);
      expect(validateDomain("https://example.com:8080/")).toMatch(/port/i);
    });

    it("rejects anything containing a space", () => {
      expect(validateDomain("exa mple.com")).toMatch(/space/i);
      expect(validateDomain("example.com other.com")).toMatch(/space/i);
      expect(validateDomain("https://example.com /")).toMatch(/space/i);
      expect(validateDomain("   ")).not.toBeNull();
    });
  });

  describe("normalizeDomain", () => {
    it("reduces accepted input to a bare lowercased hostname", () => {
      expect(normalizeDomain("https://rankuno.com/")).toBe("rankuno.com");
      expect(normalizeDomain("HTTP://WWW.Example.CO.UK")).toBe("www.example.co.uk");
      expect(normalizeDomain("example.com")).toBe("example.com");
    });

    it("returns null for anything validateDomain rejects", () => {
      expect(normalizeDomain("example..com")).toBeNull();
      expect(normalizeDomain("https://example.com/page")).toBeNull();
      expect(normalizeDomain("example.com:8080")).toBeNull();
      expect(normalizeDomain(undefined)).toBeNull();
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
