import type {
  DiscoverySource,
  FullPageIntelligenceProfile,
  PageClassificationOutput,
} from "../types/schema";

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
  /**
   * Every page behind the count, when the finding is a worklist rather than an
   * observation.
   *
   * Present only where acting on the finding means working through the pages
   * one at a time — an orphan set is a list a content team is handed, while
   * "41 duplicate title groups" is a report. A finding without this renders as
   * a card with examples, exactly as before.
   */
  pages?: FullPageIntelligenceProfile[];
  /**
   * The finding's pages clustered into the sets it is about.
   *
   * Set where the unit of work is a *group* rather than a page — duplicates are
   * decided one cluster at a time, because the decision is which member of the
   * cluster survives. A flat list of 1,920 URLs cannot express that; it is the
   * pairing that carries the finding.
   */
  groups?: FullPageIntelligenceProfile[][];
}

/**
 * The member of a duplicate set most likely to be the one worth keeping.
 *
 * A **suggestion**, and labelled as one wherever it is shown. It is not read
 * from the page: `rel=canonical` is on the profile as `canonical_url`, but a
 * site that had set it correctly would not have produced this finding, so
 * trusting it here would recommend keeping the URL the site already lost track
 * of. This ranks on evidence the crawl gathered independently instead.
 *
 * Ordered by inbound internal links first — the copy the site itself links to
 * most is the one already holding the signal, and redirecting *to* it preserves
 * the most. Ties break on the shortest path, then on the absence of a query
 * string, then alphabetically so the choice is stable between runs rather than
 * dependent on crawl order.
 */
export function suggestedSurvivor(
  group: readonly FullPageIntelligenceProfile[],
): FullPageIntelligenceProfile | undefined {
  return [...group].sort((a, b) => {
    const links = b.inbound_internal_links_count - a.inbound_internal_links_count;
    if (links !== 0) return links;
    const depth = segments(a.url).length - segments(b.url).length;
    if (depth !== 0) return depth;
    const query = Number(a.url.includes("?")) - Number(b.url.includes("?"));
    if (query !== 0) return query;
    return a.url.localeCompare(b.url);
  })[0];
}

/**
 * Why a page has no inbound internal link.
 *
 * The two are not the same finding and must not share a number. A sitemap entry
 * nothing links to is a page the site publishes to search engines and hides
 * from its own visitors — the recommendation writes itself. A page only the CMS
 * database knows about was never published anywhere a crawler can see, so
 * "add internal links" may be the wrong advice entirely.
 *
 * Measured on highradius.com: 2,182 pages have zero inbound links, but only
 * 1,142 of them are in a sitemap. Reporting the larger number as "orphans the
 * site publishes" overstates the finding by nearly a thousand pages.
 */
export type OrphanKind = "sitemap" | "cms" | "unlinked";

export function orphanKind(page: FullPageIntelligenceProfile): OrphanKind {
  const sources = discoverySourcesOf(page);
  if (sources?.sitemap) return "sitemap";
  if (sources?.cms_api) return "cms";
  return "unlinked";
}

/**
 * The discovery flags, or `undefined` on a result that predates them.
 *
 * The generated type declares this field required, and for anything the engine
 * produces today it is. It is **not** required of what the API returns:
 * `GET /jobs/{id}/result` serves the stored mapping without re-validating it
 * through the model, so a crawl saved before the field existed arrives with the
 * key simply absent. Reading it directly threw a TypeError inside `buildFindings`
 * and took the whole app to a blank page.
 *
 * Every read of the flags goes through here. The cast is the honest one: the
 * value crossing this boundary is older than the type describing it.
 */
export function discoverySourcesOf(
  page: FullPageIntelligenceProfile,
): DiscoverySource | undefined {
  return (page as { discovery_sources?: DiscoverySource }).discovery_sources;
}

/** Pages with no inbound internal link, most actionable kind first. */
export function orphanPages(
  result: PageClassificationOutput,
): FullPageIntelligenceProfile[] {
  const rank: Record<OrphanKind, number> = { sitemap: 0, cms: 1, unlinked: 2 };
  return result.pages
    .filter((page) => page.inbound_internal_links_count === 0)
    .sort((a, b) => rank[orphanKind(a)] - rank[orphanKind(b)] || a.url.localeCompare(b.url));
}

/** `1 orphaned page`, `12 orphaned pages`. A count of one is common enough to read. */
function plural(count: number, noun: string, plural?: string): string {
  // `plural` is optional because most nouns here take an `s`. It exists for the
  // ones that do not: "sitemap entry" becomes "sitemap entries", and a finding
  // title is read aloud to a client.
  const many = plural ?? `${noun}s`;
  return `${count.toLocaleString()} ${count === 1 ? noun : many}`;
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

/**
 * Whether two ancestor chains describe the same position.
 *
 * Equal chains qualify, and so does one chain being the other with segments
 * inserted — but only when the shorter chain is **non-empty**. An empty chain is
 * a subsequence of every chain, which made a root-level page match every deeper
 * page sharing its leaf: `linear.app/agents`, `/developers/agents` and
 * `/integrations/agents` are a marketing page, a docs page and a listing, and
 * were reported as one page at three addresses.
 *
 * Two empty chains are still a match — that is `/job-application/` against its
 * own query variants, which is the case this was built for.
 */
function sameAncestry(a: readonly string[], b: readonly string[]): boolean {
  const [shorter, longer] = a.length <= b.length ? [a, b] : [b, a];
  if (shorter.length === 0) return longer.length === 0;
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
      if (index === 0 || sameAncestry(chain, head)) {
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
      // Largest cluster first: a page reachable at seven addresses is a bigger
      // problem than one reachable at two, and it is the one to fix first.
      groups: [...groups].sort((a, b) => b.length - a.length),
    },
  ];
}

