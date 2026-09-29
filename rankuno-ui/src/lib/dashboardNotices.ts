import type { PageClassificationOutput } from "../types/schema";
import type { NoticeId } from "../store/useNoticeStore";
import { gscWarningFor, gscWarningTone } from "./gscEnrichment";

/**
 * One safety banner the dashboard is currently saying about the loaded crawl.
 *
 * `label` is not shown: it is the accessible name of that banner's close
 * button. Seven buttons all called "Close" is a screen reader announcing the
 * same thing seven times with no way to tell which finding is about to be
 * hidden, and hiding a finding by accident is the exact failure these banners
 * exist to prevent.
 */
export interface DashboardNotice {
  id: NoticeId;
  type: "info" | "warning" | "error";
  message: string;
  label: string;
}

/**
 * Every banner that applies to this crawl, in the order the dashboard shows
 * them.
 *
 * Lifted out of `DashboardShell` when the banners became dismissible, because
 * a stack of conditional JSX cannot be counted — and "2 hidden notices"
 * requires knowing how many banners *would* be on screen, not how many are.
 * The conditions and the wording are carried over verbatim; nothing here fires
 * on a case that did not fire before.
 *
 * `synthetic` comes from the job row rather than the result, which is why it
 * is a parameter: it is the one banner that describes where the data came from
 * instead of what is in it.
 */
export function dashboardNotices(
  result: PageClassificationOutput | null,
  synthetic: boolean,
): DashboardNotice[] {
  const notices: DashboardNotice[] = [];
  const discovery = result?.discovery;
  const navParsed = (result?.navigation?.roots.length ?? 0) > 0;

  if (synthetic) {
    notices.push({
      id: "synthetic",
      type: "warning",
      label: "synthetic dataset",
      message:
        "Synthetic dataset — generated for performance testing. Not crawl output, and not evidence about the engine.",
    });
  }

  if (discovery && discovery.pages_fetched === 0) {
    notices.push({
      id: "zero-fetch",
      type: "error",
      label: "no pages fetched",
      message:
        discovery.fetch_failures > 0
          ? `0 pages fetched — ${discovery.fetch_failures} requests were refused. Classifications rest on URL string patterns alone.`
          : "0 pages fetched over the network. Classifications rest on URL string patterns alone.",
    });
  }

  // Distinct from "no sitemap exists" (`sitemaps_fetched === 0` with
  // `sitemaps_blocked === false`), which is the ordinary, unremarkable shape of
  // most sites and gets no banner at all. This fires only when every sitemap
  // attempt this crawl made — the two hardcoded probes, anything `robots.txt`
  // named, and anything the homepage named — was refused. States what
  // happened; no retry or identity change was attempted and none is offered.
  if (discovery?.sitemaps_blocked) {
    notices.push({
      id: "sitemaps-blocked",
      type: "warning",
      label: "sitemap access blocked",
      message: `Sitemap access blocked — every sitemap request this crawl made was refused (${discovery.sitemap_fetch_attempts} attempt${discovery.sitemap_fetch_attempts === 1 ? "" : "s"}). Discovery continued from the page's own links instead. If this site should be crawlable, ask the site owner to allow this crawler.`,
    });
  }

  // Distinct from truncation. Truncated means the crawl stopped at a ceiling it
  // was told about; this means it was abandoned, and there is no way to know
  // how much of the site is missing.
  if (discovery?.stopped_reason) {
    notices.push({
      id: "stopped-early",
      type: "warning",
      label: "crawl stopped early",
      message: `Crawl stopped early — ${discovery.stopped_reason}. Showing the ${discovery.total_urls.toLocaleString()} URLs found before it stopped; this is not the whole site, and how much is missing is unknown.`,
    });
  }

  // The GSC columns go blank on four different outcomes and look identical on
  // all four, because enrichment degrades silently so a Search Console problem
  // never fails a crawl. This is the only place an operator can learn which one
  // happened — and, for the blank property URL, that the cause is an input they
  // can fill in.
  const gscWarning = gscWarningFor(result);
  if (gscWarning) {
    notices.push({
      id: "gsc",
      type: gscWarningTone(result?.gsc),
      label: "Search Console enrichment",
      message: gscWarning,
    });
  }

  if (discovery?.truncated) {
    notices.push({
      id: "truncated",
      type: "warning",
      label: "partial crawl",
      message:
        "Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it.",
    });
  }

  // Not gated on `grouping === "navigation"`. `selectJob` switches the grouping
  // to "path" the moment it sees an unparsed menu, so that condition was false
  // exactly when this needed to be said — the banner could never fire. It is
  // the fallback itself that has to be announced, not the toggle position.
  if (result && !navParsed) {
    notices.push({
      id: "nav-unparsed",
      type: "warning",
      label: "navigation not parsed",
      message:
        discovery?.pages_fetched === 0
          ? "No header menu was parsed because no page was fetched. The tree below groups by URL path, and its lane numbers are path depth — not navigation depth. Each row's badge shows the level the engine classified, which is the reliable figure."
          : "No header menu could be parsed, so the tree groups by URL path. Lane numbers are path depth, not navigation depth. Each row's badge shows the level the engine classified.",
    });
  }

  return notices;
}
