/**
 * Formatting for crawl timestamps.
 *
 * The job selector lists one row per crawl, and the same site is usually
 * crawled several times while settings are tuned. Labelled by URL alone the
 * rows are literally indistinguishable — three `https://www.highradius.com/`
 * entries with no way to tell which is today's. The timestamp is what makes a
 * row selectable rather than a guess.
 *
 * `Intl` rather than dayjs: both formatters are standard, and antd's dayjs is a
 * transitive dependency this module has no business reaching into.
 */

/** Below this, a relative phrase reads better than a clock time. */
const RELATIVE_CUTOFF_MS = 6 * 24 * 60 * 60 * 1000;

const ABSOLUTE = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** Descending, so the first unit that fits is the largest that applies. */
const UNITS: ReadonlyArray<readonly [Intl.RelativeTimeFormatUnit, number]> = [
  ["day", 24 * 60 * 60 * 1000],
  ["hour", 60 * 60 * 1000],
  ["minute", 60 * 1000],
];

/**
 * A short "how long ago" phrase, or null when the gap is under a minute.
 *
 * Null rather than "0 minutes ago" because a crawl that started seconds ago is
 * better described as "just now" by the caller than by a unit that rounds to
 * zero.
 */
function relative(from: Date, now: Date): string | null {
  const elapsed = now.getTime() - from.getTime();
  // A clock skew or a future timestamp is not worth a special case, but it must
  // not produce "in 3 hours" for a crawl that already ran.
  if (elapsed < 0) return null;
  for (const [unit, size] of UNITS) {
    const value = Math.floor(elapsed / size);
    if (value >= 1) return RELATIVE.format(-value, unit);
  }
  return null;
}

/**
 * Render a crawl timestamp for display.
 *
 * Args:
 *   iso: ISO-8601 instant, or null when the source recorded none.
 *   now: Injectable clock, so the output is testable.
 *
 * Returns:
 *   A phrase such as `"12 Aug, 14:32 · 2 hours ago"`. Recent crawls carry the
 *   relative half because that is the question actually being asked of the
 *   list; older ones drop it, since "8 days ago" is less use than the date.
 *   Unparseable or absent input returns a stated absence, never a fabricated
 *   time — a fixture that was never crawled must not appear to have been.
 */
export function formatCrawlTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (iso === null || iso === undefined || iso === "") return "time not recorded";

  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "time not recorded";

  const absolute = ABSOLUTE.format(when);
  const elapsed = now.getTime() - when.getTime();
  if (elapsed < 0 || elapsed > RELATIVE_CUTOFF_MS) return absolute;

  const ago = relative(when, now);
  return ago === null ? `${absolute} · just now` : `${absolute} · ${ago}`;
}
