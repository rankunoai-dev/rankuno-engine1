import type { SavedReconciliation } from "../adapters/adapterInterface";
import type { FullPageIntelligenceProfile } from "../types/schema";
import { OTHERS_LANE, type DashModel } from "./dashboardModel";
import { localeOf, OTHERS_LABEL } from "./navTree";

/**
 * What a Screaming Frog cross-check says about one tree node.
 *
 * `missed`: Rankuno found this page and Screaming Frog did not — an
 * `engine_only` row in the saved reconciliation.
 *
 * `added`: Screaming Frog found it and Rankuno did not. These pages exist only
 * in the merged "(+N from Screaming Frog)" job, where they are the profiles
 * whose `discovery_sources` are all `false` — nothing in *our* crawl produced
 * them. Read from the result itself, so it works on the merged job, which has
 * no sidecar of its own.
 */
export type CrossCheckMark = "none" | "missed" | "added";

/** One top-level section of the tree, totalled for the full-screen cards. */
export interface RootSummary {
  i: number;
  label: string;
  pages: number;
  missed: number;
  missedByReason: Record<string, number>;
  added: number;
  clicks: number;
  impressions: number;
  /** Pages under this root that a Search Console row reached. */
  gscPages: number;
  /** The three most common page types beneath this root, most common first. */
  topTypes: Array<[string, number]>;
}

/** One `OTHERS > <type>` bucket, totalled across every locale root. */
export interface OthersBucket {
  label: string;
  pages: number;
  missed: number;
  added: number;
  clicks: number;
  impressions: number;
  gscPages: number;
}

/** A page under OTHERS that Search Console says people reach. */
export interface OthersPage {
  i: number;
  url: string;
  type: string;
  locale: string | null;
  clicks: number;
  impressions: number;
  mark: CrossCheckMark;
  reason: string | null;
}

/** The OTHERS pages under one top-level root — the site's, or a locale's. */
export interface OthersRoot {
  i: number;
  label: string;
  pages: number;
  missed: number;
  clicks: number;
}

export interface OthersSummary {
  /** False when the tree is grouped by URL path: there is no OTHERS bucket. */
  applicable: boolean;
  pages: number;
  missed: number;
  clicks: number;
  impressions: number;
  /** Share of the site's Search Console clicks landing on OTHERS pages, 0..1. */
  clickShare: number;
  buckets: OthersBucket[];
  /**
   * Where the OTHERS pages sit, by top-level root, most clicked first.
   *
   * The tree row named OTHERS shows only its own subtree; this summary counts
   * the lane. On gep.com that is 1,522 pages and 2,673 clicks on the row against
   * 1,781 and 6,734 here, with the difference under `es-es`, `jp-ja`, `it-it`
   * and `zh-cn`. Without this list the two figures look like a bug.
   */
  byRoot: OthersRoot[];
  /** OTHERS pages with clicks, most clicked first. */
  topPages: OthersPage[];
}

export interface TreeOverlay {
  /** The model these arrays index. A mismatch means the arrays are stale. */
  model: DashModel;
  /** Whether a readable cross-check backs the `missed` marks. */
  crossCheck: boolean;
  /** Why not, in words for the disabled toggle. `null` when `crossCheck`. */
  crossCheckUnavailable: string | null;
  mark: CrossCheckMark[];
  /** The reconciliation's reason for an `engine_only` row, per node. */
  reason: Array<string | null>;
  /** Pages missed by Screaming Frog in each subtree, under the active reasons. */
  missedCnt: Int32Array;
  addedCnt: Int32Array;
  /** Every reason the sidecar used, with its full count — before any filter. */
  reasons: Record<string, number>;
  /** Whether any page carries Search Console figures. */
  gsc: boolean;
  clicks: Float64Array;
  impressions: Float64Array;
  gscPages: Int32Array;
  roots: RootSummary[];
  others: OthersSummary;
  /**
   * `engine_only` URLs that matched no node, after normalisation.
   *
   * Reported rather than swallowed. Every stored sidecar matches its result
   * exactly today, but a sidecar and a result are two files, and a future
   * change to either's URL form would otherwise show as a quietly smaller
   * number.
   */
  unmatched: number;
  /**
   * `pages − missed − added` against the sidecar's own `in_both`.
   *
   * `null` when there is no cross-check. A mismatch means the sidecar and the
   * result on screen have drifted apart, and that must be visible.
   */
  integrity: { expected: number; actual: number } | null;
}

