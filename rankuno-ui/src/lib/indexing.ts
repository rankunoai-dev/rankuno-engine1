import type { FullPageIntelligenceProfile, Indexability } from "../types/schema";

/**
 * What a page permits, what Google actually did, and where the two disagree.
 *
 * Two axes, kept apart on purpose. The engine reads what a page says about
 * itself — a `robots` tag, an `X-Robots-Tag`, a canonical, the status it
 * returned — and that covers every URL in the crawl. Search Console reports
 * which URLs drew impressions, and that covers only the ones that did.
 *
 * The trap this module exists to avoid is reading the second axis as the
 * negative of the first. Search Console returns rows **only** for URLs with
 * impressions in the requested window, so a URL missing from the export may be
 * indexed and unsearched, outside the date range, past the row cap, or reported
 * under a different canonical. Treating absence as exclusion on a 7,591-page
 * crawl matched against a 1,200-URL export would declare 6,391 pages
 * unindexed, and would be wrong in the direction that gets good pages deleted.
 *
 * So `GoogleState` has no "not indexed" member. It can confirm and it can
 * decline to say, and that is the whole truth available from this data.
 */

/** What Search Console can attest about a URL. Positive or silent, never negative. */
export type GoogleState = "CONFIRMED" | "NOT_IN_EXPORT" | "NO_GSC_DATA";

/**
 * Whether any Search Console data reached this crawl at all.
 *
 * A crawl run without a GSC property has every page unmatched, which looks
 * identical to a crawl where nothing earned an impression. The difference is
 * the difference between "nothing ranks" and "we did not ask", so it is decided
 * once over the whole set rather than per page.
 */
export function hasGscData(pages: readonly FullPageIntelligenceProfile[]): boolean {
  return pages.some((page) => page.gsc_impressions !== null && page.gsc_impressions !== undefined);
}

/**
 * What Google did with one URL.
 *
 * Impressions rather than clicks: a page can be indexed and ranking for months
 * without ever being clicked, and keying on clicks would report those as
 * unseen.
 */
export function googleStateOf(
  page: FullPageIntelligenceProfile,
  gscAvailable: boolean,
): GoogleState {
  if (!gscAvailable) return "NO_GSC_DATA";
  return (page.gsc_impressions ?? 0) > 0 ? "CONFIRMED" : "NOT_IN_EXPORT";
}

/**
 * The crawl-side verdict, tolerating a stored result that predates the field.
 *
 * `GET /jobs/{id}/result` returns the stored mapping unvalidated, so on an
 * older crawl this key is **absent** rather than defaulted — the same shape
 * that rendered the dashboard blank when `discovery_sources.sitemap` was read
 * off a crawl that never had it. Absent reads as `UNKNOWN`, which is what it
 * means: nobody measured.
 */
export function indexabilityOf(page: FullPageIntelligenceProfile): Indexability {
  const stated = (page as { indexability?: Indexability }).indexability;
  return stated ?? "UNKNOWN";
}

export function indexabilityReasonOf(page: FullPageIntelligenceProfile): string {
  return (page as { indexability_reason?: string }).indexability_reason ?? "";
}

/**
 * Whether this crawl measured indexability at all.
 *
 * Distinguishes "every page is UNKNOWN because the crawl predates the field"
 * from "every page is UNKNOWN because nothing was fetched". Both are all-grey
 * on screen and only the second is a site problem.
 */
export function measuredIndexability(pages: readonly FullPageIntelligenceProfile[]): boolean {
  return pages.some((page) => indexabilityOf(page) !== "UNKNOWN");
}

/** Short label for a column or tag. */
export const INDEXABILITY_LABEL: Record<Indexability, string> = {
  INDEXABLE: "Indexable",
  NOINDEX: "Non-indexable",
  CANONICALISED_AWAY: "Canonical elsewhere",
  NOT_A_PAGE: "Not a page",
  UNKNOWN: "Not measured",
};

/** antd tag colours. `UNKNOWN` is deliberately grey and not a warning: an
 *  unmeasured page is not a finding. */
export const INDEXABILITY_COLOR: Record<Indexability, string> = {
  INDEXABLE: "success",
  NOINDEX: "error",
  CANONICALISED_AWAY: "warning",
  NOT_A_PAGE: "default",
  UNKNOWN: "default",
};

export const GOOGLE_STATE_LABEL: Record<GoogleState, string> = {
  CONFIRMED: "Seen in Google",
  // Deliberately not "not indexed". This states what was observed — the URL is
  // absent from the export — and stops short of the conclusion the data cannot
  // support.
  NOT_IN_EXPORT: "No impressions in this export",
  NO_GSC_DATA: "No Search Console data",
};

/**
 * Where the two axes disagree, which is the only place the pair beats either
 * one alone.
 *
 * `null` when they agree, and agreement is the common case: a page that permits
 * indexing and draws impressions is working, and a page that forbids it and
 * draws none is doing what it was told.
 */
export type IndexConflict =
  | "BLOCKED_BUT_EARNING"
  | "CANONICAL_OVERRULED"
  | "DEAD_BUT_EARNING"
  | null;

export function indexConflictOf(
  page: FullPageIntelligenceProfile,
  gscAvailable: boolean,
): IndexConflict {
  if (googleStateOf(page, gscAvailable) !== "CONFIRMED") return null;
  switch (indexabilityOf(page)) {
    case "NOINDEX":
      return "BLOCKED_BUT_EARNING";
    case "CANONICALISED_AWAY":
      return "CANONICAL_OVERRULED";
    case "NOT_A_PAGE":
      return "DEAD_BUT_EARNING";
    default:
      return null;
  }
}

export const CONFLICT_LABEL: Record<Exclude<IndexConflict, null>, string> = {
  BLOCKED_BUT_EARNING: "Blocked from indexing, still earning impressions",
  CANONICAL_OVERRULED: "Google indexed this despite the canonical",
  DEAD_BUT_EARNING: "Dead URL still drawing impressions",
};
