/**
 * Include/exclude URL patterns for an engine crawl: parsed, checked, and
 * turned into the shape the wire expects.
 *
 * This is the front half of `src/modules/seo/url_filter.py`. That module
 * compiles every pattern in `URLFilter.__init__`, which runs inside the crawl
 * job — so a mistyped pattern raises `re.error` after the job has been
 * admitted, and the operator learns about it from a failed crawl rather than
 * from the form they typed it into. Everything here exists to move that moment
 * forward to the keystroke.
 *
 * The rules are copied from the filter, not invented:
 *
 * - A line is read as a **regular expression** when it starts with `^`, ends
 *   with `$`, or contains `[` — `URLFilter._compile_pattern`'s own test,
 *   character for character. Everything else is a **wildcard**.
 * - Matching is against the URL *path*. Query strings, fragments, the scheme
 *   and the host are never seen by the filter.
 * - The base URL is exempt, so no pattern can drop the seed.
 *
 * Two silent failures get named here rather than left to be discovered from a
 * crawl that returned the wrong thing, because both produce *no error at all*
 * server-side — the filter simply never matches:
 *
 * - a pattern carrying a scheme and host (`https://example.com/blog/*`), which
 *   cannot match a path; and
 * - a wildcard that starts with neither `/` nor `*`, which cannot match a path
 *   either, since every path begins with `/`. As an *include* list that means
 *   "crawl nothing but the seed", which looks like a broken crawler.
 *
 * Known limit: regex validity is checked with the JavaScript engine, not
 * Python's. The two agree on typos — an unclosed group, an unterminated
 * character class, an inverted `{2,1}` — which is what this is for. They part
 * company on constructs no URL filter needs; the two Python-only spellings a
 * copy-paste might plausibly carry are translated before the check so they are
 * not refused, and the residue (a variable-width look-behind, say) would be
 * accepted here and refused by the engine. That direction is the safe one to
 * be wrong in: it is the status quo for every pattern today.
 */

/** Which of the filter's two pattern languages a line is written in. */
export type PatternKind = "wildcard" | "regex";

/** One non-blank line, with the textarea row it came from. */
interface PatternEntry {
  /** 1-based line number *as typed*, counting blank lines. */
  line: number;
  pattern: string;
}

/** A scheme and authority at the head of a pattern: `https://example.com/…`. */
const ABSOLUTE_URL = /^[a-z][a-z0-9+.-]*:\/\/[^/]*/i;

/** Longest pattern echoed back inside an error message. */
const ECHO_LIMIT = 60;

/**
 * Decide how the engine will read a pattern.
 *
 * Mirrors `URLFilter._compile_pattern`. Note what this means in practice: a
 * line is regex because of the characters in it, not because the operator
 * meant it to be. `/products/[size]/*` is a regular expression whether or not
 * anyone intended one, and that is exactly the case worth catching early.
 */
export function patternKind(pattern: string): PatternKind {
  return pattern.startsWith("^") || pattern.endsWith("$") || pattern.includes("[")
    ? "regex"
    : "wildcard";
}

/**
 * Split a textarea into patterns.
 *
 * One pattern per line. Blank lines are dropped and each line is trimmed,
 * which is not cosmetic: the filter treats a pattern with no metacharacters as
 * a literal prefix, so a trailing space would silently stop `/admin ` from
 * matching `/admin`. A pasted column with a trailing newline is the common
 * case and must not become an empty pattern.
 */
export function parsePatternLines(text: string | null | undefined): string[] {
  return entriesOf(text).map((entry) => entry.pattern);
}

/**
 * The value to put on the wire for one of the two pattern fields.
 *
 * `null`, not `[]`, when nothing was typed. The engine reads the two
 * identically — `tool.py` builds a `URLFilter` only `if payload.include_patterns
 * or payload.exclude_patterns`, and `URLFilter.__init__` does `or []` on each —
 * so this is a choice about what a stored request says it asked for, and
 * `null` is what every request has said so far.
 */
export function patternsForWire(text: string | null | undefined): string[] | null {
  const patterns = parsePatternLines(text);
  return patterns.length === 0 ? null : patterns;
}

