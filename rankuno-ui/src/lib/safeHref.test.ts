import { describe, expect, it } from "vitest";
import { safeHref } from "./safeHref";

/**
 * The allow-list that stands between crawled URLs and `href`.
 *
 * The rejected cases are the variants a string match misses: browsers fold case
 * and strip tabs and leading whitespace before reading the scheme, so each of
 * these runs script exactly as `javascript:` does.
 */
describe("safeHref", () => {
  it.each(["https://example.com/a?b=1#c", "http://example.com", "HTTPS://Example.com/x"])(
    "admits %s unchanged",
    (url) => {
      expect(safeHref(url)).toBe(url);
    },
  );

  it.each([
    ["javascript:alert(1)"],
    ["JavaScript:alert(1)"],
    ["java\tscript:alert(1)"],
    ["java\nscript:alert(1)"],
    [" javascript:alert(1)"],
    ["\u0000javascript:alert(1)"],
    ["data:text/html,<script>alert(1)</script>"],
    ["vbscript:msgbox(1)"],
    ["file:///etc/passwd"],
    ["//evil.example"],
    ["/relative/path"],
    ["www.http://x"],
    ["www.example.com"],
    ["http://"],
    [""],
    ["not a url at all"],
    ["%%%"],
  ])("refuses %j", (url) => {
    expect(safeHref(url)).toBeNull();
  });

  it("refuses null and undefined", () => {
    expect(safeHref(null)).toBeNull();
    expect(safeHref(undefined)).toBeNull();
  });
});