/** `?page=2`, `/page/2/` — one page indexed many times over. */
function isPaginated(url: string): boolean {
  return /[?&]page=\d+/i.test(url) || /\/page\/\d+\/?$/i.test(pathOf(url));
}

/**
 * A page's final address after redirects, read defensively.
 *
 * Every crawl stored before redirects were recorded lacks the field entirely,
 * and those results are still loadable. Absent is not "did not redirect" — it
 * is "nobody looked" — and a finding that conflates them accuses a site of a
 * defect on the strength of a missing column.
 */
function finalUrlOf(page: FullPageIntelligenceProfile): string {
  return (page as { final_url?: string }).final_url ?? "";
}

/** `/a/b/` and `/a/b` are the same destination; a scheme hop is not a move. */
function sameAddress(a: string, b: string): boolean {
  const strip = (url: string): string => {
    try {
      const parsed = new URL(url);
      return `${parsed.host.replace(/^www\./, "")}${parsed.pathname.replace(/\/$/, "")}${parsed.search}`;
    } catch {
      return url;
    }
  };
  return strip(a) === strip(b);
}

/**
 * Sitemap entries that redirect somewhere else.
 *
 * A sitemap is a site telling search engines *these are my pages*. An entry
 * that redirects is telling them to go somewhere else instead — it wastes crawl
 * budget on every visit, and the destination gets no direct signal from being
 * listed, because it is not the thing listed.
 *
 * Sharp rather than noisy, and that is what makes it worth reporting. Measured
 * on a fresh 300-page crawl of highradius.com, only 3% of fetched pages
 * redirect at all; of those, exactly one was in the sitemap. A finding that
 * fires on 1 URL in 300 is a specific defect an analyst can hand over, not a
 * list somebody has to triage.
 *
 * Two exclusions, both drawn from that same crawl:
 *
 * * A redirect that lands back on the same address is not a move.
 *   `/demo-request/` carries a redirect hop and ends exactly where it started —
 *   a scheme or trailing-slash normalisation, which every site does and no
 *   client needs to hear about.
 * * A page the sitemap does not list is not a sitemap defect. Three
 *   `/software/record-to-report/*` pages redirect properly and were found by
 *   following links, not by reading the sitemap.
 */
function sitemapRedirectFindings(
  pages: readonly FullPageIntelligenceProfile[],
): Finding[] {
  const moved = pages.filter((page) => {
    if (!page.discovery_sources?.sitemap) return false;
    const destination = finalUrlOf(page);
    return destination !== "" && !sameAddress(destination, page.url);
  });
  if (moved.length === 0) return [];

  // A redirect to the homepage is a different and worse defect: the page is
  // gone and the site is pointing search engines at something unrelated, which
  // Google treats as a soft 404 rather than as a move.
  const toHome = moved.filter((page) => {
    try {
      return new URL(finalUrlOf(page)).pathname.replace(/\/$/, "") === "";
    } catch {
      return false;
    }
  });

  return [
    {
      id: "sitemap-redirects",
      // Agreement matters here: these strings are read aloud to a client, and
      // this file has already shipped "1 orphaned pages" once.
      title:
        `${plural(moved.length, "sitemap entry", "sitemap entries")} that ` +
        `${moved.length === 1 ? "redirects" : "redirect"} elsewhere`,
      count: moved.length,
      detail:
        "A sitemap is the site telling search engines these are its pages. Each one " +
        "here redirects to a different address, so every crawl of it is spent twice " +
        "and the real destination gets no benefit from being listed — because it is " +
        "not the thing listed." +
        (toHome.length > 0
          ? ` ${
              toHome.length === 1
                ? "One of them lands"
                : `${toHome.length.toLocaleString()} of them land`
            } on the homepage, which search engines usually read as the page being ` +
            "gone rather than moved."
          : ""),
      action:
        "Replace each entry with the address it resolves to, or drop it if the page " +
        "no longer exists. A sitemap should list destinations, never the way to them.",
      severity: "medium",
      examples: moved.slice(0, 5).map((page) => `${page.url}  →  ${finalUrlOf(page)}`),
      pages: moved,
    },
  ];
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

  const orphans = orphanPages(result);
  if (orphans.length > 0) {
    const published = orphans.filter((page) => orphanKind(page) === "sitemap").length;
    findings.push({
      id: "orphans",
      title: `${plural(orphans.length, "orphaned page")}`,
      count: orphans.length,
      detail:
        `Nothing on the site links to these. ${plural(published, "page")} of them ` +
        "sit in a sitemap, so search engines spend crawl budget reaching pages " +
        "visitors cannot navigate to, and no internal link equity flows back. The " +
        "rest were found only in the CMS database and are not published anywhere " +
        "a crawler can see them.",
      action:
        "Work the sitemap ones first: link each from a relevant index or article, " +
        "or remove it from the sitemap. Leaving a page in both places is the one " +
        "option with no upside. Cross the list against Search Console before " +
        "deleting anything — an orphan already earning impressions is a page to " +
        "link, not to cut.",
      severity: "high",
      examples: orphans.slice(0, 5).map((page) => page.url),
      pages: orphans,
    });
  }

  findings.push(...sitemapRedirectFindings(pages));
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
