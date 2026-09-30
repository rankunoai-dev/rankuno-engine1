import { describe, expect, it } from "vitest";
import {
  parsePatternLines,
  patternKind,
  patternsForWire,
  validatePatterns,
} from "./urlPatterns";

/**
 * The front half of `src/modules/seo/url_filter.py`.
 *
 * Two rules decide whether these tests are worth anything:
 *
 * 1. Every case here is taken from `tests/modules/seo/test_url_filter.py` or
 *    from the filter's own source. The UI must offer what the engine actually
 *    supports, and the way that guarantee rots is by being restated from
 *    memory — `patternKind` in particular is a transcription of
 *    `URLFilter._compile_pattern`'s three-part test and has no independent
 *    opinion.
 * 2. A pattern accepted here must be one the engine can act on, and a pattern
 *    refused here must be one it cannot. Refusing something valid is the worse
 *    failure: it takes away a capability that shipped.
 */

describe("patternKind", () => {
  it("reads a bare path or a glob as a wildcard", () => {
    expect(patternKind("/blog/*")).toBe("wildcard");
    expect(patternKind("/articles/**")).toBe("wildcard");
    expect(patternKind("/admin")).toBe("wildcard");
  });

  it("reads ^, $ and [ as regular expressions, exactly as the filter does", () => {
    /* `URLFilter._compile_pattern`: `startswith("^") or endswith("$") or "[" in`. */
    expect(patternKind("^/api/v1")).toBe("regex");
    expect(patternKind("/admin$")).toBe("regex");
    expect(patternKind("/blog/[0-9]{4}/")).toBe("regex");
  });

  it("reads a bracket anywhere as a regular expression, intended or not", () => {
    /* The trap this exists to catch: `[size]` is a character class, and an
       operator who meant it literally gets a pattern that matches one letter
       rather than the word. It is at least a *valid* regex, so it passes
       validation — the teaching is in the form, not here. */
    expect(patternKind("/products/[size]/*")).toBe("regex");
  });
});

describe("parsePatternLines", () => {
  it("is empty for nothing typed", () => {
    expect(parsePatternLines("")).toEqual([]);
    expect(parsePatternLines(null)).toEqual([]);
    expect(parsePatternLines(undefined)).toEqual([]);
    expect(parsePatternLines("   \n\n  \n")).toEqual([]);
  });

  it("drops blank lines and trims each pattern", () => {
    /* Trailing whitespace is not cosmetic here: a pattern with no
       metacharacters is matched as a literal prefix, so `/admin ` would match
       nothing at all. */
    expect(parsePatternLines("  /blog/**  \n\n\t/admin\t\n")).toEqual(["/blog/**", "/admin"]);
  });

  it("splits on Windows line endings too", () => {
    expect(parsePatternLines("/a\r\n/b\r\n")).toEqual(["/a", "/b"]);
  });
});

describe("patternsForWire", () => {
  it("sends null, not an empty array, when nothing was typed", () => {
    /* The engine cannot tell the two apart, so this is a choice about what a
       stored request records — and `null` is what every crawl has sent since
       the field existed. Changing it would rewrite the meaning of the archive
       for no gain. */
    expect(patternsForWire("")).toBeNull();
    expect(patternsForWire("\n  \n")).toBeNull();
    expect(patternsForWire(undefined)).toBeNull();
  });

  it("sends the cleaned list when something was typed", () => {
    expect(patternsForWire(" /blog/** \n\n/news/*\n")).toEqual(["/blog/**", "/news/*"]);
  });
});

