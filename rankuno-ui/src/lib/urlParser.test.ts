/**
 * Tests for URL parser utility.
 */

import { describe, it, expect } from "vitest";
import {
  extractDomain,
  isValidUrl,
  parseCSV,
  parsePlainText,
  extractDomainsWithCounts,
  filterUrlsByDomain,
} from "./urlParser";

describe("urlParser", () => {
  describe("extractDomain", () => {
    it("extracts domain from full URL", () => {
      expect(extractDomain("https://www.example.com/path")).toBe("www.example.com");
      expect(extractDomain("http://example.com")).toBe("example.com");
    });

    it("accepts bare domain strings", () => {
      expect(extractDomain("www.example.com")).toBe("www.example.com");
      expect(extractDomain("example.co.uk")).toBe("example.co.uk");
    });

    it("returns null for invalid input", () => {
      expect(extractDomain("not a domain")).toBeNull();
      expect(extractDomain("")).toBeNull();
      expect(extractDomain("   ")).toBeNull();
    });

    it("handles subdomains", () => {
      expect(extractDomain("https://sub.example.com")).toBe("sub.example.com");
      expect(extractDomain("https://api.v2.example.com")).toBe("api.v2.example.com");
    });

    it("is case-insensitive", () => {
      expect(extractDomain("HTTPS://EXAMPLE.COM")).toBe("example.com");
    });
  });

  describe("isValidUrl", () => {
    it("validates URLs and domains", () => {
      expect(isValidUrl("https://www.example.com")).toBe(true);
      expect(isValidUrl("www.example.com")).toBe(true);
      expect(isValidUrl("example.com")).toBe(true);
    });

    it("rejects invalid URLs", () => {
      expect(isValidUrl("not a url")).toBe(false);
      expect(isValidUrl("")).toBe(false);
    });
  });

  describe("parseCSV", () => {
    it("parses single-column CSV", () => {
      const csv = "https://example.com/page1\nhttps://example.com/page2";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(2);
      expect(urls[0]).toBe("https://example.com/page1");
    });

    it("skips header rows", () => {
      const csv = "URL\nhttps://example.com/page1\nhttps://example.com/page2";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(2);
    });

    it("skips empty rows", () => {
      const csv = "https://example.com/page1\n\nhttps://example.com/page2";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(2);
    });

    it("handles multi-column CSV", () => {
      const csv = "Title,URL\nPage A,https://example.com/page1\nPage B,https://example.com/page2";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(2);
      expect(urls[0]).toBe("https://example.com/page1");
    });

    it("finds URLs in any column", () => {
      const csv = "https://example.com,other,data";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(1);
      expect(urls[0]).toBe("https://example.com");
    });

    it("handles CRLF line endings", () => {
      const csv = "https://example.com/page1\r\nhttps://example.com/page2";
      const urls = parseCSV(csv);
      expect(urls).toHaveLength(2);
    });
  });

  describe("parsePlainText", () => {
    it("parses plain text with one URL per line", () => {
      const text = "https://example.com/page1\nhttps://example.com/page2";
      const urls = parsePlainText(text);
      expect(urls).toHaveLength(2);
    });

    it("skips empty lines", () => {
      const text = "https://example.com/page1\n\nhttps://example.com/page2";
      const urls = parsePlainText(text);
      expect(urls).toHaveLength(2);
    });

    it("trims whitespace", () => {
      const text = "  https://example.com/page1  \n https://example.com/page2  ";
      const urls = parsePlainText(text);
      expect(urls[0]).toBe("https://example.com/page1");
      expect(urls[1]).toBe("https://example.com/page2");
    });
  });

  describe("extractDomainsWithCounts", () => {
    it("extracts unique domains with counts", () => {
      const urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://other.com/page1",
      ];
      const domains = extractDomainsWithCounts(urls);
      expect(domains).toHaveLength(2);
      expect(domains[0]?.urlCount).toBe(2);
      expect(domains[1]?.urlCount).toBe(1);
    });

    it("sorts by count descending", () => {
      const urls = [
        "https://a.com/1",
        "https://b.com/1",
        "https://b.com/2",
        "https://b.com/3",
      ];
      const domains = extractDomainsWithCounts(urls);
      expect(domains[0]?.domain).toBe("b.com");
      expect(domains[1]?.domain).toBe("a.com");
    });

    it("is case-insensitive", () => {
      const urls = [
        "https://EXAMPLE.COM/page1",
        "https://example.com/page2",
      ];
      const domains = extractDomainsWithCounts(urls);
      expect(domains).toHaveLength(1);
      expect(domains[0]?.urlCount).toBe(2);
    });
  });

  describe("filterUrlsByDomain", () => {
    it("filters URLs by domain", () => {
      const urls = [
        "https://example.com/page1",
        "https://other.com/page1",
        "https://example.com/page2",
      ];
      const filtered = filterUrlsByDomain(urls, "example.com");
      expect(filtered).toHaveLength(2);
      expect(filtered.every((url) => url.includes("example.com"))).toBe(true);
    });

    it("is case-insensitive", () => {
      const urls = [
        "https://EXAMPLE.COM/page1",
        "https://example.com/page2",
      ];
      const filtered = filterUrlsByDomain(urls, "example.com");
      expect(filtered).toHaveLength(2);
    });
  });
});
