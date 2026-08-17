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

/** `1 orphaned page`, `12 orphaned pages`. A count of one is common enough to read. */
function plural(count: number, noun: string): string {
  return `${count.toLocaleString()} ${noun}${count === 1 ? "" : "s"}`;
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
      title: `${plural(group.length, "page")} under /${segment}/ with no matching menu entry`,
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

/**
 * Tokens that carry no addressing meaning inside a URL segment.
 *
 * rankuno.com serves `marketing-strategy-transformation` and
 * `marketing-strategy-and-transformation` as separate pages. Dropping these
 * makes the two segments compare equal, which is the only way to see that they
 * are one page at two addresses.
 */
const FILLER_TOKENS = new Set([
  "a",
  "an",
  "and",
  "for",
  "in",
  "of",
  "on",
  "the",
  "to",
  "with",
]);

function segments(url: string): string[] {
  return pathOf(url).split("/").filter(Boolean);
}

/** `Marketing-Strategy-and-Transformation` and `marketing-strategy-transformation` alike. */
function normalizeSegment(segment: string): string {
  return segment
    .toLowerCase()
    .split(/[-_]+/)
    .filter((token) => token && !FILLER_TOKENS.has(token))
    .join("-");
}

/** Whether `shorter` appears inside `longer` in order, gaps allowed. */
function isSubsequence(shorter: readonly string[], longer: readonly string[]): boolean {
  let index = 0;
  for (const item of longer) {
    if (index < shorter.length && shorter[index] === item) index += 1;
  }
  return index === shorter.length;
}

/**
 * URLs that address the same page.
 *
 * Grouped on the leaf segment, then confirmed on the ancestry — a leaf alone is
 * far too weak, because `/products/socks/reviews` and `/products/hats/reviews`
 * share one and are two pages. Two URLs are the same page when their ancestor
 * chains match once filler tokens are dropped, or when one chain is the other
 * with segments inserted. Both shapes are live on rankuno.com:
 *
 * * `…/marketing-strategy-transformation/multi-channel-digital-roadmap/` and
 *   `…/marketing-strategy-and-transformation/multi-channel-digital-roadmap/`
 * * `/expertise/digital-channels/paid-search/` and
 *   `/expertise/digital-channels/search/paid-search/`
 *
 * Query strings are ignored, so `?role=copywriter` and `?role=copywriter-2`
 * collapse onto the path they decorate. That found 13 variants of one job
 * application form on the same crawl.
 *
 * This is a finding rather than a tree repair on purpose. Both URLs were
 * crawled and both must appear in the tree; what is wrong is that they exist,
 * and on rankuno.com they publish *contradictory breadcrumbs* — one names `Our
 * Expertise` as the section and the other does not, which is what put a second
 * `Marketing Strategy & Transformation` at the top of the report.
 */
function duplicateFindings(pages: readonly FullPageIntelligenceProfile[]): Finding[] {
  const byLeaf = new Map<string, FullPageIntelligenceProfile[]>();
  for (const page of pages) {
    const parts = segments(page.url);
    const leaf = normalizeSegment(parts[parts.length - 1] ?? "");
    const bucket = byLeaf.get(leaf);
    if (bucket) bucket.push(page);
    else byLeaf.set(leaf, [page]);
  }

  const groups: FullPageIntelligenceProfile[][] = [];
  for (const bucket of byLeaf.values()) {
    if (bucket.length < 2) continue;
    // Ancestries compared pairwise against the group's first member, which is
    // enough: a group is only reported, never merged, so a near-miss costs a
    // smaller count rather than a wrong one.
    const chains = bucket.map((page) => segments(page.url).slice(0, -1).map(normalizeSegment));
    const head = chains[0];
    if (!head) continue;
    const matched: FullPageIntelligenceProfile[] = [];
    bucket.forEach((page, index) => {
      const chain = chains[index];
      if (!chain) return;
      if (index === 0 || isSubsequence(chain, head) || isSubsequence(head, chain)) {
        matched.push(page);
      }
    });
    if (matched.length > 1) groups.push(matched);
  }

  if (groups.length === 0) return [];
  const total = groups.reduce((sum, group) => sum + group.length, 0);
  return [
    {
      id: "duplicate-urls",
      title: `${total.toLocaleString()} URLs serving ${plural(groups.length, "page")}`,
      // Groups, not URLs. Every example line is a whole group, and the card's
      // "+ N more" counts lines — against the URL total it claimed 16 further
      // examples when all four groups were already on screen.
      count: groups.length,
      detail:
        "The same page is reachable at more than one address. Each copy competes " +
        "with the others for the same query, so the ranking signal for that page " +
        "is split across them rather than concentrated. Where the copies also " +
        "publish different breadcrumbs, they additionally disagree about which " +
        "section the page belongs to.",
      action:
        "Pick one address per page and point the rest at it with rel=canonical, or " +
        "301 them. Check the breadcrumb on the surviving URL afterwards — on this " +
        "crawl the duplicates did not agree about their own parent section.",
      severity: "high",
      // One line per group, so the pairing is visible rather than inferred from
      // a flat list of URLs that happen to look similar.
      // Capped per group as well as across groups: one live group held 14 query
      // variants of a single form, and printed whole it was a wall of text with
      // the point buried in it. Three URLs is enough to show the pattern.
      examples: groups.slice(0, 5).map((group) => {
        const shown = group.slice(0, 3).map((page) => page.url).join("  ≡  ");
        return group.length > 3 ? `${shown}  ≡  (+${group.length - 3} more URLs)` : shown;
      }),
    },
  ];
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
      title: `${plural(orphans.length, "orphaned page")}`,
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

  findings.push(...duplicateFindings(pages));
  findings.push(...siloFindings(pages, labels));

  const paginated = pages.filter((page) => isPaginated(page.url));
  if (paginated.length > 0) {
    findings.push({
      id: "pagination",
      title: `${plural(paginated.length, "paginated URL variant")} indexed separately`,
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
      title: `${plural(mismatched.length, "page")} whose URL folder contradicts their menu path`,
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
      title: `${plural(unknown.length, "page")} the engine could not classify`,
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
