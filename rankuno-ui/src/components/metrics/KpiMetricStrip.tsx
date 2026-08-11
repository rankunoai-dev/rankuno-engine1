import type { PageClassificationOutput } from "../../types/schema";
import type { DashModel } from "../../lib/dashboardModel";


interface Props {
  result: PageClassificationOutput;
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
  const { summary, discovery, nav_coverage: coverage } = result;
  const inNav = coverage.exact_matches + coverage.inherited_matches;
  const navPercent = coverage.total_urls
    ? Math.round((inNav / coverage.total_urls) * 100)
    : 0;

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
        <div className="lab">In navigation</div>
        <div className="val">{inNav.toLocaleString()}</div>
        <div className="sub">{navPercent}% of pages · {coverage.nav_entries} menu entries</div>
      </div>

      <div className="kpi">
        <div className="lab">OTHERS</div>
        <div className="val">{coverage.unmatched.toLocaleString()}</div>
        <div className="sub">no navigation path reaches these</div>
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
