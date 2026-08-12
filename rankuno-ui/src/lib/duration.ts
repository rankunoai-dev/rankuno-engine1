/**
 * Elapsed and remaining time, for crawl progress.
 *
 * Lifted out of `LiveCrawlProgressModal` when that modal was removed. The
 * header pill, the jobs table and the job detail panel all show the same two
 * quantities, and three copies of this rounding would have disagreed with each
 * other the first time one was adjusted.
 */

/** `mm:ss`, or `h:mm:ss` past an hour. */
export function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const rest = safe % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(rest).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * A remaining-time phrase.
 *
 * Rounded coarsely on purpose: the estimate is not accurate to the second, and
 * a display that counts down precisely implies a confidence it does not have.
 */
export function formatRemaining(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest > 0 ? `${minutes} min ${rest} sec` : `${minutes} min`;
  return `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}

/**
 * Percent of discovered URLs that have been fetched.
 *
 * Not "percent complete", and the callers say so. The denominator is every URL
 * discovered, most of which come from the sitemap and are never fetched — so a
 * sitemap-heavy crawl finishes well short of 100% and that is correct.
 */
export function fetchedPercent(completed: number, discovered: number): number {
  if (discovered <= 0) return 0;
  return Math.min(100, Math.round((completed / discovered) * 100));
}

/** Seconds a job has been running, frozen once it ends. */
export function elapsedSeconds(startedAt: number, endedAt: number | null, now: number): number {
  return Math.floor(((endedAt ?? now) - startedAt) / 1000);
}
