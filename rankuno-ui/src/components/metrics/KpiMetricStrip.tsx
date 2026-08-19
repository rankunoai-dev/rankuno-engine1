import { useMemo } from "react";
import type { PageClassificationOutput } from "../../types/schema";
import type { DashModel } from "../../lib/dashboardModel";

interface Props {
  result: PageClassificationOutput;
}

/**
 * Where a site's pages get their published position, and how many have none.
 *
 * Two sources place a page: the header menu, and the page's own published
 * breadcrumb. They are reported apart because they fail differently — a menu
 * path is wrong for the whole site at once, a breadcrumb is wrong one page at a
 * time — and summed only for the headline.
 */
interface NavSources {
  menu: number;
  breadcrumb: number;
  unplaced: number;
  /** True when the split was derived from pages rather than read from the report. */
  derived: boolean;
}

/**
 * The placement split, from the stored report or recomputed from the pages.
 *
 * `nav_coverage.breadcrumb_matches` is authoritative and is what a crawl run
 * today writes. Results stored before cycle 0022 do not have it, and those are
 * still loadable from `.jobs/` — for them the engine counted the menu alone, so
 * `unmatched` holds every breadcrumb-placed page and reading it directly
 * reproduces the exact defect this replaced: kinsta.com showed 24,371 pages
 * under "no navigation path reaches these" while the tree placed 22,869 of them.
 *
 * The fallback recounts `trail_source` over the pages, which is the same input
 * the engine's `recount_placements` uses, so an old result and a reparsed one
 * agree on screen.
 *
 * Results older still carry no `trail_source` at all. Nothing can be derived
 * there, so the stored menu-only numbers stand rather than a zero being
 * asserted — an absent measurement is not a measurement of zero.
 */
function navSources(result: PageClassificationOutput): NavSources {
  const coverage = result.nav_coverage;
  const menuMatches = coverage.exact_matches + coverage.inherited_matches;

  // Read through a cast, not off the type. The contract is generated from the
  // Pydantic model and declares this field required, which describes what the
  // engine emits *today* — not what is on disk. Every result stored before
  // cycle 0022 lacks it entirely, and reading it as a guaranteed number puts
  // `undefined` behind `number` and renders "NaN" on the card. Same defensive
  // shape, and the same reason, as `trailSourceOf` in `dashboardModel`.
  const stored = (coverage as { breadcrumb_matches?: number }).breadcrumb_matches;

  if (typeof stored === "number") {
    return {
      menu: menuMatches,
      breadcrumb: stored,
      unplaced: coverage.unmatched,
      derived: false,
    };
  }

  let menu = 0;
  let breadcrumb = 0;
  let tagged = 0;
  for (const page of result.pages) {
    const source = (page as { trail_source?: string }).trail_source;
    if (source === undefined) continue;
    tagged += 1;
    if (source === "menu") menu += 1;
    else if (source === "breadcrumb") breadcrumb += 1;
  }

  if (tagged === 0) {
    return {
      menu: menuMatches,
      breadcrumb: 0,
      unplaced: coverage.unmatched,
      derived: false,
    };
  }

  return {
    menu,
    breadcrumb,
    unplaced: result.pages.length - menu - breadcrumb,
    derived: true,
  };
}

/**
 * The five headline numbers.
 *
 * Every one is read from the crawl result. The reference design's fifth card
 * was a fixed `$0.00` spend; this reads `summary.llm_spend_usd` against the job's
 * own cap, because a hard-coded zero would keep reading zero after Layer 3 is
 * implemented and starts costing money.
 */
export function KpiMetricStrip({ result }: Props): JSX.Element {
  const { summary, discovery } = result;

  // Memoized because the legacy branch walks every page, and at 27,656 pages
  // that is not something to redo on an unrelated re-render.
  const sources = useMemo(() => navSources(result), [result]);

  const placed = sources.menu + sources.breadcrumb;
  const total = result.nav_coverage.total_urls || result.pages.length;
  const placedPercent = total ? Math.round((placed / total) * 100) : 0;

  return (
    <div className="kpis">
      <div className="kpi">
        <div className="lab">URLs classified</div>
        <div className="val">{summary.pages_classified.toLocaleString()}</div>
        <div className="sub">
          {discovery.total_urls.toLocaleString()} discovered
          {discovery.truncated && " · ceiling hit"}
        </div>
      </div>

      <div className="kpi">
        <div className="lab">Placed in navigation</div>
        <div className="val">{placed.toLocaleString()}</div>
        {/* Both sources named on the card. The split is the analytically
            interesting part: a site placed almost entirely by breadcrumbs has a
            header menu that reaches very little of it, which is a finding, and
            one number covering both would hide it. */}
        <div className="sub">
          {placedPercent}% of pages · {sources.menu.toLocaleString()} via header menu ·{" "}
          {sources.breadcrumb.toLocaleString()} via published breadcrumbs
        </div>
      </div>

      <div className="kpi">
        <div className="lab">OTHERS</div>
        <div className="val">{sources.unplaced.toLocaleString()}</div>
        <div className="sub">
          neither the menu nor a breadcrumb places these
          {sources.derived && " · recounted from this crawl's pages"}
        </div>
      </div>

      <div className="kpi">
        <div className="lab">Unclassified</div>
        <div className={`val${summary.unknown_pages > 0 ? " warn" : ""}`}>
          {summary.unknown_pages.toLocaleString()}
        </div>
        {/* Phase 1's stated goal is zero, so a non-zero value is a defect
            signal rather than a neutral statistic. */}
        <div className="sub">
          {summary.unknown_pages > 0 ? "target is zero" : "target met"}
        </div>
      </div>

      <div className="kpi">
        <div className="lab">LLM spend</div>
        <div className="val spend">${summary.llm_spend_usd.toFixed(2)}</div>
        <div className="sub">
          {summary.escalated_to_llm.toLocaleString()} escalated ·{" "}
          {(summary.escalation_rate * 100).toFixed(2)}%
        </div>
      </div>
    </div>
  );
}

/** Nodes per lane, for the filter chip tooltips. */
export function laneSummary(model: DashModel): string {
  return model.laneCounts.map((count, lane) => `L${lane}:${count}`).join(" ");
}
