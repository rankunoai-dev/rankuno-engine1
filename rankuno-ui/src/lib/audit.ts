import type { FullPageIntelligenceProfile, PageClassificationOutput } from "../types/schema";

/**
 * Site defects worth reporting to a client, derived from a finished crawl.
 *
 * Findings, not categories. The distinction decides the whole shape of this
 * module: a page can be an orphan *and* sit in a mis-signposted URL silo, which
 * a tree cannot express because a node has one parent. Everything here is a
 * list a page can appear on more than once.
 *
 * Nothing is computed that the engine did not already produce. Inbound link
 * counts, breadcrumb trails and page types are all on the profile; this reads
 * them and phrases them as actions.
 */

/** Share of a site a URL prefix must hold before its signposting is a finding. */
const SILO_SHARE = 0.01;

/** Smallest group worth naming. Below this a "silo" is a handful of pages. */
const MIN_SILO_PAGES = 25;

export interface Finding {
  id: string;
  /** One line an analyst could read aloud to a client. */
  title: string;
  count: number;
  /** Why it matters, in the client's terms rather than the engine's. */
  detail: string;
  /** What to do about it. A finding without one is trivia. */
  action: string;
  severity: "high" | "medium" | "low";
  /** A handful of URLs, so the claim can be checked rather than trusted. */
  examples: string[];
}

