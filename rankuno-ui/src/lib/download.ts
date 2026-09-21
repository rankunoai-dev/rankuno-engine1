/**
 * Hand the browser an already-fetched binary to save.
 *
 * Separate from `csv.ts`, which builds its own text and adds a BOM for Excel.
 * This one saves bytes that arrived over an authenticated request — a crawl
 * bundle from `GET /workers/jobs/{id}/bundle` — where an `<a href>` pointing at
 * the API would carry no `Authorization` header and `401` instead of
 * downloading.
 */

/**
 * Save a blob under `filename`.
 *
 * The object URL is revoked on the next tick rather than immediately: Firefox
 * cancels a download whose blob URL is released while the click is still being
 * processed. Same reasoning, and the same shape, as `downloadCsv`.
 */
export function saveBlob(filename: string, blob: Blob): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(href), 0);
}

/**
 * A byte count as an operator would read it.
 *
 * Returns a stated absence for `null`/`undefined` rather than "0 B": a record
 * written before `bundle_size_bytes` existed did not report an empty archive,
 * it reported nothing, and the two must not look alike.
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "size not recorded";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"] as const;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}
