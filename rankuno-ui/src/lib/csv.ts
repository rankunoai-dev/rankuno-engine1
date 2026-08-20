/**
 * Client-side CSV export.
 *
 * Client-side rather than a server endpoint because every row is already in the
 * browser: the crawl result is loaded, and asking the API to re-derive a list
 * the client is currently rendering would introduce a second definition of the
 * same set. The reconciliation CSV is served from the API for the opposite
 * reason — it is computed there and never sent to the UI in full.
 */

/**
 * One CSV field, escaped.
 *
 * Quoted whenever the value contains a delimiter, a quote or a newline. URLs
 * carry commas often enough (`?a=1,2`) that skipping this produces a file which
 * opens in a spreadsheet with the columns silently shifted — the worst failure
 * mode available, because it looks like data.
 */
function field(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** A header row plus body rows, CRLF-terminated as RFC 4180 specifies. */
export function toCsv(
  headers: readonly string[],
  rows: readonly (readonly (string | number | boolean | null | undefined)[])[],
): string {
  return [headers, ...rows].map((row) => row.map(field).join(",")).join("\r\n");
}

/**
 * Hand the browser a file to save.
 *
 * A BOM is prepended because Excel on Windows reads a UTF-8 CSV as the system
 * codepage without one, and these files carry URLs with percent-encoded
 * non-ASCII in them. The object URL is revoked on the next tick rather than
 * immediately — Firefox cancels a download whose blob URL is released while the
 * click is still being processed.
 */
export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([`﻿${content}`], { type: "text/csv;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(href), 0);
}

/** `highradius.com` from a crawl root, for naming an export after its site. */
export function hostSlug(baseUrl: string): string {
  try {
    return new URL(baseUrl).hostname.replace(/^www\./, "");
  } catch {
    return "site";
  }
}
