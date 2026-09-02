import type { FullPageIntelligenceProfile } from "../../types/schema";
import { GscMetricsFormatter, calculateOpportunityScore } from "../../lib/gscMetrics";
import "./gsc.css";

interface Props {
  page: FullPageIntelligenceProfile;
}

/**
 * Displays GSC metrics (clicks, impressions, position, CTR) for a single page.
 *
 * Shows null fields as dashes, color-codes performance indicators, and
 * explains what each metric means to an analyst.
 */
export function GscMetricsCard({ page }: Props) {
  const { gsc_clicks, gsc_impressions, gsc_avg_position, gsc_ctr } = page;

  // All fields null/undefined = no GSC data
  if (
    (gsc_clicks === null || gsc_clicks === undefined) &&
    (gsc_impressions === null || gsc_impressions === undefined) &&
    (gsc_avg_position === null || gsc_avg_position === undefined) &&
    (gsc_ctr === null || gsc_ctr === undefined)
  ) {
    return (
      <div className="gsc-card">
        <h4 className="gsc-title">Google Search Console</h4>
        <div className="gsc-empty">No GSC data available</div>
      </div>
    );
  }

  const opportunity = calculateOpportunityScore(page);
  const posColor = GscMetricsFormatter.positionColor(gsc_avg_position);
  const ctrColor = GscMetricsFormatter.ctrColor(gsc_ctr, gsc_avg_position);

  return (
    <div className="gsc-card">
      <h4 className="gsc-title">Google Search Console</h4>

      <div className="gsc-metrics">
        {/* Clicks */}
        <div className="gsc-metric">
          <span className="gsc-label">Clicks</span>
          <span className="gsc-value">
            {gsc_clicks === null || gsc_clicks === undefined ? "—" : String(gsc_clicks).toLocaleString()}
          </span>
        </div>

        {/* Impressions */}
        <div className="gsc-metric">
          <span className="gsc-label">Impressions</span>
          <span className="gsc-value">
            {gsc_impressions === null || gsc_impressions === undefined ? "—" : String(gsc_impressions).toLocaleString()}
          </span>
        </div>

        {/* Position */}
        <div className="gsc-metric">
          <span className="gsc-label">Avg Position</span>
          <span className={`gsc-value gsc-value--pos-${posColor}`}>
            {GscMetricsFormatter.position(gsc_avg_position)}
          </span>
          <span className="gsc-hint">
            {GscMetricsFormatter.positionLabel(gsc_avg_position)}
          </span>
        </div>

        {/* CTR */}
        <div className="gsc-metric">
          <span className="gsc-label">CTR</span>
          <span className={`gsc-value gsc-value--ctr-${ctrColor}`}>
            {GscMetricsFormatter.ctr(gsc_ctr)}
          </span>
          {gsc_avg_position !== null && (
            <span className="gsc-hint">
              {posColor === "green" && gsc_ctr !== null && gsc_ctr < 0.1 && "Expected 15%+ for top 3"}
              {posColor === "yellow" && gsc_ctr !== null && gsc_ctr < 0.05 && "Expected 5%+ for top 10"}
              {!gsc_ctr || (gsc_ctr > 0.03 && "Above benchmark")}
            </span>
          )}
        </div>
      </div>

      {/* Opportunity hint */}
      {opportunity.category !== "none" && (
        <div className={`gsc-opportunity gsc-opp--${opportunity.category}`}>
          <span className="gsc-opp-label">{opportunity.category.toUpperCase()}</span>
          <span className="gsc-opp-text">{opportunity.reason}</span>
        </div>
      )}

      {/* Not indexed warning */}
      {(gsc_impressions ?? 0) === 0 && gsc_impressions !== null && gsc_impressions !== undefined && (
        <div className="gsc-alert gsc-alert--warning">
          <span>⚠️ Not indexed in Google Search Console</span>
        </div>
      )}

      {/* High position, zero clicks insight */}
      {gsc_avg_position !== null &&
        gsc_avg_position !== undefined &&
        gsc_avg_position <= 5 &&
        (gsc_clicks ?? 0) === 0 &&
        gsc_clicks !== null &&
        gsc_clicks !== undefined &&
        (gsc_impressions ?? 0) > 0 &&
        gsc_impressions !== null &&
        gsc_impressions !== undefined && (
          <div className="gsc-alert gsc-alert--info">
            <span>📊 Ranking well but not getting clicks—check snippet</span>
          </div>
        )}
    </div>
  );
}