describe("validatePatterns", () => {
  it("accepts an empty field", () => {
    expect(validatePatterns("")).toBeNull();
    expect(validatePatterns(undefined)).toBeNull();
    expect(validatePatterns("\n\n   ")).toBeNull();
  });

  it("accepts every shape the filter's own tests exercise", () => {
    const accepted = [
      "/blog/*",
      "/articles/**",
      "/admin",
      "/",
      "/*/post/*",
      "/api/*/response/*",
      "/**-draft",
      "/blog/[0-9]{4}/",
      "^/api/v[0-9]",
      "/admin$",
      "^(/blog|/news)",
      "[0-9]{4}/[0-9]{2}",
    ];
    for (const pattern of accepted) {
      expect(validatePatterns(pattern), pattern).toBeNull();
    }
  });

  it("refuses a malformed regular expression and names the fault", () => {
    /* `URLFilter(include_patterns=["[invalid(regex"])` raises `re.error` in
       `__init__`, which runs inside the crawl job — so without this check the
       operator's typo surfaces as a crawl that died after admission. The
       message has to carry three things: which line, what was typed, and why
       it was read as a regex at all. */
    const message = validatePatterns("/blog/**\n[invalid(regex");
    expect(message).not.toBeNull();
    expect(message).toContain("Line 2");
    expect(message).toContain("[invalid(regex");
    expect(message).toContain("regular expression");
    expect(message).toMatch(/group|class|Unterminated|Invalid/i);
  });

  it("counts the line as typed, blank lines included", () => {
    /* The number has to point at a row the operator can find. */
    expect(validatePatterns("/ok\n\n\n^(")).toContain("Line 4");
  });

  it("reports one problem at a time, and says how many more there are", () => {
    const message = validatePatterns("^(\n[b\n(?<");
    expect(message).toContain("Line 1");
    expect(message).toContain("2 more lines also need fixing.");
  });

  it("uses the singular for a single further problem", () => {
    expect(validatePatterns("^(\n[b")).toContain("1 more line also needs fixing.");
  });

  it("accepts Python's named-group spelling, which the engine compiles", () => {
    /* Validity is checked with the JavaScript engine, so `(?P<…>)` would be
       refused by a naive check even though `re.compile` accepts it. Refusing a
       pattern the engine supports is the failure this test exists to prevent. */
    expect(validatePatterns("^/(?P<section>blog|news)/")).toBeNull();
    expect(validatePatterns("^/(?P<a>x)(?P=a)")).toBeNull();
  });

  it("refuses a pattern carrying a scheme and host, and offers the path", () => {
    /* No error server-side — it simply never matches, because the filter is
       given `urlparse(url).path`. As an include list that is a crawl of the
       seed and nothing else. */
    const message = validatePatterns("https://example.com/blog/*");
    expect(message).toContain("names a site");
    expect(message).toContain('"/blog/*"');
  });

  it("offers no path when the address has none", () => {
    /* The literal answer would be `"/"`, which the filter reads as
       *everything* — ruinous as an exclude list. */
    const message = validatePatterns("https://example.com/");
    expect(message).toContain("names a site");
    expect(message).not.toContain('write "/"');
  });

  it("sees through a regex anchor to the host behind it", () => {
    expect(validatePatterns("^https://example.com/blog")).toContain("names a site");
  });

  it("refuses a wildcard that cannot start a path, and offers the fix", () => {
    /* `blog/*` compiles to `^blog/[^/]*$` and is matched against a path that
       always begins with `/`. Silent, total non-match. */
    const message = validatePatterns("blog/*");
    expect(message).toContain("would never match");
    expect(message).toContain('"/blog/*"');
  });

  it("does not offer a leading slash when the line is a bare host", () => {
    const message = validatePatterns("example.com/blog/*");
    expect(message).toContain("would never match");
    expect(message).not.toContain('"/example.com/blog/*"');
  });

  it("allows a wildcard to open with a star, which can stand in for the slash", () => {
    // A leading double star becomes `^.*` and a single one `^[^/]*`, and
    // both can match the empty string before the slash — so these do match
    // `/tag`. Refusing them would take away something that works.
    expect(validatePatterns("**/tag")).toBeNull();
    expect(validatePatterns("*/tag")).toBeNull();
  });

  it("leaves an unanchored regex alone, slash or no slash", () => {
    /* Regex patterns are matched with `search`, not `match`, so one that does
       not start with `/` is perfectly usable. */
    expect(validatePatterns("[0-9]{4}")).toBeNull();
    expect(validatePatterns("draft$")).toBeNull();
  });

  it("shortens a runaway paste rather than printing it back in full", () => {
    const message = validatePatterns(`${"x".repeat(400)}/[`);
    expect(message).not.toBeNull();
    expect(message?.length).toBeLessThan(260);
    expect(message).toContain("…");
  });
});