function pathOf(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

function firstSegment(url: string): string {
  return pathOf(url).split("/").filter(Boolean)[0] ?? "";
}

/** Loose comparison: `/order-to-cash/` against "Order To Cash". */
function flatten(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function menuLabels(result: PageClassificationOutput): Set<string> {
  const labels = new Set<string>();
  const walk = (nodes: readonly { label: string; children: readonly unknown[] }[]): void => {
    for (const node of nodes) {
      if (node.label) labels.add(flatten(node.label));
      walk(node.children as readonly { label: string; children: readonly unknown[] }[]);
    }
  };
  walk(result.navigation?.roots ?? []);
  return labels;
}

/**
 * URL prefixes holding a meaningful share of the site with no menu entry.
 *
 * The case this was built from: highradius.com serves 1,113 pages — a tenth of
 * the site — under `/software/`, and has no `Software` tab. A search engine
 * infers a silo from the URL; a visitor is offered Product and Resources
 * instead. The two audiences are given different maps of the same site.
 */
function siloFindings(
  pages: readonly FullPageIntelligenceProfile[],
  labels: Set<string>,
): Finding[] {
  const bySegment = new Map<string, FullPageIntelligenceProfile[]>();
  for (const page of pages) {
    const segment = firstSegment(page.url);
    // A single-segment URL has no silo to disagree with.
    if (!segment || pathOf(page.url).split("/").filter(Boolean).length < 2) continue;
    const bucket = bySegment.get(segment);
    if (bucket) bucket.push(page);
    else bySegment.set(segment, [page]);
  }

  const findings: Finding[] = [];
  for (const [segment, group] of bySegment) {
    if (group.length < MIN_SILO_PAGES || group.length / pages.length < SILO_SHARE) continue;
    const flat = flatten(segment);
    const inMenu = [...labels].some((label) => label.includes(flat) || flat.includes(label));
    if (inMenu) continue;
    const share = Math.round((group.length / pages.length) * 100);
    findings.push({
      id: `silo:${segment}`,
      title: `${group.length.toLocaleString()} pages under /${segment}/ with no matching menu entry`,
      count: group.length,
      detail:
        `${share}% of the site sits in this URL folder, but no header-menu item names it. ` +
        `Search engines infer a topical silo from the URL; visitors are never shown one.`,
      action:
        `Either add a menu entry for /${segment}/, or move these pages under the section ` +
        `the menu already advertises. Consistency between the two is what compounds.`,
      severity: "high",
      examples: group.slice(0, 5).map((page) => page.url),
    });
  }
  return findings;
}

/** `?page=2`, `/page/2/` — one page indexed many times over. */
function isPaginated(url: string): boolean {
  return /[?&]page=\d+/i.test(url) || /\/page\/\d+\/?$/i.test(pathOf(url));
}

/**
 * Every finding for one crawl, most severe first.
 *
 * Ordered by what an analyst can act on rather than by count. An orphan set is
 * a smaller number than an unclassified set and a far better recommendation.
 */
export function buildFindings(result: PageClassificationOutput): Finding[] {
  const pages = result.pages;
  if (pages.length === 0) return [];
  const labels = menuLabels(result);
  const findings: Finding[] = [];

  const orphans = pages.filter((page) => page.inbound_internal_links_count === 0);
  if (orphans.length > 0) {
    findings.push({
      id: "orphans",
      title: `${orphans.length.toLocaleString()} orphaned pages`,
      count: orphans.length,
      detail:
        "Nothing on the site links to these. They exist in the sitemap, so search " +
        "engines spend crawl budget reaching them, and they receive no internal " +
        "link equity in return. Visitors cannot navigate to them at all.",
      action:
        "Link them from a relevant index or article, or remove them from the sitemap. " +
        "Leaving them in both places is the one option with no upside.",
      severity: "high",
      examples: orphans.slice(0, 5).map((page) => page.url),
    });
  }

  findings.push(...siloFindings(pages, labels));

  const paginated = pages.filter((page) => isPaginated(page.url));
  if (paginated.length > 0) {
    findings.push({
      id: "pagination",
      title: `${paginated.length.toLocaleString()} paginated URL variants indexed separately`,
      count: paginated.length,
      detail:
        "Page 2, page 3 and so on are being treated as distinct pages. They compete " +
        "with the page they paginate and dilute its ranking signals.",
      action:
        "Point each variant at the first page with rel=canonical, or noindex them. " +
        "Check first whether robots.txt already excludes them — several sites have " +
        "done half of this and stopped.",
      severity: "medium",
      examples: paginated.slice(0, 5).map((page) => page.url),
    });
  }

  const mismatched = pages.filter((page) => {
    const segment = firstSegment(page.url);
    if (!segment || page.breadcrumb_path.length === 0) return false;
    if (pathOf(page.url).split("/").filter(Boolean).length < 2) return false;
    const flat = flatten(segment);
    return !page.breadcrumb_path.some(
      (label) => flatten(label).includes(flat) || flat.includes(flatten(label)),
    );
  });
  if (mismatched.length > 0) {
    findings.push({
      id: "silo-mismatch",
      title: `${mismatched.length.toLocaleString()} pages whose URL folder contradicts their menu path`,
      count: mismatched.length,
      detail:
        "The URL says one section and the navigation says another. Each is a signal " +
        "about topical grouping, and they disagree.",
      action:
        "Pick one structure and make the other follow it. Which one matters less than " +
        "that they agree.",
      severity: "medium",
      examples: mismatched.slice(0, 5).map((page) => page.url),
    });
  }

  const unknown = pages.filter((page) => page.final_confidence_score === 0);
  if (unknown.length > 0) {
    findings.push({
      id: "unclassified",
      title: `${unknown.length.toLocaleString()} pages the engine could not classify`,
      count: unknown.length,
      detail:
        "A finding about this report, not about the site. These pages carried no " +
        "structural signal the engine could read — usually because they were never " +
        "fetched, or carry no schema markup, headings or internal links to learn from.",
      action:
        "Treat their page types as unknown rather than as the fallback shown. Re-crawling " +
        "with a larger page budget resolves the ones that were simply never reached.",
      severity: "low",
      examples: unknown.slice(0, 5).map((page) => page.url),
    });
  }

  const order = { high: 0, medium: 1, low: 2 };
  return findings.sort((a, b) => order[a.severity] - order[b.severity] || b.count - a.count);
}