/** Reasons Screaming Frog's default configuration filters out by itself. */
export const REASON_MEANINGS: Record<string, string> = {
  SITEMAP_ORPHAN:
    "Listed in the sitemap but reached by no internal link. Screaming Frog only follows " +
    "links, so it never saw these — the clearest case of a page it missed.",
  QUERY_VARIANT:
    "A `?page=N`-style variant of a page both crawlers found. Screaming Frog drops these " +
    "by default; whether they matter depends on whether Google indexes them separately.",
  REPEATED_SUFFIX_TRAP:
    "A URL whose path repeats itself. Both crawlers treat these as traps; Rankuno kept the " +
    "record of having found them.",
  MALFORMED_MARKUP:
    "Linked from markup Screaming Frog could not parse. Rankuno's parser is more tolerant.",
  PDF_FILE:
    "A PDF. Screaming Frog files documents under its own tab, so they never appear in the " +
    "HTML export this cross-check reads.",
  PRESENTATION_FILE: "A slide deck (.ppt, .pptx). Listed separately by Screaming Frog.",
  SPREADSHEET_FILE: "A workbook or CSV. Listed separately by Screaming Frog.",
  OTHER_FILE: "A Word document, archive or media file, not an HTML page.",
};

/** Plain-language names, for chips. Falls back to the raw token. */
export function reasonLabel(reason: string): string {
  return reason
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** How many OTHERS pages the insight panel lists. */
const TOP_PAGES = 30;

/**
 * Whether a profile was merged in from a Screaming Frog export.
 *
 * A page the engine found has at least one discovery source. A page merged
 * from an export has none, because no part of the crawl produced it — the
 * reconciler writes all three `false`. Checked on the 7 pages merged into
 * gep.com's job `d0a59fbc`: all seven, and no other page in that result.
 *
 * A profile with no `discovery_sources` at all predates the field (98% of the
 * stored corpus). That is *unknown*, never *added*: the contract types the
 * field as required, and reading it through the type alone would call every
 * old crawl a Screaming Frog import.
 */
export function addedFromFrog(profile: FullPageIntelligenceProfile): boolean {
  const sources = (profile as { discovery_sources?: unknown }).discovery_sources;
  if (!sources || typeof sources !== "object") return false;
  const flags = Object.values(sources as Record<string, unknown>);
  return flags.length > 0 && flags.every((flag) => flag === false);
}

/** The form URLs are compared in when exact matching leaves a residue. */
function loose(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.hostname.toLowerCase()}${path}${parsed.search}`;
  } catch {
    return url;
  }
}

/**
 * What a saved cross-check says about `engine_only`, read defensively.
 *
 * A sidecar written before the reasons existed, or one whose list is missing,
 * is reported as no cross-check rather than as an empty one.
 */
function engineOnlyOf(
  reconciliation: SavedReconciliation | null,
): { rows: Array<{ url: string; reason: string }> } | { unavailable: string } {
  if (!reconciliation) {
    return {
      unavailable:
        "No Screaming Frog cross-check is saved for this job. Upload one from the Jobs " +
        "view — and note that a merged “(+N from Screaming Frog)” job stores its " +
        "cross-check on the job it was merged from.",
    };
  }
  const rows = (reconciliation as { engine_only?: unknown }).engine_only;
  if (!Array.isArray(rows)) {
    return {
      unavailable:
        "This cross-check was saved before the engine recorded which URLs Screaming Frog " +
        "missed. Re-upload the export to see them.",
    };
  }
  return {
    rows: rows.map((row) => ({
      url: String((row as { url?: unknown }).url ?? ""),
      reason: String((row as { reason?: unknown }).reason ?? "UNKNOWN"),
    })),
  };
}

/**
 * Build the cross-check and Search Console overlay for one tree.
 *
 * Parallel arrays indexed by `DashNode.i`, never fields on the node. The model
 * is rebuilt only when the crawl or grouping changes and is shared by the
 * search index, the focus graph and the printable report; decorating it with
 * data from a different file would make every one of those depend on a sidecar
 * that may not exist. This is also what lets the toggle be a toggle — the
 * overlay is simply not read.
 *
 * Subtree totals use the same reverse pass `buildDashModel` uses for `cnt`,
 * and for the same reason: children always carry a higher index than their
 * parent, so one pass settles the tree.
 *
 * `hiddenReasons` removes reasons from `missedCnt` and the summaries, not from
 * `mark` — a row keeps its badge so an analyst can still see *why* it is not
 * being counted.
 */
export function buildTreeOverlay(
  model: DashModel,
  reconciliation: SavedReconciliation | null,
  hiddenReasons: ReadonlySet<string> = new Set(),
): TreeOverlay {
  const size = model.nodes.length;
  const mark: CrossCheckMark[] = new Array<CrossCheckMark>(size).fill("none");
  const reason: Array<string | null> = new Array<string | null>(size).fill(null);
  const missedCnt = new Int32Array(size);
  const addedCnt = new Int32Array(size);
  const clicks = new Float64Array(size);
  const impressions = new Float64Array(size);
  const gscPages = new Int32Array(size);
  const reasons: Record<string, number> = {};

  // Nodes by URL. Several nodes can share one URL — a section page and a
  // duplicate profile — and each of them should carry the mark.
  //
  // `!node.profile` already excludes `kind: "defaulter"` nodes — they are
  // built with `profile: null` by construction — and that exclusion is
  // deliberate, not incidental: a defaulter's URL was never crawled, so it
  // can never collide with a `missed`/`added` cross-check mark, which this
  // map exists to attach.
  const byUrl = new Map<string, number[]>();
  for (const node of model.nodes) {
    if (!node.profile) continue;
    const list = byUrl.get(node.profile.url);
    if (list) list.push(node.i);
    else byUrl.set(node.profile.url, [node.i]);
  }

  const engineOnly = engineOnlyOf(reconciliation);
  const crossCheck = "rows" in engineOnly;
  let unmatched = 0;

  if ("rows" in engineOnly) {
    // Exact first. Only the residue is retried loosely, so a sidecar that
    // matches its result — all ten stored ones do — never pays for it.
    const residue: Array<{ url: string; reason: string }> = [];
    for (const row of engineOnly.rows) {
      reasons[row.reason] = (reasons[row.reason] ?? 0) + 1;
      const hits = byUrl.get(row.url);
      if (hits) {
        for (const i of hits) {
          mark[i] = "missed";
          reason[i] = row.reason;
        }
      } else {
        residue.push(row);
      }
    }
    if (residue.length > 0) {
      const looseIndex = new Map<string, number[]>();
      for (const [url, indices] of byUrl) {
        const key = loose(url);
        const list = looseIndex.get(key);
        if (list) list.push(...indices);
        else looseIndex.set(key, [...indices]);
      }
      for (const row of residue) {
        const hits = looseIndex.get(loose(row.url));
        if (!hits) {
          unmatched += 1;
          continue;
        }
        for (const i of hits) {
          mark[i] = "missed";
          reason[i] = row.reason;
        }
      }
    }
  }

  // Search Console figures live on the profile — written by the Search Console
  // integration, present on every page it reached and `null` elsewhere. The
  // per-node card in the inspector reads the same fields, so a section total
  // here and a page figure there can never disagree.
  let gsc = false;
  let siteClicks = 0;
  for (const node of model.nodes) {
    const profile = node.profile;
    if (!profile) continue;
    if (mark[node.i] === "none" && addedFromFrog(profile)) mark[node.i] = "added";
    const pageClicks = profile.gsc_clicks ?? null;
    const pageImpressions = profile.gsc_impressions ?? null;
    if (pageClicks !== null || pageImpressions !== null) {
      gsc = true;
      gscPages[node.i] = 1;
      clicks[node.i] = pageClicks ?? 0;
      impressions[node.i] = pageImpressions ?? 0;
      siteClicks += pageClicks ?? 0;
    }
  }

  // Own contribution first, then the reverse pass folds each node into its
  // parent. A missed page under a hidden reason keeps its mark and adds nothing.
  for (let i = 0; i < size; i += 1) {
    if (mark[i] === "missed" && !hiddenReasons.has(reason[i] ?? "")) missedCnt[i] = 1;
    if (mark[i] === "added") addedCnt[i] = 1;
  }
  for (let i = size - 1; i >= 0; i -= 1) {
    const parent = model.nodes[i]!.p;
    if (parent === null) continue;
    missedCnt[parent] = missedCnt[parent]! + missedCnt[i]!;
    addedCnt[parent] = addedCnt[parent]! + addedCnt[i]!;
    clicks[parent] = clicks[parent]! + clicks[i]!;
    impressions[parent] = impressions[parent]! + impressions[i]!;
    gscPages[parent] = gscPages[parent]! + gscPages[i]!;
  }

  const roots = summariseRoots(model, mark, reason, missedCnt, addedCnt, clicks, impressions, gscPages, hiddenReasons);
  const others = summariseOthers(model, mark, reason, hiddenReasons, siteClicks);

  let integrity: TreeOverlay["integrity"] = null;
  if (crossCheck && reconciliation) {
    // Pages, not nodes: the section page counted once even when its node also
    // heads a section, and a duplicate profile counted once. The sidecar
    // reasons about URLs.
    let missedUrls = 0;
    let addedUrls = 0;
    for (const [, indices] of byUrl) {
      const first = indices[0]!;
      if (mark[first] === "missed") missedUrls += 1;
      else if (mark[first] === "added") addedUrls += 1;
    }
    integrity = {
      expected: reconciliation.summary.in_both,
      actual: byUrl.size - missedUrls - addedUrls,
    };
  }

  return {
    model,
    crossCheck,
    crossCheckUnavailable: "unavailable" in engineOnly ? engineOnly.unavailable : null,
    mark,
    reason,
    missedCnt,
    addedCnt,
    reasons,
    gsc,
    clicks,
    impressions,
    gscPages,
    roots,
    others,
    unmatched,
    integrity,
  };
}

function summariseRoots(
  model: DashModel,
  mark: CrossCheckMark[],
  reason: Array<string | null>,
  missedCnt: Int32Array,
  addedCnt: Int32Array,
  clicks: Float64Array,
  impressions: Float64Array,
  gscPages: Int32Array,
  hiddenReasons: ReadonlySet<string>,
): RootSummary[] {
  // Which root each node descends from. A forward pass suffices: parents
  // precede children.
  const rootOf = new Int32Array(model.nodes.length);
  const byReason = new Map<number, Record<string, number>>();
  const types = new Map<number, Map<string, number>>();
  for (const node of model.nodes) {
    const root = node.p === null ? node.i : rootOf[node.p]!;
    rootOf[node.i] = root;
    if (mark[node.i] === "missed") {
      const key = reason[node.i] ?? "UNKNOWN";
      if (!hiddenReasons.has(key)) {
        const counts = byReason.get(root) ?? {};
        counts[key] = (counts[key] ?? 0) + 1;
        byReason.set(root, counts);
      }
    }
    if (node.profile) {
      const counts = types.get(root) ?? new Map<string, number>();
      const type = node.profile.primary_page_type;
      counts.set(type, (counts.get(type) ?? 0) + 1);
      types.set(root, counts);
    }
  }

  return model.roots.map((i) => {
    const node = model.nodes[i]!;
    return {
      i,
      label: node.label,
      pages: node.cnt,
      missed: missedCnt[i]!,
      missedByReason: byReason.get(i) ?? {},
      added: addedCnt[i]!,
      clicks: clicks[i]!,
      impressions: impressions[i]!,
      gscPages: gscPages[i]!,
      topTypes: [...(types.get(i) ?? new Map<string, number>())]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3),
    };
  });
}

/** The label of the child of OTHERS that holds node `i`, or `null` if none does. */
function bucketOf(model: DashModel, i: number): string | null {
  let current = model.nodes[i];
  while (current && current.p !== null) {
    const parent = model.nodes[current.p]!;
    if (parent.label === OTHERS_LABEL) return current.label;
    current = parent;
  }
  return null;
}

/**
 * OTHERS is not one node. `navTree` roots each locale separately, so
 * `/es-es/company` sits under `es-es > OTHERS > UNKNOWN` and not under the
 * top-level OTHERS at all — and on gep.com the four most-clicked OTHERS pages
 * are localised homepages. The lane, not the label, is what identifies the
 * bucket: every page in the OTHERS lane is counted, wherever its root.
 */
function summariseOthers(
  model: DashModel,
  mark: CrossCheckMark[],
  reason: Array<string | null>,
  hiddenReasons: ReadonlySet<string>,
  siteClicks: number,
): OthersSummary {
  const buckets = new Map<string, OthersBucket>();
  const byRoot = new Map<number, OthersRoot>();
  const rootOf = new Int32Array(model.nodes.length);
  const candidates: OthersPage[] = [];
  let pages = 0;
  let missed = 0;
  let clicks = 0;
  let impressions = 0;

  for (const node of model.nodes) {
    rootOf[node.i] = node.p === null ? node.i : rootOf[node.p]!;
    // `kind: "defaulter"` nodes sit in `DEFAULTER_LANE`, never `OTHERS_LANE`,
    // and carry no profile either — doubly excluded, deliberately: a
    // quarantined URL is not an OTHERS page and must never appear in this
    // bucket's counts or its Search-Console-backed page list.
    if (node.lv !== OTHERS_LANE || !node.profile) continue;
    const profile = node.profile;
    // The bucket is the node directly beneath OTHERS in the tree on screen —
    // a URL folder, or FLAT_URLS — read by walking up from the page. Not the
    // engine's trail: that still says `OTHERS > <page type>`, and `navTree`
    // regroups it by folder before anything is drawn.
    const label = bucketOf(model, node.i) ?? profile.primary_page_type;
    const bucket = buckets.get(label) ?? {
      label,
      pages: 0,
      missed: 0,
      added: 0,
      clicks: 0,
      impressions: 0,
      gscPages: 0,
    };
    const nodeMark = mark[node.i]!;
    const nodeReason = reason[node.i] ?? null;
    const counted = nodeMark === "missed" && !hiddenReasons.has(nodeReason ?? "");
    const pageClicks = profile.gsc_clicks ?? 0;
    const pageImpressions = profile.gsc_impressions ?? 0;
    const hasGsc = profile.gsc_clicks !== null || profile.gsc_impressions !== null;

    bucket.pages += 1;
    if (counted) bucket.missed += 1;
    if (nodeMark === "added") bucket.added += 1;
    bucket.clicks += pageClicks;
    bucket.impressions += pageImpressions;
    if (hasGsc) bucket.gscPages += 1;
    buckets.set(label, bucket);

    pages += 1;
    if (counted) missed += 1;
    clicks += pageClicks;
    impressions += pageImpressions;

    const rootIndex = rootOf[node.i]!;
    const root = byRoot.get(rootIndex) ?? {
      i: rootIndex,
      label: model.nodes[rootIndex]!.label,
      pages: 0,
      missed: 0,
      clicks: 0,
    };
    root.pages += 1;
    if (counted) root.missed += 1;
    root.clicks += pageClicks;
    byRoot.set(rootIndex, root);

    if (pageClicks > 0) {
      candidates.push({
        i: node.i,
        url: profile.url,
        type: label,
        locale: localeOf(profile.url),
        clicks: pageClicks,
        impressions: pageImpressions,
        mark: nodeMark,
        reason: nodeReason,
      });
    }
  }

  candidates.sort((a, b) => b.clicks - a.clicks);

  return {
    applicable: (model.laneCounts[OTHERS_LANE] ?? 0) > 0,
    pages,
    missed,
    clicks,
    impressions,
    clickShare: siteClicks > 0 ? clicks / siteClicks : 0,
    buckets: [...buckets.values()].sort((a, b) => b.clicks - a.clicks || b.pages - a.pages),
    byRoot: [...byRoot.values()].sort((a, b) => b.clicks - a.clicks || b.pages - a.pages),
    topPages: candidates.slice(0, TOP_PAGES),
  };
}
