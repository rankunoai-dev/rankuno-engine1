import type { FullPageIntelligenceProfile } from "../../types/schema";
import {
  GscMetricsFormatter,
  calculateSiteMetrics,
  findTopOpportunities,
  calculateOpportunityScore,
} from "../../lib/gscMetrics";
import "./gsc.css";

interface Props {
  pages: FullPageIntelligenceProfile[];
}

/**
 * Displays GSC summary metrics for a crawl.
 *
 * Shows:
 * - Total clicks, impressions, avg position
 * - Index coverage % (crawled pages in GSC)
 * - Alerts if coverage < 80% or avg position > 20
 * - Top 5 opportunities (high-opportunity pages)
 */
export function GscPerformanceSection({ pages }: Props) {
  const metrics = calculateSiteMetrics(pages);
  const opportunities = findTopOpportunities(pages, 5);

  // No GSC data
  if (metrics.indexed === 0 && metrics.notIndexed === pages.length) {
    return (
      <div className="gsc-summary">
        <h3 className="gsc-summary-title">Google Search Console</h3>
        <div className="gsc-empty">No GSC data available for this crawl</div>
      </div>
    );
  }

  const coveragePct = Math.round(metrics.coverage);
  const showCoverageAlert = metrics.coverage < 80;
  const showPositionAlert = metrics.avgPosition !== null && metrics.avgPosition > 20;

  return (
    <div className="gsc-summary">
      <h3 className="gsc-summary-title">Google Search Console Performance</h3>

      {/* Main metrics */}
      <div className="gsc-summary-stats">
        <div className="gsc-stat">
          <div className="gsc-stat-value">{metrics.totalClicks.toLocaleString()}</div>
          <div className="gsc-stat-label">Total Clicks</div>
        </div>
        <div className="gsc-stat">
          <div className="gsc-stat-value">{metrics.totalImpressions.toLocaleString()}</div>
          <div className="gsc-stat-label">Total Impressions</div>
        </div>
        <div className="gsc-stat">
          <div className="gsc-stat-value">
            {GscMetricsFormatter.ctr(metrics.avgCtr)}
          </div>
          <div className="gsc-stat-label">Avg CTR</div>
        </div>
        <div className="gsc-stat">
          <div
            className={`gsc-stat-value gsc-value--pos-${GscMetricsFormatter.positionColor(metrics.avgPosition)}`}
          >
            {GscMetricsFormatter.position(metrics.avgPosition)}
          </div>
          <div className="gsc-stat-label">Avg Position</div>
        </div>
      </div>

      {/* Index coverage gauge */}
      <div className="gsc-coverage">
        <div>
          <div style={{ fontSize: "12px", color: "#8c8c8c", marginBottom: "4px" }}>
            Index Coverage
          </div>
          <div className="gsc-coverage-bar">
            <div
              className="gsc-coverage-fill"
              style={{
                width: `${Math.min(100, metrics.coverage)}%`,
              }}
            />
          </div>
        </div>
        <div className="gsc-coverage-text">
          {coveragePct}%
          <div style={{ fontSize: "11px", color: "#8c8c8c", marginTop: "2px" }}>
            {metrics.indexed} of {metrics.indexed + metrics.notIndexed}
          </div>
        </div>
      </div>

      {/* Alerts */}
      <div className="gsc-alerts">
        {showCoverageAlert && (
          <div className="gsc-alert-box gsc-alert-box--warning">
            ⚠️ Index coverage at {coveragePct}% — {metrics.notIndexed} pages not in GSC
          </div>
        )}
        {showPositionAlert && (
          <div className="gsc-alert-box gsc-alert-box--warning">
            ⚠️ Avg position {metrics.avgPosition!.toFixed(1)} (below top 20) — authority or
            content opportunity
          </div>
        )}
        {metrics.coverage === 100 && metrics.avgPosition !== null && metrics.avgPosition <= 10 && (
          <div className="gsc-alert-box gsc-alert-box--info">
            ✅ Full index coverage with strong ranking (avg position {metrics.avgPosition.toFixed(1)})
          </div>
        )}
      </div>

      {/* Top opportunities */}
      {opportunities.length > 0 && (
        <div className="gsc-opportunities">
          <div className="gsc-opp-list-title">Top Opportunities</div>
          {opportunities.map(({ page, score }) => (
            <div key={page.url} className={`gsc-opp-item gsc-opp-item--${score.category}`}>
              <div>
                <div className="gsc-opp-item-url">{new URL(page.url).pathname}</div>
                <div style={{ fontSize: "11px", color: "#8c8c8c", marginTop: "2px" }}>
                  {score.reason}
                </div>
              </div>
              <div className="gsc-opp-item-score">
                {score.score > 0 ? score.score.toFixed(0) : "—"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
