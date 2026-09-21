import type { GscEnrichmentReport, PageClassificationOutput } from "../types/schema";

/**
 * Turn the engine's Search Console enrichment outcome into one operator sentence.
 *
 * Enrichment never fails a crawl — a Search Console outage must not cost a
 * 20,000-page run — so every failure path produces a result that looks exactly
 * like a crawl which never wanted metrics: every page carrying `gsc_* = null`.
 * The only place the difference was recorded was a server log line, which the
 * person looking at the dashboard cannot see. This is that line, on screen.
 *
 * Each message names the *next action*, not just the fact, because each outcome
 * has a different fix: supply the missing property URL, name a property that
 * covers the site, or re-check the account's authorisation. The blank property
 * URL is the common case and the one that reads as a bug, so it is spelled out
 * with an example.
 *
 * Returns the empty string when there is nothing to say — enrichment that
 * matched pages, or a result stored before the field existed.
 */
export function gscEnrichmentWarning(
  gsc: GscEnrichmentReport | null | undefined,
): string {
  // `undefined`, not just `null`: the type says this field is always present,
  // and the type describes what the engine emits today rather than what is on
  // disk. A crawl stored before this field existed has no key at all, and it
  // cannot say which outcome it had — so it says nothing.
  if (!gsc) return "";

  const detail = gsc.reason ? ` (${gsc.reason})` : "";
  const account = gsc.account ? `the "${gsc.account}" account` : "the default account";

  switch (gsc.status) {
    case "not_requested":
      return (
        "No Search Console metrics: this crawl was started without a GSC property URL, " +
        "so clicks, impressions, CTR and position were never fetched. Re-run the crawl " +
        "with the property URL filled in (for example https://example.com/ or " +
        "sc-domain:example.com) to add them."
      );
    case "property_mismatch":
      return (
        "No Search Console metrics: the property this crawl queried does not cover the " +
        `site that was crawled${detail}. Re-run naming the property that covers this site.`
      );
    case "failed":
      return (
        `No Search Console metrics: the request to Search Console failed${detail}. ` +
        `The crawl itself is unaffected — check that ${account} is still authorised for ` +
        "this property, then re-run to add metrics."
      );
    case "succeeded":
      // Distinct from a failure, and the distinction matters: the request
      // worked, so the credentials and the property are fine. Nothing lined up
      // with a crawled URL, which is a hostname, protocol or trailing-slash
      // difference between the property and the crawl.
      if (gsc.pages_matched === 0) {
        return (
          "Search Console answered, but none of its URLs matched a crawled page " +
          `(0 of ${gsc.pages_crawled.toLocaleString()}). Check the property covers the ` +
          "same hostname and protocol as the crawl, then re-run."
        );
      }
      return "";
    default:
      // A status this build does not know about. Saying nothing is correct:
      // inventing a message for an outcome we cannot interpret is worse.
      return "";
  }
}

/** The enrichment outcome of a loaded result, tolerant of one that predates it. */
export function gscWarningFor(
  result: PageClassificationOutput | null | undefined,
): string {
  return gscEnrichmentWarning(result?.gsc);
}

/**
 * How loudly to say it.
 *
 * Colour on this dashboard means severity, so the two outcomes where something
 * actually went wrong — a refused or unreachable Search Console, and a property
 * that does not cover the site — are `warning`. A crawl simply started without
 * a property URL is `info`: nothing failed, an input was left blank.
 */
export function gscWarningTone(
  gsc: GscEnrichmentReport | null | undefined,
): "info" | "warning" {
  return gsc?.status === "failed" || gsc?.status === "property_mismatch" ? "warning" : "info";
}
