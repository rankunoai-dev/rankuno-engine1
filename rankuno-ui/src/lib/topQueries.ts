/**
 * Reading the engine's answer to a top-queries fetch.
 *
 * The response is untrusted JSON. The engine's own types guarantee its shape,
 * but this screen is the last thing between a wire value and a reader who may
 * take "complete" at its word, so every field is checked here before anything
 * is shown. A value that fails a check is treated as no answer at all, never
 * as a partial one.
 */

/** Mirrors `GscStopReason` in `src/integrations/gsc_schemas.py`. */
export const TOP_QUERIES_STOP_REASONS = ["exhausted", "row_cap", "fetch_failed"] as const;

export type TopQueriesStopReason = (typeof TOP_QUERIES_STOP_REASONS)[number];

export interface TopQueriesResult {
  /** Rows received and kept. A count only: the query text stays on the server. */
  rows: number;
  complete: boolean;
  stopReason: TopQueriesStopReason;
}

/**
 * Fixed copy for each stop reason. Never built from the response, so a value
 * the server did not promise cannot reach the page as text.
 */
export const TOP_QUERIES_STOP_COPY: Record<TopQueriesStopReason, string> = {
  exhausted: "Every row Search Console holds for this window was read.",
  row_cap: "Search Console holds more rows than one fetch reads. Rows past the limit were not read.",
  fetch_failed:
    "Search Console stopped answering partway through. The rows received before that are kept.",
};

function isStopReason(value: string): value is TopQueriesStopReason {
  return (TOP_QUERIES_STOP_REASONS as readonly string[]).includes(value);
}

/**
 * Check a top-queries response and return it typed, or `null` if any field is
 * missing, the wrong type, or contradicts another field.
 *
 * `complete` and `stop_reason` state one fact twice. A response where they
 * disagree is refused rather than shown, because showing "complete" over a
 * fetch that stopped at its cap is the exact failure this screen exists to
 * prevent.
 */
export function parseTopQueriesResult(value: unknown): TopQueriesResult | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const { rows, complete, stop_reason: stopReason } = value as Record<string, unknown>;

  if (typeof rows !== "number" || !Number.isInteger(rows) || rows < 0) return null;
  if (typeof complete !== "boolean") return null;
  if (typeof stopReason !== "string" || !isStopReason(stopReason)) return null;
  if (complete !== (stopReason === "exhausted")) return null;

  return { rows, complete, stopReason };
}