/**
 * Check every line, and describe the first thing wrong with one.
 *
 * @returns A message naming the offending line and what to do about it, or
 *   `null` when the field is empty or every line is usable.
 */
export function validatePatterns(text: string | null | undefined): string | null {
  const problems = entriesOf(text)
    .map((entry) => describeProblem(entry))
    .filter((message): message is string => message !== null);

  const [first] = problems;
  if (first === undefined) return null;

  const rest = problems.length - 1;
  if (rest === 0) return first;
  return `${first} (${rest} more line${rest === 1 ? " also needs" : "s also need"} fixing.)`;
}

/** Non-blank lines, trimmed, each remembering where it was typed. */
function entriesOf(text: string | null | undefined): PatternEntry[] {
  if (!text) return [];
  return text
    .split(/\r?\n/)
    .map((raw, index) => ({ line: index + 1, pattern: raw.trim() }))
    .filter((entry) => entry.pattern !== "");
}

/** What is wrong with one line, or `null` if the engine can use it. */
function describeProblem(entry: PatternEntry): string | null {
  const { line, pattern } = entry;
  const shown = echo(pattern);

  // A leading `^` is regex anchoring, not part of any address, so it is
  // stripped before asking whether the rest names a host.
  const address = pattern.startsWith("^") ? pattern.slice(1) : pattern;
  const authority = ABSOLUTE_URL.exec(address);
  if (authority !== null) {
    const path = address.slice(authority[0].length);
    // No suggestion when the address carries no path of its own. The literal
    // answer would be `"/"`, which the filter reads as *everything* — helpful
    // as an include list and ruinous as an exclude one.
    return path === "" || path === "/"
      ? `Line ${line}: ${shown} names a site. Patterns are matched against the path alone, so write the part that comes after the address, starting with a slash.`
      : `Line ${line}: ${shown} names a site. Patterns are matched against the path alone, so write ${echo(path)} instead.`;
  }

  if (patternKind(pattern) === "regex") {
    const detail = regexError(pattern);
    return detail === null
      ? null
      : `Line ${line}: ${shown} is read as a regular expression, because it starts with ^, ends with $ or contains [ — and it is not a valid one: ${detail}.`;
  }

  // Every URL path starts with `/`. A wildcard that does not, and does not
  // open with a `*` that can stand in for the leading `/`, matches nothing at
  // all — quietly, with no error from the engine.
  if (!pattern.startsWith("/") && !pattern.startsWith("*")) {
    // A dot in the first segment says this is a bare host rather than a path
    // missing its slash, and prefixing a slash would not be the fix.
    const looksLikeHost = (pattern.split("/")[0] ?? "").includes(".");
    return looksLikeHost
      ? `Line ${line}: ${shown} would never match. Patterns are matched against the path alone, with no domain — write the part that comes after the address, starting with a slash.`
      : `Line ${line}: ${shown} would never match. A path starts with a slash, so write ${echo(`/${pattern}`)} — or use ^ or [ to write it as a regular expression.`;
  }

  return null;
}

/**
 * The reason a regular expression will not compile, in the plainest words
 * available.
 *
 * `RegExp` reports `Invalid regular expression: /…/i: Unterminated group`; the
 * operator already knows what they typed, so only the clause after the last
 * colon is worth showing.
 */
function regexError(pattern: string): string | null {
  try {
    // `i` because the filter compiles with `re.IGNORECASE`. Two Python
    // spellings are translated first so a pattern the engine would accept is
    // not refused here: named groups, and back-references to them.
    const translated = pattern.replace(/\(\?P</g, "(?<").replace(/\(\?P=(\w+)\)/g, "\\k<$1>");
    new RegExp(translated, "i");
    return null;
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    const tail = message.lastIndexOf(": ");
    return tail === -1 ? message : message.slice(tail + 2);
  }
}

/** A pattern quoted for an error message, shortened if it is a paste gone wrong. */
function echo(pattern: string): string {
  const body =
    pattern.length > ECHO_LIMIT ? `${pattern.slice(0, ECHO_LIMIT - 1)}…` : pattern;
  return `"${body}"`;
}
